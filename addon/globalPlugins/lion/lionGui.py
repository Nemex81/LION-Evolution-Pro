import wx
import addonHandler
import gui
import config
import ui
import api
addonHandler.initTranslation()

def getActiveProfileName():
	if hasattr(gui.mainFrame, "lionActiveProfile"):
		return gui.mainFrame.lionActiveProfile
	return "global"

class frmMain(wx.Frame):
	def __init__(self, parent, backend):
		wx.Frame.__init__(self, parent, id=wx.ID_ANY, title=_("LION Settings"), style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
		self.backend = backend
		self.SetSize((400, 300))
		
		self.panel = wx.Panel(self)
		self.sizer = wx.WrapSizer(wx.HORIZONTAL)
		self.panel.SetSizer(self.sizer)
		
		self.lblActiveProfile = wx.StaticText(self.panel, label=_("Active Profile: ") + getActiveProfileName())
		self.sizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)
		
		self.btnSaveProfile = wx.Button(self.panel, label=_("Save Profile"))
		self.sizer.Add(self.btnSaveProfile, 0, wx.ALL, 5)
		
		self.btnResetProfile = wx.Button(self.panel, label=_("Reset Profile"))
		self.sizer.Add(self.btnResetProfile, 0, wx.ALL, 5)
		
		self.btnSaveProfile.Bind(wx.EVT_BUTTON, self.onSaveProfile)
		self.btnResetProfile.Bind(wx.EVT_BUTTON, self.onResetProfile)
		
	
	def onSaveProfile(self, event):
		obj = api.getFocusObject()
		appName = obj.appModule.appName if hasattr(obj, "appModule") else "global"
		data = {
			"cropLeft": config.conf["lion"]["cropLeft"],
			"cropRight": config.conf["lion"]["cropRight"],
			"cropUp": config.conf["lion"]["cropUp"],
			"cropDown": config.conf["lion"]["cropDown"],
			"threshold": config.conf["lion"]["threshold"],
			"interval": config.conf["lion"]["interval"]
		}
		self.backend.saveProfileForApp(appName, data)
		gui.mainFrame.lionActiveProfile = appName
		self.lblActiveProfile.SetLabel(_("Active Profile: ") + appName)
		ui.message(_("profile saved"))
	
	def onResetProfile(self, event):
		obj = api.getFocusObject()
		appName = obj.appModule.appName if hasattr(obj, "appModule") else "global"
		self.backend.deleteProfileForApp(appName)
		gui.mainFrame.lionActiveProfile = "global"
		self.lblActiveProfile.SetLabel(_("Active Profile: global"))
		ui.message(_("profile reset"))
