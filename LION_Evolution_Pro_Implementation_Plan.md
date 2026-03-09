# Piano Tecnico di Implementazione — LION Evolution Pro

Versione piano: 1.0
Data: 2026-03-09
Repository: https://github.com/Nemex81/LION-Evolution-Pro
Riferimento audit: `LION_Evolution_Pro_Complete_Audit_Report.md` v2.0

---

## Istruzioni per Copilot

Questo documento guida la correzione sistematica del codice di LION Evolution Pro.
Ogni intervento è descritto con:
- file esatto da modificare;
- funzione/classe coinvolta;
- codice da rimuovere e codice sostitutivo completo;
- motivazione tecnica;
- test di verifica.

**Regole da rispettare durante l'implementazione:**
1. Non modificare funzionalità non elencate in questo piano.
2. Non rinominare variabili o metodi esistenti salvo indicazione esplicita.
3. Non aggiungere dipendenze esterne non già presenti nel file.
4. Eseguire le modifiche nell'ordine indicato per ogni file: le priorità 1 hanno dipendenze tra loro.
5. Ogni modifica deve essere minimale e chirurgica rispetto al contesto circostante.
6. Mantenere lo stile di indentazione (tab) già presente in `__init__.py`.
7. Per `lionGui.py`: il file è generato da wxGlade, ma le modifiche indicate qui vanno applicate direttamente al `.py`; aggiornare `lionGui.wxg` in modo coerente è opzionale e secondario.

---

## FASE 1 — Correzioni critiche

### 1.1 — Correggere la formula di `cropRectLTWH()`

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `cropRectLTWH(self, r, cfg)`
**Priorità:** Massima

**Problema:**
La formula attuale contiene due difetti geometrici distinti.

- Difetto A (origine): `r.left + r.width` equivale a `r.right`, non a `r.left`. Per target diversi dallo schermo intero (dove `r.left > 0`) l'origine del rettangolo viene calcolata a partire dal bordo destro invece che dal sinistro.
- Difetto B (dimensioni): `newWidth` e `newHeight` sottraggono solo il crop del lato destro/inferiore dalla larghezza/altezza originali, senza compensare lo spostamento dell'origine già applicato a sinistra/sopra.

**Codice attuale da rimuovere:**
```python
newX = int((r.left + r.width) * cLeft / 100.0)
newY = int((r.top + r.height) * cUp / 100.0)
newWidth = int(r.width - (r.width * cRight / 100.0))
newHeight = int(r.height - (r.height * cDown / 100.0))
```

**Codice sostitutivo:**
```python
newX = int(r.left + r.width * cLeft / 100.0)
newY = int(r.top + r.height * cUp / 100.0)
newWidth = int(r.width * (1.0 - (cLeft + cRight) / 100.0))
newHeight = int(r.height * (1.0 - (cUp + cDown) / 100.0))
```

**Nota:** Non modificare il codice di clamping successivo (min/max su `newX`, `newY`, `newWidth`, `newHeight`): rimane corretto.

**Verifica matematica della formula:**
Esempio: finestra a posizione (200, 100), dimensioni 800×600, crop sinistro=10%, destro=10%, superiore=5%, inferiore=5%:
- `newX` = 200 + 800 × 0.10 = **280** ✓ (bordo sinistro + offset 10%)
- `newY` = 100 + 600 × 0.05 = **130** ✓
- `newWidth` = 800 × (1.0 − 0.20) = **640** ✓ (esclude 10% sin + 10% des)
- `newHeight` = 600 × (1.0 − 0.10) = **540** ✓

**Test manuale:**
1. Aprire una finestra browser con testo leggibile.
2. Configurare crop sinistro=20%, destro=20%, alto=0%, basso=0% con target "Current Window".
3. Attivare OCR live con NVDA+Alt+L.
4. Verificare che NVDA legga solo il testo della porzione centrale della finestra (40% di larghezza).
5. Ripetere con target "Navigator Object" su un controllo con posizione non nulla sullo schermo.
6. Verificare che il crop si applichi correttamente all'oggetto navigatore, non allo schermo intero.

