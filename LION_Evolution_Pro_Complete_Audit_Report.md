# Rapporto di audit completo - LION Evolution Pro (revisione validata)

Data audit: 2026-03-09
Repository: https://github.com/Nemex81/LION-Evolution-Pro
Ramo analizzato: `master`
Commit osservato tramite API contenuti: `33d14daf36aee3f1982329c712f1e1642a714b51`
Versione rapporto: 2.0 (revisione critica validata)

---

## 1. Scopo
Questo rapporto documenta un audit statico approfondito del repository **LION Evolution Pro**, con attenzione a:
- stato attuale del progetto;
- qualità architetturale dell'add-on NVDA;
- solidità delle procedure;
- completezza delle funzionalità offerte;
- errori, refusi, imprecisioni e fragilità che possono compromettere precisione, stabilità o corretto funzionamento.

L'audit è basato sulla lettura integrale dei file effettivamente presenti nel repository:
- `readme.md`
- `addon/manifest.ini`
- `addon/globalPlugins/lion/__init__.py`
- `addon/globalPlugins/lion/lionGui.py`
- `addon/doc/en/readme.htm`

Questa versione incorpora la revisione critica del primo rapporto, che ha identificato tre imprecisioni tecniche, due omissioni rilevanti e una raccomandazione vaga. Tutti e cinque i punti sono stati corretti.

---

## 2. Stato attuale del progetto

Il repository è un add-on NVDA reale, strutturalmente riconoscibile e tecnicamente funzionante.

### Struttura osservata

```
Root repository:
  .github/
  .gitignore
  .vscode/
  addon/
  copilot docs/
  lionGui.wxg
  readme.md

addon/:
  doc/
  globalPlugins/
  manifest.ini

addon/globalPlugins/lion/:
  __init__.py
  lionGui.py
```

### Valutazione sintetica dello stato

Il progetto è attivo, ordinato e dotato di una logica runtime concreta. La separazione tra backend OCR e GUI è reale. La presenza del file `lionGui.wxg` indica una base progettuale per la manutenzione grafica dell'interfaccia tramite wxGlade.

Il progetto mostra segnali di maturazione incompleta soprattutto su: documentazione utente non aggiornata, packaging artigianale, compatibilità non confermata sulle release NVDA più recenti e alcuni residui di codice di sviluppo non rimossi.

---

## 3. Manifest e compatibilità

Contenuto rilevante di `addon/manifest.ini`:

```ini
name = LionEvolutionPro
summary = "LION Evolution Pro - Advanced OCR for NVDA"
version = 2.0.0
author = "Nemex81 ..., based on work by Stefan Moisei"
description = "Live OCR with application-specific profiles. Based on LION by vortex1024."
docFileName = readme.htm
minimumNVDAVersion = 2024.1.0
lastTestedNVDAVersion = 2025.3.2
```

### Punti positivi
- Nome add-on coerente con il codice.
- Descrizione aderente alla funzione principale.
- Compatibilità minima e ultima versione testata esplicitate.
- Attributo `docFileName` correttamente impostato.

### Punti deboli
- Non risulta conferma esplicita di test su NVDA 2026.x.
- La documentazione utente interna è ferma a versioni storiche (`1.12`, `1.11`, `1.1`, `1.0`) e non riflette la realtà della versione `2.0.0`, creando un disallineamento tra metadati del manifest e documentazione pubblica.

---

## 4. Architettura dell'add-on

### Componente backend (`__init__.py`)

Il backend implementa:
- configurazione globale in `config.conf["lion"]` con `confspec` dichiarato;
- profili per-app in file JSON nella cartella `profiles` sotto la configurazione NVDA;
- merge configurazione globale e override applicativi tramite `getEffectiveConfig()`;
- cambio automatico profilo al cambio focus tramite `event_gainFocus()`;
- thread OCR separato con `threading.Event` per start/stop;
- cache anti-ripetizione del testo OCR per chiave `(appName, targetIndex)`;
- menu impostazioni integrato nel menu Preferenze di NVDA;
- gesture `NVDA+Alt+L` per attivare/disattivare l'OCR live.

