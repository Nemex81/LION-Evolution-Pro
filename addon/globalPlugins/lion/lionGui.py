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
		# Load target from profile with robust parsing
		target_value = self._getSafeTargetSelection(data)
		self.choiceTarget.SetSelection(target_value)
		targetSizer.Add(self.choiceTarget, 0, wx.ALL | wx.EXPAND, 5)
		mainSizer.Add(targetSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Threshold and interval
		timingBox = wx.StaticBox(panel, label=_("Recognition"))
		timingSbSizer = wx.StaticBoxSizer(timingBox, wx.VERTICAL)

		timingGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		timingGrid.AddGrowableCol(1, 1)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Threshold (0-1)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinThreshold = wx.SpinCtrlDouble(timingBox, 
			min=0.0, max=1.0, initial=float(data.get("threshold", config.conf["lion"]["threshold"])),
			inc=0.01, style=wx.SP_ARROW_KEYS)
		self.spinThreshold.SetDigits(2)
		timingGrid.Add(self.spinThreshold, 1, wx.ALL | wx.EXPAND, 5)

		timingGrid.Add(wx.StaticText(timingBox, label=_("Interval (seconds)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinInterval = wx.SpinCtrlDouble(timingBox,
			min=0.1, max=10.0, initial=float(data.get("interval", config.conf["lion"]["interval"])),
			inc=0.1, style=wx.SP_ARROW_KEYS)
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
	
	def _getSafeTargetSelection(self, value_or_data):
		"""
		Safely parse and clamp target value from profile data or config value.
		Returns a valid target index [0..3] with fallback to 1 (whole screen).
		"""
		try:
			# Handle dict-like data (from profile) or direct value (from config)
			if isinstance(value_or_data, dict):
				target_value = int(value_or_data.get("target", config.conf["lion"]["target"]))
			else:
				target_value = int(value_or_data)
			# Clamp to valid range [0..3]
			target_value = max(0, min(3, target_value))
		except (ValueError, TypeError, KeyError):
			# Fallback to global config or default (1 = whole screen)
			try:
				target_value = int(config.conf["lion"]["target"])
				target_value = max(0, min(3, target_value))
			except (ValueError, TypeError, KeyError):
				target_value = 1  # Default to whole screen
		return target_value
	
	def _validateInputs(self):
		"""Get threshold and interval values from spin controls (already validated by range)."""
		threshold = self.spinThreshold.GetValue()
		interval = self.spinInterval.GetValue()
		# SpinCtrlDouble already enforces min/max, so no additional validation needed
		return threshold, interval

	def btnOk_click(self, event):
		threshold, interval = self._validateInputs()

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
		self.spinThreshold.SetValue(float(config.conf["lion"]["threshold"]))
		self.spinInterval.SetValue(float(config.conf["lion"]["interval"]))
		# Use robust target parsing with fallback
		target_value = self._getSafeTargetSelection(config.conf["lion"]["target"])
		self.choiceTarget.SetSelection(target_value)
		ui.message(_("profile reset"))

	def onClose(self, event):
		self.backend.settingsDialog = None
		self.Destroy()
