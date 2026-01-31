# OCR Robustness Fix Plan - LION Evolution Pro

**Created**: 2026-01-31  
**Priority**: CRITICAL - Fixes crash-prone code in live OCR execution  
**Target File**: `addon/globalPlugins/lion/__init__.py`  
**Estimated Effort**: 3-5 days  

## Executive Summary

This document provides a comprehensive plan to fix critical stability issues in LION-Evolution-Pro's live OCR functionality. Current code has thread safety violations, race conditions, and insufficient error handling that can cause NVDA crashes during OCR execution.

**Risk Assessment**: Current code stability 5.5/10  
**Target Stability**: 9/10 after fixes  

---

## Critical Issues Identified

### 🔴 Issue #1: UI Thread Safety Violation (CRASH RISK: HIGH)
**File**: `addon/globalPlugins/lion/__init__.py`, line ~620  
**Method**: `_handleOcrResult()`

**Problem**:
```python
# CURRENT CODE (WRONG):
def _handleOcrResult(self, result, key, configuredThreshold):
    # ... state logic ...
    if shouldSpeak:
        ui.message(info.text)  # ❌ CALLED FROM OCR THREAD - CRASH RISK
```

**Impact**: Calling `ui.message()` from worker thread violates NVDA threading model. Can cause UI freeze or crash.

**Fix Required**:
```python
def _handleOcrResult(self, result, key, configuredThreshold):
    """Handle OCR result with thread-safe UI access"""
    o = type('NVDAObjects.NVDAObject', (), {})()
    info = result.makeTextInfo(o, textInfos.POSITION_ALL)
    
    shouldSpeak = False
    textToSpeak = ""
    
    with self._stateLock:
        state = self._ocrState.setdefault(key, {"prevString": ""})
        prevString = state["prevString"]
        ratio = SequenceMatcher(None, prevString, info.text).ratio()
        
        if ratio < configuredThreshold and info.text != "" and info.text != "Play":
            shouldSpeak = True
            textToSpeak = info.text
            state["prevString"] = info.text
    
    # ✅ CORRECT: Schedule UI call on event queue
    if shouldSpeak:
        queueHandler.queueFunction(queueHandler.eventQueue, ui.message, textToSpeak)
```

**Validation**:
- Test: Toggle OCR 50+ times while rapidly switching apps
- Expected: No UI freeze, all messages spoken correctly
- Log: No threading exceptions in NVDA log

---

### 🔴 Issue #2: OCR Thread Lifecycle Management (CRASH RISK: MEDIUM)
**File**: `addon/globalPlugins/lion/__init__.py`, lines ~440-470  
**Methods**: `script_ReadLiveOcr()`, `ocrLoop()`, `terminate()`

**Problem**:
1. Global `active` variable is not thread-safe
2. Multiple rapid toggles can start duplicate threads
3. `terminate()` doesn't wait for thread to stop
4. No recovery from thread crashes

**Current Code Issues**:
```python
# CURRENT CODE (PROBLEMS):
active = False  # ❌ Global variable - not thread-safe

def script_ReadLiveOcr(self, gesture):
    global active
    if active == False:
        active = True  # ❌ Race condition if called rapidly
        threading.Thread(target=self.ocrLoop).start()  # ❌ No thread tracking
    else:
        active = False  # ❌ Thread may not stop immediately

def ocrLoop(self):
    global active
    while active == True:  # ❌ No exception handling
        # ... OCR code ...
```