### Componente GUI (`lionGui.py`)

La GUI implementa:
- finestra con due tab (`Profiles` e `Settings`);
- elenco profili con stato;
- creazione/cancellazione/selezione profili;
- salvataggio esplicito delle impostazioni;
- restore defaults per profili applicativi;
- dirty tracking con conferma in chiusura e in cambio profilo.

### Giudizio architetturale

L'impianto è sopra la media dei comuni add-on NVDA amatoriali. La separazione logica/interfaccia è reale e la strategia "global config + override per applicazione" è semplice, efficace e manutenibile.

### Limiti architetturali

`__init__.py` supera i 30 KB e concentra in un unico modulo: persistenza profili, gestione thread, geometria crop, OCR, anti-repeat, menu e gestione focus. Questo non rompe l'addon ma riduce modularità, testabilità e facilità di manutenzione futura.

---

## 5. Solidità delle procedure

### 5.1 Gestione profili

**Aspetti positivi:**
- I profili salvano solo gli override rispetto al globale.
- I profili legacy vengono normalizzati automaticamente al primo caricamento.
- I profili vuoti `{}` sono supportati come "uguale al globale" ma persistenti.
- Il cambio focus attiva automaticamente il profilo associato all'applicazione.

**Problema — rischio collisione nomi profilo:**

Il nome file del profilo è derivato filtrando il nome applicazione:

```python
safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
```

Nomi applicazione diversi che producono lo stesso `safeName` dopo il filtro condividerebbero involontariamente lo stesso file JSON di profilo. Non è presente una strategia più robusta basata su hash o nome esteso stabile.

### 5.2 Gestione thread OCR

**Aspetti positivi:**
- Thread OCR dedicato e separato dal thread principale NVDA.
- Avvio protetto da `_ocrLock` per evitare start duplicati.
- `terminate()` arresta e attende il thread prima di distruggere l'addon.
- Loop OCR con contatore errori consecutivi e backoff esponenziale.

**Problema critico — temporizzazione:**

Nel loop `ocrLoop()` viene usato:

```python
self._ocrActive.wait(timeout=interval)
```

`_ocrActive` è un `threading.Event` **mantenuto settato** durante il normale funzionamento. Quando un `Event` è già settato, `wait(timeout=...)` ritorna **immediatamente**, ignorando il timeout. Questo significa che il loop OCR può girare senza alcuna pausa reale tra un'iterazione e la successiva.

**Impatto:**
- OCR molto più frequente del previsto;
- consumo CPU elevato;
- carico eccessivo su riconoscimento e capture screen;
- comportamento incoerente rispetto all'impostazione `interval` mostrata all'utente.

**Soluzione corretta:**

Usare due eventi separati: uno per il flag di run (`_ocrActive`) e uno dedicato all'interruzione del sleep (`_stopSleep`), normalmente non settato durante il run:

```python
# In __init__:
self._ocrActive = threading.Event()   # True = loop deve girare
self._stopSleep = threading.Event()   # Settato solo per interrompere il wait

# In ocrLoop():
while self._ocrActive.is_set():
    # ... esegui OCR ...
    self._stopSleep.clear()
    self._stopSleep.wait(timeout=interval)  # Attende interval O stop

# Per fermare il loop:
self._ocrActive.clear()
self._stopSleep.set()  # Interrompe il wait immediatamente
```

In questo modo `_stopSleep` è normalmente **non settato**, quindi `wait(timeout=interval)` funziona correttamente come timer interrompibile.

**Problema — fragilità stop/start:**

In `script_ReadLiveOcr()`, se il thread non termina entro `join(timeout=2.0)`, il codice lo considera comunque fermo e azzera `self._ocrThread`. Questo crea una finestra temporale in cui il thread precedente potrebbe essere ancora attivo mentre il backend ritiene di poterne avviare uno nuovo.