---

### 1.2 — Correggere il timing del loop OCR in `ocrLoop()`

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `__init__` (inizializzazione attributi), `ocrLoop()`, `script_ReadLiveOcr()`, `terminate()`
**Priorità:** Massima

**Problema:**
`self._ocrActive` è mantenuto settato durante il funzionamento normale. `threading.Event.wait(timeout=T)` su un evento già settato ritorna immediatamente, quindi il loop OCR non rispetta l'intervallo configurato e può girare senza pausa.

**Passo 1 — Aggiungere `_stopSleep` in `__init__`:**

Individuare nel metodo `__init__` la riga:
```python
self._ocrActive = threading.Event()
```
Aggiungere immediatamente dopo:
```python
self._stopSleep = threading.Event()
```

**Passo 2 — Modificare `ocrLoop()`:**

Individuare nel corpo del loop la riga:
```python
self._ocrActive.wait(timeout=interval)
```
Sostituirla con:
```python
self._stopSleep.clear()
self._stopSleep.wait(timeout=interval)
```

**Passo 3 — Modificare lo stop in `script_ReadLiveOcr()`:**

Individuare il blocco che ferma l'OCR (dove viene chiamato `self._ocrActive.clear()`).
Aggiungere immediatamente dopo quella riga:
```python
self._stopSleep.set()
```
Questo interrompe immediatamente il `wait` corrente nel loop, evitando attese fino a timeout prima dello stop effettivo.

**Passo 4 — Modificare lo stop in `terminate()`:**

Individuare nel metodo `terminate()` la riga che chiama `self._ocrActive.clear()`.
Aggiungere immediatamente dopo:
```python
if hasattr(self, '_stopSleep'):
    self._stopSleep.set()
```

**Logica risultante:**
- Durante il run: `_ocrActive` è settato, `_stopSleep` è normalmente **non settato**.
- Il loop esegue OCR, poi chiama `_stopSleep.clear()` + `_stopSleep.wait(timeout=interval)`: attende realmente fino a `interval` secondi.
- Allo stop: `_ocrActive` viene pulito, `_stopSleep` viene settato → il `wait` corrente si interrompe immediatamente.

**Test manuale:**
1. Aprire il Monitoraggio risorse di Windows (Task Manager → Prestazioni → CPU).
2. Avviare NVDA con l'add-on caricato.
3. Attivare OCR live con NVDA+Alt+L con intervallo impostato a 2 secondi.
4. Osservare che il processo `nvda.exe` non mostra picchi di CPU continui.
5. Verificare con un timer che NVDA annunci testo OCR circa ogni 2 secondi, non in modo continuo.
6. Disattivare l'OCR live: verificare che si fermi in meno di 1 secondo (non dopo `join(timeout=2.0)`).

---

### 1.3 — Sostituire `wx.Frame` con `wx.Dialog` in `frmMain`

**File:** `addon/globalPlugins/lion/lionGui.py`
**Classe:** `frmMain`
**Priorità:** Alta

**Problema:**
Usare `wx.Frame` per un dialogo impostazioni in un add-on NVDA causa problemi di accessibilità: il focus non viene annunciato correttamente all'apertura, la navigazione da tastiera è meno prevedibile e il tasto Esc non chiude la finestra per convenzione di sistema.

**Passo 1 — Cambiare la classe base:**

Riga attuale:
```python
class frmMain(wx.Frame):
```
Sostituire con:
```python
class frmMain(wx.Dialog):
```

**Passo 2 — Aggiornare `__init__` della classe:**

Riga attuale nella `__init__` di `frmMain`:
```python
wx.Frame.__init__(self, parent, id=wx.ID_ANY, ...)
```
Sostituire con:
```python
wx.Dialog.__init__(self, parent, id=wx.ID_ANY, ...)
```
I parametri (`title`, `pos`, `size`, `style`) rimangono identici, tranne il flag di stile:
- Rimuovere `wx.DEFAULT_FRAME_STYLE` se presente.
- Usare `wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER` per mantenere la ridimensionabilità.

