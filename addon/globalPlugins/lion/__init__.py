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
   - Also includes spotlight_* keys for spotlight feature

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
- Spotlight feature works with both global and per-app configs

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
from . import lionGui
from scriptHandler import getLastScriptRepeatCount, script

from difflib import SequenceMatcher
import ctypes
import os
import json
import globalVars


addonHandler.initTranslation()
active=False

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
	"spotlight_cropUp": "integer(0,100,default=0)",
	"spotlight_cropLeft": "integer(0,100,default=0)",
	"spotlight_cropRight": "integer(0,100,default=0)",
	"spotlight_cropDown": "integer(0,100,default=0)",
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

	currentAppProfile = "global"
	currentProfileData = {}
	
	user32 = ctypes.windll.user32
	resX, resY= user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
	
	spotlightStartPoint = None
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		self._stateLock = threading.Lock()
		self._ocrState = {}
		self._profileLock = threading.Lock()
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
			"spotlight_cropLeft": config.conf["lion"]["spotlight_cropLeft"],
			"spotlight_cropRight": config.conf["lion"]["spotlight_cropRight"],
			"spotlight_cropUp": config.conf["lion"]["spotlight_cropUp"],
			"spotlight_cropDown": config.conf["lion"]["spotlight_cropDown"],
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
		
		# Spotlight keys: always keep if present (they are inherently overrides)
		spotlightKeys = ["spotlight_cropLeft", "spotlight_cropRight", "spotlight_cropUp", "spotlight_cropDown"]
		for key in spotlightKeys:
			if key in profileData:
				# Check if it differs from global spotlight defaults
				if key in config.conf["lion"] and profileData[key] != config.conf["lion"][key]:
					overrides[key] = profileData[key]
				elif key not in config.conf["lion"]:
					# If spotlight key doesn't exist in global, keep it as override
					overrides[key] = profileData[key]
		
		return overrides
	
	def loadProfileForApp(self, appName):
		"""Load profile for specific app. If no profile exists, keeps currentAppProfile="global".
		
		Args:
			appName: Application name to load profile for
		"""
		path = self.getProfilePath(appName)
		if os.path.exists(path):
			try:
				with open(path, "r") as f:
					rawProfileData = json.load(f)
				
				# Migrate/normalize: convert full config to overrides-only
				profileData = self._normalizeProfileToOverrides(rawProfileData)
				
				# If normalized profile is empty (all values matched global), treat as no profile
				if not profileData:
					logHandler.log.info(f"{ADDON_NAME}: Profile for {appName} is now empty after normalization (all values match global)")
					self.currentAppProfile = "global"
					self.currentProfileData = {}
					# Optionally delete the empty profile file
					try:
						os.remove(path)
						logHandler.log.info(f"{ADDON_NAME}: Removed empty profile file for {appName}")
					except:
						pass
					return
				
				# Save normalized profile back to disk (migration)
				if profileData != rawProfileData:
					try:
						with open(path, "w", encoding="utf-8") as f:
							json.dump(profileData, f, indent=2)
						logHandler.log.info(f"{ADDON_NAME}: Migrated profile for {appName} to override-only format")
					except Exception as e:
						logHandler.log.error(f"{ADDON_NAME}: Failed to migrate profile for {appName}: {e}")
				
				self.currentProfileData = profileData
				self.currentAppProfile = appName
				logHandler.log.info(f"{ADDON_NAME}: Loaded profile overrides for {appName}")
				return
			except Exception as e:
				logHandler.log.error(f"{ADDON_NAME}: Error loading {appName}: {e}")
		
		# No profile exists - fall back to global (upstream behavior)
		self.currentAppProfile = "global"
		self.currentProfileData = {}
		logHandler.log.info(f"{ADDON_NAME}: No profile for {appName}, using global config")
	
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
			self.currentProfileData = data
			logHandler.log.info(f"{ADDON_NAME}: Saved profile for {appName} (overrides only)")
		except Exception as e:
			logHandler.log.error(f"{ADDON_NAME}: Error saving profile for {appName}: {e}")
	
	def deleteProfileForApp(self, appName):
		path = self.getProfilePath(appName)
		if os.path.exists(path):
			try:
				os.remove(path)
				logHandler.log.info(f"{ADDON_NAME}: Deleted profile for {appName}")
			except Exception as e:
				logHandler.log.error(f"{ADDON_NAME}: Error deleting profile for {appName}: {e}")
		self.loadGlobalProfile()
		
	def createMenu(self):
		self.prefsMenu = gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
		self.lionSettingsItem = self.prefsMenu.Append(wx.ID_ANY,
			# Translators: name of the option in the menu.
			_("&Lion Evolution Pro settings..."),
			# Translators: tooltip text for the menu item.
			_("Modify OCR zone, interval and per-app profiles"))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onSettings, self.lionSettingsItem)

	def terminate(self):
		try:
			self.prefsMenu.RemoveItem(self.lionSettingsItem)
		except wx.PyDeadObjectError:
			pass

	def onSettings(self, evt):
		if hasattr(self, "settingsDialog") and self.settingsDialog:
			try:
				self.settingsDialog.Raise()
				self.settingsDialog.Show()
				return
			except Exception:
				self.settingsDialog = None
		try:
			self.settingsDialog = lionGui.frmMain(gui.mainFrame, self)
			self.settingsDialog.Show()
		except Exception as e:
			logHandler.log.error(f"{ADDON_NAME}: Error creating settings dialog: {e}")
			self.settingsDialog = None
			ui.message("Error opening settings")

	def script_ReadLiveOcr(self, gesture):
		repeat = getLastScriptRepeatCount()