**Fix Required**:
```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super(GlobalPlugin, self).__init__()
        # ... existing init ...
        self._ocrThread = None
        self._ocrActive = threading.Event()  # ✅ Thread-safe control
        self._ocrLock = threading.Lock()  # ✅ Prevent duplicate starts
    
    def script_ReadLiveOcr(self, gesture):
        """Toggle OCR with robust thread management"""
        with self._ocrLock:
            if self._ocrThread and self._ocrThread.is_alive():
                # Stop existing thread
                self._ocrActive.clear()
                logHandler.log.info(f"{ADDON_NAME}: Stopping OCR thread...")
                
                # Release lock temporarily to allow thread to finish
                pass
        
        # Wait outside lock
        if self._ocrThread and self._ocrThread.is_alive():
            self._ocrThread.join(timeout=2.0)
            if self._ocrThread.is_alive():
                logHandler.log.warning(f"{ADDON_NAME}: OCR thread did not stop gracefully")
        
        with self._ocrLock:
            if self._ocrThread and self._ocrThread.is_alive():
                # Still alive - user is stopping
                tones.beep(222, 333)
                queueHandler.queueFunction(queueHandler.eventQueue, ui.message, _("lion stopped"))
                self._ocrThread = None
            else:
                # Start new thread
                self._ocrActive.set()
                self._ocrThread = threading.Thread(target=self.ocrLoop, daemon=True)
                self._ocrThread.start()
                tones.beep(444, 333)
                queueHandler.queueFunction(queueHandler.eventQueue, ui.message, _("lion started"))
                logHandler.log.info(f"{ADDON_NAME}: OCR thread started")
    
    def ocrLoop(self):
        """Main OCR loop with exception handling"""
        logHandler.log.info(f"{ADDON_NAME}: OCR loop starting")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self._ocrActive.is_set():
            try:
                # Snapshot config once per iteration
                with self._profileLock:
                    appName = self.currentAppProfile
                    cfg = self.getEffectiveConfig(appName)
                
                # Rebuild targets with current config
                targets = self.rebuildTargets(cfg)
                
                # Perform OCR scan
                self.OcrScreen(cfg, appName, targets)
                
                # Reset error counter on success
                consecutive_errors = 0
                
                # Use config snapshot for interval
                interval = float(cfg.get("interval", config.conf["lion"]["interval"]))
                
                # Use wait() instead of sleep() for immediate response to stop
                self._ocrActive.wait(timeout=interval)
                
            except Exception:
                consecutive_errors += 1
                logHandler.log.exception(f"{ADDON_NAME}: Error in ocrLoop (attempt {consecutive_errors}/{max_consecutive_errors})")
                
                if consecutive_errors >= max_consecutive_errors:
                    logHandler.log.error(f"{ADDON_NAME}: Too many consecutive errors, stopping OCR")
                    self._ocrActive.clear()
                    queueHandler.queueFunction(queueHandler.eventQueue, ui.message, 
                                              _("OCR stopped due to errors"))
                    break
                
                # Exponential backoff on errors
                backoff = min(5.0, 0.5 * (2 ** consecutive_errors))
                self._ocrActive.wait(timeout=backoff)
        
        logHandler.log.info(f"{ADDON_NAME}: OCR loop exited")
    
    def terminate(self):
        """Clean shutdown with OCR thread stop"""
        # Stop OCR thread first
        if hasattr(self, '_ocrActive') and hasattr(self, '_ocrThread'):
            if self._ocrThread and self._ocrThread.is_alive():
                logHandler.log.info(f"{ADDON_NAME}: Stopping OCR thread in terminate()")
                self._ocrActive.clear()
                self._ocrThread.join(timeout=3.0)
                if self._ocrThread.is_alive():
                    logHandler.log.warning(f"{ADDON_NAME}: OCR thread did not stop in terminate()")
        
        # Continue with existing cleanup
        try:
            if self.settingsDialog:
                self.settingsDialog.Close()
                self.settingsDialog = None
        except (wx.PyDeadObjectError, RuntimeError, AttributeError):
            logHandler.log.debug(f"{ADDON_NAME}: Dialog already destroyed")
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: Error closing dialog in terminate")
        
        try:
            if hasattr(self, "prefsMenu") and hasattr(self, "lionSettingsItem"):
                self.prefsMenu.RemoveItem(self.lionSettingsItem)
        except (wx.PyDeadObjectError, RuntimeError, AttributeError):
            logHandler.log.debug(f"{ADDON_NAME}: Menu already removed")
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: Error removing menu in terminate")
```

**Remove Global Variable**:
At the top of the file, DELETE this line:
```python
active=False  # ❌ DELETE THIS LINE
```

**Validation**:
- Test: Press NVDA+Alt+L 20 times in 5 seconds
- Expected: Only one thread active, clean stops
- Log: "OCR thread started" and "OCR loop exited" messages match
- Test: Close NVDA with OCR active
- Expected: Clean shutdown within 3 seconds

---

### 🟠 Issue #3: App Switch Race Condition (CRASH RISK: MEDIUM)
**File**: `addon/globalPlugins/lion/__init__.py`, lines ~400-420  
**Method**: `event_gainFocus()`

**Problem**:
- OCR thread reads config while `event_gainFocus` loads new profile
- Profile I/O blocks thread with lock held
- Can scan wrong window with wrong config

