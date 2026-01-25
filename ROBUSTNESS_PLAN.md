# LionEvolution Pro — Robustness Plan (Phase 7)

**Target repository (fork):** `Nemex81/LION-Evolution-Pro`

**Upstream repository (original):** `vortex1024/LION`

**Target NVDA:** 2025.x (validate against NVDA Developer Guide constraints for add-ons: threading/event loop, UI access, configuration).

---

## Scope
This plan addresses the urgent issues identified in the current codebase to improve **robustness**, **correctness**, and **effective per-app behavior**.

Primary focus files:
- `addon/globalPlugins/lion/__init__.py`
- `addon/globalPlugins/lion/lionGui.py`

Non-goals (for this phase):
- Large refactors unrelated to stability.
- New OCR engines or external dependencies.
- Changing existing gestures.

---

## Phase 7 — Progress Tracker (update after each commit)

### 7.1 Threading & lifecycle (highest priority)
- [ ] 7.1.1 Replace global `active` flag with `threading.Event` stop mechanism.
- [ ] 7.1.2 Ensure only one live OCR worker thread runs at a time.
- [ ] 7.1.3 Ensure worker is stopped in `terminate()`.

### 7.2 UI thread safety (high priority)
- [ ] 7.2.1 Route all UI output from worker/callbacks via `queueHandler.queueFunction(queueHandler.eventQueue, ...)`.
- [ ] 7.2.2 Ensure no direct `ui.message()` runs on non-NVDA threads.

### 7.3 Dynamic target rectangles (high priority)
- [ ] 7.3.1 Recompute OCR target rectangle on every loop iteration.
- [ ] 7.3.2 Centralize target resolution logic (navigator / whole screen / foreground window / focus).

### 7.4 Profiles fully effective (high priority)
- [ ] 7.4.1 Add a unified accessor: profile → global fallback.
- [ ] 7.4.2 Make **interval**, **threshold**, **target**, and crop keys profile-aware.
- [ ] 7.4.3 Make spotlight crop keys (`spotlight_*`) profile-aware.

### 7.5 Efficiency & error handling (medium priority)
- [ ] 7.5.1 Reuse a `UwpOcr` instance; recreate only on failure.
- [ ] 7.5.2 Add safe error handling inside the OCR loop; optional backoff.

### 7.6 GUI & persistence alignment (medium priority)
- [ ] 7.6.1 Ensure GUI “Save Profile” persists all relevant keys (at minimum: crop*, threshold, interval, target).
- [ ] 7.6.2 Ensure GUI “Reset Profile” restores global values and refreshes controls.

### 7.7 Verification (required)
- [ ] 7.7.1 Manual test plan executed (start/stop stress test + app switching).
- [ ] 7.7.2 NVDA log review: no unhandled exceptions from LionEvolution Pro.

---

## Implementation instructions for coding agent

### Branch
Create a dedicated branch in the fork:
- `fix/robust-live-ocr-profiles`

### Commit style
- Small, atomic commits.
- After each commit, update this file’s checklist items relevant to that commit.

---

## 7.1 Threading & lifecycle — Technical spec

### Current problems
- Live OCR uses a global `active` flag and starts threads without a stop event.
- There is no guarantee the worker stops at NVDA shutdown.

### Required changes (`addon/globalPlugins/lion/__init__.py`)

1) Add internal state in `GlobalPlugin.__init__`:
- `self._stopEvent = threading.Event()`
- `self._workerThread = None`

2) Add private lifecycle helpers:
- `_startLiveOcr()`
- `_stopLiveOcr()`

Pseudo-implementation:
```python
def _startLiveOcr(self):
    if self._workerThread and self._workerThread.is_alive():
        return
    self._stopEvent.clear()
    self._workerThread = threading.Thread(target=self.ocrLoop, daemon=True)
    self._workerThread.start()

def _stopLiveOcr(self):
    self._stopEvent.set()
```

3) Update `script_ReadLiveOcr` to toggle based on `self._workerThread.is_alive()` (do not change gestures).

