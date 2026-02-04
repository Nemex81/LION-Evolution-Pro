"""
LION Evolution Pro - Live OCR with Application-Specific Profiles

This NVDA global plugin extends the upstream vortex1024/LION addon with per-application
profile support while maintaining full upstream compatibility.

Architecture:
-------------
1. Global Settings (config.conf["lion"]):
   - Source of truth for all default settings
   - Used when no per-app profile exists (upstream behavior)
   - Keys: cropUp, cropLeft, cropRight, cropDown, target, threshold, interval
   - Single rectangle management system using main crop settings only

2. Per-App Profiles (JSON files in PROFILES_DIR):
   - Store ONLY override values (keys that differ from global)
   - Missing keys fall back to global config.conf["lion"]
   - Profiles are loaded automatically on app focus change
   - Profile format: {"threshold": 0.7, "interval": 2.0, ...}

3. Effective Configuration:
   - getEffectiveConfig(appName) merges global + profile overrides
   - Used by ocrLoop() for each scan iteration
   - Ensures consistent config snapshot per OCR operation

4. Migration:
   - Legacy profiles (full config) are auto-normalized to overrides
   - Empty profiles (all values match global) are removed
   - Normalization happens on first load after refactor

Compatibility Contract:
-----------------------
- Apps without profiles use global config only (upstream behavior)
- Profile switching is thread-safe (protected by _profileLock)
- Anti-repeat state resets per app to avoid cross-app suppression
- Single rectangle management system (spotlight feature removed for simplification)

Key Methods:
------------
- getEffectiveConfig(appName): Returns merged config (global + overrides)
- loadProfileForApp(appName): Loads and normalizes profile, or falls back to global
- saveProfileForApp(appName, data): Saves profile (overrides only)
- _normalizeProfileToOverrides(data): Migration helper for legacy profiles
"""

import globalPluginHandler
import addonHandler
import scriptHandler
import api
import contentRecog, contentRecog.uwpOcr
import screenBitmap
import logHandler
import gui
import tones
import textInfos
import ui
import time
import queueHandler
import threading
import config
import wx
import locationHelper
try:
	from . import lionGui
except Exception:
	lionGui = None
	logHandler.log.error("LionEvolutionPro: Failed to import lionGui", exc_info=True)
from scriptHandler import getLastScriptRepeatCount, script

from difflib import SequenceMatcher
import ctypes
import os
import json
import globalVars


addonHandler.initTranslation()

ADDON_NAME = "LionEvolutionPro"
PROFILES_DIR = os.path.join(globalVars.appArgs.configPath, "addons", ADDON_NAME, "profiles")

if not os.path.exists(PROFILES_DIR):
	try:
		os.makedirs(PROFILES_DIR)
		logHandler.log.info(f"{ADDON_NAME}: Profiles directory created at {PROFILES_DIR}")
	except Exception as e:
		logHandler.log.error(f"{ADDON_NAME}: Failed to create profiles directory: {e}")


