# Rapporto di audit completo - LION Evolution Pro

Data audit: 2026-03-09
Repository: https://github.com/Nemex81/LION-Evolution-Pro
Ramo analizzato: `master`
Commit osservato tramite API contenuti: `33d14daf36aee3f1982329c712f1e1642a714b51`

## 1. Scopo
Questo rapporto documenta un audit statico approfondito del repository **LION Evolution Pro**, con attenzione a:
- stato attuale del progetto;
- qualità architetturale dell'add-on NVDA;
- solidità delle procedure;
- completezza delle funzionalità offerte;
- errori, refusi, imprecisioni e fragilità che possono compromettere precisione, stabilità o corretto funzionamento.

L'audit è basato sulla lettura dei file principali effettivamente presenti nel repository:
- `readme.md`
- `addon/manifest.ini`
- `addon/globalPlugins/lion/__init__.py`
- `addon/globalPlugins/lion/lionGui.py`
- `addon/doc/en/readme.htm`

## 2. Stato attuale del progetto
Il repository è un add-on NVDA reale e strutturalmente riconoscibile.

### Struttura osservata
Root repository:
- `.github/`
- `.gitignore`
- `.vscode/`
- `addon/`
- `copilot docs/`
- `lionGui.wxg`
- `readme.md`

Cartella `addon/`:
- `doc/`
- `globalPlugins/`
- `manifest.ini`

Cartella `addon/globalPlugins/lion/`:
- `__init__.py`
- `lionGui.py`

### Valutazione sintetica dello stato
Il progetto è attivo, ordinato e dotato di una logica runtime concreta. La separazione tra backend OCR e GUI è presente. La presenza del file `lionGui.wxg` indica anche una base progettuale per manutenzione dell'interfaccia.

Tuttavia il progetto mostra anche segnali di maturazione incompleta o documentazione non aggiornata, soprattutto sul packaging, sulla compatibilità dichiarata e sul materiale utente.

## 3. Manifest e compatibilità
Contenuto rilevante del manifest:
- `name = LionEvolutionPro`
- `summary = "LION Evolution Pro - Advanced OCR for NVDA"`
- `version = 2.0.0`
- `description = "Live OCR with application-specific profiles. Based on LION by vortex1024."`
- `minimumNVDAVersion = 2024.1.0`
- `lastTestedNVDAVersion = 2025.3.2`

### Giudizio
Il manifest è essenziale ma coerente.

### Punti positivi
- Nome add-on coerente con il codice.
- Descrizione breve ma aderente alla funzione principale.
- Compatibilità minima dichiarata.
- Ultima versione testata esplicitata.

### Punti deboli
- Non risulta conferma esplicita di test su NVDA 2026.x.
- Il documento utente interno è fermo a versioni storiche (`1.12`, `1.11`, `1.1`, `1.0`) e non riflette chiaramente la realtà della versione `2.0.0`.
- Questo crea un disallineamento importante tra metadati e documentazione pubblica.

## 4. Architettura dell'add-on
L'architettura è centralizzata ma leggibile.

### Componente backend (`__init__.py`)
Il backend implementa:
- configurazione globale in `config.conf["lion"]`;
- profili per-app in JSON nella cartella `profiles` sotto la configurazione NVDA;
- merge tra config globale e override applicativi;
- cambio automatico profilo al cambio focus;
- thread OCR separato;
- cache anti-ripetizione;
- menu impostazioni nel menu Preferenze di NVDA;
- gesture `NVDA+Alt+L` per attivare/disattivare l'OCR live.

### Componente GUI (`lionGui.py`)
La GUI implementa:
- finestra wx con tab `Profiles` e `Settings`;
- elenco profili con stato;
- creazione/cancellazione/selezione profili;
- salvataggio esplicito delle impostazioni;
- restore defaults per profili applicativi;
- dirty tracking con conferma in chiusura o cambio profilo.

### Giudizio architetturale
L'impianto è buono e sopra la media di molti add-on NVDA amatoriali.

La separazione tra logica e interfaccia è reale. La gestione dei profili è concettualmente valida. La strategia "global config + override per applicazione" è semplice, efficace e manutenibile.