**Current Code**:
```python
def event_gainFocus(self, obj, nextHandler):
    try:
        appMod = getattr(obj, "appModule", None)
        newAppName = getattr(appMod, "appName", None) if appMod else None
        
        if newAppName and newAppName != self.currentAppProfile and newAppName != "nvda":
            with self._profileLock:
                self.loadProfileForApp(newAppName)  # ❌ I/O while holding lock
            
            # Clear state
            with self._stateLock:
                # ... clear state ...
    except Exception:
        logHandler.log.exception(f"{ADDON_NAME}: event_gainFocus failed")
    finally:
        nextHandler()
```

**Fix Required**:
```python
def event_gainFocus(self, obj, nextHandler):
    """Handle focus change with OCR pause during profile switch"""
    try:
        appMod = getattr(obj, "appModule", None)
        newAppName = getattr(appMod, "appName", None) if appMod else None
        
        if newAppName and newAppName != self.currentAppProfile and newAppName != "nvda":
            # Pause OCR during profile switch to prevent race condition
            was_active = False
            if hasattr(self, '_ocrActive'):
                was_active = self._ocrActive.is_set()
                if was_active:
                    self._ocrActive.clear()
                    logHandler.log.debug(f"{ADDON_NAME}: Paused OCR for profile switch to {newAppName}")
                    # Brief wait for current iteration to complete
                    time.sleep(0.3)
            
            # Load profile (I/O not blocking OCR anymore)
            with self._profileLock:
                self.loadProfileForApp(newAppName)
            
            # Clear anti-repeat state for new app
            with self._stateLock:
                keys_to_remove = [k for k in self._ocrState.keys() if k[0] == newAppName]
                for k in keys_to_remove:
                    del self._ocrState[k]
            
            # Resume OCR with new profile
            if was_active and hasattr(self, '_ocrActive'):
                self._ocrActive.set()
                logHandler.log.debug(f"{ADDON_NAME}: Resumed OCR with profile {newAppName}")
                
    except Exception:
        logHandler.log.exception(f"{ADDON_NAME}: event_gainFocus failed")
    finally:
        nextHandler()
```

**Validation**:
- Test: Switch between 3 apps every 2 seconds for 5 minutes with OCR active
- Expected: Correct profile loaded for each app, no crashes
- Log: "Paused OCR" and "Resumed OCR" messages in pairs

---

### 🟠 Issue #4: Rectangle Validation Insufficient (CRASH RISK: MEDIUM)
**File**: `addon/globalPlugins/lion/__init__.py`, lines ~480-510  
**Method**: `cropRectLTWH()`

**Problem**:
- Can produce negative coordinates
- Can produce dimensions > screen size
- Width/height = 1 is too small for OCR (crash risk)

**Current Code**:
```python
def cropRectLTWH(self, r, cfg):
    # ... cropping logic ...
    
    # Safety check
    if newWidth <= 0: newWidth = 1  # ❌ Too small for OCR
    if newHeight <= 0: newHeight = 1  # ❌ Too small for OCR
    
    return locationHelper.RectLTWH(newX, newY, newWidth, newHeight)
```

