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

		data = backend.currentProfileData if backend.currentProfileData else config.conf["lion"]

		panel = wx.Panel(self)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		panel.SetSizer(mainSizer)

		# Active profile label
		self.lblActiveProfile = wx.StaticText(panel, label=_("Active Profile: ") + backend.currentAppProfile)
		mainSizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)

		# Crop settings
		cropBox = wx.StaticBox(panel, label=_("Crop Settings (%)"))
		cropSizer = wx.StaticBoxSizer(cropBox, wx.VERTICAL)

		self.spinCropLeft = self._addSpin(cropSizer, cropBox, _("Crop Left"), int(data.get("cropLeft", 0)))
		self.spinCropRight = self._addSpin(cropSizer, cropBox, _("Crop Right"), int(data.get("cropRight", 0)))
		self.spinCropUp = self._addSpin(cropSizer, cropBox, _("Crop Up"), int(data.get("cropUp", 0)))
		self.spinCropDown = self._addSpin(cropSizer, cropBox, _("Crop Down"), int(data.get("cropDown", 0)))

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
		# Load target from profile or global config
		target_value = int(data.get("target", config.conf["lion"]["target"]))
		self.choiceTarget.SetSelection(target_value)
		targetSizer.Add(self.choiceTarget, 0, wx.ALL | wx.EXPAND, 5)
		mainSizer.Add(targetSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Threshold and interval
		timingBox = wx.StaticBox(panel, label=_("Recognition"))
		timingSbSizer = wx.StaticBoxSizer(timingBox, wx.VERTICAL)

		timingGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		timingGrid.AddGrowableCol(1, 1)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Threshold (0-1)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.txtThreshold = wx.TextCtrl(timingBox, value=str(data.get("threshold", config.conf["lion"]["threshold"])))
		timingGrid.Add(self.txtThreshold, 1, wx.ALL | wx.EXPAND, 5)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Interval (seconds)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.txtInterval = wx.TextCtrl(timingBox, value=str(data.get("interval", config.conf["lion"]["interval"])))
		timingGrid.Add(self.txtInterval, 1, wx.ALL | wx.EXPAND, 5)

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
	
	def _validateInputs(self):
		"""Validate threshold and interval inputs. Returns (threshold, interval) or (None, None) with error message."""
		try:
			threshold = float(self.txtThreshold.GetValue())
			interval = float(self.txtInterval.GetValue())
			
			# Validate threshold (0-1)
			if threshold < 0.0 or threshold > 1.0:
				ui.message(_("Threshold must be between 0 and 1"))
				return None, None
			
			# Validate interval (> 0, use safe minimum)
			if interval < 0.1:
				ui.message(_("Interval must be at least 0.1 seconds"))
				return None, None
			
			return threshold, interval
		except ValueError:
			ui.message(_("Invalid numeric value"))
			return None, None

	def btnOk_click(self, event):
		threshold, interval = self._validateInputs()
		if threshold is None:
			return

		config.conf["lion"]["threshold"] = threshold
		config.conf["lion"]["interval"] = interval
		config.conf["lion"]["target"] = self.choiceTarget.GetSelection()
		config.conf["lion"]["cropLeft"] = int(self.spinCropLeft.GetValue())
		config.conf["lion"]["cropRight"] = int(self.spinCropRight.GetValue())
		config.conf["lion"]["cropUp"] = int(self.spinCropUp.GetValue())
		config.conf["lion"]["cropDown"] = int(self.spinCropDown.GetValue())

		ui.message(_("settings saved"))
		self.Close()  # triggers onClose

	def btnCancel_click(self, event):
		ui.message(_("changes canceled"))
		self.Close()  # triggers onClose

	def onSaveProfile(self, event):
		threshold, interval = self._validateInputs()
		if threshold is None:
			return
		
		appName = self.backend.currentAppProfile
		data = {
			"cropLeft": int(self.spinCropLeft.GetValue()),
			"cropRight": int(self.spinCropRight.GetValue()),
			"cropUp": int(self.spinCropUp.GetValue()),
			"cropDown": int(self.spinCropDown.GetValue()),
			"threshold": threshold,
			"interval": interval,
			"target": self.choiceTarget.GetSelection()
		}
		
		# Always save spotlight crop values (from profile if exists, else from global config)
		for key in ["spotlight_cropLeft", "spotlight_cropRight", "spotlight_cropUp", "spotlight_cropDown"]:
			if self.backend.currentProfileData and key in self.backend.currentProfileData:
				data[key] = self.backend.currentProfileData[key]
			else:
				data[key] = config.conf["lion"][key]
		
		self.backend.saveProfileForApp(appName, data)
		self.lblActiveProfile.SetLabel(_("Active Profile: ") + appName)
		ui.message(_("profile saved"))

	def onResetProfile(self, event):
		appName = self.backend.currentAppProfile
		self.backend.deleteProfileForApp(appName)
		self.lblActiveProfile.SetLabel(_("Active Profile: global"))
		# Reload global values into GUI
		self.spinCropLeft.SetValue(int(config.conf["lion"]["cropLeft"]))
		self.spinCropRight.SetValue(int(config.conf["lion"]["cropRight"]))
		self.spinCropUp.SetValue(int(config.conf["lion"]["cropUp"]))
		self.spinCropDown.SetValue(int(config.conf["lion"]["cropDown"]))
		self.txtThreshold.SetValue(str(config.conf["lion"]["threshold"]))
		self.txtInterval.SetValue(str(config.conf["lion"]["interval"]))
		self.choiceTarget.SetSelection(int(config.conf["lion"]["target"]))
		ui.message(_("profile reset"))

	def onClose(self, event):
		self.backend.settingsDialog = None
		self.Destroy()
