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

	currentAppProfile = "global"
	currentProfileData = {}
	
	user32 = ctypes.windll.user32
	resX, resY= user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
	
	spotlightStartPoint = None
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		self._stateLock = threading.Lock()
		self._ocrState = {}
		self.createMenu()
	
	def getProfilePath(self, appName):
		safeName = "".join(x for x in appName if x.isalnum() or x in "-_")
		return os.path.join(PROFILES_DIR, f"{safeName}.json")
	
	def loadGlobalProfile(self):
		self.currentAppProfile = "global"
		self.currentProfileData = {
			"cropLeft": config.conf["lion"]["cropLeft"],
			"cropRight": config.conf["lion"]["cropRight"],
			"cropUp": config.conf["lion"]["cropUp"],
			"cropDown": config.conf["lion"]["cropDown"],
			"spotlight_cropLeft": config.conf["lion"]["spotlight_cropLeft"],
			"spotlight_cropRight": config.conf["lion"]["spotlight_cropRight"],
			"spotlight_cropUp": config.conf["lion"]["spotlight_cropUp"],
			"spotlight_cropDown": config.conf["lion"]["spotlight_cropDown"],
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
		
		# Fallback: Load global defaults but set the CURRENT APP name so we can save it later
		self.currentProfileData = {
			"cropLeft": config.conf["lion"]["cropLeft"],
			"cropRight": config.conf["lion"]["cropRight"],
			"cropUp": config.conf["lion"]["cropUp"],
			"cropDown": config.conf["lion"]["cropDown"],
			"spotlight_cropLeft": config.conf["lion"]["spotlight_cropLeft"],
			"spotlight_cropRight": config.conf["lion"]["spotlight_cropRight"],
			"spotlight_cropUp": config.conf["lion"]["spotlight_cropUp"],
			"spotlight_cropDown": config.conf["lion"]["spotlight_cropDown"],
			"threshold": config.conf["lion"]["threshold"],
			"interval": config.conf["lion"]["interval"]
		}
		self.currentAppProfile = appName
		logHandler.log.info(f"{ADDON_NAME}: Loaded global defaults for new app context: {appName}")
	
	def saveProfileForApp(self, appName, data):
		path = self.getProfilePath(appName)
		try:
			with open(path, "w", encoding="utf-8") as f:
				json.dump(data, f)
			self.currentAppProfile = appName
			self.currentProfileData = data
			logHandler.log.info(f"{ADDON_NAME}: Saved profile for {appName}")
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
		if hasattr(obj, "appModule"):
			newAppName = obj.appModule.appName
			
			if newAppName != self.currentAppProfile and newAppName != "nvda":
				self.loadProfileForApp(newAppName)
				
				# Clear anti-repeat state for the new app to avoid stale suppression
				with self._stateLock:
					# Remove all keys for this app (all targets)
					keys_to_remove = [k for k in self._ocrState.keys() if k[0] == newAppName]
					for k in keys_to_remove:
						del self._ocrState[k]
				
		nextHandler()

	def cropRectLTWH(self, r, useSpotlight=False):
		cfg = self.currentProfileData if self.currentProfileData else config.conf["lion"]
		
		if r is None: return locationHelper.RectLTWH(0,0,0,0)
		
		prefix = "spotlight_" if useSpotlight else ""
		
		try:
			cLeft = int(cfg.get(f"{prefix}cropLeft", 0))
			cUp = int(cfg.get(f"{prefix}cropUp", 0))
			cRight = int(cfg.get(f"{prefix}cropRight", 0))
			cDown = int(cfg.get(f"{prefix}cropDown", 0))
		except (ValueError, TypeError):
			cLeft, cUp, cRight, cDown = 0, 0, 0, 0
		
		# Calculate actual pixel values
		newX = int(r.left + (r.width * cLeft / 100.0))
		newY = int(r.top + (r.height * cUp / 100.0))
		
		# The remaining width is: TotalWidth - (LeftCropPixels + RightCropPixels)
		newWidth = int(r.width * (100 - cLeft - cRight) / 100.0)
		newHeight = int(r.height * (100 - cUp - cDown) / 100.0)
		
		# Safety check to avoid negative or zero dimensions causing OCR crash
		if newWidth <= 0: newWidth = 1
		if newHeight <= 0: newHeight = 1
		
		return locationHelper.RectLTWH(newX, newY, newWidth, newHeight)
	
	def ocrLoop(self):
		cfg=config.conf["lion" ]
		
		self.targets={
			0:api.getNavigatorObject().location,
			#1:locationHelper.RectLTRB(int(cfg["cropLeft"]*self.resX/100.0), int(cfg["cropUp"]*self.resY/100.0), int(self.resX-cfg["cropRight"]*self.resX/100.0), int(self.resY-cfg["cropDown"]*self.resY/100.0)).toLTWH(),
			1:self.cropRectLTWH(locationHelper.RectLTWH(0,0, self.resX, self.resY)),
			2:self.cropRectLTWH(api.getForegroundObject().location),
			3:api.getFocusObject().location
		}
		#print( self.targets)
		global active


		while(active==True ):
			self.OcrScreen()
			time.sleep(config.conf["lion"]["interval"])

	def OcrScreen(self):
		# Snapshot scan context for consistent state during callback
		appName = self.currentAppProfile
		
		# Determine targetIndex with per-app profile fallback
		cfg = self.currentProfileData if self.currentProfileData else config.conf["lion"]
		try:
			targetIndex = int(cfg.get("target", config.conf["lion"]["target"]))
		except (ValueError, TypeError, KeyError):
			targetIndex = int(config.conf["lion"]["target"])
		
		# Get configured threshold for this app
		try:
			configuredThreshold = float(cfg.get("threshold", config.conf["lion"]["threshold"]))
		except (ValueError, TypeError, KeyError):
			configuredThreshold = float(config.conf["lion"]["threshold"])
		
		key = (appName, targetIndex)
		
		left, top, width, height = self.targets[targetIndex]
		
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
		
		# Update current profile data
		if not self.currentProfileData:
			self.currentProfileData = config.conf["lion"]
			
		self.currentProfileData["spotlight_cropLeft"] = pLeft
		self.currentProfileData["spotlight_cropRight"] = pRight
		self.currentProfileData["spotlight_cropUp"] = pUp
		self.currentProfileData["spotlight_cropDown"] = pDown
		
		# Save immediately to persist
		self.saveProfileForApp(self.currentAppProfile, self.currentProfileData)
		
		ui.message(_("Spotlight zone saved"))
		self.spotlightStartPoint = None

	def script_ScanSpotlight(self, gesture):
		logHandler.log.info("LION: script_ScanSpotlight triggered")
		# Manual scan of the spotlight zone
		ui.message(_("Scanning spotlight..."))
		
		# Calculate rect based on spotlight settings
		# Spotlight is always relative to SCREEN (target=1 equivalent)
		
		r = locationHelper.RectLTWH(0, 0, self.resX, self.resY)
		rect = self.cropRectLTWH(r, useSpotlight=True)
		
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
		
		# Thread-safe state access
		with self._stateLock:
			# Get previous string for this key
			state = self._ocrState.get(key, {"prevString": ""})
			prevString = state["prevString"]
			
			# Compute similarity ratio
			ratio = SequenceMatcher(None, prevString, info.text).ratio()
			
			# Speak only if sufficiently different and valid
			if ratio < configuredThreshold and info.text != "" and info.text != "Play":
				ui.message(info.text)
				# Update state for this key
				state["prevString"] = info.text
				self._ocrState[key] = state

	__gestures={
		"kb:nvda+alt+l":"ReadLiveOcr",
		"kb:nvda+shift+1": "SetStartMarker",
		"kb:nvda+shift+2": "SetEndMarker",
		"kb:nvda+shift+l": "ScanSpotlight"
	}