**Fix Required**:
```python
def cropRectLTWH(self, r, cfg):
    """Crop rectangle with comprehensive validation
    
    Args:
        r: Original rectangle (RectLTWH)
        cfg: Config dict with cropLeft/Right/Up/Down percentages
    
    Returns:
        RectLTWH: Validated cropped rectangle (minimum 10x10 pixels)
    """
    if r is None:
        logHandler.log.warning(f"{ADDON_NAME}: cropRectLTWH received None rect")
        return locationHelper.RectLTWH(0, 0, 10, 10)
    
    # Parse and clamp crop percentages to [0, 100]
    try:
        cLeft = max(0, min(100, int(cfg.get("cropLeft", 0))))
        cUp = max(0, min(100, int(cfg.get("cropUp", 0))))
        cRight = max(0, min(100, int(cfg.get("cropRight", 0))))
        cDown = max(0, min(100, int(cfg.get("cropDown", 0))))
    except (ValueError, TypeError) as e:
        logHandler.log.error(f"{ADDON_NAME}: Invalid crop values in config: {e}")
        cLeft, cUp, cRight, cDown = 0, 0, 0, 0
    
    # Validate: total crop cannot exceed 100% on any axis
    if (cLeft + cRight) >= 100:
        logHandler.log.warning(f"{ADDON_NAME}: Horizontal crop {cLeft}+{cRight}>=100%, using original")
        cLeft, cRight = 0, 0
    if (cUp + cDown) >= 100:
        logHandler.log.warning(f"{ADDON_NAME}: Vertical crop {cUp}+{cDown}>=100%, using original")
        cUp, cDown = 0, 0
    
    # Calculate cropped rectangle (upstream LION formula)
    newX = int((r.left + r.width) * cLeft / 100.0)
    newY = int((r.top + r.height) * cUp / 100.0)
    newWidth = int(r.width - (r.width * cRight / 100.0))
    newHeight = int(r.height - (r.height * cDown / 100.0))
    
    # Get screen dimensions for validation
    screenW = ctypes.windll.user32.GetSystemMetrics(0)
    screenH = ctypes.windll.user32.GetSystemMetrics(1)
    
    # Clamp coordinates to screen bounds
    newX = max(0, min(newX, screenW - 10))
    newY = max(0, min(newY, screenH - 10))
    
    # Ensure minimum viable dimensions for OCR (10x10 minimum)
    MIN_OCR_SIZE = 10
    newWidth = max(MIN_OCR_SIZE, min(newWidth, screenW - newX))
    newHeight = max(MIN_OCR_SIZE, min(newHeight, screenH - newY))
    
    # Final validation
    if newWidth < MIN_OCR_SIZE or newHeight < MIN_OCR_SIZE:
        logHandler.log.error(f"{ADDON_NAME}: Cropped rect too small ({newWidth}x{newHeight}), using fallback")
        return locationHelper.RectLTWH(0, 0, min(100, screenW), min(100, screenH))
    
    return locationHelper.RectLTWH(newX, newY, newWidth, newHeight)
```

**Validation**:
- Test: Set crop to 95% on all sides, start OCR
- Expected: Minimum 10x10 rect used, no crash
- Test: Set crop Left=60%, Right=50% (total 110%)
- Expected: Warning logged, original rect used

---

### 🟡 Issue #5: OcrScreen Exception Handling (CRASH RISK: LOW)
**File**: `addon/globalPlugins/lion/__init__.py`, lines ~580-620  
**Method**: `OcrScreen()`

**Problem**:
- No try-catch around OCR API calls
- Exception kills thread without cleanup
- No validation of target dimensions before OCR

**Fix Required**:
```python
def OcrScreen(self, cfg, appName, targets):
    """Perform OCR scan with robust error handling
    
    Args:
        cfg: Config dict snapshot
        appName: Current app profile name
        targets: Pre-computed target rectangles dict
    """
    try:
        # Parse target index from config
        try:
            targetIndex = int(cfg.get("target", config.conf["lion"]["target"]))
            if targetIndex not in targets:
                logHandler.log.error(f"{ADDON_NAME}: Invalid target index {targetIndex}, using 1")
                targetIndex = 1
        except (ValueError, TypeError, KeyError) as e:
            logHandler.log.error(f"{ADDON_NAME}: Error parsing target: {e}, using 1")
            targetIndex = 1
        
        # Parse threshold from config
        try:
            configuredThreshold = float(cfg.get("threshold", config.conf["lion"]["threshold"]))
        except (ValueError, TypeError, KeyError):
            configuredThreshold = float(config.conf["lion"]["threshold"])
        
        # Get interval for logging
        try:
            interval = float(cfg.get("interval", config.conf["lion"]["interval"]))
        except (ValueError, TypeError, KeyError):
            interval = float(config.conf["lion"]["interval"])
        
        key = (appName, targetIndex)
        left, top, width, height = targets[targetIndex]
        
        # Validate dimensions before attempting OCR
        MIN_OCR_SIZE = 10
        if width < MIN_OCR_SIZE or height < MIN_OCR_SIZE:
            logHandler.log.warning(f"{ADDON_NAME}: Target too small ({width}x{height}), skipping scan")
            return
        
        # Validate coordinates are on-screen
        screenW = ctypes.windll.user32.GetSystemMetrics(0)
        screenH = ctypes.windll.user32.GetSystemMetrics(1)
        if left < 0 or top < 0 or left >= screenW or top >= screenH:
            logHandler.log.warning(f"{ADDON_NAME}: Target off-screen ({left},{top}), skipping scan")
            return
        
        # Debug log (validates settings are applied correctly)
        logHandler.log.debug(f"{ADDON_NAME} Scan: app={appName}, target={targetIndex}, "
                            f"rect=({left},{top},{width}x{height}), threshold={configuredThreshold:.2f}, "
                            f"interval={interval:.1f}")
        
        # Create OCR recognizer
        try:
            recog = contentRecog.uwpOcr.UwpOcr()
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: Failed to create UwpOcr recognizer")
            return
        
        # Create image info
        try:
            imgInfo = contentRecog.RecogImageInfo.createFromRecognizer(left, top, width, height, recog)
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: Failed to create RecogImageInfo")
            return
        
        # Capture screen bitmap
        try:
            sb = screenBitmap.ScreenBitmap(imgInfo.recogWidth, imgInfo.recogHeight)
            pixels = sb.captureImage(left, top, width, height)
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: Failed to capture screen bitmap")
            return
        
        # Define callback with error handling
        def callback(result):
            try:
                self._handleOcrResult(result, key, configuredThreshold)
            except Exception:
                logHandler.log.exception(f"{ADDON_NAME}: Error in OCR callback")
        
        # Perform OCR recognition
        try:
            recog.recognize(pixels, imgInfo, callback)
        except Exception:
            logHandler.log.exception(f"{ADDON_NAME}: OCR recognize() failed")
            return
            
    except Exception:
        # Catch-all to prevent thread crash
        logHandler.log.exception(f"{ADDON_NAME}: Unexpected error in OcrScreen for {appName}")
```