### 5.3 Gestione errori

**Aspetti positivi:**
Il codice protegge molti punti critici con `try/except`:
- import GUI;
- creazione menu;
- apertura dialogo;
- focus event;
- creazione recognizer OCR;
- capture bitmap;
- callback OCR;
- loop principale.

Questo riduce il rischio di crash diretto di NVDA.

**Limite:**
Alcuni errori vengono solo loggati e l'esecuzione continua in fallback. Questo è spesso corretto in un add-on NVDA ma può mascherare malfunzionamenti reali invece di esporli all'utente.

---

## 6. Validità e completezza delle funzionalità

**Funzionalità presenti e funzionanti per design:**
- OCR live di porzioni dello schermo;
- lettura differenziale del testo per evitare ripetizioni;
- selezione target OCR tra navigatore, schermo intero, finestra corrente e controllo corrente;
- crop configurabile per percentuale;
- soglia di similarità configurabile;
- intervallo OCR configurabile;
- profili specifici per applicazione;
- GUI di gestione profili e impostazioni;
- attivazione/disattivazione via gesture `NVDA+Alt+L`.

**Limiti funzionali reali:**
- La documentazione utente non descrive le funzionalità di "Evolution Pro".
- La formula di crop è errata, quindi il crop configurato può produrre risultati non corrispondenti a quanto atteso dall'utente.
- Il timing OCR live può non rispettare l'intervallo configurato.
- Il filtro hardcoded `"Play"` introduce un comportamento speciale non documentato.

---

## 7. Bug, errori e fragilità rilevate

### 7.1 Bug critico — Formula di crop errata (due difetti distinti)

**Funzione coinvolta:** `cropRectLTWH()`

Il codice attuale è:

```python
newX = int((r.left + r.width) * cLeft / 100.0)
newY = int((r.top + r.height) * cUp / 100.0)
newWidth = int(r.width - (r.width * cRight / 100.0))
newHeight = int(r.height - (r.height * cDown / 100.0))
```

**Difetto A — Origine del rettangolo:**

`r.left + r.width` equivale a `r.right`, cioè il bordo destro del rettangolo sorgente. Usare il bordo destro come base per calcolare lo spostamento dell'origine sinistra è geometricamente errato.

Per il target 1 (schermo intero) dove `r.left = 0`, il calcolo produce per coincidenza un valore accettabile. Per qualsiasi altro target (navigator object, finestra corrente, focus object) con `r.left > 0`, `newX` viene calcolato rispetto al bordo destro anziché al bordo sinistro, producendo valori che possono essere fuori schermo o non rappresentare l'area attesa.

**Difetto B — Dimensioni del rettangolo:**

`newWidth` sottrae solo il crop destro dalla larghezza, senza ridurre la larghezza in funzione anche del crop sinistro già applicato all'origine. Analogamente `newHeight` non considera il crop superiore già applicato a `newY`. Il risultato è un rettangolo le cui dimensioni non corrispondono all'area effettiva compresa tra i quattro bordi ritagliati.

**Formula corretta:**

```python
newX = int(r.left + r.width * cLeft / 100.0)
newY = int(r.top + r.height * cUp / 100.0)
newWidth = int(r.width * (1.0 - (cLeft + cRight) / 100.0))
newHeight = int(r.height * (1.0 - (cUp + cDown) / 100.0))
```

**Impatto:**
- Per target schermo intero: difetto A silente, difetto B attivo.
- Per tutti gli altri target: entrambi i difetti attivi.
- L'area OCR effettiva può risultare completamente diversa dall'area configurata.
- L'addon può produrre risultati parziali o errati senza alcun segnale d'errore.

**Priorità:** Massima.

---

### 7.2 Bug critico — Timing OCR non rispettato

**Funzione coinvolta:** `ocrLoop()`

