import wx
import addonHandler
import gui
import config
import ui
import api
import os

addonHandler.initTranslation()

class frmMain(wx.Frame):
	def __init__(self, parent, backend):
		wx.Frame.__init__(self, parent, id=wx.ID_ANY, title=_("LION Settings"), style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
		self.backend = backend
		self.SetSize((500, 500))
		self.Bind(wx.EVT_CLOSE, self.onClose)

		# Get effective config (global + overrides)
		effectiveConfig = backend.getEffectiveConfig(backend.currentAppProfile)

		panel = wx.Panel(self)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		panel.SetSizer(mainSizer)

		# Active profile label
		self.lblActiveProfile = wx.StaticText(panel, label=_("Active Profile: ") + backend.currentAppProfile)
		mainSizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)

		# Create notebook with tabs
		self.notebook = wx.Notebook(panel)
		mainSizer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 5)

		# Tab 1: General Settings (upstream order)
		self.generalTab = wx.Panel(self.notebook)
		self.notebook.AddPage(self.generalTab, _("General"))
		self._createGeneralTab(self.generalTab, effectiveConfig)

		# Tab 2: Profiles
		self.profilesTab = wx.Panel(self.notebook)
		self.notebook.AddPage(self.profilesTab, _("Profiles"))
		self._createProfilesTab(self.profilesTab)

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

	def _createGeneralTab(self, parent, effectiveConfig):
		"""Create General settings tab with upstream order: Interval → Target → Threshold → Crop"""
		tabSizer = wx.BoxSizer(wx.VERTICAL)
		parent.SetSizer(tabSizer)

		# Interval (first, as per upstream)
		intervalBox = wx.StaticBox(parent, label=_("Interval"))
		intervalSizer = wx.StaticBoxSizer(intervalBox, wx.VERTICAL)
		intervalGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		intervalGrid.AddGrowableCol(1, 1)
		intervalGrid.Add(wx.StaticText(intervalBox, label=_("Interval (seconds)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinInterval = wx.SpinCtrlDouble(intervalBox, min=0.0, max=10.0, inc=0.1, initial=float(effectiveConfig.get("interval", config.conf["lion"]["interval"])))
		self.spinInterval.SetDigits(1)
		intervalGrid.Add(self.spinInterval, 1, wx.ALL | wx.EXPAND, 5)
		intervalSizer.Add(intervalGrid, 0, wx.EXPAND | wx.ALL, 5)
		tabSizer.Add(intervalSizer, 0, wx.ALL | wx.EXPAND, 5)

		# OCR Target (second, as per upstream)
		targetBox = wx.StaticBox(parent, label=_("OCR Target"))
		targetSizer = wx.StaticBoxSizer(targetBox, wx.VERTICAL)
		self.choiceTarget = wx.Choice(targetBox, choices=[
			_("Navigator object"),
			_("Whole Screen"),
			_("Current window"),
			_("Current control")
		])
		self.choiceTarget.SetSelection(int(effectiveConfig.get("target", config.conf["lion"]["target"])))
		targetSizer.Add(self.choiceTarget, 0, wx.ALL | wx.EXPAND, 5)
		tabSizer.Add(targetSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Threshold (third, as per upstream)
		thresholdBox = wx.StaticBox(parent, label=_("Threshold"))
		thresholdSizer = wx.StaticBoxSizer(thresholdBox, wx.VERTICAL)
		thresholdGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		thresholdGrid.AddGrowableCol(1, 1)
		thresholdGrid.Add(wx.StaticText(thresholdBox, label=_("Threshold (0-1)")), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinThreshold = wx.SpinCtrlDouble(thresholdBox, min=0.0, max=1.0, inc=0.05, initial=float(effectiveConfig.get("threshold", config.conf["lion"]["threshold"])))
		self.spinThreshold.SetDigits(2)
		thresholdGrid.Add(self.spinThreshold, 1, wx.ALL | wx.EXPAND, 5)
		thresholdSizer.Add(thresholdGrid, 0, wx.EXPAND | wx.ALL, 5)
		tabSizer.Add(thresholdSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Crop settings (fourth, as per upstream)
		cropBox = wx.StaticBox(parent, label=_("Crop Settings (%)"))
		cropSizer = wx.StaticBoxSizer(cropBox, wx.VERTICAL)
		self.spinCropLeft = self._addSpin(cropSizer, cropBox, _("Crop Left"), int(effectiveConfig.get("cropLeft", 0)))
		self.spinCropRight = self._addSpin(cropSizer, cropBox, _("Crop Right"), int(effectiveConfig.get("cropRight", 0)))
		self.spinCropUp = self._addSpin(cropSizer, cropBox, _("Crop Up"), int(effectiveConfig.get("cropUp", 0)))
		self.spinCropDown = self._addSpin(cropSizer, cropBox, _("Crop Down"), int(effectiveConfig.get("cropDown", 0)))
		tabSizer.Add(cropSizer, 0, wx.ALL | wx.EXPAND, 5)

	def _createProfilesTab(self, parent):
		"""Create Profiles management tab"""
		tabSizer = wx.BoxSizer(wx.VERTICAL)
		parent.SetSizer(tabSizer)

		# Profile list
		listBox = wx.StaticBox(parent, label=_("Available Profiles"))
		listSizer = wx.StaticBoxSizer(listBox, wx.VERTICAL)
		
		self.lstProfiles = wx.ListBox(listBox)
		listSizer.Add(self.lstProfiles, 1, wx.ALL | wx.EXPAND, 5)
		tabSizer.Add(listSizer, 1, wx.ALL | wx.EXPAND, 5)

		# Populate profile list
		self._refreshProfileList()

		# Profile action buttons
		btnSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnAddProfile = wx.Button(parent, label=_("Add Profile"))
		self.btnDeleteProfile = wx.Button(parent, label=_("Delete Profile"))
		self.btnSetActive = wx.Button(parent, label=_("Set Active"))
		self.btnSaveProfile = wx.Button(parent, label=_("Save Current Settings to Profile"))
		
		btnSizer.Add(self.btnAddProfile, 0, wx.ALL, 5)
		btnSizer.Add(self.btnDeleteProfile, 0, wx.ALL, 5)
		btnSizer.Add(self.btnSetActive, 0, wx.ALL, 5)
		btnSizer.Add(self.btnSaveProfile, 0, wx.ALL, 5)
		tabSizer.Add(btnSizer, 0, wx.ALL | wx.CENTER, 5)

		# Bindings
		self.btnAddProfile.Bind(wx.EVT_BUTTON, self.onAddProfile)
		self.btnDeleteProfile.Bind(wx.EVT_BUTTON, self.onDeleteProfile)
		self.btnSetActive.Bind(wx.EVT_BUTTON, self.onSetActive)
		self.btnSaveProfile.Bind(wx.EVT_BUTTON, self.onSaveProfile)

	def _refreshProfileList(self):
		"""Refresh the list of available profiles"""
		self.lstProfiles.Clear()
		
		# Use the PROFILES_DIR from the backend module
		from addon.globalPlugins.lion import PROFILES_DIR
		if os.path.exists(PROFILES_DIR):
			for filename in sorted(os.listdir(PROFILES_DIR)):
				if filename.endswith('.json'):
					profileName = filename[:-5]  # Remove .json extension
					self.lstProfiles.Append(profileName)

	def _addSpin(self, sizer, parent, label, value):
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(parent, label=label), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		spin = wx.SpinCtrl(parent, min=0, max=100, initial=value)
		row.Add(spin, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		return spin

	def btnOk_click(self, event):
		"""OK button saves ONLY global settings to config.conf["lion"]"""
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
		ui.message(_("Changes canceled"))
		self.Close()  # triggers onClose

	def onAddProfile(self, event):
		"""Add a new profile for a specific application"""
		dlg = wx.TextEntryDialog(self, _("Enter application name (e.g., notepad, firefox):"), _("Add Profile"))
		if dlg.ShowModal() == wx.ID_OK:
			appName = dlg.GetValue().strip()
			if appName:
				# Create profile with at least one override to prevent auto-deletion
				# Use a small difference from global interval as initial override
				initialOverride = {"interval": config.conf["lion"]["interval"] + 0.1}
				self.backend.saveProfileForApp(appName, initialOverride)
				self._refreshProfileList()
				ui.message(_("Profile added for ") + appName + _(" with initial override"))
		dlg.Destroy()

	def onDeleteProfile(self, event):
		"""Delete selected profile"""
		selection = self.lstProfiles.GetSelection()
		if selection == wx.NOT_FOUND:
			ui.message(_("No profile selected"))
			return
		
		profileName = self.lstProfiles.GetString(selection)
		dlg = wx.MessageDialog(self, 
			_("Delete profile for ") + profileName + "?",
			_("Confirm Delete"),
			wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
		
		if dlg.ShowModal() == wx.ID_YES:
			self.backend.deleteProfileForApp(profileName)
			self._refreshProfileList()
			ui.message(_("Profile deleted"))
		dlg.Destroy()

	def onSetActive(self, event):
		"""Set the selected profile as active (load it)"""
		selection = self.lstProfiles.GetSelection()
		if selection == wx.NOT_FOUND:
			ui.message(_("No profile selected"))
			return
		
		profileName = self.lstProfiles.GetString(selection)
		self.backend.loadProfileForApp(profileName)
		
		# Update label from actual loaded profile (may be "global" if profile was empty)
		actualProfile = self.backend.currentAppProfile
		self.lblActiveProfile.SetLabel(_("Active Profile: ") + actualProfile)
		
		# Reload controls with new effective config
		effectiveConfig = self.backend.getEffectiveConfig(actualProfile)
		self.spinInterval.SetValue(float(effectiveConfig.get("interval", config.conf["lion"]["interval"])))
		self.choiceTarget.SetSelection(int(effectiveConfig.get("target", config.conf["lion"]["target"])))
		self.spinThreshold.SetValue(float(effectiveConfig.get("threshold", config.conf["lion"]["threshold"])))
		self.spinCropLeft.SetValue(int(effectiveConfig.get("cropLeft", config.conf["lion"]["cropLeft"])))
		self.spinCropRight.SetValue(int(effectiveConfig.get("cropRight", config.conf["lion"]["cropRight"])))
		self.spinCropUp.SetValue(int(effectiveConfig.get("cropUp", config.conf["lion"]["cropUp"])))
		self.spinCropDown.SetValue(int(effectiveConfig.get("cropDown", config.conf["lion"]["cropDown"])))
		
		ui.message(_("Loaded profile: ") + actualProfile)

	def onSaveProfile(self, event):
		"""Save current settings to active profile as overrides"""
		appName = self.backend.currentAppProfile
		
		# If we're in global mode, can't save a profile
		if appName == "global":
			ui.message(_("Cannot save profile in global mode. Use 'Add Profile' first or switch to an app."))
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
		
		self.backend.saveProfileForApp(appName, overrides)
		ui.message(_("Profile saved for ") + appName + _(" (overrides only)"))

	def onClose(self, event):
		self.backend.settingsDialog = None
		self.Destroy()