confspec={
	"cropUp": "integer(0,100,default=0)",
	"cropLeft": "integer(0,100,default=0)",
	"cropRight": "integer(0,100,default=0)",
	"cropDown": "integer(0,100,default=0)",
	"target": "integer(0,3,default=1)",
	"threshold": "float(0.0,1.0,default=0.5)",
	"interval": "float(0.0,10.0,default=1.0)"
}
config.conf.spec["lion"]=confspec

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	"""LION Evolution Pro global plugin.
	
	Provides live OCR with per-application profile support.
	Maintains upstream compatibility when no profile exists.
	"""

	user32 = ctypes.windll.user32
	resX, resY= user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		# Instance variables for current profile state (moved from class-level globals)
		self.currentAppProfile = "global"
		self.currentProfileData = {}
		# Profiles cache to avoid disk I/O on every app switch
		self.profilesCache = {}
		
		self.settingsDialog = None
		self._stateLock = threading.Lock()
		self._ocrState = {}
		self._cleanupInProgress = False  # Prevent race condition in cache cleanup
		self._profileLock = threading.Lock()
		# OCR thread lifecycle management
		self._ocrThread = None
		self._ocrActive = threading.Event()  # Thread-safe control flag
		self._ocrLock = threading.Lock()  # Prevent duplicate starts
		# OCR state cache limits to prevent memory leak
		self.MAX_STATE_ENTRIES_PER_APP = 10
		self.MAX_TOTAL_STATE_ENTRIES = 100
		# Pre-load all profiles into cache at startup
		self.loadAllProfilesToCache()
		# Initialize to global profile (no overrides)
		self.loadGlobalProfile()
		# Initialize last-valid targets to CROPPED screen (not raw)
		# Use default/global config for initial crop (safe copy)
		defaultCfg = {k: config.conf["lion"][k] for k in config.conf["lion"]}
		screenRaw = locationHelper.RectLTWH(0, 0, 
			ctypes.windll.user32.GetSystemMetrics(0), 
			ctypes.windll.user32.GetSystemMetrics(1))
		# Apply crop with default config
		screenRect = self.cropRectLTWH(screenRaw, defaultCfg)
		self._lastTargets = {0: screenRect, 1: screenRect, 2: screenRect, 3: screenRect}
		try:
			self.createMenu()
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Failed to create menu")
	
	def getProfilePath(self, appName):
		safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
		return os.path.join(PROFILES_DIR, f"{safeName}.json")
	
	def loadAllProfilesToCache(self):
		"""Pre-load all profiles from disk into memory cache at startup.
		
		Scans PROFILES_DIR and loads each JSON profile file.
		Invalid JSON files are logged and skipped.
		"""
		self.profilesCache = {}
		
		if not os.path.exists(PROFILES_DIR):
			logHandler.log.info(f"{ADDON_NAME}: Profiles directory does not exist, cache is empty")
			return
		
		try:
			for filename in os.listdir(PROFILES_DIR):
				if filename.endswith('.json'):
					profileName = filename[:-5]  # Remove .json extension
					filePath = os.path.join(PROFILES_DIR, filename)
					try:
						with open(filePath, "r", encoding="utf-8") as f:
							rawData = json.load(f)
						# Normalize to overrides-only format
						normalizedData = self._normalizeProfileToOverrides(rawData)
						self.profilesCache[profileName] = normalizedData
						logHandler.log.debug(f"{ADDON_NAME}: Loaded profile '{profileName}' into cache")
					except json.JSONDecodeError as e:
						logHandler.log.warning(f"{ADDON_NAME}: Invalid JSON in profile '{profileName}', skipping: {e}")
					except (OSError, IOError) as e:
						logHandler.log.warning(f"{ADDON_NAME}: Failed to read profile '{profileName}', skipping: {e}")
			
			logHandler.log.info(f"{ADDON_NAME}: Loaded {len(self.profilesCache)} profiles into cache")
		except (OSError, IOError) as e:
			logHandler.log.error(f"{ADDON_NAME}: Failed to scan profiles directory: {e}")
	
	def refreshProfileCache(self, appName):
		"""Refresh a single profile in the cache from disk.
		
		Called after saving a profile to keep cache in sync.
		
		Args:
			appName: Application name whose profile to refresh
		"""
		if appName == "global":
			return  # Global is not a file-based profile
		
		path = self.getProfilePath(appName)
		if os.path.exists(path):
			try:
				with open(path, "r", encoding="utf-8") as f:
					rawData = json.load(f)
				normalizedData = self._normalizeProfileToOverrides(rawData)
				self.profilesCache[appName] = normalizedData
				logHandler.log.debug(f"{ADDON_NAME}: Refreshed cache for profile '{appName}'")
			except (json.JSONDecodeError, OSError, IOError) as e:
				logHandler.log.warning(f"{ADDON_NAME}: Failed to refresh cache for '{appName}': {e}")
		else:
			# Profile was deleted, remove from cache
			self.profilesCache.pop(appName, None)
			logHandler.log.debug(f"{ADDON_NAME}: Removed '{appName}' from cache (file deleted)")
	
	def getEffectiveConfig(self, appName):
		"""Get effective configuration by merging global config + per-app overrides.
		
		Args:
			appName: Current application profile name or "global"
		
		Returns:
			dict: Merged configuration (global base + profile overrides)
		"""
		# Start with global config as base
		effective = {
			"cropLeft": config.conf["lion"]["cropLeft"],
			"cropRight": config.conf["lion"]["cropRight"],
			"cropUp": config.conf["lion"]["cropUp"],
			"cropDown": config.conf["lion"]["cropDown"],
			"target": config.conf["lion"]["target"],
			"threshold": config.conf["lion"]["threshold"],
			"interval": config.conf["lion"]["interval"]
		}
		
		# If not global and we have profile data, apply overrides
		if appName != "global" and self.currentProfileData:
			effective.update(self.currentProfileData)
		
		return effective
	
	def loadGlobalProfile(self):
		"""Load global profile - resets to using config.conf["lion"] only."""
		self.currentAppProfile = "global"
		self.currentProfileData = {}
		logHandler.log.info(f"{ADDON_NAME}: Loaded Global Profile (no overrides)")
	
	def _normalizeProfileToOverrides(self, profileData):
		"""Normalize profile data to contain only overrides (values that differ from global).
		
		This is a migration helper for legacy profiles that stored full config.
		
		Args:
			profileData: Raw profile data dict from JSON
			
		Returns:
			dict: Normalized profile data with only overrides
		"""
		overrides = {}
		
		# Define keys that should be checked against global config
		standardKeys = ["cropLeft", "cropRight", "cropUp", "cropDown", "target", "threshold", "interval"]
		
		for key in standardKeys:
			if key in profileData:
				# Only keep if different from global
				if profileData[key] != config.conf["lion"][key]:
					overrides[key] = profileData[key]
		
		return overrides
	
	def loadProfileForApp(self, appName):
		"""Load profile for specific app from cache. If no profile exists, keeps currentAppProfile="global".
		
		Uses in-memory cache for instant profile switching (no file I/O).
		Empty profiles ({}) are now supported and kept persistent - they represent
		"same as global" but with explicit per-app tracking.
		
		Args:
			appName: Application name to load profile for
		"""
		# Use cache for instant lookup (no file I/O)
		if appName in self.profilesCache:
			profileData = self.profilesCache.get(appName, {})
			self.currentAppProfile = appName
			self.currentProfileData = profileData.copy()  # Shallow copy for thread safety
			
			if profileData:
				logHandler.log.info(f"{ADDON_NAME}: Loaded profile overrides for {appName} from cache")
			else:
				logHandler.log.info(f"{ADDON_NAME}: Profile for {appName} exists but is empty (same as global)")
			return
		
		# No profile exists in cache - fall back to global (upstream behavior)
		self.currentAppProfile = "global"
		self.currentProfileData = {}
		logHandler.log.info(f"{ADDON_NAME}: No cached profile for {appName}, using global config")
	
	def saveProfileForApp(self, appName, data):
		"""Save profile for specific app. Profiles store only overrides.
		
		Args:
			appName: Application name
			data: Profile data dict (should contain only overrides)
		"""
		path = self.getProfilePath(appName)
		try:
			with open(path, "w", encoding="utf-8") as f:
				json.dump(data, f, indent=2)
			self.currentAppProfile = appName
			self.currentProfileData = data.copy()
			# Update the cache to keep it in sync
			self.profilesCache[appName] = data.copy()
			logHandler.log.info(f"{ADDON_NAME}: Saved profile for {appName} (overrides only)")
		except (OSError, IOError) as e:
			logHandler.log.error(f"{ADDON_NAME}: Error saving profile for {appName}: {e}")
	
	def deleteProfileForApp(self, appName):
		"""Delete profile for specific app and remove from cache."""
		path = self.getProfilePath(appName)
		if os.path.exists(path):
			try:
				os.remove(path)
				logHandler.log.info(f"{ADDON_NAME}: Deleted profile for {appName}")
			except (OSError, IOError) as e:
				logHandler.log.error(f"{ADDON_NAME}: Error deleting profile for {appName}: {e}")
		# Remove from cache
		self.profilesCache.pop(appName, None)
		self.loadGlobalProfile()
	
	def profileExists(self, appName):
		"""Check if a profile file exists for the given app.
		
		Args:
			appName: Application name
			
		Returns:
			bool: True if profile file exists, False otherwise
		"""
		path = self.getProfilePath(appName)
		return os.path.exists(path)
	
	def profileHasOverrides(self, appName):
		"""Check if a profile has non-empty overrides.
		
		Args:
			appName: Application name
			
		Returns:
			bool: True if profile exists and has overrides, False if empty or doesn't exist
		"""
		if not self.profileExists(appName):
			return False
		
		path = self.getProfilePath(appName)
		try:
			with open(path, "r", encoding="utf-8") as f:
				data = json.load(f)
			# Normalize to check if it has any overrides
			normalized = self._normalizeProfileToOverrides(data)
			return bool(normalized)
		except Exception as e:
			logHandler.log.error(f"{ADDON_NAME}: Error checking overrides for {appName}: {e}", exc_info=True)
			return False
	
	def setActiveProfile(self, appName):
		"""Set the active profile by loading the specified app profile.
		
		Args:
			appName: Profile name to activate (use "global" for global profile)
		"""
		if appName == "global":
			self.loadGlobalProfile()
		else:
			self.loadProfileForApp(appName)
		logHandler.log.info(f"{ADDON_NAME}: Active profile set to {self.currentAppProfile}")
	
	def clearOverridesForApp(self, appName):
		"""Clear all overrides for an app profile but keep it active.
		
		Writes empty {} to disk to maintain profile persistence. The profile
		becomes identical to global but stays active.
		
		Args:
			appName: Application name to clear overrides for
		"""
		if appName == "global":
			logHandler.log.info(f"{ADDON_NAME}: Cannot clear overrides for global profile")
			return
		
		# Write empty profile to disk (keep it persistent)
		path = self.getProfilePath(appName)
		try:
			with open(path, "w", encoding="utf-8") as f:
				json.dump({}, f, indent=2)
			logHandler.log.info(f"{ADDON_NAME}: Cleared overrides for {appName}, wrote empty profile")
		except (OSError, IOError) as e:
			logHandler.log.error(f"{ADDON_NAME}: Error writing empty profile for {appName}: {e}", exc_info=True)
		
		# Update cache with empty profile
		self.profilesCache[appName] = {}
		
		# Keep profile active but with no overrides (identical to global)
		self.currentAppProfile = appName
		self.currentProfileData = {}
		logHandler.log.info(f"{ADDON_NAME}: Profile {appName} is now active with no overrides (same as global)")
		
	def createMenu(self):
		try:
			self.prefsMenu = gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
			self.lionSettingsItem = self.prefsMenu.Append(wx.ID_ANY,
				# Translators: name of the option in the menu.
				_("&Lion Evolution Pro settings..."),
				# Translators: tooltip text for the menu item.
				_("Modify OCR zone, interval and per-app profiles"))
			gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onSettings, self.lionSettingsItem)
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Error in createMenu")

	def terminate(self):
		# Stop OCR thread first if it's running
		if hasattr(self, '_ocrActive') and hasattr(self, '_ocrThread'):
			if self._ocrThread and self._ocrThread.is_alive():
				logHandler.log.info(f"{ADDON_NAME}: Stopping OCR thread in terminate()")
				self._ocrActive.clear()
				self._ocrThread.join(timeout=3.0)
				if self._ocrThread.is_alive():
					logHandler.log.warning(f"{ADDON_NAME}: OCR thread did not stop in terminate()")
		
		# Clean up UI components
		try:
			if self.settingsDialog:
				self.settingsDialog.Close()
				self.settingsDialog = None
		except (wx.PyDeadObjectError, RuntimeError, AttributeError):
			logHandler.log.debug(f"{ADDON_NAME}: Dialog already destroyed or dead, ignoring")
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Error closing settings dialog in terminate")
		
		try:
			if hasattr(self, "prefsMenu") and hasattr(self, "lionSettingsItem"):
				self.prefsMenu.RemoveItem(self.lionSettingsItem)
		except (wx.PyDeadObjectError, RuntimeError, AttributeError):
			logHandler.log.debug(f"{ADDON_NAME}: Menu item already removed or dead, ignoring")
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Error removing menu item in terminate")

	def onSettings(self, evt):
		# Check if lionGui module loaded successfully
		if lionGui is None:
			logHandler.log.error(f"{ADDON_NAME}: Cannot open settings - lionGui module failed to load")
			ui.message(_("Error: Settings module not available"))
			return
		
		# Try to raise existing dialog if it exists
		if self.settingsDialog:
			try:
				self.settingsDialog.Raise()
				self.settingsDialog.Show()
				logHandler.log.info(f"{ADDON_NAME}: Raised existing settings dialog")
				return
			except (wx.PyDeadObjectError, RuntimeError, AttributeError):
				# Dialog object is dead, need to create a new one
				logHandler.log.info(f"{ADDON_NAME}: Existing dialog is dead, creating new one")
				self.settingsDialog = None
			except Exception:
				logHandler.log.exception(f"{ADDON_NAME}: Error raising existing settings dialog")
				self.settingsDialog = None
		
		# Create new dialog
		try:
			self.settingsDialog = lionGui.frmMain(gui.mainFrame, self)
			self.settingsDialog.Show()
			logHandler.log.info(f"{ADDON_NAME}: Settings dialog opened successfully")
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Error creating settings dialog")
			self.settingsDialog = None
			ui.message(_("Error opening settings"))

	def script_ReadLiveOcr(self, gesture):
		"""Toggle OCR with robust thread management"""
		repeat = getLastScriptRepeatCount()