`self._ocrActive.wait(timeout=interval)` su evento normalmente settato ritorna immediatamente. Il loop OCR può girare senza rispettare l'intervallo configurato.

**Impatto:**
- Intervallo OCR ignorato in condizioni normali.
- Consumo CPU e carico OCR molto più alti del necessario.
- Comportamento incoerente rispetto alle impostazioni mostrate all'utente.

**Soluzione:** Vedi §5.2 per il codice corretto.

**Priorità:** Massima.

---

### 7.3 Fragilità — Stop/start thread OCR non atomico

**Funzione coinvolta:** `script_ReadLiveOcr()`

Se il thread non termina entro `join(timeout=2.0)`, il riferimento viene azzerato comunque. Il backend può considerare il thread arrestato mentre il worker precedente è ancora in esecuzione.

**Impatto:**
- Piccola finestra di race condition in stop/start rapidi.
- Stato interno potenzialmente incoerente.

**Priorità:** Alta.

---

### 7.4 Problema accessibilità — GUI usa `wx.Frame` invece di `wx.Dialog`

**Funzione coinvolta:** `class frmMain(wx.Frame)` in `lionGui.py`

Questa è una delle omissioni più rilevanti rispetto alla prima versione del rapporto.

`frmMain` estende `wx.Frame` invece di `wx.Dialog` (o `gui.SettingsDialog`). Per un add-on NVDA, questa scelta introduce problemi di accessibilità di primo livello:

- `wx.Frame` non invia automaticamente l'evento di focus corretto agli screen reader al momento dell'apertura;
- la navigazione da tastiera può comportarsi diversamente da un dialogo modale;
- il tasto `Esc` non chiude un `wx.Frame` per convenzione di sistema, riducendo la prevedibilità per utenti non vedenti;
- NVDA usa `gui.SettingsDialog` o almeno `wx.Dialog` per tutti i propri dialoghi impostazioni.

Un add-on per screen reader che usa `wx.Frame` per la propria finestra impostazioni può risultare meno accessibile proprio agli utenti che dovrebbe servire.

**Impatto:** Problema di accessibilità su un add-on NVDA destinato a utenti non vedenti.

**Priorità:** Alta.

---

### 7.5 Problema — `time.sleep(0.3)` in `event_gainFocus`

**Funzione coinvolta:** `event_gainFocus()`

Pausa bloccante di 300ms dentro un event handler globale, eseguita sul thread di NVDA.

**Impatto:**
- Potenziale rallentamento percepibile.
- Peggiore reattività su applicazioni con cambio focus frequente.

**Priorità:** Media.

---

### 7.6 Problema — Filtro hardcoded del testo `"Play"`

**Funzione coinvolta:** `_handleOcrResult()`

```python
if ratio < configuredThreshold and info.text != "" and info.text != "Play":
```

Il testo `"Play"` viene sempre soppresso, indipendentemente dal contesto.

**Impatto:**
- Comportamento speciale non documentato.
- Soppressione di testo legittimo in contesti reali.
- Minore prevedibilità per l'utente.

**Priorità:** Media.

---

### 7.7 Problema — Residui di codice di sviluppo non rimossi

**File coinvolto:** `addon/globalPlugins/lion/__init__.py`

Nel corpo di `script_ReadLiveOcr()` è presente il seguente blocco commentato:

```python
#		if repeat>=2:
#			ui.message("o sa vine profile")
```

La stringa `"o sa vine profile"` è in lingua rumena (eredità del codice di Stefan Moisei, autore originale di LION). Se per qualsiasi motivo venisse decommentata produrrebbe un messaggio vocale in rumeno per tutti gli utenti. La stringa non è gestita dal sistema di traduzione NVDA (`addonHandler.initTranslation()`).

**Impatto:**
- Residuo di sviluppo non rimosso.
- Stringa non traducibile in un add-on internazionalizzato.
- Riduce la pulizia del sorgente.

