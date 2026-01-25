# LionEvolution Pro - Implementation Master Plan

This document serves as the primary instruction manual and progress tracker for transforming the `vortex1024/LION` add-on into **LionEvolution Pro**.

**Target Repository:** `Nemex81/LION-Evolution-Pro`
**Objective:** Implement application-specific profiles for OCR settings (dynamic loading based on active window focus).

---

## 📋 Progress Tracking (Agent Checklist)
*The coding agent must update this section after each successful commit.*

- [x] **Phase 1: Infrastructure & Setup**
    - [x] 1.1 Update `manifest.ini` (Rename & Versioning)
    - [x] 1.2 Initialize `profiles` directory logic in `__init__.py`

- [x] **Phase 2: Backend Logic (State & I/O)**
    - [x] 2.1 Add State Variables (`currentAppProfile`, `currentProfileData`)
    - [x] 2.2 Implement `loadGlobalProfile()` method
    - [x] 2.3 Implement `getProfilePath()` and `loadProfileForApp()` methods

- [x] **Phase 3: Event Listeners (The Trigger)**
    - [x] 3.1 Implement `event_gainFocus` to detect app switching
    - [x] 3.2 Add logic to trigger profile loading on focus change

- [x] **Phase 4: Core Integration (OCR Engine)**
    - [x] 4.1 Refactor `cropRectLTWH` to use dynamic `currentProfileData`
    - [x] 4.2 Verify/Refactor `ocrLoop` variables (if necessary)

- [x] **Phase 5: GUI Enhancements**
    - [x] 5.1 Add "Active Profile" label to `LionGui`
    - [x] 5.2 Add "Save Profile" and "Reset" buttons to layout

- [x] **Phase 6: GUI Logic & Persistence**
    - [x] 6.1 Implement `onSaveProfile` handler (connect GUI to Backend)
    - [x] 6.2 Implement `onResetProfile` handler
    - [x] 6.3 Implement backend `saveProfileForApp` and `deleteProfileForApp` methods

---

## 🛠️ Detailed Technical Specifications

### Phase 1: Infrastructure & Setup

**File:** `addon/manifest.ini`
**Task:** Update metadata to reflect the new identity.
```ini
name = LionEvolutionPro
summary = "LION Evolution Pro - Advanced OCR for NVDA"
version = 2.0.0-dev
description = "Live OCR with application-specific profiles. Based on LION by vortex1024."
author = "Nemex81 <your-email@example.com>, based on work by Stefan Moisei"
minimumNVDAVersion = 2024.1.0
lastTestedNVDAVersion = 2025.1.0
```

**File:** `addon/globalPlugins/lion/__init__.py`
**Task:** Setup imports and profiles directory.
```python
import os
import json
import globalVars
import logHandler

ADDON_NAME = "LionEvolutionPro"
PROFILES_DIR = os.path.join(globalVars.appArgs.configPath, "addons", ADDON_NAME, "profiles")

if not os.path.exists(PROFILES_DIR):
    try:
        os.makedirs(PROFILES_DIR)
        logHandler.log.info(f"{ADDON_NAME}: Profiles directory created at {PROFILES_DIR}")
    except Exception as e:
        logHandler.log.error(f"{ADDON_NAME}: Failed to create profiles directory: {e}")
```

---

### Phase 2: Backend Logic

**File:** `addon/globalPlugins/lion/__init__.py`
**Class:** `GlobalPlugin`

**Task:** Add state and loading methods.
```python
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # State Variables
    currentAppProfile = "global"
    currentProfileData = {}

    def getProfilePath(self, appName):
        safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
        return os.path.join(PROFILES_DIR, f"{safeName}.json")

    def loadGlobalProfile(self):
        self.currentAppProfile = "global"
        # Map current config.conf values to our local dictionary
        self.currentProfileData = {
            "cropLeft": config.conf["lion"]["cropLeft"],
            "cropRight": config.conf["lion"]["cropRight"],
            "cropUp": config.conf["lion"]["cropUp"],
            "cropDown": config.conf["lion"]["cropDown"],
            "threshold": config.conf["lion"]["threshold"],
            "interval": config.conf["lion"]["interval"]
        }
        logHandler.log.info(f"{ADDON_NAME}: Loaded Global Profile")

    def loadProfileForApp(self, appName):
        path = self.getProfilePath(appName)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.currentProfileData = json.load(f)
                self.currentAppProfile = appName
                logHandler.log.info(f"{ADDON_NAME}: Loaded profile for {appName}")
                return
            except Exception as e:
                logHandler.log.error(f"{ADDON_NAME}: Error loading {appName}: {e}")
        
        # Fallback to global if file doesn't exist or error occurs
        self.loadGlobalProfile()
```

---

### Phase 3: Event Listeners

**File:** `addon/globalPlugins/lion/__init__.py`
**Class:** `GlobalPlugin`

**Task:** Detect window focus changes.
```python
    def event_gainFocus(self, obj, nextHandler):
        if hasattr(obj, "appModule"):
            newAppName = obj.appModule.appName
            
            # Optimization: Only reload if app actually changed
            if newAppName != self.currentAppProfile:
                self.loadProfileForApp(newAppName)
                
        nextHandler()
```

---

### Phase 4: Core Integration

**File:** `addon/globalPlugins/lion/__init__.py`
**Method:** `cropRectLTWH`

**Task:** Replace static config lookups with dynamic `currentProfileData`.
```python
    def cropRectLTWH(self, r):
        # Use dynamic profile data (or fallback to global config)
        cfg = self.currentProfileData if self.currentProfileData else config.conf["lion"]
        
        if r is None: return locationHelper.RectLTWH(0,0,0,0)
        
        # Safe casting
        try:
            cLeft = int(cfg.get("cropLeft", 0))
            cUp = int(cfg.get("cropUp", 0))
            cRight = int(cfg.get("cropRight", 0))
            cDown = int(cfg.get("cropDown", 0))
        except (ValueError, TypeError):
            cLeft, cUp, cRight, cDown = 0, 0, 0, 0

        # Original math logic preserved
        return locationHelper.RectLTWH(
            int((r.left+r.width)*cLeft/100.0), 
            int((r.top+r.height)*cUp/100.0), 
            int(r.width-(r.width*cRight/100.0)), 
            int(r.height-(r.height*cDown/100.0))
        )
```

---

### Phase 5 & 6: GUI & Persistence

**File:** `addon/globalPlugins/lion/lionGui.py` & `__init__.py`

**Tasks:**
1.  Add `Save` and `Reset` buttons to the wxPython dialog.
2.  Implement `saveProfileForApp(appName, data)` in `__init__.py` using `json.dump`.
3.  Implement `deleteProfileForApp(appName)` in `__init__.py` using `os.remove`.
4.  Connect buttons to these backend methods.

**Specific JSON Format for Profiles:**
```json
{
    "cropLeft": 0,
    "cropRight": 0,
    "cropUp": 10,
    "cropDown": 0,
    "threshold": 0.5,
    "interval": 2.0
}
```

---

## 📝 Commit Guidelines for Agent
1.  **Read First:** Always check the "Progress Tracking" section to see what is next.
2.  **Atomic Commits:** Do not bundle Phase 1 and Phase 2 in one commit. Keep them separate.
3.  **Update Checklist:** After pushing a commit, edit this file (`IMPLEMENTATION_PLAN.md`) to mark the task as `[x]`.
4.  **Verification:** Ensure no syntax errors (Python indentation) are introduced.
