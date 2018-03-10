#!/usr/bin/python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import sys
import os
import gettext
import subprocess

from pathlib import Path
from installer import installer

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

class AppUninstaller:
    def __init__(self, desktopFile):
        self.desktopFile = desktopFile

        self.installer = installer.Installer().init(self.on_installer_ready)

    def on_installer_ready(self):
        pkg_name = None

        pkg_name = self.get_apt_name()

        if pkg_name == None:
            pkg_name = self.get_fp_name()

        if pkg_name == None:
            print("Package for '%s' not found")
            self.on_finished()

        pkginfo = self.installer.find_pkginfo(pkg_name)

        if pkginfo and self.installer.pkginfo_is_installed(pkginfo):
            self.installer.select_pkginfo(pkginfo, self.on_installer_ready_to_remove)
        else:
            print("Package '%s' is not installed")
            self.on_finished()

    def on_installer_ready_to_remove(self, task):
        self.installer.execute_task(task, self.on_finished)

    def get_apt_name(self):
        (status, output) = subprocess.getstatusoutput("dpkg -S " + self.desktopFile)
        package = output[:output.find(":")].split(",")[0]

        if status == 0:
            return package
        else:
            return None

    def get_fp_name(self):
        path = Path(self.desktopFile)

        if "flatpak" not in path.parts:
            return None

        return path.stem

    def on_finished(self, pkginfo=None, error=None):
        Gtk.main_quit()

if __name__ == "__main__":

    # Exit if the given path does not exist
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]) or not sys.argv[1].endswith(".desktop"):
        print("mintinstall-remove-app: Single argument required, the full path of a desktop file.")
        sys.exit(1)

    mainwin = AppUninstaller(sys.argv[1])
    Gtk.main()