### Limite architetturale
Quasi tutta la logica runtime resta concentrata in `__init__.py`, che supera 30 KB e combina:
- persistenza profili;
- gestione thread;
- geometria crop;
- OCR;
- anti-repeat;
- menu;
- gestione focus.

Questo non rompe l'addon, ma riduce modularità, testabilità e facilità di manutenzione futura.

## 5. Solidità delle procedure
### 5.1 Gestione profili
La procedura di gestione profili è generalmente solida.

#### Aspetti positivi
- I profili salvano solo gli override rispetto al globale.
- I profili legacy vengono normalizzati automaticamente.
- I profili vuoti `{}` sono supportati come "uguale al globale" ma persistenti.
- Il cambio focus attiva automaticamente il profilo associato all'applicazione.

#### Problemi
- Il nome file del profilo è derivato da una sanitizzazione semplice del nome applicazione: vengono tenuti solo caratteri alfanumerici, `-` e `_`.
- Questo può causare collisioni tra nomi applicazione diversi che, dopo filtraggio, producono lo stesso nome file.
- Non c'è una strategia più robusta di identificazione profilo basata, ad esempio, su nome completo stabile o hashing.

### 5.2 Gestione thread OCR
Il progetto prova a gestire correttamente il lifecycle del thread OCR, ma qui emergono le fragilità più importanti.

#### Aspetti positivi
- Esiste un thread dedicato per OCR.
- L'avvio è protetto con `_ocrLock`.
- In `terminate()` il thread viene arrestato e atteso.
- Nel loop OCR sono presenti gestione errori, contatore errori consecutivi e backoff esponenziale.

#### Problema grave
Nel loop `ocrLoop()` viene usato:

```python
self._ocrActive.wait(timeout=interval)
```

ma `_ocrActive` è un `threading.Event` che viene mantenuto **set** mentre l'OCR è attivo.

Quando un `Event` è già impostato, `wait(timeout=...)` ritorna immediatamente. Questo significa che, durante il normale funzionamento, il loop può non rispettare davvero l'intervallo configurato e girare quasi senza pausa.

#### Impatto
Questo è un problema **critico** perché può causare:
- OCR molto più frequente del previsto;
- consumo CPU superiore al necessario;
- carico eccessivo su riconoscimento e capture screen;
- comportamento incoerente rispetto all'impostazione `interval` mostrata all'utente.

#### Raccomandazione
La logica di attesa va corretta. Serve un meccanismo che attenda fino a timeout **solo se non arriva uno stop**, non un `wait()` su un evento già impostato come stato normale di run.

### 5.3 Gestione errori
La gestione errori è buona.

#### Aspetti positivi
Il codice protegge molti punti critici con `try/except`:
- import GUI;
- creazione menu;
- apertura dialogo;
- focus event;
- creazione recognizer OCR;
- capture del bitmap;
- callback OCR;
- loop principale.

Questo riduce il rischio di crash diretto di NVDA.

#### Limite
Alcuni errori vengono solo loggati e l'esecuzione continua in fallback. Questo è spesso corretto in un add-on NVDA, ma in alcuni casi può mascherare malfunzionamenti reali invece di esporli chiaramente all'utente.

## 6. Validità e completezza delle funzionalità
### Funzionalità dichiarate / presenti
In base a codice e documentazione, l'add-on offre:
- OCR live di porzioni dello schermo;
- lettura differenziale del testo per evitare ripetizioni;
- selezione target OCR tra navigatore, schermo intero, finestra corrente e controllo corrente;
- crop configurabile;
- soglia di similarità configurabile;
- intervallo OCR configurabile;
- profili specifici per applicazione;
- GUI di gestione profili e impostazioni;
- attivazione/disattivazione via gesture.

### Giudizio sulla completezza
La dotazione funzionale è buona e concreta.

Il progetto non è un prototipo minimale: ha una vera logica utente, una GUI, persistenza, configurazione e comportamento contestuale per-app. Da questo punto di vista la completezza funzionale è soddisfacente.

### Limiti funzionali reali
La completezza è indebolita da alcuni punti:
- la documentazione utente non descrive chiaramente l'evoluzione a "Evolution Pro" e i profili per applicazione;
- il comportamento di crop descritto non è garantito correttamente dalla formula attuale;
- il timing dell'OCR live è potenzialmente errato;
- l'esclusione hardcoded del testo `"Play"` introduce un comportamento speciale non documentato.