**Passo 3 — Gestire la chiusura con Esc:**

In `wx.Dialog`, premere Esc genera un evento `wx.EVT_CLOSE` o `wx.ID_CANCEL`. Verificare che il metodo `onClose` (o equivalente) che già gestisce il dirty tracking venga chiamato correttamente anche su Esc. Se non è già associato a `wx.EVT_CLOSE`, aggiungere:
```python
self.Bind(wx.EVT_CLOSE, self.onClose)
```
dove `onClose` è il metodo che gestisce la conferma in chiusura (già presente nel file).

**Passo 4 — Usare `ShowModal()` all'apertura:**

Individuare nel backend (`__init__.py`) il punto dove viene creata e mostrata la finestra GUI (tipicamente in `onSettings` o nella callback del menu).

Se la finestra viene mostrata con `.Show()`, valutare di passare a `.ShowModal()` per garantire modalità corretta. Se si usa `.ShowModal()`, assicurarsi che venga chiamato `.Destroy()` dopo la chiusura, non solo `.Hide()`.

Se mantenere `.Show()` non-modale è un requisito funzionale, lasciare `.Show()` ma verificare comunque la corretta ricezione del focus da parte di NVDA all'apertura.

**Test manuale:**
1. Aprire le impostazioni LION dal menu NVDA → Preferenze → LION.
2. Verificare che NVDA annunci la finestra e il primo controllo focalizzato immediatamente all'apertura.
3. Navigare con Tab tra i controlli: verificare che NVDA legga ogni controllo.
4. Premere Esc: verificare che venga mostrata la conferma di chiusura se ci sono modifiche non salvate.
5. Premere Esc senza modifiche: verificare che la finestra si chiuda direttamente.

---

## FASE 2 — Correzioni di stabilità

### 2.1 — Rendere più sicuro lo stop del thread OCR

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `script_ReadLiveOcr()`
**Priorità:** Alta

**Problema:**
Dopo `self._ocrThread.join(timeout=2.0)`, il codice azzera `self._ocrThread = None` anche se il thread è ancora vivo, creando una potenziale race condition.

**Codice attuale (schema):**
```python
self._ocrActive.clear()
if self._ocrThread:
    self._ocrThread.join(timeout=2.0)
    self._ocrThread = None
    ui.message(_("OCR stopped"))
```

**Codice sostitutivo:**
```python
self._ocrActive.clear()
self._stopSleep.set()
if self._ocrThread and self._ocrThread.is_alive():
    self._ocrThread.join(timeout=3.0)
    if self._ocrThread.is_alive():
        logHandler.log.warning(
            "LION: OCR thread did not stop within timeout. "
            "Proceeding anyway."
        )
self._ocrThread = None
ui.message(_("OCR stopped"))
```

**Nota:** Il timeout è aumentato a 3.0 secondi perché con la correzione 1.2 il thread si interrompe immediatamente al `_stopSleep.set()`, quindi nella pratica il join terminerà quasi istantaneamente. Il timeout più lungo è solo una rete di sicurezza.

**Test manuale:**
1. Avviare OCR live con NVDA+Alt+L.
2. Premere NVDA+Alt+L nuovamente entro 0.5 secondi per fermare: verificare che NVDA annunci lo stop senza errori nel log.
3. Premere NVDA+Alt+L più volte in rapida successione: verificare che non si avviino thread multipli (controllare nel log NVDA che non compaiano errori `_ocrLock` o eccezioni di threading).
4. Aprire il log NVDA (NVDA → Strumenti → Visualizza Log): verificare assenza di stack trace relativi al thread OCR.

---

### 2.2 — Rimuovere il filtro hardcoded del testo `"Play"`

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `_handleOcrResult()`
**Priorità:** Media

