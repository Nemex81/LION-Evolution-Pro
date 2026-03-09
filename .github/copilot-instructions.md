<!-- Copilot workspace bootstrap instructions for LION -->
# LION — Copilot / Agent bootstrap instructions

Scopo
-----
Fornire a Copilot/agent linee guida operative per essere immediatamente produttivi in questo repository.

Punti chiave
----------
- Tipo di progetto: NVDA addon (Python + WXGlade GUI). Vedi [addon/manifest.ini](addon/manifest.ini#L1).
- GUI: il file sorgente è `lionGui.wxg` (WXGlade). Generare `lionGui.py` solo con WXGlade.
- Packaging: zip della cartella `addon/` e rinominare estensione in `.nvda-addon` (vedi README).

File importanti
---------------
- [addon/manifest.ini](addon/manifest.ini#L1) — metadati addon.
- [lionGui.wxg](lionGui.wxg#L1) — sorgente GUI (modificare solo con WXGlade).
- [addon/globalPlugins/lion/__init__.py](addon/globalPlugins/lion/__init__.py#L1) — plugin NVDA principale (logica OCR, profili per-app, script `script_ReadLiveOcr`).
- `addon/globalPlugins/lion/lionGui.py` — file generato da WXGlade (non versionare manualmente se rigenerabile).
- `copilot docs/` — note e piani di implementazione utili per il contesto.

Comandi di build / test
-----------------------
- Non esiste una pipeline di build automatica nel repo. Operazioni manuali principali:
  - Generare GUI: aprire `lionGui.wxg` con WXGlade → File → Generate code → posizionare `lionGui.py` in `addon/globalPlugins/lion/`.
  - Creare pacchetto NVDA: zip della cartella `addon/`, rinominare `.zip` → `.nvda-addon`.

Convezioni di sviluppo
---------------------
- Modificare la GUI solo tramite WXGlade; non editare direttamente `lionGui.wxg` a mano.
- Le impostazioni globali sono in `config.conf["lion"]` definite in `__init__.py`.
- I profili per-app sono memorizzati in runtime in `addons/LionEvolutionPro/profiles/` (vari path di NVDA configPath); il plugin crea la directory se manca.

Indicazioni per l'agent
-----------------------
- Priorità: preservare le regole NVDA e le modifiche UX; non sovrascrivere file generati da WXGlade senza segnalarlo.
- Quando modifichi la GUI, suggerire i comandi WXGlade e includere il file generato nel PR con spiegazione.
- Applicare istruzioni `applyTo` per: `addon/globalPlugins/**`, `lionGui.wxg`, `copilot docs/**`.

Esempi di prompt utili
---------------------
- "Mostrami le funzioni pubbliche in [addon/globalPlugins/lion/__init__.py](addon/globalPlugins/lion/__init__.py#L1) e le dipendenze esterne." 
- "Rigenera `lionGui.py` da `lionGui.wxg` usando WXGlade e crea un breve changelog delle differenze." 
- "Aggiungi un controllo CI che verifica che `lionGui.py` sia aggiornato rispetto a `lionGui.wxg`."

Prossimi suggerimenti di automazioni
-----------------------------------
- Un agent per: generare `lionGui.py` tramite WXGlade (invocazione manuale), verificare file generati e creare PR con artefatti aggiornati.
- Un hook pre-commit che avvisi se `lionGui.wxg` è stato modificato senza la rigenerazione di `lionGui.py`.

Contatti / note
---------------
Questo file è un bootstrap: adattalo se emergono convenzioni aggiuntive o script di build.