## 7. Bug, errori e fragilità rilevate
### 7.1 Bug critico nel calcolo del crop
Funzione coinvolta: `cropRectLTWH()`.

Il rettangolo ritagliato viene calcolato con una formula incoerente:
- `newX` e `newY` si spostano in base al crop sinistro/superiore;
- `newWidth` e `newHeight` sottraggono solo crop destro e inferiore dalla larghezza/altezza originali.

Questo significa che il rettangolo finale non rappresenta correttamente un crop combinato da tutti e quattro i lati.

### Impatto
- l'area OCR può risultare diversa da quella attesa dall'utente;
- il crop può diventare impreciso;
- la funzione cardine dell'addon può fornire risultati errati pur senza crash.

### Priorità
**Massima**.

### 7.2 Bug critico nella temporizzazione OCR
Funzione coinvolta: `ocrLoop()`.

Uso improprio di `threading.Event.wait(timeout=interval)` su evento normalmente settato durante l'esecuzione.

### Impatto
- l'intervallo può non essere rispettato;
- scansioni troppo ravvicinate;
- prestazioni degradate;
- comportamento incoerente rispetto alle impostazioni salvate.

### Priorità
**Massima**.

### 7.3 Fragilità nello stop del thread OCR
Funzione coinvolta: `script_ReadLiveOcr()`.

Se il thread non termina entro `join(timeout=2.0)`, il codice può comunque trattarlo come arrestato a livello logico e azzerare il riferimento.

### Impatto
- stato interno potenzialmente incoerente;
- piccola finestra di race condition;
- possibili comportamenti non del tutto prevedibili in stop/start rapidi.

### Priorità
Alta.

### 7.4 `time.sleep(0.3)` in `event_gainFocus`
Funzione coinvolta: `event_gainFocus()`.

È presente una pausa bloccante durante la gestione del cambio focus.

### Impatto
- potenziale rallentamento percepibile;
- peggiore reattività su applicazioni con focus molto dinamico.

### Priorità
Media.

### 7.5 Filtro hardcoded del testo `"Play"`
Funzione coinvolta: `_handleOcrResult()`.

Il codice evita di parlare il testo `"Play"` indipendentemente dal contesto.

### Impatto
- comportamento non documentato;
- soppressione di testo potenzialmente legittimo;
- minore prevedibilità per l'utente.

### Priorità
Media.

### 7.6 Rischio collisione nomi profilo
Funzione coinvolta: `getProfilePath()`.

La sanitizzazione semplice del nome app può produrre collisioni tra applicazioni diverse.

### Impatto
- profili condivisi involontariamente;
- comportamento per-app non affidabile in alcuni casi limite.

### Priorità
Media.

### 7.7 Menu Preferenze agganciato in modo fragile
Funzione coinvolta: `createMenu()`.

Il codice usa un accesso posizionale:

```python
gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
```

### Impatto
- dipendenza fragile dalla struttura attuale del menu NVDA;
- possibile regressione futura se cambia l'ordine o la costruzione del menu.

### Priorità
Media.

## 8. Analisi della GUI
### Aspetti positivi
- Interfaccia ordinata in due tab.
- Dirty tracking corretto.
- Prompt in chiusura e cambio profilo.
- Validazione dei crop prima del salvataggio.
- Profili vuoti gestiti in modo coerente con il modello degli override.

### Fragilità
- Creare un profilo lo rende immediatamente attivo: scelta tecnicamente coerente, ma non chiarissima lato UX.
- Se l'utente inserisce nome vuoto, non c'è un feedback esplicito forte oltre al mancato effetto.
- `Restore Defaults` per il profilo globale non ripristina davvero i default del componente: mostra solo un messaggio informativo.

### Giudizio
La GUI è nel complesso buona, ma potrebbe essere resa più chiara e più rigorosa sul significato delle operazioni per profilo globale vs profili applicativi.

## 9. Documentazione e procedure di build
### Root README
Il `readme.md` di root è molto breve. Rimanda al documento HTML dell'addon e spiega che:
- `lionGui.wxg` va modificato con wxGlade;
- il codice generato finisce in `addon\globalPlugins`;
- poi basta zippare il contenuto della cartella `addon` e cambiare estensione in `nvda-addon`.

