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

prevString=""
counter=0

# Constants for threading and error handling
STOP_THREAD_JOIN_TIMEOUT = 0.5  # seconds to wait for thread to stop
ERROR_MESSAGE_RATE_LIMIT = 10.0  # seconds between repeated error messages
ERROR_BACKOFF_THRESHOLD = 3  # number of errors before applying backoff
ERROR_BACKOFF_DELAY = 2.0  # seconds to wait after repeated errors
MIN_OCR_INTERVAL = 0.1  # minimum seconds between OCR iterations
DEFAULT_THRESHOLD = 0.5  # default similarity threshold for OCR text changes
DEFAULT_TARGET = 1  # default OCR target (whole screen)

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
		# Threading & lifecycle state
		self._stopEvent = threading.Event()
		self._workerThread = None
		self._ocrRecognizer = None
		# Error handling state
		self._errorCount = 0
		self._lastErrorTime = 0
		self._lastInvalidTargetWarnTime = 0  # Rate-limit target warning
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
			"interval": config.conf["lion"]["interval"],
			"target": config.conf["lion"]["target"]
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
			"interval": config.conf["lion"]["interval"],
			"target": config.conf["lion"]["target"]
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
	
	def _getSetting(self, key, default=None):
		"""Unified accessor: profile value with fallback to global config."""
		if self.currentProfileData and key in self.currentProfileData:
			return self.currentProfileData.get(key, default)
		return config.conf['lion'].get(key, default)
	
	def _speak(self, text):
		"""Thread-safe UI output via NVDA event queue."""
		queueHandler.queueFunction(queueHandler.eventQueue, ui.message, text)
	
	def _startLiveOcr(self):
		"""Start live OCR worker thread if not already running."""
		if self._workerThread and self._workerThread.is_alive():
			return
		self._stopEvent.clear()
		self._workerThread = threading.Thread(target=self.ocrLoop, daemon=True)
		self._workerThread.start()
	
	def _stopLiveOcr(self):
		"""Signal live OCR worker thread to stop."""
		self._stopEvent.set()
		# Optional brief join to allow clean stop without blocking NVDA
		if self._workerThread and self._workerThread.is_alive():
			self._workerThread.join(timeout=STOP_THREAD_JOIN_TIMEOUT)
	
	def _getRecognizer(self):
		"""Get or create UwpOcr recognizer instance."""
		if self._ocrRecognizer is None:
			self._ocrRecognizer = contentRecog.uwpOcr.UwpOcr()
		return self._ocrRecognizer
	
	def _getCurrentTargetBaseRect(self):
		"""Compute the base rectangle for current OCR target (before cropping)."""
		# Robust target parsing with fallback and clamping
		try:
			target = int(self._getSetting('target', config.conf['lion']['target']))
			# Clamp to valid range (0..3)
			target = max(0, min(3, target))
		except (ValueError, TypeError, KeyError):
			# Fallback to global config or default on parse error
			try:
				target = int(config.conf['lion']['target'])
				target = max(0, min(3, target))
			except (ValueError, TypeError, KeyError):
				# Rate-limit warning to avoid spam (max once per 30 seconds)
				currentTime = time.time()
				if currentTime - self._lastInvalidTargetWarnTime > 30:
					logHandler.log.warning(f"{ADDON_NAME}: Invalid target value, using default {DEFAULT_TARGET}")
					self._lastInvalidTargetWarnTime = currentTime
				target = DEFAULT_TARGET
		
		if target == 0:
			return api.getNavigatorObject().location
		if target == 1:
			return locationHelper.RectLTWH(0, 0, self.resX, self.resY)
		if target == 2:
			return api.getForegroundObject().location
		return api.getFocusObject().location
	
	def _getCurrentTargetRect(self):
		"""Compute the current OCR target rectangle (after cropping)."""
		base = self._getCurrentTargetBaseRect()
		return self.cropRectLTWH(base)
		
	def createMenu(self):
		self.prefsMenu = gui.mainFrame.sysTrayIcon.menu.GetMenuItems()[0].GetSubMenu()
		self.lionSettingsItem = self.prefsMenu.Append(wx.ID_ANY,
			# Translators: name of the option in the menu.
			_("&Lion Evolution Pro settings..."),
			# Translators: tooltip text for the menu item.
			_("Modify OCR zone, interval and per-app profiles"))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onSettings, self.lionSettingsItem)

	def terminate(self):
		# Stop live OCR worker thread before terminating
		self._stopLiveOcr()
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
		
		# Check if live OCR is currently running
		isRunning = self._workerThread and self._workerThread.is_alive()
		
		if not isRunning:
			self._startLiveOcr()
			tones.beep(444, 333)
			ui.message(_("lion started"))
		else:
			self._stopLiveOcr()
			tones.beep(222, 333)
			ui.message(_("lion stopped"))
			
	def event_gainFocus(self, obj, nextHandler):
		if hasattr(obj, "appModule"):
			newAppName = obj.appModule.appName
			
			if newAppName != self.currentAppProfile and newAppName != "nvda":
				self.loadProfileForApp(newAppName)
				
		nextHandler()

	def cropRectLTWH(self, r, useSpotlight=False):
		if r is None: return locationHelper.RectLTWH(0,0,0,0)
		
		prefix = "spotlight_" if useSpotlight else ""
		
		try:
			cLeft = int(self._getSetting(f"{prefix}cropLeft", 0))
			cUp = int(self._getSetting(f"{prefix}cropUp", 0))
			cRight = int(self._getSetting(f"{prefix}cropRight", 0))
			cDown = int(self._getSetting(f"{prefix}cropDown", 0))
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
		"""Live OCR worker loop with dynamic target rectangles and interruptible sleep."""
		logHandler.log.info(f"{ADDON_NAME}: Live OCR loop started")
		
		try:
			while not self._stopEvent.is_set():
				try:
					# Recompute target rectangle dynamically every iteration
					rect = self._getCurrentTargetRect()
					
					# Validate rect dimensions
					if rect.width <= 0 or rect.height <= 0:
						logHandler.log.warning(f"{ADDON_NAME}: Invalid target rect, skipping OCR iteration")
					else:
						self.OcrScreen(rect)
						# Reset error count on successful OCR
						self._errorCount = 0
				except Exception as e:
					logHandler.log.error(f"{ADDON_NAME}: Error in OCR loop: {e}")
					# Reset recognizer on failure
					self._ocrRecognizer = None
					
					# Error spam prevention: rate-limit error messages
					currentTime = time.time()
					self._errorCount += 1
					
					# Only speak error if: first error OR more than rate limit seconds since last error message
					if self._errorCount == 1 or (currentTime - self._lastErrorTime) > ERROR_MESSAGE_RATE_LIMIT:
						self._speak(_("OCR error"))
						self._lastErrorTime = currentTime
					
					# Backoff on repeated errors: wait longer after threshold consecutive errors
					if self._errorCount >= ERROR_BACKOFF_THRESHOLD:
						logHandler.log.warning(f"{ADDON_NAME}: Multiple errors ({self._errorCount}), applying backoff")
						self._stopEvent.wait(ERROR_BACKOFF_DELAY)  # Extra backoff delay
						continue
				
				# Interruptible sleep using profile-aware interval with robust parsing
				try:
					interval = float(self._getSetting('interval', 1.0))
					# Enforce minimum interval at runtime
					if interval < MIN_OCR_INTERVAL:
						interval = MIN_OCR_INTERVAL
				except (ValueError, TypeError):
					logHandler.log.warning(f"{ADDON_NAME}: Invalid interval value, using default 1.0s")
					interval = 1.0
				
				self._stopEvent.wait(interval)
		finally:
			# Always reset worker thread reference on exit
			self._workerThread = None
			logHandler.log.info(f"{ADDON_NAME}: Live OCR loop stopped")

	def OcrScreen(self, rect):
		"""Perform OCR on the given rectangle using reusable recognizer."""
		# Robust rect unpacking using attributes (RectLTWH may not be iterable)
		left = rect.left
		top = rect.top
		width = rect.width
		height = rect.height
		
		recog = self._getRecognizer()
		
		imgInfo = contentRecog.RecogImageInfo.createFromRecognizer(left, top, width, height, recog)
		sb = screenBitmap.ScreenBitmap(imgInfo.recogWidth, imgInfo.recogHeight) 
		pixels = sb.captureImage(left, top, width, height)
		
		# Get threshold from profile with robust parsing and clamping
		try:
			threshold = float(self._getSetting('threshold', DEFAULT_THRESHOLD))
			# Clamp threshold between 0.0 and 1.0 (consistent with GUI validation)
			threshold = max(0.0, min(1.0, threshold))
		except (ValueError, TypeError):
			logHandler.log.warning(f"{ADDON_NAME}: Invalid threshold value, using default {DEFAULT_THRESHOLD}")
			threshold = DEFAULT_THRESHOLD
		
		recog.recognize(pixels, imgInfo, lambda result: recog_onResult(result, threshold, self._speak))
	
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
					# Thread-safe UI output
					queueHandler.queueFunction(queueHandler.eventQueue, ui.message, info.text)
				else:
					queueHandler.queueFunction(queueHandler.eventQueue, ui.message, _("No text found"))

			recog.recognize(pixels, imgInfo, on_spotlight_result)
		except Exception as e:
			logHandler.log.error(f"Spotlight OCR failed: {e}")
			ui.message(_("OCR error"))

	__gestures={
		"kb:nvda+alt+l":"ReadLiveOcr",
		"kb:nvda+shift+1": "SetStartMarker",
		"kb:nvda+shift+2": "SetEndMarker",
		"kb:nvda+shift+l": "ScanSpotlight"
	}
	
def recog_onResult(result, threshold, speak_func):
	"""
	OCR result callback with thread-safe UI output.
	
	Args:
		result: OCR result object
		threshold: similarity threshold from profile
		speak_func: thread-safe function to output text
	"""
	global prevString
	global counter
	counter += 1
	o = type('NVDAObjects.NVDAObject', (), {})()
	info = result.makeTextInfo(o, textInfos.POSITION_ALL)
	similarity = SequenceMatcher(None, prevString, info.text).ratio()
	
	if similarity < threshold and info.text != "" and info.text != "Play":
		speak_func(info.text)
		prevString = info.text
	
	if counter > 9:
		counter = 0