4) Update `terminate()` to call `_stopLiveOcr()` (best-effort; no blocking forever).

5) Update `ocrLoop` to:
- Loop while `not self._stopEvent.is_set()`
- Sleep using `self._stopEvent.wait(interval)` so it can stop quickly.

---

## 7.2 UI thread safety — Technical spec

### Current problems
- `ui.message()` can be called from OCR callbacks / worker thread.

### Required changes
1) Introduce a helper that always speaks via NVDA event queue:
```python
from queueHandler import queueFunction, eventQueue

def _speak(text: str):
    queueFunction(eventQueue, ui.message, text)
```

2) Replace all `ui.message(...)` calls triggered from callbacks or worker context with `_speak(...)`.

Targets to check:
- `recog_onResult` callback
- spotlight on-result callback inside `script_ScanSpotlight`
- error handling paths inside OCR loop

---

## 7.3 Dynamic target rectangles — Technical spec

### Current problems
- `self.targets` is computed once; target rectangles go stale when focus/window changes.

### Required changes
1) Centralize target rectangle computation:
```python
def _getCurrentTargetBaseRect(self):
    target = int(self._getSetting('target', config.conf['lion']['target']))
    if target == 0:
        return api.getNavigatorObject().location
    if target == 1:
        return locationHelper.RectLTWH(0, 0, self.resX, self.resY)
    if target == 2:
        return api.getForegroundObject().location
    return api.getFocusObject().location


def _getCurrentTargetRect(self):
    base = self._getCurrentTargetBaseRect()
    return self.cropRectLTWH(base)
```

2) In each OCR iteration, compute rect fresh and validate width/height.

---

## 7.4 Profiles fully effective — Technical spec

### Current problems
- Profiles exist but several runtime decisions still read `config.conf['lion']` directly.

### Required changes
1) Add unified accessor:
```python
def _getSetting(self, key, default=None):
    if self.currentProfileData and key in self.currentProfileData:
        return self.currentProfileData.get(key, default)
    return config.conf['lion'].get(key, default)
```

2) Use `_getSetting` for:
- `interval` (live loop)
- `threshold` (result filtering)
- `target` (target selection)
- `crop*` and `spotlight_crop*` (rect computation)

3) Ensure `event_gainFocus` sets `currentProfileData` correctly when switching apps.

---

## 7.5 Efficiency & error handling — Technical spec

### Current problems
- `UwpOcr()` is recreated each scan.

### Required changes
1) Keep `self._ocrRecognizer`:
```python
self._ocrRecognizer = None

def _getRecognizer(self):
    if self._ocrRecognizer is None:
        self._ocrRecognizer = contentRecog.uwpOcr.UwpOcr()
    return self._ocrRecognizer
```

2) On exceptions in OCR capture/recognize:
- log error
- optionally reset `self._ocrRecognizer = None`
- optionally speak a short error message (queued)

3) Optional backoff:
- after N consecutive errors, increase sleep interval temporarily or stop live OCR.

---

## 7.6 GUI & persistence alignment — Technical spec

### Current problems
- GUI saves only a subset of settings.

### Required changes (`addon/globalPlugins/lion/lionGui.py`)
1) When saving a profile, include at least:
- `cropLeft`, `cropRight`, `cropUp`, `cropDown`
- `threshold`, `interval`
- `target` (from `self.choiceTarget.GetSelection()`)

2) Validate numeric ranges:
- threshold must be 0..1
- interval must be > 0 (use a safe minimum like 0.1)

3) Reset profile should:
- delete the app profile
- set GUI fields back to global config values

---

## 7.7 Manual verification checklist (run before merging)

- [ ] Live OCR toggle (NVDA+Alt+L) pressed 10+ times: no crash, no multiple threads, correct feedback.
- [ ] Switch between apps while live OCR running: OCR follows current target.
- [ ] Save per-app profile (interval/threshold/crop), switch away and back: values restored.
- [ ] Spotlight workflow: set start marker, set end marker, scan spotlight; saved spotlight is reused.
- [ ] NVDA log: no unhandled exceptions from the add-on during the above tests.