**Priorità:** Bassa (ma da rimuovere).

---

### 7.8 Problema — Rischio collisione nomi profilo

**Funzione coinvolta:** `getProfilePath()`

Sanitizzazione semplice del nome app può causare collisioni tra applicazioni con nomi diversi ma identici dopo il filtro.

**Priorità:** Media.

---

### 7.9 Problema — Menu Preferenze agganciato in modo fragile

**Funzione coinvolta:** `createMenu()`

```python
gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
```

Accesso posizionale dipendente dalla struttura interna del menu NVDA. Una modifica futura a quell'ordine romperebbe silenziosamente la registrazione del menu.

**Priorità:** Media.

---

## 8. Analisi della GUI

### Aspetti positivi
- Interfaccia organizzata in due tab coerenti con i due domini (profili e impostazioni).
- Dirty tracking corretto con prompt in chiusura e in cambio profilo.
- Salvataggio bloccato se la validazione fallisce.
- Profili vuoti gestiti in modo coerente con il modello degli override.

### Fragilità

**Tipo finestra non adeguata per un add-on NVDA:**
`frmMain` estende `wx.Frame` invece di `wx.Dialog`. Questo è il problema più rilevante della GUI e impatta direttamente sull'accessibilità. Vedi §7.4 per l'analisi completa.

**Validazione crop parziale:**
La GUI valida che `cropLeft + cropRight < 100` e `cropUp + cropDown < 100`. Questo vincolo è necessario ma non sufficiente, perché la formula di crop sottostante è errata indipendentemente dai valori inseriti. La validazione garantisce l'assenza di valori estremi, non la correttezza geometrica del risultato.

**Creazione profilo:**
Creare un profilo lo rende immediatamente attivo. È una scelta tecnicamente coerente ma non immediatamente ovvia per l'utente. Non è presente feedback esplicito se il nome inserito è vuoto e l'utente conferma.

**Restore Defaults per profilo globale:**
`onRestoreDefaults()` per il profilo globale non ripristina i valori default dichiarati nel `confspec`, ma mostra solo un messaggio che rimanda al reset della configurazione NVDA. La funzione "Restore Defaults" non è semanticamente completa sul profilo principale.

---

## 9. Documentazione e procedure di build

### Root README (`readme.md`)

Il file è molto sintetico. Rimanda al documento HTML dell'addon per informazioni generali e descrive la procedura di build.

**Problemi rilevati:**
- Refuso: `chage` invece di `change`.
- Procedura di packaging molto artigianale (zip manuale + rinomina estensione).
- Nessuna documentazione di: struttura progetto, requisiti, test, compatibilità, rilascio, changelog.
- Non spiega le differenze tra LION originale e LION Evolution Pro.

### Addon README HTML (`addon/doc/en/readme.htm`)

Descrive bene il concetto originario di LION, ma è chiaramente datato e non aggiornato all'evoluzione del progetto.

**Refusi rilevati nel testo:**
- `Intellligent` (tripla l)
- `Automatic OCr` (maiuscola errata)
- `tV` (capitalizzazione incoerente)
- `mainlly` (doppia l)

**Problemi di contenuto:**
- Version history ferma a `1.12`, `1.11`, `1.1`, `1.0`.
- Nessuna documentazione delle nuove funzionalità di `Evolution Pro` (profili per-app, GUI a tab, gestione override).
- La descrizione del crop non corrisponde alla logica attuale del codice.
- Nessun riferimento alla gesture `NVDA+Alt+L` nel contesto della versione corrente.

### Giudizio documentale

La documentazione è il punto più debole del repository dopo i bug critici del backend. Non è aggiornata alla versione `2.0.0` e non rappresenta il valore reale del progetto.

---

## 10. Precisione e affidabilità complessiva

### Punti forti
- Architettura comprensibile e intenzionalmente separata.
- Funzionalità reali, utili e non banali.
- Buon livello di difesa da crash diretti di NVDA.
- Supporto profili per-app concettualmente ben progettato.
- GUI con dirty tracking e salvataggio esplicito.