### Problemi del README
- È troppo sintetico.
- Contiene almeno un refuso (`chage` invece di `change`).
- Descrive una procedura di packaging molto debole e artigianale.
- Non documenta build ripetibile, test, compatibilità, rilascio, dipendenze o struttura del progetto.

### Addon readme HTML
Il file `addon/doc/en/readme.htm` descrive bene il concetto originario di LION, ma è chiaramente **datato**.

#### Problemi rilevati
- Refusi multipli: ad esempio `Intellligent`, `Automatic OCr`, `tV`, `mainlly`.
- Version history ferma a release storiche (`1.12`, `1.11`, `1.1`, `1.0`).
- Nessuna spiegazione esplicita delle nuove funzioni per-app di `Evolution Pro`.
- Descrizione del crop parzialmente disallineata con la logica attuale del codice.
- Linguaggio e struttura HTML molto essenziali.

### Giudizio documentale
La documentazione è il punto più debole del repository dopo i bug critici del backend.

Non è completa, non è aggiornata alla realtà della versione `2.0.0` e non rappresenta adeguatamente il valore distintivo dell'evoluzione del progetto.

## 10. Precisione e affidabilità complessiva
### Punti forti
- Architettura comprensibile.
- Funzionalità reali e utili.
- Buon livello di difesa da crash diretti.
- Supporto profili per-app concettualmente ben progettato.
- GUI pratica e abbastanza pulita.

### Punti deboli
- Crop geometrico calcolato in modo errato.
- Timing OCR potenzialmente non rispettato.
- Alcune scelte hardcoded non documentate.
- Documentazione arretrata e incompleta.
- Packaging descritto in modo non professionale.
- Modulo backend troppo monolitico.

### Verdetto tecnico
Il progetto è **valido come base funzionale**, ma **non ancora pienamente solido**.

La logica generale è buona e l'idea è forte. Tuttavia esistono almeno due problemi critici che possono compromettere correttezza percepita e qualità d'uso reale:
1. bug nel crop;
2. bug nel rispetto dell'intervallo OCR.

Finché questi due punti non vengono corretti, non è prudente considerare l'addon pienamente affidabile dal punto di vista operativo.

## 11. Priorità di correzione consigliate
### Priorità 1 - immediata
1. Correggere la formula di `cropRectLTWH()`.
2. Correggere la logica di attesa in `ocrLoop()`.
3. Rendere più sicura la gestione di stop/start del thread OCR.

### Priorità 2 - breve termine
4. Rimuovere o rendere configurabile il filtro hardcoded `"Play"`.
5. Eliminare `time.sleep(0.3)` dal focus event o sostituirlo con soluzione non bloccante.
6. Rendere più robusta la generazione del nome file dei profili.
7. Ridurre dipendenza dall'indice del menu Preferenze di NVDA.

### Priorità 3 - manutenzione e qualità
8. Aggiornare completamente `addon/doc/en/readme.htm`.
9. Espandere `readme.md` con build, test, struttura progetto, packaging e compatibilità.
10. Valutare una rifattorizzazione moderata di `__init__.py` in moduli separati.

## 12. Giudizio finale
### Stato del progetto
Buono, reale, attivo e tecnicamente interessante.

### Solidità delle procedure
Media: buona intenzione architetturale, ma presenza di punti critici nel cuore del loop OCR e nel crop.

### Completezza funzionale
Buona: le funzioni offerte sono concrete e non banali.

### Precisione e affidabilità
Medie tendenti al buono come design, ma indebolite in modo significativo da due bug centrali.

### Documentazione e manutenzione
Sotto il livello desiderabile per un add-on NVDA maturo.

## 13. Conclusione operativa per il manutentore
LION Evolution Pro merita di essere proseguito: non appare un progetto fragile per concezione, ma un progetto valido con alcuni punti tecnici da correggere subito.

La base è promettente. Con correzione di crop e timing OCR, aggiornamento documentazione e un piccolo consolidamento architetturale, l'add-on può diventare sensibilmente più affidabile, preciso e professionale.
