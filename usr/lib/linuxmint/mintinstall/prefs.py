#!/usr/bin/python3

import gettext

from gi.repository import Gtk

from xapp.SettingsWidgets import SettingsPage, Text
from xapp.GSettingsWidgets import GSettingsSwitch, GSettingsComboBox

# GSettings
SCHEMA_ID = "com.linuxmint.install"

SEARCH_IN_SUMMARY = "search-in-summary"
SEARCH_IN_DESCRIPTION = "search-in-description"
INSTALLED_APPS = "installed-apps"
SEARCH_IN_CATEGORY = "search-in-category"
HAMONIKR_SCREENSHOTS = "hamonikr-screenshots"
PACKAGE_TYPE_PREFERENCE = "search-package-type-preference"
ALLOW_UNVERIFIED_FLATPAKS = "allow-unverified-flatpaks"

# Flatpak search option items
PACKAGE_TYPE_PREFERENCE_ALL = "all"
PACKAGE_TYPE_PREFERENCE_APT = "apt"
PACKAGE_TYPE_PREFERENCE_FLATPAK = "flatpak"

_ = gettext.gettext

class PrefsWidget(Gtk.Box):
    def __init__(self, warning_box):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        # Settings
        page = SettingsPage()
        box.pack_start(page, True, True, 0)

        section = page.add_section(_("General search options"))

        widget = GSettingsSwitch(_("Search in packages summary (slower search)"), SCHEMA_ID, SEARCH_IN_SUMMARY)
        section.add_row(widget)
        widget = GSettingsSwitch(_("Search in packages description (even slower search)"), SCHEMA_ID, SEARCH_IN_DESCRIPTION)
        section.add_row(widget)

        section = page.add_section(_("Flatpaks"))


        widget = GSettingsSwitch(_("Show unverified Flatpaks (not recommended)"), SCHEMA_ID, ALLOW_UNVERIFIED_FLATPAKS)
        section.add_row(widget)

        section.add(warning_box)
        
        search_options = [
            [PACKAGE_TYPE_PREFERENCE_ALL, _("List all types")],
            (PACKAGE_TYPE_PREFERENCE_FLATPAK, _("Only list the Flatpak")),
            (PACKAGE_TYPE_PREFERENCE_APT, _("Only list the system package")),
        ]

        section = page.add_section()
        widget = GSettingsComboBox(_("When an app has mutiple formats:"), SCHEMA_ID, PACKAGE_TYPE_PREFERENCE, search_options)
        section.add_row(widget)

        self.show_all()