#		if repeat>=2:
#			ui.message("o sa vine profile")
		global active
		
		if(active==False):
			active=True
			tones.beep(444,333)
			ui.message(_("lion started"))
			nav=api.getNavigatorObject()

			threading.Thread(target=self.ocrLoop).start()
		
		else:
			
			active=False
			tones.beep(222,333)
			ui.message(("lion stopped"))
			
	def event_gainFocus(self, obj, nextHandler):
		try:
			# Safe access to appModule and appName
			appMod = getattr(obj, "appModule", None)
			newAppName = getattr(appMod, "appName", None) if appMod else None
			
			if newAppName and newAppName != self.currentAppProfile and newAppName != "nvda":
				# Thread-safe profile loading
				with self._profileLock:
					self.loadProfileForApp(newAppName)
				
				# Clear anti-repeat state for the new app to avoid stale suppression
				with self._stateLock:
					# Remove all keys for this app (all targets)
					keys_to_remove = [k for k in self._ocrState.keys() if k[0] == newAppName]
					for k in keys_to_remove:
						del self._ocrState[k]
		except Exception:
			# Never crash NVDA on focus events
			logHandler.log.exception(f"{ADDON_NAME}: event_gainFocus failed")
		finally:
			# Always call nextHandler
			nextHandler()

	def cropRectLTWH(self, r, cfg, useSpotlight=False):
		"""Crop rectangle using config. Pure function (no self state access).
		Uses upstream LION-compatible crop semantics.
		"""
		if r is None: return locationHelper.RectLTWH(0,0,0,0)
		
		prefix = "spotlight_" if useSpotlight else ""
		
		try:
			cLeft = int(cfg.get(f"{prefix}cropLeft", 0))
			cUp = int(cfg.get(f"{prefix}cropUp", 0))
			cRight = int(cfg.get(f"{prefix}cropRight", 0))
			cDown = int(cfg.get(f"{prefix}cropDown", 0))
		except (ValueError, TypeError):
			cLeft, cUp, cRight, cDown = 0, 0, 0, 0
		
		# Upstream LION-compatible formula
		# Left/Top: (original + size) * percentage
		# Width/Height: original size - (size * right/down percentage)
		newX = int((r.left + r.width) * cLeft / 100.0)
		newY = int((r.top + r.height) * cUp / 100.0)
		newWidth = int(r.width - (r.width * cRight / 100.0))
		newHeight = int(r.height - (r.height * cDown / 100.0))
		
		# Safety check to avoid negative or zero dimensions causing OCR crash
		if newWidth <= 0: newWidth = 1
		if newHeight <= 0: newHeight = 1
		
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
		global active
		
		while(active==True ):
			# Snapshot effective config once per scan (thread-safe)
			with self._profileLock:
				appName = self.currentAppProfile
				cfg = self.getEffectiveConfig(appName)
			
			# Rebuild targets with this config snapshot
			targets = self.rebuildTargets(cfg)
			
			# Perform OCR with consistent config and targets
			self.OcrScreen(cfg, appName, targets)
			
			# Use interval from same config snapshot
			try:
				interval = float(cfg.get("interval", config.conf["lion"]["interval"]))
			except (ValueError, TypeError, KeyError):
				interval = float(config.conf["lion"]["interval"])
			time.sleep(interval)

	def OcrScreen(self, cfg, appName, targets):
		"""Perform OCR scan with provided config and targets.
		
		Args:
			cfg: Configuration dict snapshot
			appName: Current app profile name
			targets: Pre-computed target rectangles dict
		"""
		# Determine targetIndex from config snapshot
		try:
			targetIndex = int(cfg.get("target", config.conf["lion"]["target"]))
		except (ValueError, TypeError, KeyError):
			targetIndex = int(config.conf["lion"]["target"])
		
		# Get configured threshold from config snapshot
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
		
		# Debug logging (helps validate settings are applied)
		logHandler.log.info(f"{ADDON_NAME} Scan: app={appName}, target={targetIndex}, "
			f"rect=({left},{top},{width}x{height}), threshold={configuredThreshold:.2f}, interval={interval:.1f}")
		
		recog = contentRecog.uwpOcr.UwpOcr()

		imgInfo = contentRecog.RecogImageInfo.createFromRecognizer(left, top, width, height, recog)
		sb = screenBitmap.ScreenBitmap(imgInfo.recogWidth, imgInfo.recogHeight) 
		pixels = sb.captureImage(left, top, width, height)
		
		# Pass key and threshold to callback via closure
		def callback(result):
			self._handleOcrResult(result, key, configuredThreshold)
		
		recog.recognize(pixels, imgInfo, callback)
	
	def script_SetStartMarker(self, gesture):
		logHandler.log.info("LION: script_SetStartMarker triggered")
		pos = api.getMouseObject().location
		# Store top-left of mouse pointer as the start point (x, y)
		self.spotlightStartPoint = (pos.left, pos.top)
		ui.message(_("Start marker set"))
	
	def script_SetEndMarker(self, gesture):
		logHandler.log.info("LION: script_SetEndMarker triggered")
		if not self.spotlightStartPoint:
			ui.message(_("Set start marker first"))
			return
			
		pos = api.getMouseObject().location
		endX, endY = pos.left, pos.top
		startX, startY = self.spotlightStartPoint
		
		# Calculate screen dimensions from global config or system metrics
		screenWidth = self.resX
		screenHeight = self.resY
		
		# Ensure start is top-left and end is bottom-right regardless of selection order
		left = min(startX, endX)
		top = min(startY, endY)
		right = max(startX, endX)
		bottom = max(startY, endY)
		
		# Calculate percentages relative to full screen
		# Left % = (Left Coord / Width) * 100
		pLeft = int((left / screenWidth) * 100)
		pUp = int((top / screenHeight) * 100)
		
		# Right % = ((Width - Right Coord) / Width) * 100
		pRight = int(((screenWidth - right) / screenWidth) * 100)
		pDown = int(((screenHeight - bottom) / screenHeight) * 100)
		
		# Update current profile data (spotlight overrides)
		# Ensure we have a profile data dict to modify
		if not self.currentProfileData:
			self.currentProfileData = {}
			
		self.currentProfileData["spotlight_cropLeft"] = pLeft
		self.currentProfileData["spotlight_cropRight"] = pRight
		self.currentProfileData["spotlight_cropUp"] = pUp
		self.currentProfileData["spotlight_cropDown"] = pDown
		
		# If we're in global mode, we need to get the current app to save a profile
		with self._profileLock:
			appName = self.currentAppProfile
			# If still global, try to get current foreground app
			if appName == "global":
				try:
					fgObj = api.getForegroundObject()
					if hasattr(fgObj, "appModule") and hasattr(fgObj.appModule, "appName"):
						appName = fgObj.appModule.appName
						self.currentAppProfile = appName
				except:
					pass
		
		# Save immediately to persist
		if appName != "global":
			self.saveProfileForApp(appName, self.currentProfileData)
		
		ui.message(_("Spotlight zone saved"))
		self.spotlightStartPoint = None

	def script_ScanSpotlight(self, gesture):
		logHandler.log.info("LION: script_ScanSpotlight triggered")
		# Manual scan of the spotlight zone
		ui.message(_("Scanning spotlight..."))
		
		# Calculate rect based on spotlight settings
		# Spotlight is always relative to SCREEN (target=1 equivalent)
		
		# Get current profile config for spotlight crop
		with self._profileLock:
			appName = self.currentAppProfile
			cfg = self.getEffectiveConfig(appName)
		
		r = locationHelper.RectLTWH(0, 0, self.resX, self.resY)
		rect = self.cropRectLTWH(r, cfg, useSpotlight=True)
		
		# Validate rect before OCR to avoid "Image not visible" error
		if rect.width <= 0 or rect.height <= 0:
			ui.message(_("Invalid spotlight area"))
			return

		try:
			recog = contentRecog.uwpOcr.UwpOcr()
			imgInfo = contentRecog.RecogImageInfo.createFromRecognizer(rect.left, rect.top, rect.width, rect.height, recog)
			sb = screenBitmap.ScreenBitmap(imgInfo.recogWidth, imgInfo.recogHeight) 
			pixels = sb.captureImage(rect.left, rect.top, rect.width, rect.height) 
			
			def on_spotlight_result(result):
				o = type('NVDAObjects.NVDAObject', (), {})()
				info = result.makeTextInfo(o, textInfos.POSITION_ALL)
				if info.text:
					ui.message(info.text)
				else:
					ui.message(_("No text found"))

			recog.recognize(pixels, imgInfo, on_spotlight_result)
		except Exception as e:
			logHandler.log.error(f"Spotlight OCR failed: {e}")
			ui.message(_("OCR error"))
	
	def _handleOcrResult(self, result, key, configuredThreshold):
		"""Handle OCR result with per-key anti-repeat state.
		
		Args:
			result: OCR result object
			key: (appName, targetIndex) tuple for state tracking
			configuredThreshold: similarity threshold for this scan
		"""
		o = type('NVDAObjects.NVDAObject', (), {})()
		info = result.makeTextInfo(o, textInfos.POSITION_ALL)
		
		# Thread-safe state access - compute decision under lock
		shouldSpeak = False
		with self._stateLock:
			# Get or create state for this key
			state = self._ocrState.setdefault(key, {"prevString": ""})
			prevString = state["prevString"]
			
			# Compute similarity ratio
			ratio = SequenceMatcher(None, prevString, info.text).ratio()
			
			# Determine if we should speak
			if ratio < configuredThreshold and info.text != "" and info.text != "Play":
				shouldSpeak = True
				# Update state for this key
				state["prevString"] = info.text
		
		# Speak outside of lock to avoid blocking
		if shouldSpeak:
			ui.message(info.text)

	__gestures={
		"kb:nvda+alt+l":"ReadLiveOcr",
		"kb:nvda+shift+1": "SetStartMarker",
		"kb:nvda+shift+2": "SetEndMarker",
		"kb:nvda+shift+l": "ScanSpotlight"
	}