### Punti deboli
- Formula di crop errata su due livelli distinti.
- Timing OCR non rispettato in condizioni normali.
- GUI non accessibile per tipo finestra (`wx.Frame` invece di `wx.Dialog`).
- Codice di sviluppo residuo non rimosso.
- Documentazione arretrata e non aggiornata.
- Packaging descritto in modo non professionale.
- Modulo backend troppo monolitico.

### Verdetto tecnico

Il progetto è **valido come base funzionale** ma **non ancora pienamente solido**.

Esistono almeno due bug centrali che possono compromettere l'affidabilità operativa reale (crop errato e timing OCR), un problema di accessibilità rilevante per un add-on NVDA (tipo finestra GUI) e documentazione non aggiornata. Finché questi punti non vengono corretti, non è prudente considerare l'addon pronto per un rilascio maturo.

---

## 11. Priorità di correzione consigliate

### Priorità 1 — Immediata (bloccanti per affidabilità)
1. **Correggere entrambi i difetti della formula `cropRectLTWH()`** (difetto A sull'origine, difetto B sulle dimensioni).
2. **Correggere la logica di attesa in `ocrLoop()`** usando un secondo evento `_stopSleep` separato (vedi §5.2).
3. **Sostituire `wx.Frame` con `wx.Dialog`** in `frmMain` per garantire accessibilità corretta.

### Priorità 2 — Breve termine (stabilità e correttezza)
4. Rendere più sicura la gestione di stop/start del thread OCR in `script_ReadLiveOcr()`.
5. Rimuovere o rendere configurabile il filtro hardcoded `"Play"`.
6. Eliminare `time.sleep(0.3)` dall'handler di focus o sostituirlo con soluzione non bloccante.
7. Rimuovere il blocco di codice commentato in rumeno da `script_ReadLiveOcr()`.
8. Rendere più robusta la generazione del nome file dei profili.
9. Ridurre dipendenza dall'indice posizionale del menu Preferenze di NVDA.

### Priorità 3 — Manutenzione e qualità
10. Aggiornare completamente `addon/doc/en/readme.htm` con le funzionalità di Evolution Pro, version history corretta e correzione di tutti i refusi.
11. Espandere `readme.md` con build, test, struttura progetto, packaging e compatibilità.
12. Valutare una rifattorizzazione moderata di `__init__.py` in moduli separati (es. `profiles.py`, `ocr.py`, `menu.py`).
13. Aggiornare `lastTestedNVDAVersion` dopo test su build NVDA 2026.x.

---

## 12. Giudizio finale

| Dimensione | Giudizio |
|---|---|
| Stato del progetto | Buono: reale, attivo, tecnicamente interessante |
| Solidità delle procedure | Media: buona intenzione, due bug critici nel cuore del sistema |
| Completezza funzionale | Buona: funzioni concrete, utili e non banali |
| Precisione e affidabilità | Media: design valido, indebolito da bug centrali |
| Accessibilità GUI | Insufficiente: `wx.Frame` non adeguato per add-on NVDA |
| Documentazione | Insufficiente: datata, non aggiornata, con refusi |
| Packaging | Insufficiente: artigianale, non ripetibile, non documentato |

---

## 13. Conclusione operativa per il manutentore

LION Evolution Pro merita di essere proseguito. Non è un progetto fragile per concezione, ma un progetto valido con punti tecnici ben identificati da correggere.

Le correzioni di priorità 1 (formula crop, timing OCR, tipo finestra GUI) sono le più urgenti e, da sole, migliorerebbero sensibilmente affidabilità, precisione e accessibilità dell'addon. Le correzioni di priorità 2 e 3 completano il quadro verso un rilascio maturo.

La base architetturale è promettente. Con le correzioni indicate, l'add-on può diventare un contributo solido e professionale all'ecosistema NVDA.
