import wx
import addonHandler
import gui
import config
import ui
import api

addonHandler.initTranslation()

class frmMain(wx.Frame):
	def __init__(self, parent, backend):
		wx.Frame.__init__(self, parent, id=wx.ID_ANY, title=_("LION Settings"), style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
		self.backend = backend
		self.SetSize((420, 420))
		self.Bind(wx.EVT_CLOSE, self.onClose)

		# Get effective config (global + overrides)
		effectiveConfig = backend.getEffectiveConfig(backend.currentAppProfile)

		panel = wx.Panel(self)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		panel.SetSizer(mainSizer)

		# Active profile label
		self.lblActiveProfile = wx.StaticText(panel, label=_("Active Profile: ") + backend.currentAppProfile)
		mainSizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)

		# Crop settings
		cropBox = wx.StaticBox(panel, label=_("Crop Settings (%)"))
		cropSizer = wx.StaticBoxSizer(cropBox, wx.VERTICAL)

		self.spinCropLeft = self._addSpin(cropSizer, cropBox, _("Crop Left"), int(effectiveConfig.get("cropLeft", 0)))
		self.spinCropRight = self._addSpin(cropSizer, cropBox, _("Crop Right"), int(effectiveConfig.get("cropRight", 0)))
		self.spinCropUp = self._addSpin(cropSizer, cropBox, _("Crop Up"), int(effectiveConfig.get("cropUp", 0)))
		self.spinCropDown = self._addSpin(cropSizer, cropBox, _("Crop Down"), int(effectiveConfig.get("cropDown", 0)))

		mainSizer.Add(cropSizer, 0, wx.ALL | wx.EXPAND, 5)

		# OCR target
		targetBox = wx.StaticBox(panel, label=_("OCR Target"))
		targetSizer = wx.StaticBoxSizer(targetBox, wx.VERTICAL)
		self.choiceTarget = wx.Choice(targetBox, choices=[
			_("Navigator object"),
			_("Whole Screen"),
			_("Current window"),
			_("Current control")
		])
		self.choiceTarget.SetSelection(int(effectiveConfig.get("target", config.conf["lion"]["target"])))
		targetSizer.Add(self.choiceTarget, 0, wx.ALL | wx.EXPAND, 5)
		mainSizer.Add(targetSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Threshold and interval
		timingBox = wx.StaticBox(panel, label=_("Recognition"))
		timingSbSizer = wx.StaticBoxSizer(timingBox, wx.VERTICAL)

		timingGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		timingGrid.AddGrowableCol(1, 1)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Threshold (0-1)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinThreshold = wx.SpinCtrlDouble(timingBox, min=0.0, max=1.0, inc=0.05, initial=float(effectiveConfig.get("threshold", config.conf["lion"]["threshold"])))
		self.spinThreshold.SetDigits(2)
		timingGrid.Add(self.spinThreshold, 1, wx.ALL | wx.EXPAND, 5)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Interval (seconds)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinInterval = wx.SpinCtrlDouble(timingBox, min=0.0, max=10.0, inc=0.1, initial=float(effectiveConfig.get("interval", config.conf["lion"]["interval"])))
		self.spinInterval.SetDigits(1)
		timingGrid.Add(self.spinInterval, 1, wx.ALL | wx.EXPAND, 5)

		timingSbSizer.Add(timingGrid, 1, wx.EXPAND | wx.ALL, 5)
		mainSizer.Add(timingSbSizer, 0, wx.ALL | wx.EXPAND, 5)

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

	def _addSpin(self, sizer, parent, label, value):
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(parent, label=label), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		spin = wx.SpinCtrl(parent, min=0, max=100, initial=value)
		row.Add(spin, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		return spin

	def btnOk_click(self, event):
		config.conf["lion"]["threshold"] = self.spinThreshold.GetValue()
		config.conf["lion"]["interval"] = self.spinInterval.GetValue()
		config.conf["lion"]["target"] = self.choiceTarget.GetSelection()
		config.conf["lion"]["cropLeft"] = int(self.spinCropLeft.GetValue())
		config.conf["lion"]["cropRight"] = int(self.spinCropRight.GetValue())
		config.conf["lion"]["cropUp"] = int(self.spinCropUp.GetValue())
		config.conf["lion"]["cropDown"] = int(self.spinCropDown.GetValue())

		ui.message(_("Global settings saved"))
		self.Close()  # triggers onClose

	def btnCancel_click(self, event):
		ui.message(_("changes canceled"))
		self.Close()  # triggers onClose

	def onSaveProfile(self, event):
		appName = self.backend.currentAppProfile
		
		# If we're in global mode, can't save a profile
		if appName == "global":
			ui.message(_("Cannot save profile in global mode. Switch to an app first."))
			return
		
		# Build data with only values that differ from global config
		# This creates an override-only profile
		overrides = {}
		
		currentValues = {
			"cropLeft": int(self.spinCropLeft.GetValue()),
			"cropRight": int(self.spinCropRight.GetValue()),
			"cropUp": int(self.spinCropUp.GetValue()),
			"cropDown": int(self.spinCropDown.GetValue()),
			"target": self.choiceTarget.GetSelection(),
			"threshold": self.spinThreshold.GetValue(),
			"interval": self.spinInterval.GetValue()
		}
		
		# Only include values that differ from global config
		for key, value in currentValues.items():
			if value != config.conf["lion"][key]:
				overrides[key] = value
		
		# Include spotlight values from backend if they exist in current profile
		if self.backend.currentProfileData:
			for key in ["spotlight_cropLeft", "spotlight_cropRight", "spotlight_cropUp", "spotlight_cropDown"]:
				if key in self.backend.currentProfileData:
					overrides[key] = self.backend.currentProfileData[key]
		
		self.backend.saveProfileForApp(appName, overrides)
		self.lblActiveProfile.SetLabel(_("Active Profile: ") + appName)
		ui.message(_("Per-app profile saved (overrides only)"))

	def onResetProfile(self, event):
		appName = self.backend.currentAppProfile
		self.backend.deleteProfileForApp(appName)
		self.lblActiveProfile.SetLabel(_("Active Profile: global"))
		# Reload global values
		self.spinCropLeft.SetValue(int(config.conf["lion"]["cropLeft"]))
		self.spinCropRight.SetValue(int(config.conf["lion"]["cropRight"]))
		self.spinCropUp.SetValue(int(config.conf["lion"]["cropUp"]))
		self.spinCropDown.SetValue(int(config.conf["lion"]["cropDown"]))
		self.choiceTarget.SetSelection(int(config.conf["lion"]["target"]))
		self.spinThreshold.SetValue(float(config.conf["lion"]["threshold"]))
		self.spinInterval.SetValue(float(config.conf["lion"]["interval"]))
		ui.message(_("Profile reset to global settings"))

	def onClose(self, event):
		self.backend.settingsDialog = None
		self.Destroy()
