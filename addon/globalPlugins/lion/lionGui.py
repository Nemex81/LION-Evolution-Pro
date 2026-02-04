import wx
import addonHandler
import gui
import config
import ui
import api
import os
import logHandler

addonHandler.initTranslation()

class frmMain(wx.Frame):
	def __init__(self, parent, backend):
		wx.Frame.__init__(self, parent, id=wx.ID_ANY, title=_("LION Settings"), 
			style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT)
		self.backend = backend
		self.SetSize((600, 550))
		
		# Dirty tracking flags
		self._dirty = False
		self._suppressControlEvents = False
		
		self.Bind(wx.EVT_CLOSE, self.onClose)

		# Get effective config (global + overrides)
		effectiveConfig = backend.getEffectiveConfig(backend.currentAppProfile)

		panel = wx.Panel(self)
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		panel.SetSizer(mainSizer)

		# Active profile label
		self.lblActiveProfile = wx.StaticText(panel, label=_("Active Profile: ") + backend.currentAppProfile)
		mainSizer.Add(self.lblActiveProfile, 0, wx.ALL, 5)

		# Create notebook with tabs - SETTINGS FIRST, then PROFILES
		self.notebook = wx.Notebook(panel)
		mainSizer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 5)

		# Tab 1: Settings (FIRST as per requirements)
		self.settingsTab = wx.Panel(self.notebook)
		self.notebook.AddPage(self.settingsTab, _("Settings"))
		self._createSettingsTab(self.settingsTab, effectiveConfig)

		# Tab 2: Profiles (SECOND as per requirements)
		self.profilesTab = wx.Panel(self.notebook)
		self.notebook.AddPage(self.profilesTab, _("Profiles"))
		self._createProfilesTab(self.profilesTab)

		# Close button (no OK/Cancel - settings saved explicitly)
		actionSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnClose = wx.Button(panel, wx.ID_CLOSE, _("Close"))
		actionSizer.Add(self.btnClose, 0, wx.ALL, 5)
		mainSizer.Add(actionSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

		# Bindings (D: button calls Close(), EVT_CLOSE handles prompts)
		self.btnClose.Bind(wx.EVT_BUTTON, self.onCloseButton)

	def _createProfilesTab(self, parent):
		"""Create Profiles management tab with ListCtrl"""
		tabSizer = wx.BoxSizer(wx.VERTICAL)
		parent.SetSizer(tabSizer)

		# Profile list (using ListCtrl in report mode with 2 columns)
		listBox = wx.StaticBox(parent, label=_("Available Profiles"))
		listSizer = wx.StaticBoxSizer(listBox, wx.VERTICAL)
		
		self.lstProfiles = wx.ListCtrl(listBox, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		self.lstProfiles.AppendColumn(_("Profile"), width=200)
		self.lstProfiles.AppendColumn(_("Status"), width=150)
		
		listSizer.Add(self.lstProfiles, 1, wx.ALL | wx.EXPAND, 5)
		tabSizer.Add(listSizer, 1, wx.ALL | wx.EXPAND, 5)

		# Populate profile list
		self._refreshProfileList()

		# Profile action buttons
		btnSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnCreateProfile = wx.Button(parent, label=_("Create Profile"))
		self.btnDeleteProfile = wx.Button(parent, label=_("Delete Profile"))
		self.btnSetActive = wx.Button(parent, label=_("Set Active Profile"))
		
		btnSizer.Add(self.btnCreateProfile, 0, wx.ALL, 5)
		btnSizer.Add(self.btnDeleteProfile, 0, wx.ALL, 5)
		btnSizer.Add(self.btnSetActive, 0, wx.ALL, 5)
		tabSizer.Add(btnSizer, 0, wx.ALL | wx.CENTER, 5)

		# Bindings
		self.btnCreateProfile.Bind(wx.EVT_BUTTON, self.onCreateProfile)
		self.btnDeleteProfile.Bind(wx.EVT_BUTTON, self.onDeleteProfile)
		self.btnSetActive.Bind(wx.EVT_BUTTON, self.onSetActive)

	def _createSettingsTab(self, parent, effectiveConfig):
		"""Create Settings tab with controls for active profile"""
		tabSizer = wx.BoxSizer(wx.VERTICAL)
		parent.SetSizer(tabSizer)

		# Interval
		intervalBox = wx.StaticBox(parent, label=_("Interval"))
		intervalSizer = wx.StaticBoxSizer(intervalBox, wx.VERTICAL)
		intervalGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		intervalGrid.AddGrowableCol(1, 1)
		intervalGrid.Add(wx.StaticText(intervalBox, label=_("Interval (seconds)")), 
			0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinInterval = wx.SpinCtrlDouble(intervalBox, min=0.0, max=10.0, inc=0.1, 
			initial=float(effectiveConfig.get("interval", config.conf["lion"]["interval"])))
		self.spinInterval.SetDigits(1)
		intervalGrid.Add(self.spinInterval, 1, wx.ALL | wx.EXPAND, 5)
		intervalSizer.Add(intervalGrid, 0, wx.EXPAND | wx.ALL, 5)
		tabSizer.Add(intervalSizer, 0, wx.ALL | wx.EXPAND, 5)

		# OCR Target
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

		# Threshold
		thresholdBox = wx.StaticBox(parent, label=_("Threshold"))
		thresholdSizer = wx.StaticBoxSizer(thresholdBox, wx.VERTICAL)
		thresholdGrid = wx.FlexGridSizer(cols=2, hgap=5, vgap=5)
		thresholdGrid.AddGrowableCol(1, 1)
		thresholdGrid.Add(wx.StaticText(thresholdBox, label=_("Threshold (0-1)")), 
			0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		self.spinThreshold = wx.SpinCtrlDouble(thresholdBox, min=0.0, max=1.0, inc=0.05, 
			initial=float(effectiveConfig.get("threshold", config.conf["lion"]["threshold"])))
		self.spinThreshold.SetDigits(2)
		thresholdGrid.Add(self.spinThreshold, 1, wx.ALL | wx.EXPAND, 5)
		thresholdSizer.Add(thresholdGrid, 0, wx.EXPAND | wx.ALL, 5)
		tabSizer.Add(thresholdSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Crop settings
		cropBox = wx.StaticBox(parent, label=_("Crop Settings (%)"))
		cropSizer = wx.StaticBoxSizer(cropBox, wx.VERTICAL)
		self.spinCropLeft = self._addSpin(cropSizer, cropBox, _("Crop Left"), 
			int(effectiveConfig.get("cropLeft", 0)))
		self.spinCropRight = self._addSpin(cropSizer, cropBox, _("Crop Right"), 
			int(effectiveConfig.get("cropRight", 0)))
		self.spinCropUp = self._addSpin(cropSizer, cropBox, _("Crop Up"), 
			int(effectiveConfig.get("cropUp", 0)))
		self.spinCropDown = self._addSpin(cropSizer, cropBox, _("Crop Down"), 
			int(effectiveConfig.get("cropDown", 0)))
		tabSizer.Add(cropSizer, 0, wx.ALL | wx.EXPAND, 5)

		# Action buttons for Settings tab
		settingsBtnSizer = wx.BoxSizer(wx.HORIZONTAL)
		self.btnSave = wx.Button(parent, label=_("Save"))
		self.btnRestoreDefaults = wx.Button(parent, label=_("Restore Defaults"))
		settingsBtnSizer.Add(self.btnSave, 0, wx.ALL, 5)
		settingsBtnSizer.Add(self.btnRestoreDefaults, 0, wx.ALL, 5)
		tabSizer.Add(settingsBtnSizer, 0, wx.ALL | wx.CENTER, 5)

		# Bindings for Settings buttons
		self.btnSave.Bind(wx.EVT_BUTTON, self.onSave)
		self.btnRestoreDefaults.Bind(wx.EVT_BUTTON, self.onRestoreDefaults)

		# Bind control change events to set dirty flag
		self.spinInterval.Bind(wx.EVT_SPINCTRLDOUBLE, self.onControlChanged)
		self.choiceTarget.Bind(wx.EVT_CHOICE, self.onControlChanged)
		self.spinThreshold.Bind(wx.EVT_SPINCTRLDOUBLE, self.onControlChanged)
		self.spinCropLeft.Bind(wx.EVT_SPINCTRL, self.onControlChanged)
		self.spinCropRight.Bind(wx.EVT_SPINCTRL, self.onControlChanged)
		self.spinCropUp.Bind(wx.EVT_SPINCTRL, self.onControlChanged)
		self.spinCropDown.Bind(wx.EVT_SPINCTRL, self.onControlChanged)

	def _refreshProfileList(self):
		"""Refresh the list of available profiles (ListCtrl with global first)"""
		try:
			self.lstProfiles.DeleteAllItems()
			
			# Always add "global" as first row
			index = self.lstProfiles.InsertItem(0, "global")
			if self.backend.currentAppProfile == "global":
				self.lstProfiles.SetItem(index, 1, _("Active Profile"))
			else:
				self.lstProfiles.SetItem(index, 1, "")
			
			# Use the PROFILES_DIR from the backend module
			from . import PROFILES_DIR
			if os.path.exists(PROFILES_DIR):
				profileNames = []
				for filename in sorted(os.listdir(PROFILES_DIR)):
					if filename.endswith('.json'):
						profileName = filename[:-5]  # Remove .json extension
						profileNames.append(profileName)
				
				# Add profiles to list
				for profileName in profileNames:
					index = self.lstProfiles.InsertItem(self.lstProfiles.GetItemCount(), profileName)
					if self.backend.currentAppProfile == profileName:
						self.lstProfiles.SetItem(index, 1, _("Active Profile"))
					elif not self.backend.profileHasOverrides(profileName):
						# Profile exists but has no overrides (empty {})
						self.lstProfiles.SetItem(index, 1, _("Same as global"))
					else:
						self.lstProfiles.SetItem(index, 1, "")
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error refreshing profile list")

	def _addSpin(self, sizer, parent, label, value):
		"""Helper to add a spin control with label"""
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(parent, label=label), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		spin = wx.SpinCtrl(parent, min=0, max=100, initial=value)
		row.Add(spin, 0, wx.ALL, 5)
		sizer.Add(row, 0, wx.EXPAND)
		return spin

	def onControlChanged(self, event):
		"""Called when any control value changes - set dirty flag if not suppressed"""
		if not self._suppressControlEvents:
			self._dirty = True
		event.Skip()

	def _refreshSettingsControls(self):
		"""Refresh Settings tab controls with active profile config"""
		try:
			self._suppressControlEvents = True
			effectiveConfig = self.backend.getEffectiveConfig(self.backend.currentAppProfile)
			
			self.spinInterval.SetValue(float(effectiveConfig.get("interval", config.conf["lion"]["interval"])))
			self.choiceTarget.SetSelection(int(effectiveConfig.get("target", config.conf["lion"]["target"])))
			self.spinThreshold.SetValue(float(effectiveConfig.get("threshold", config.conf["lion"]["threshold"])))
			self.spinCropLeft.SetValue(int(effectiveConfig.get("cropLeft", config.conf["lion"]["cropLeft"])))
			self.spinCropRight.SetValue(int(effectiveConfig.get("cropRight", config.conf["lion"]["cropRight"])))
			self.spinCropUp.SetValue(int(effectiveConfig.get("cropUp", config.conf["lion"]["cropUp"])))
			self.spinCropDown.SetValue(int(effectiveConfig.get("cropDown", config.conf["lion"]["cropDown"])))
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error refreshing settings controls")
		finally:
			self._suppressControlEvents = False

	def onCreateProfile(self, event):
		"""Create a new profile for a specific application"""
		try:
			dlg = wx.TextEntryDialog(self, 
				_("Enter application name (e.g., notepad, firefox):"), 
				_("Create Profile"))
			if dlg.ShowModal() == wx.ID_OK:
				appName = dlg.GetValue().strip()
				if appName and appName != "global":
					# Create profile with empty overrides {} - persistent but same as global
					self.backend.saveProfileForApp(appName, {})
					
					# Update UI to reflect the newly active profile
					self.lblActiveProfile.SetLabel(_("Active Profile: ") + self.backend.currentAppProfile)
					self._refreshProfileList()
					self._refreshSettingsControls()
					self._dirty = False
					
					ui.message(_("Profile created for ") + appName)
				elif appName == "global":
					ui.message(_("Cannot create a profile named 'global'"))
			dlg.Destroy()
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error creating profile")

	def onDeleteProfile(self, event):
		"""Delete selected profile"""
		try:
			selection = self.lstProfiles.GetFirstSelected()
			if selection == -1:
				ui.message(_("No profile selected"))
				return
			
			profileName = self.lstProfiles.GetItemText(selection, 0)
			
			# Can't delete global
			if profileName == "global":
				ui.message(_("Cannot delete global profile"))
				return
			
			dlg = wx.MessageDialog(self, 
				_("Delete profile for ") + profileName + "?",
				_("Confirm Delete"),
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
			
			if dlg.ShowModal() == wx.ID_YES:
				self.backend.deleteProfileForApp(profileName)
				self._refreshProfileList()
				self.lblActiveProfile.SetLabel(_("Active Profile: ") + self.backend.currentAppProfile)
				self._refreshSettingsControls()
				self._dirty = False
				ui.message(_("Profile deleted"))
			dlg.Destroy()
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error deleting profile")

	def onSetActive(self, event):
		"""Set the selected profile as active (with dirty check)"""
		try:
			selection = self.lstProfiles.GetFirstSelected()
			if selection == -1:
				ui.message(_("No profile selected"))
				return
			
			profileName = self.lstProfiles.GetItemText(selection, 0)
			
			# Check if dirty
			if self._dirty:
				dlg = wx.MessageDialog(self,
					_("You have unsaved changes. What would you like to do?"),
					_("Unsaved Changes"),
					wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
				dlg.SetYesNoCancelLabels(_("Save and Switch"), _("Discard and Switch"), _("Cancel"))
				result = dlg.ShowModal()
				dlg.Destroy()
				
				if result == wx.ID_YES:
					# Save and switch (C: block switch if save fails)
					if not self._saveSettings():
						# Save failed, do not switch profile
						return
				elif result == wx.ID_NO:
					# Discard and switch
					pass
				else:
					# Cancel
					return
			
			# Set active profile
			self.backend.setActiveProfile(profileName)
			
			# Update UI (but do NOT switch tabs)
			self.lblActiveProfile.SetLabel(_("Active Profile: ") + self.backend.currentAppProfile)
			self._refreshProfileList()
			self._refreshSettingsControls()
			self._dirty = False
			
			ui.message(_("Active profile: ") + self.backend.currentAppProfile)
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error setting active profile")

	def onSave(self, event):
		"""Save current settings"""
		if self._saveSettings():
			# Only clear dirty flag if save succeeded
			self._dirty = False
			ui.message(_("Settings saved"))
		else:
			ui.message(_("Error saving settings"))

	def _saveSettings(self):
		"""Internal method to save settings with validation.
		
		Returns:
			bool: True if save succeeded, False if validation failed
		"""
		try:
			appName = self.backend.currentAppProfile
			
			currentValues = {
				"cropLeft": int(self.spinCropLeft.GetValue()),
				"cropRight": int(self.spinCropRight.GetValue()),
				"cropUp": int(self.spinCropUp.GetValue()),
				"cropDown": int(self.spinCropDown.GetValue()),
				"target": self.choiceTarget.GetSelection(),
				"threshold": self.spinThreshold.GetValue(),
				"interval": self.spinInterval.GetValue()
			}
			
			# Validate horizontal crop total
			if (currentValues["cropLeft"] + currentValues["cropRight"]) >= 100:
				ui.message(_("Error: Total horizontal crop (Left + Right) cannot be 100% or more"))
				logHandler.log.warning(f"LionEvolutionPro: Invalid horizontal crop: "
					f"{currentValues['cropLeft']}+{currentValues['cropRight']}")
				return False
			
			# Validate vertical crop total
			if (currentValues["cropUp"] + currentValues["cropDown"]) >= 100:
				ui.message(_("Error: Total vertical crop (Up + Down) cannot be 100% or more"))
				logHandler.log.warning(f"LionEvolutionPro: Invalid vertical crop: "
					f"{currentValues['cropUp']}+{currentValues['cropDown']}")
				return False
			
			if appName == "global":
				# Save directly to config.conf["lion"]
				for key, value in currentValues.items():
					config.conf["lion"][key] = value
				logHandler.log.info("LionEvolutionPro: Saved global settings to config.conf")
			else:
				# Compute overrides (only values different from global)
				overrides = {}
				for key, value in currentValues.items():
					if value != config.conf["lion"][key]:
						overrides[key] = value
				
				# Save profile with overrides
				self.backend.saveProfileForApp(appName, overrides)
				logHandler.log.info(f"LionEvolutionPro: Saved profile for {appName} with overrides")
			
			return True
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error saving settings")
			return False

	def onRestoreDefaults(self, event):
		"""Restore defaults for current profile"""
		try:
			appName = self.backend.currentAppProfile
			
			if appName == "global":
				# For global, show message that this would reset to factory defaults
				dlg = wx.MessageDialog(self,
					_("Restore defaults is disabled for global profile.\nTo reset global settings, use NVDA's configuration reset."),
					_("Restore Defaults"),
					wx.OK | wx.ICON_INFORMATION)
				dlg.ShowModal()
				dlg.Destroy()
			else:
				# For app profile: clear overrides but stay active
				dlg = wx.MessageDialog(self,
					_("This will clear all overrides for this profile, making it identical to global.\nThe profile will remain active. Continue?"),
					_("Restore Defaults"),
					wx.YES_NO | wx.ICON_QUESTION)
				
				if dlg.ShowModal() == wx.ID_YES:
					# Clear overrides (writes empty {} to disk)
					self.backend.clearOverridesForApp(appName)
					
					# Update UI - profile stays active
					self.lblActiveProfile.SetLabel(_("Active Profile: ") + self.backend.currentAppProfile)
					self._refreshProfileList()
					self._refreshSettingsControls()
					self._dirty = False
					
					ui.message(_("Overrides cleared, profile still active"))
				dlg.Destroy()
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error restoring defaults")

	def onCloseButton(self, event):
		"""Close button handler - delegates to EVT_CLOSE (D)"""
		self.Close()

	def onClose(self, event):
		"""Handle window close with dirty check (EVT_CLOSE handler)"""
		try:
			if self._dirty:
				dlg = wx.MessageDialog(self,
					_("You have unsaved changes. What would you like to do?"),
					_("Unsaved Changes"),
					wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
				dlg.SetYesNoCancelLabels(_("Save"), _("Discard"), _("Cancel"))
				result = dlg.ShowModal()
				dlg.Destroy()
				
				if result == wx.ID_YES:
					# Save and close (C: block close if save fails)
					if not self._saveSettings():
						# Save failed, cancel close and keep dirty flag
						if hasattr(event, 'Veto'):
							event.Veto()
						return
				elif result == wx.ID_NO:
					# Discard and close
					pass
				else:
					# Cancel close
					if hasattr(event, 'Veto'):
						event.Veto()
					return
			
			# Close the dialog
			self.backend.settingsDialog = None
			self.Destroy()
		except Exception:
			logHandler.log.exception("LionEvolutionPro: Error closing dialog")
			# Always clean up
			self.backend.settingsDialog = None
			self.Destroy()