**Problema:**
Il testo `"Play"` viene sempre soppresso indipendentemente dal contesto, con comportamento non documentato e non configurabile.

**Codice attuale (schema):**
```python
if ratio < configuredThreshold and info.text != "" and info.text != "Play":
    # ... parla il testo
```

**Codice sostitutivo:**
```python
if ratio < configuredThreshold and info.text.strip():
    # ... parla il testo
```

**Nota:** `info.text.strip()` sostituisce il doppio controllo `!= ""` e `!= "Play"` con una verifica più pulita che esclude solo stringhe vuote o composte da soli spazi. Non aggiungere altri filtri hardcoded.

**Test manuale:**
1. Avviare OCR live su una pagina web che contiene un pulsante o testo con scritta "Play" (es. YouTube con controlli visibili).
2. Verificare che NVDA legga il testo "Play" quando rilevato dall'OCR.
3. Verificare che il comportamento anti-repeat funzioni normalmente anche per questo testo.

---

### 2.3 — Eliminare `time.sleep(0.3)` da `event_gainFocus()`

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `event_gainFocus(self, obj, nextHandler)`
**Priorità:** Media

**Problema:**
Una pausa bloccante di 300ms nell'handler di focus viene eseguita sul thread principale di NVDA, degradando la reattività generale.

**Codice attuale (schema):**
```python
def event_gainFocus(self, obj, nextHandler):
    try:
        appName = obj.appModule.appName if obj.appModule else "global"
        self._ocrActive.clear()
        time.sleep(0.3)
        self._loadProfileForApp(appName)
        self._ocrActive.set()
    except Exception:
        logHandler.log.exception("LION: error in gainFocus")
    nextHandler()
```

**Codice sostitutivo:**
```python
def event_gainFocus(self, obj, nextHandler):
    try:
        appName = obj.appModule.appName if obj.appModule else "global"
        self._ocrActive.clear()
        self._stopSleep.set()
        self._loadProfileForApp(appName)
        self._ocrActive.set()
        self._stopSleep.clear()
    except Exception:
        logHandler.log.exception("LION: error in gainFocus")
    nextHandler()
```

**Spiegazione:** Invece di bloccare il thread per 300ms, il codice ora:
1. Ferma il loop OCR in modo pulito settando `_stopSleep` (interrompe il wait attuale).
2. Carica il profilo della nuova applicazione.
3. Riavvia il loop pulendo `_stopSleep` e settando `_ocrActive`.

Il profilo viene caricato solo se l'OCR è attivo (controllare: `_loadProfileForApp` deve essere chiamata solo se il loop è in esecuzione; aggiungere un guard `if self._ocrThread and self._ocrThread.is_alive()` se necessario).

**Test manuale:**
1. Con OCR live attivo, passare tra varie applicazioni usando Alt+Tab.
2. Verificare che NVDA non mostri rallentamenti o ritardi percepibili nel leggere i controlli delle nuove finestre.
3. Verificare nel log NVDA che il cambio di profilo avvenga correttamente ad ogni cambio applicazione.

---

### 2.4 — Rimuovere il codice di sviluppo commentato in rumeno

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `script_ReadLiveOcr()` (o area circostante)
**Priorità:** Bassa

**Operazione:** Localizzare e rimuovere il seguente blocco commentato:

```python
#		if repeat>=2:
#			ui.message("o sa vine profile")
```

Rimuovere le due righe interamente. Non sostituirle con altro.

**Test:** Verificare che `__init__.py` non contenga più la stringa `o sa vine profile`.

---

### 2.5 — Rendere più robusto il nome file del profilo

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `getProfilePath(self, appName)` (o equivalente)
**Priorità:** Media

**Problema:**
La sanitizzazione semplice del nome app può produrre collisioni tra applicazioni con nomi diversi che diventano identici dopo il filtraggio.

**Codice attuale (schema):**
```python
safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
return os.path.join(self._profilesDir, safeName + ".json")
```