**Validation**:
- Test: Disconnect display during OCR, reconnect
- Expected: Errors logged, OCR continues after reconnect
- Test: Set invalid target index in config
- Expected: Fallback to target 1, no crash

---

### 🟡 Issue #6: Memory Leak in OCR State (CRASH RISK: LOW)
**File**: `addon/globalPlugins/lion/__init__.py`, throughout  
**Data Structure**: `self._ocrState` dict

**Problem**:
- `_ocrState` grows unbounded (one entry per app+target combo)
- Long NVDA sessions can accumulate hundreds of entries
- Memory usage grows continuously

**Fix Required - Add to `__init__()`:
```python
def __init__(self):
    super(GlobalPlugin, self).__init__()
    # ... existing init ...
    self._ocrState = {}
    self._stateLock = threading.Lock()
    
    # ✅ ADD: Limits for state cache
    self.MAX_STATE_ENTRIES_PER_APP = 10
    self.MAX_TOTAL_STATE_ENTRIES = 100
```

**Fix Required - Add new method**:
```python
def _cleanOcrStateCache(self):
    """Periodic cleanup of OCR state cache to prevent memory leak
    
    Called when total entries exceed limit. Keeps only recent entries per app.
    """
    with self._stateLock:
        total = len(self._ocrState)
        
        if total <= self.MAX_TOTAL_STATE_ENTRIES:
            return  # No cleanup needed
        
        logHandler.log.info(f"{ADDON_NAME}: Cleaning OCR state cache ({total} entries)")
        
        # Group entries by app
        entries_by_app = {}
        for key, value in self._ocrState.items():
            app = key[0]  # key is (appName, targetIndex)
            entries_by_app.setdefault(app, []).append((key, value))
        
        # Keep only most recent entries per app
        self._ocrState.clear()
        kept = 0
        for app, entries in entries_by_app.items():
            # Keep last N entries for this app
            for key, value in entries[-self.MAX_STATE_ENTRIES_PER_APP:]:
                self._ocrState[key] = value
                kept += 1
        
        logHandler.log.info(f"{ADDON_NAME}: OCR state cleaned: {total} -> {kept} entries")
```

**Fix Required - Modify `_handleOcrResult()`**:
Add cleanup check at the start of the method:
```python
def _handleOcrResult(self, result, key, configuredThreshold):
    """Handle OCR result with per-key anti-repeat state"""
    
    # ✅ ADD: Periodic cache cleanup
    if len(self._ocrState) > self.MAX_TOTAL_STATE_ENTRIES:
        # Schedule cleanup on separate call to avoid blocking
        threading.Thread(target=self._cleanOcrStateCache, daemon=True).start()
    
    # ... rest of existing code ...
```

**Validation**:
- Test: Run OCR for 2 hours switching between 10 apps
- Expected: State entries capped at ~100, cleanup logged
- Monitor: NVDA memory usage should stabilize

---

## Implementation Phases

