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
		self.SetSize((420, 420))

		data = backend.currentProfileData if backend.currentProfileData else config.conf["lion"]

		panel = wx.Panel(self)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		panel.SetSizer(mainSizer)

		# Active profile label
		self.lblActiveProfile = wx.StaticText(panel, label=_("Active Profile: ") + getActiveProfileName())
		mainSizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)

		# Crop settings
		cropBox = wx.StaticBox(panel, label=_("Crop Settings (%)"))
		cropSizer = wx.StaticBoxSizer(cropBox, wx.VERTICAL)

		self.spinCropLeft = self._addSpin(cropSizer, panel, _("Crop Left"), int(data.get("cropLeft", 0)))
		self.spinCropRight = self._addSpin(cropSizer, panel, _("Crop Right"), int(data.get("cropRight", 0)))
		self.spinCropUp = self._addSpin(cropSizer, panel, _("Crop Up"), int(data.get("cropUp", 0)))
		self.spinCropDown = self._addSpin(cropSizer, panel, _("Crop Down"), int(data.get("cropDown", 0)))

		mainSizer.Add(cropSizer, 0, wx.ALL | wx.EXPAND, 5)

		# OCR target
		targetBox = wx.StaticBox(panel, label=_("OCR Target"))
		targetSizer = wx.StaticBoxSizer(targetBox, wx.VERTICAL)
		self.choiceTarget = wx.Choice(panel, choices=[
			_("Navigator object"),
			_("Whole Screen"),
			_("Current window"),
			_("Current control")
		])
		self.choiceTarget.SetSelection(int(config.conf["lion"]["target"]))
		targetSizer.Add(self.choiceTarget, 0, wx.ALL | wx.EXPAND, 5)
		mainSizer.Add(targetSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Threshold and interval
		timingBox = wx.StaticBox(panel, label=_("Recognition"))
		timingSizer = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		timingSizer.AddGrowableCol(1, 1)

		timingSizer.Add(wx.StaticText(panel, label=_("Threshold (0-1)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.txtThreshold = wx.TextCtrl(panel, value=str(data.get("threshold", config.conf["lion"]["threshold"])))
		timingSizer.Add(self.txtThreshold, 1, wx.ALL | wx.EXPAND, 5)

		timingSizer.Add(wx.StaticText(panel, label=_("Interval (seconds)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.txtInterval = wx.TextCtrl(panel, value=str(data.get("interval", config.conf["lion"]["interval"])))
		timingSizer.Add(self.txtInterval, 1, wx.ALL | wx.EXPAND, 5)

		mainSizer.Add(timingBox, 0, wx.ALL | wx.EXPAND, 5)
		timingBox.SetSizer(timingSizer)

		# Profile buttons
		btnSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnSaveProfile = wx.Button(panel, label=_("Save Profile"))
		self.btnResetProfile = wx.Button(panel, label=_("Reset Profile"))
		btnSizer.Add(self.btnSaveProfile, 0, wx.ALL, 5)
		btnSizer.Add(self.btnResetProfile, 0, wx.ALL, 5)
		mainSizer.Add(btnSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

		# OK / Cancel buttons
		actionSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnOk = wx.Button(panel, wx.ID_OK, _("OK"))
		self.btnCancel = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
		actionSizer.Add(self.btnOk, 0, wx.ALL, 5)
		actionSizer.Add(self.btnCancel, 0, wx.ALL, 5)
		mainSizer.Add(actionSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

		# Bindings
		self.btnOk.Bind(wx.EVT_BUTTON, self.btnOk_click)
		self.btnCancel.Bind(wx.EVT_BUTTON, self.btnCancel_click)
		self.btnSaveProfile.Bind(wx.EVT_BUTTON, self.onSaveProfile)
		self.btnResetProfile.Bind(wx.EVT_BUTTON, self.onResetProfile)

	def _addSpin(self, sizer, panel, label, value):
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label=label), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		spin = wx.SpinCtrl(panel, min=0, max=100, initial=value)
		row.Add(spin, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		return spin

	def btnOk_click(self, event):
		try:
			config.conf["lion"]["threshold"] = float(self.txtThreshold.GetValue())
			config.conf["lion"]["interval"] = float(self.txtInterval.GetValue())
		except ValueError:
			ui.message(_("Invalid numeric value"))
			return

		config.conf["lion"]["target"] = self.choiceTarget.GetSelection()
		config.conf["lion"]["cropLeft"] = int(self.spinCropLeft.GetValue())
		config.conf["lion"]["cropRight"] = int(self.spinCropRight.GetValue())
		config.conf["lion"]["cropUp"] = int(self.spinCropUp.GetValue())
		config.conf["lion"]["cropDown"] = int(self.spinCropDown.GetValue())

		ui.message(_("settings saved"))
		self.Close()

	def btnCancel_click(self, event):
		ui.message(_("changes canceled"))
		self.Close()

	def onSaveProfile(self, event):
		obj = api.getFocusObject()
		appName = obj.appModule.appName if hasattr(obj, "appModule") else "global"
		data = {
			"cropLeft": int(self.spinCropLeft.GetValue()),
			"cropRight": int(self.spinCropRight.GetValue()),
			"cropUp": int(self.spinCropUp.GetValue()),
			"cropDown": int(self.spinCropDown.GetValue()),
			"threshold": float(self.txtThreshold.GetValue()),
			"interval": float(self.txtInterval.GetValue())
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
		# Reload global values
		self.spinCropLeft.SetValue(int(config.conf["lion"]["cropLeft"]))
		self.spinCropRight.SetValue(int(config.conf["lion"]["cropRight"]))
		self.spinCropUp.SetValue(int(config.conf["lion"]["cropUp"]))
		self.spinCropDown.SetValue(int(config.conf["lion"]["cropDown"]))
		self.txtThreshold.SetValue(str(config.conf["lion"]["threshold"]))
		self.txtInterval.SetValue(str(config.conf["lion"]["interval"]))
		ui.message(_("profile reset"))