**Codice sostitutivo:**
```python
import hashlib

safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
if not safeName:
    safeName = "unknown"
# Aggiunge un suffisso hash breve per prevenire collisioni tra nomi
# che producono lo stesso safeName dopo sanitizzazione.
hash_suffix = hashlib.md5(appName.encode("utf-8")).hexdigest()[:6]
return os.path.join(self._profilesDir, f"{safeName}_{hash_suffix}.json")
```

**Nota importante sulla migrazione:** Questo cambio modifica i nomi dei file profilo esistenti. Aggiornare `loadProfiles()` o la funzione di enumerazione profili per gestire la migrazione dei file vecchi (senza suffisso hash) verso i nuovi nomi, oppure mantenere retrocompatibilità cercando prima il file con hash e poi quello senza.

**Schema di migrazione retrocompatibile:**
```python
# In getProfilePath, dopo aver calcolato newPath:
oldPath = os.path.join(self._profilesDir, safeName + ".json")
newPath = os.path.join(
    self._profilesDir, f"{safeName}_{hash_suffix}.json"
)
# Se esiste il vecchio file e non quello nuovo, rinominare automaticamente.
if os.path.exists(oldPath) and not os.path.exists(newPath):
    try:
        os.rename(oldPath, newPath)
    except OSError:
        logHandler.log.exception(
            f"LION: could not migrate profile {oldPath}"
        )
return newPath
```

**Test manuale:**
1. Creare un profilo per un'applicazione corrente.
2. Verificare che il file JSON del profilo sia creato con il nuovo nome `nomeapp_xxxxxx.json`.
3. Riavviare NVDA: verificare che il profilo venga caricato correttamente.
4. Se presenti profili vecchi senza suffisso hash, verificare che vengano migrati automaticamente.

---

### 2.6 — Ridurre fragilità accesso al menu Preferenze NVDA

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `createMenu()` (o equivalente)
**Priorità:** Media

**Problema:**
Accesso posizionale al menu tramite `GetMenuItems()[0].GetSubMenu()` dipende dalla struttura interna del menu NVDA, che potrebbe cambiare in versioni future.

**Codice attuale (schema):**
```python
prefsMenu = gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
```

**Codice sostitutivo con accesso per titolo:**
```python
prefsMenu = None
try:
    for item in gui.mainFrame.sysTrayIcon.menu.GetMenuItems():
        # Il menu Preferenze è identificabile dal suo titolo localizzato.
        subMenu = item.GetSubMenu()
        if subMenu is not None:
            # Verifica che sia il menu Preferenze controllando
            # la presenza di voci tipiche (es. Settings/Impostazioni).
            # Fallback: usa il primo sottomenu disponibile.
            prefsMenu = subMenu
            break
except Exception:
    logHandler.log.exception("LION: could not find NVDA Preferences menu")

if prefsMenu is None:
    logHandler.log.warning(
        "LION: Preferences menu not found, LION menu not registered."
    )
    return
```

**Nota:** NVDA espone anche `gui.mainFrame.sysTrayIcon.preferencesMenu` in alcune versioni. Se disponibile, usare preferibilmente quello:
```python
if hasattr(gui.mainFrame.sysTrayIcon, 'preferencesMenu'):
    prefsMenu = gui.mainFrame.sysTrayIcon.preferencesMenu
else:
    # fallback con iterazione come sopra
    ...
```

**Test manuale:**
1. Avviare NVDA con l'add-on installato.
2. Aprire il menu NVDA dalla tray icon.
3. Navigare a Preferenze: verificare che la voce "LION" sia presente nel sottomenu.
4. Selezionare la voce LION: verificare che si apra la finestra impostazioni.

---

## FASE 3 — Osservazioni aggiuntive per Copilot (non bloccanti)

### 3.1 — Risoluzione schermo catturata a import-time

**File:** `addon/globalPlugins/lion/__init__.py`
**Posizione:** Definizione di classe o `__init__`