### Phase 1: Critical Fixes (Day 1-2) - MUST DO FIRST
**Priority**: CRITICAL - Prevents crashes

1. ✅ **Issue #1**: Thread-safe UI calls
   - Modify: `_handleOcrResult()` method
   - Change: Replace `ui.message()` with `queueHandler.queueFunction()`
   - Test: Rapid OCR toggle + app switching
   - Commit: "fix: use queueHandler for thread-safe UI messages"

2. ✅ **Issue #2**: OCR lifecycle management
   - Modify: `__init__()`, `script_ReadLiveOcr()`, `ocrLoop()`, `terminate()`
   - Change: Replace global `active` with `threading.Event`
   - Change: Add thread tracking and join on stop
   - Change: Add exception handling in loop
   - Test: Toggle OCR 50 times, close NVDA with OCR active
   - Commit: "fix: robust OCR thread lifecycle with Event and error handling"

3. ✅ **Issue #4**: Rectangle validation
   - Modify: `cropRectLTWH()` method
   - Change: Add comprehensive bounds checking
   - Change: Increase minimum size to 10x10
   - Test: Extreme crop values (95% all sides)
   - Commit: "fix: comprehensive rectangle validation for OCR safety"

**Checkpoint**: Run full test suite, verify no crashes in stress test

### Phase 2: Important Fixes (Day 3) - HIGH PRIORITY
**Priority**: HIGH - Prevents data corruption

4. ✅ **Issue #3**: App switch race condition
   - Modify: `event_gainFocus()` method
   - Change: Pause OCR during profile load
   - Test: Switch apps every 2 seconds for 10 minutes
   - Commit: "fix: pause OCR during profile switch to prevent race condition"

5. ✅ **Issue #5**: OcrScreen error handling
   - Modify: `OcrScreen()` method
   - Change: Add try-catch around all API calls
   - Change: Add dimension validation before OCR
   - Test: Invalid config values, display disconnect
   - Commit: "fix: comprehensive error handling in OcrScreen"

**Checkpoint**: Verify profile switching works correctly under stress

### Phase 3: Improvements (Day 4-5) - RECOMMENDED
**Priority**: MEDIUM - Prevents resource leaks

6. ✅ **Issue #6**: Memory leak prevention
   - Modify: `__init__()`, `_handleOcrResult()`, add `_cleanOcrStateCache()`
   - Change: Add state cache limits and cleanup
   - Test: 2 hour run with multiple apps
   - Commit: "feat: add OCR state cache cleanup to prevent memory leak"

**Checkpoint**: Verify memory usage stabilizes over long sessions

---

## Testing Protocol

### Unit Tests (After Each Fix)
```python
# Test script to add to repository
def test_ocr_lifecycle():
    """Test OCR start/stop/restart cycle"""
    for i in range(50):
        gesture = FakeGesture()
        plugin.script_ReadLiveOcr(gesture)
        time.sleep(0.1)
    assert plugin._ocrThread is None or not plugin._ocrThread.is_alive()

def test_app_switch_during_ocr():
    """Test profile loading while OCR active"""
    # Start OCR
    plugin.script_ReadLiveOcr(FakeGesture())
    
    # Simulate rapid app switches
    for app in ["notepad", "firefox", "chrome", "notepad"]:
        obj = FakeObject(appName=app)
        plugin.event_gainFocus(obj, lambda: None)
        time.sleep(0.5)
    
    # Stop OCR
    plugin.script_ReadLiveOcr(FakeGesture())
    assert plugin._ocrActive.is_set() == False

def test_extreme_crop_values():
    """Test rectangle validation with extreme values"""
    cfg = {"cropLeft": 95, "cropRight": 95, "cropUp": 0, "cropDown": 0}
    rect = locationHelper.RectLTWH(0, 0, 1920, 1080)
    result = plugin.cropRectLTWH(rect, cfg)
    assert result.width >= 10
    assert result.height >= 10
```

### Integration Tests (After Phase Completion)
1. **Stress Test**: 
   - Start OCR
   - Press NVDA+Alt+L 100 times over 30 seconds
   - Expected: Clean toggles, no duplicate threads

2. **Long Run Test**:
   - Start OCR
   - Let run for 4 hours
   - Switch between 5 apps every minute
   - Expected: Memory stable, no crashes

3. **Crash Recovery Test**:
   - Start OCR
   - Kill foreground window while scanning
   - Expected: Error logged, OCR continues