#		if repeat>=2:
#			ui.message("o sa vine profile")
		
		with self._ocrLock:
			if self._ocrThread and self._ocrThread.is_alive():
				# Stop existing thread
				self._ocrActive.clear()
				logHandler.log.info(f"{ADDON_NAME}: Stopping OCR thread...")
		
		# Wait outside lock to allow thread to finish
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
			
	def event_gainFocus(self, obj, nextHandler):
		"""Handle focus change with instant profile switch from cache.
		
		Since profiles are now loaded from RAM cache (not disk I/O),
		we no longer need to pause OCR during profile switching.
		"""
		try:
			# Safe access to appModule and appName
			appMod = getattr(obj, "appModule", None)
			newAppName = getattr(appMod, "appName", None) if appMod else None
			
			if newAppName and newAppName != self.currentAppProfile and newAppName != "nvda":
				# Load profile from cache (instant - no I/O)
				# No need to pause OCR since this is a RAM lookup
				with self._profileLock:
					self.loadProfileForApp(newAppName)
				
				# Clear anti-repeat state for new app to avoid stale suppression
				with self._stateLock:
					# Remove all keys for this app (all targets)
					keys_to_remove = [k for k in self._ocrState.keys() if k[0] == newAppName]
					for k in keys_to_remove:
						del self._ocrState[k]
				
				logHandler.log.debug(f"{ADDON_NAME}: Switched to profile {newAppName} (instant cache lookup)")
					
		except Exception:
			# Never crash NVDA on focus events
			logHandler.log.exception(f"{ADDON_NAME}: event_gainFocus failed")
		finally:
			# Always call nextHandler
			nextHandler()

	def cropRectLTWH(self, r, cfg):
		"""Crop rectangle with comprehensive validation.
		
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
	
	def rebuildTargets(self, cfg):
		"""Rebuild targets dict using provided config. Keeps last-valid rects on failure.
		
		Args:
			cfg: Configuration dict with crop/target settings
		
		Returns:
			dict: Target index -> RectLTWH
		"""
		targets = {}
		try:
			# Compute screen rect with current crop settings
			screenRect = self.cropRectLTWH(locationHelper.RectLTWH(0, 0, self.resX, self.resY), cfg)
			
			# Try to get each target location, fall back to last-valid if unavailable
			# Target 0: Navigator object (with crop applied)
			navObj = api.getNavigatorObject()
			navLoc = getattr(navObj, "location", None) if navObj else None
			if navLoc:
				navCropped = self.cropRectLTWH(navLoc, cfg)
				targets[0] = navCropped
				self._lastTargets[0] = navCropped
			else:
				targets[0] = self._lastTargets[0]
			
			# Target 1: Whole screen (always use current screenRect)
			targets[1] = screenRect
			self._lastTargets[1] = screenRect
			
			# Target 2: Foreground object (with crop applied)
			fgObj = api.getForegroundObject()
			fgLoc = getattr(fgObj, "location", None) if fgObj else None
			if fgLoc:
				fgCropped = self.cropRectLTWH(fgLoc, cfg)
				targets[2] = fgCropped
				self._lastTargets[2] = fgCropped
			else:
				targets[2] = self._lastTargets[2]
			
			# Target 3: Focus object (with crop applied)
			focusObj = api.getFocusObject()
			focusLoc = getattr(focusObj, "location", None) if focusObj else None
			if focusLoc:
				focusCropped = self.cropRectLTWH(focusLoc, cfg)
				targets[3] = focusCropped
				self._lastTargets[3] = focusCropped
			else:
				targets[3] = self._lastTargets[3]
				
		except Exception:
			# On any error, use last-valid targets
			logHandler.log.exception(f"{ADDON_NAME}: rebuildTargets failed, using last-valid")
			targets = dict(self._lastTargets)
		
		return targets
	
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
				try:
					interval = float(cfg.get("interval", config.conf["lion"]["interval"]))
				except (ValueError, TypeError, KeyError):
					interval = float(config.conf["lion"]["interval"])
				
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

	def OcrScreen(self, cfg, appName, targets):
		"""Perform OCR scan with robust error handling.
		
		Args:
			cfg: Configuration dict snapshot
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
	
	def _cleanOcrStateCache(self):
		"""Periodic cleanup of OCR state cache to prevent memory leak.
		
		Called when total entries exceed limit. Keeps only recent entries per app.
		"""
		try:
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
		except Exception:
			logHandler.log.exception(f"{ADDON_NAME}: Error during cache cleanup")
		finally:
			# CRITICAL: Reset flag to allow future cleanups
			with self._stateLock:
				self._cleanupInProgress = False
	
	def _handleOcrResult(self, result, key, configuredThreshold):
		"""Handle OCR result with per-key anti-repeat state.
		
		Args:
			result: OCR result object
			key: (appName, targetIndex) tuple for state tracking
			configuredThreshold: similarity threshold for this scan
		"""
		# Trigger cleanup with race condition protection
		should_cleanup = False
		with self._stateLock:
			if (len(self._ocrState) > self.MAX_TOTAL_STATE_ENTRIES 
				and not self._cleanupInProgress):
				self._cleanupInProgress = True
				should_cleanup = True
		
		if should_cleanup:
			threading.Thread(target=self._cleanOcrStateCache, daemon=True).start()
		
		o = type('NVDAObjects.NVDAObject', (), {})()
		info = result.makeTextInfo(o, textInfos.POSITION_ALL)
		
		# Thread-safe state access - compute decision under lock
		shouldSpeak = False
		textToSpeak = ""
		with self._stateLock:
			# Get or create state for this key
			state = self._ocrState.setdefault(key, {"prevString": ""})
			prevString = state["prevString"]
			
			# Compute similarity ratio
			ratio = SequenceMatcher(None, prevString, info.text).ratio()
			
			# Determine if we should speak
			if ratio < configuredThreshold and info.text != "" and info.text != "Play":
				shouldSpeak = True
				textToSpeak = info.text
				# Update state for this key
				state["prevString"] = info.text
		
		# Thread-safe UI call: schedule on event queue instead of calling directly
		if shouldSpeak:
			queueHandler.queueFunction(queueHandler.eventQueue, ui.message, textToSpeak)

	__gestures={
		"kb:nvda+alt+l":"ReadLiveOcr"
	}
