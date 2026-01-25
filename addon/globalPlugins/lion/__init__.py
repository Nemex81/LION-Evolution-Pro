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

prevString=""
counter=0
recog = contentRecog.uwpOcr.UwpOcr()

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

	currentAppProfile = "global"
	currentProfileData = {}
	
	user32 = ctypes.windll.user32
	resX, resY= user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
	
	
	def __init__(self):
		super(GlobalPlugin, self).__init__()
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
		
		self.loadGlobalProfile()
	
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
		if gui.isInMessageBox:
			return
		gui.mainFrame.prePopup()
		d = lionGui.frmMain(gui.mainFrame, self)
		d.Show()
		gui.mainFrame.postPopup()

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
			
			if newAppName != self.currentAppProfile:
				self.loadProfileForApp(newAppName)
				
		nextHandler()

	def cropRectLTWH(self, r):
		cfg = self.currentProfileData if self.currentProfileData else config.conf["lion"]
		
		if r is None: return locationHelper.RectLTWH(0,0,0,0)
		
		try:
			cLeft = int(cfg.get("cropLeft", 0))
			cUp = int(cfg.get("cropUp", 0))
			cRight = int(cfg.get("cropRight", 0))
			cDown = int(cfg.get("cropDown", 0))
		except (ValueError, TypeError):
			cLeft, cUp, cRight, cDown = 0, 0, 0, 0
		
		return locationHelper.RectLTWH(
			int((r.left+r.width)*cLeft/100.0), 
			int((r.top+r.height)*cUp/100.0), 
			int(r.width-(r.width*cRight/100.0)), 
			int(r.height-(r.height*cDown/100.0))
		)
	
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
		
		global recog
		
		

		left,top, width,height=self.targets[config.conf["lion"]["target"]]
		
		recog = contentRecog.uwpOcr.UwpOcr()

		imgInfo = contentRecog.RecogImageInfo.createFromRecognizer(left, top, width, height, recog)
		sb = screenBitmap.ScreenBitmap(imgInfo.recogWidth, imgInfo.recogHeight) 
		pixels = sb.captureImage(left, top, width, height) 
		recog.recognize(pixels, imgInfo, recog_onResult)


		
	__gestures={
	"kb:nvda+alt+l":"ReadLiveOcr"
	}
	
def recog_onResult(result):
	global prevString
	global recog
	global counter
	counter+=1
	o=type('NVDAObjects.NVDAObject', (), {})()
	info=result.makeTextInfo(o, textInfos.POSITION_ALL)
	threshold=SequenceMatcher(None, prevString, info.text).ratio()
	if threshold<config.conf['lion']['threshold'] and info.text!="" and info.text!="Play":
		ui.message(info.text)
		prevString=info.text

	if counter>9:
		del recog
		counter=0