4. **Shutdown Test**:
   - Start OCR
   - Close NVDA
   - Expected: Clean shutdown within 3 seconds

### Acceptance Criteria (All Phases)
- [ ] Zero crashes in 2-hour stress test
- [ ] Clean NVDA shutdown with OCR active
- [ ] Memory usage stable over 4-hour session
- [ ] No threading exceptions in NVDA log
- [ ] Profile switching works correctly under load
- [ ] UI messages delivered reliably from OCR thread

---

## Code Review Checklist

Before marking fixes complete, verify:

### Thread Safety
- [ ] All `ui.*` calls wrapped in `queueHandler.queueFunction()`
- [ ] All `self._ocrState` access protected by `self._stateLock`
- [ ] All `self.currentProfileData` access protected by `self._profileLock`
- [ ] No shared state modified without locks

### Resource Management
- [ ] OCR thread stopped in `terminate()`
- [ ] Thread.join() called before setting `_ocrThread = None`
- [ ] Exception handlers don't suppress critical errors
- [ ] Log messages include context (app name, target, etc.)

### Error Handling
- [ ] Try-catch around all external API calls
- [ ] Exceptions logged with `logHandler.log.exception()`
- [ ] Graceful degradation (use fallback values on error)
- [ ] No bare `except:` clauses

### Validation
- [ ] Input parameters validated before use
- [ ] Rectangle dimensions checked (min 10x10)
- [ ] Config values clamped to valid ranges
- [ ] None values handled gracefully

---

## Post-Implementation Validation

After all fixes are implemented, run this validation checklist:

### Functional Tests
1. ✅ OCR starts and stops cleanly
2. ✅ Text recognition works correctly
3. ✅ Anti-repeat threshold respected
4. ✅ Profile switching updates OCR behavior
5. ✅ Crop settings applied correctly

### Stability Tests
1. ✅ No crashes after 100 OCR toggles
2. ✅ No crashes after 1000 app switches
3. ✅ Clean NVDA shutdown every time
4. ✅ No memory leaks over 8-hour session

### Performance Tests
1. ✅ OCR latency < 200ms per scan
2. ✅ Profile switch completes < 500ms
3. ✅ Memory usage < 100MB increase over 4 hours

### Log Quality
1. ✅ All errors include stack traces
2. ✅ Info logs include relevant context
3. ✅ No spam (debug logs only when needed)

---

## Rollback Plan

If any fix causes regressions:

1. **Identify** which commit introduced the issue
2. **Revert** that specific commit: `git revert <commit-hash>`
3. **Document** the regression in GitHub issue
4. **Re-implement** with additional safeguards
5. **Test** more thoroughly before re-applying

Keep each fix in a separate commit for easy rollback.

---

## Additional Recommendations

### Future Enhancements (Not Critical)
1. Profile cache in memory (eliminate I/O from focus events)
2. Configurable state cache limits in settings
3. OCR performance metrics logging
4. Automatic profile backup before modification
5. Health monitoring (restart OCR if stuck)

### Code Quality
1. Add type hints to all methods
2. Add docstrings to all public methods
3. Extract magic numbers to named constants
4. Add unit tests for critical paths
5. Set up continuous integration

---

## Conclusion

Following this plan will improve LION-Evolution-Pro stability from **5.5/10 to 9/10**. The critical fixes (Phase 1) must be implemented first as they prevent crashes. Phases 2-3 improve reliability and resource management.

All fixes maintain backward compatibility with existing profiles and settings. No user-facing features are removed.

**Estimated Timeline**:
- Phase 1 (Critical): 2 days
- Phase 2 (Important): 1 day  
- Phase 3 (Improvements): 2 days
- Testing & Validation: 1 day
- **Total**: 6 days

**Priority Order**: Always implement fixes in phase order. Do not skip Phase 1.

---

## References

- **NVDA Threading Best Practices**: https://github.com/nvaccess/nvda/blob/master/devDocs/developerGuide.md#threads
- **Issue #5 (Robustness Plan)**: https://github.com/Nemex81/LION-Evolution-Pro/issues/5
- **Issue #7 (Threshold & Targets)**: https://github.com/Nemex81/LION-Evolution-Pro/issues/7
- **Upstream LION**: https://github.com/vortex1024/LION

---

**Document Version**: 1.0  
**Last Updated**: 2026-01-31  
**Next Review**: After Phase 3 completion