`resX` e `resY` vengono probabilmente catturati con `ctypes.windll.user32.GetSystemMetrics()` al momento del caricamento del modulo. Se la risoluzione cambia (monitor aggiuntivo, cambio risoluzione) dopo il caricamento dell'addon, i valori non vengono aggiornati.

**Correzione opzionale:** spostare la lettura della risoluzione dentro `rebuildTargets()` o all'inizio di ogni ciclo OCR invece che a livello di classe:
```python
# All'inizio di rebuildTargets() o nel loop OCR:
resX = ctypes.windll.user32.GetSystemMetrics(0)
resY = ctypes.windll.user32.GetSystemMetrics(1)
```

---

### 3.2 — Pattern dummy NVDAObject in `_handleOcrResult()`

**File:** `addon/globalPlugins/lion/__init__.py`
**Funzione:** `_handleOcrResult()`

Il codice crea un oggetto anonimo per passarlo a `result.makeTextInfo()`:
```python
o = type('NVDAObjects.NVDAObject', (), {})()
info = result.makeTextInfo(o, textInfos.POSITION_ALL)
```

Questo pattern è fragile: se il recognizer accede ad attributi specifici di `NVDAObject`, il dummy object genera `AttributeError`. Questo non è un bug attuale confermato (il codice funziona), ma è un punto di fragilità da monitorare.

**Azione consigliata:** aggiungere un try/except più specifico attorno a questa chiamata e loggare in modo dettagliato se si verifica un `AttributeError` qui, per facilitare il debug in versioni future di NVDA.

---

## FASE 4 — Aggiornamento documentazione

### 4.1 — Aggiornare `addon/doc/en/readme.htm`

**File:** `addon/doc/en/readme.htm`
**Priorità:** Media

Riscrivere il file HTML aggiornando:

1. **Titolo:** Aggiornare a `LION Evolution Pro - Live Intelligent OCR for NVDA`.

2. **Sezione "What is it":** Descrivere la versione 2.0 con profili per applicazione. Esempio:
   > LION Evolution Pro is an advanced version of LION, featuring application-specific OCR profiles. Each application can have its own crop, interval, target, and similarity settings, which are automatically applied when that application receives focus.

3. **Sezione "What can I do with it":** Mantenere il testo originale, aggiungere il caso d'uso dei profili per giochi e applicazioni inaccessibili.

4. **Sezione "How do I use it":** Aggiungere descrizione della GUI a due tab (Profiles e Settings) e del flusso di creazione profilo.

5. **Sezione "Settings":** Aggiornare l'elenco delle impostazioni:
   - OCR interval (0.1–10 secondi)
   - OCR target (full screen, current window, navigator object, focus object)
   - Crop left/right/top/bottom (percentuali)
   - Similarity threshold (0.0–1.0)
   - Profili per applicazione

6. **Sezione "What's new":** Aggiungere:
   ```html
   <h2>Version 2.0.0</h2>
   <ol>
   <li>Application-specific OCR profiles.</li>
   <li>New settings GUI with Profiles and Settings tabs.</li>
   <li>Automatic profile switching on application focus change.</li>
   <li>Global config with per-app overrides.</li>
   <li>NVDA compatibility updated to 2024.1.0+.</li>
   </ol>
   ```

7. **Correggere tutti i refusi:**
   - `Intellligent` → `Intelligent`
   - `Automatic OCr` → `Automatic OCR`
   - `tV` → `TV`
   - `mainlly` → `mainly`

---

### 4.2 — Aggiornare `readme.md` nella root

**File:** `readme.md`
**Priorità:** Media

Sostituire il contenuto con un README più completo. Struttura minima:

```markdown
# LION Evolution Pro — Live Intelligent OCR for NVDA

LION Evolution Pro is an NVDA add-on for live OCR of screen portions,
with application-specific profiles.
Based on [LION by vortex1024](https://github.com/vortex1024/LION).

## Features
- Live OCR with configurable interval and target area
- Per-application profiles with automatic switching
- Crop configuration (left, right, top, bottom percentage)
- Similarity threshold to avoid repeating unchanged text
- Settings GUI with Profiles and Settings tabs

## Requirements
- NVDA 2024.1.0 or later
- Windows (NVDA's built-in OCR engine)

## Installation
Download the `.nvda-addon` file from the Releases page and open it with NVDA.

## Building from source
1. Clone the repository.
2. If modifying the GUI: open `lionGui.wxg` in [wxGlade](https://github.com/wxGlade/wxGlade),
   make changes and generate code (File → Generate code).
   The output `lionGui.py` will be placed in `addon/globalPlugins/lion/`.
3. Package: zip the contents of the `addon/` folder
   and rename the archive with `.nvda-addon` extension.

## Testing
1. Install the built `.nvda-addon` file in NVDA.
2. Restart NVDA.
3. Open a window with visible text.
4. Press NVDA+Alt+L to start live OCR.
5. Verify NVDA reads detected text at the configured interval.
6. Open preferences via NVDA Menu → Preferences → LION.

## Compatibility
- Minimum NVDA version: 2024.1.0
- Last tested: 2025.3.2

## Credits
- Original LION: Stefan Moisei (vortex1024)
- LION Evolution Pro: Nemex81
```

---

### 4.3 — Aggiornare `addon/manifest.ini`

**File:** `addon/manifest.ini`
**Priorità:** Bassa

Dopo il completamento dei test sulle build NVDA 2026.x:
```ini
lastTestedNVDAVersion = 2026.x.x
```
Aggiornare il valore alla versione effettiva testata.

---

## Ordine di esecuzione consigliato per Copilot

Eseguire le modifiche nel seguente ordine per minimizzare rischi di regressione:

1. `__init__.py` — Fix 1.1 (crop formula): modifica isolata, nessuna dipendenza.
2. `__init__.py` — Fix 1.2 passo 1 (aggiungere `_stopSleep` in `__init__`): prerequisito per i passi successivi.
3. `__init__.py` — Fix 1.2 passi 2-4 (ocrLoop, script_ReadLiveOcr, terminate).
4. `__init__.py` — Fix 2.1 (stop thread): dipende da `_stopSleep` già presente.
5. `__init__.py` — Fix 2.3 (rimuovere sleep in gainFocus): dipende da `_stopSleep`.
6. `__init__.py` — Fix 2.4 (rimuovere codice rumeno): operazione semplice e isolata.
7. `__init__.py` — Fix 2.2 (rimuovere filtro Play): operazione semplice e isolata.
8. `__init__.py` — Fix 2.5 (nomi profilo): aggiungere import hashlib in cima al file se non presente.
9. `__init__.py` — Fix 2.6 (menu fragile): modifica isolata.
10. `lionGui.py` — Fix 1.3 (wx.Frame → wx.Dialog): modificare dopo aver stabilizzato il backend.
11. Documentazione: `readme.htm`, `readme.md`, `manifest.ini`.

---

## Criteri di accettazione globali

Il piano è considerato completamente implementato quando:
1. NVDA non produce eccezioni nel log durante un ciclo normale di OCR live (avvio, funzionamento, stop).
2. Il crop applicato corrisponde visivamente all'area attesa per tutti i target (schermo intero, finestra corrente, navigator object).
3. Il loop OCR rispetta l'intervallo configurato (misurabile con timer esterno, tolleranza ±10%).
4. La finestra impostazioni LION viene annunciata correttamente da NVDA all'apertura senza intervento manuale.
5. Il tasto Esc chiude la finestra impostazioni (con prompt se dirty).
6. I profili per applicazione si attivano automaticamente al cambio focus senza ritardi percepibili.
7. Il log NVDA non contiene warning `LION:` durante il funzionamento normale.
8. Il file `addon/doc/en/readme.htm` non contiene refusi e descrive le funzionalità della versione 2.0.0.
