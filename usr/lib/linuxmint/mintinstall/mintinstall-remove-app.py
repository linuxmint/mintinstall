#!/usr/bin/python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

import sys
import os
import gettext
import subprocess

from pathlib import Path
from mintcommon.installer import installer
from mintcommon.installer import dialogs
from mintcommon.installer.misc import check_ml

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

class AppUninstaller:
    def __init__(self, desktopFile):
        self.desktopFile = desktopFile

        self.error = None
        self.installer = installer.Installer().init(self.on_installer_ready)
        self.progress_window = None
        self.progress_bar = None
        self.pkg_name = None

    def on_installer_ready(self):
        pkg_name = None

        pkg_name = self.get_apt_name()

        if pkg_name is None:
            pkg_name = self.get_fp_name()

        if pkg_name is None:
            print("Package for '%s' not found" % self.desktopFile)
            self.on_finished(None, 1)

        self.pkginfo = self.installer.find_pkginfo(pkg_name)

        if self.pkginfo and self.installer.pkginfo_is_installed(self.pkginfo):
            self.installer.select_pkginfo(self.pkginfo,
                                          self.on_installer_info_ready, None,
                                          self.on_uninstall_complete, self.on_uninstall_progress, use_mainloop=True)
        else:
            print("Package '%s' is not installed" % pkg_name)
            self.on_uninstall_complete(None)

    def on_installer_info_ready(self, task):
        self.task = task
        if self.installer.confirm_task(task):
            self.installer.execute_task(task)
        else:
            print("cancel task")
            self.installer.cancel_task(task)

    def on_uninstall_progress(self, pkginfo, progress, estimating, status_text=None):
        if self.progress_window is None:
            self.progress_window = Gtk.Dialog()
            self.progress_window.set_default_size(400, -1)
            self.progress_window.set_title(_("Removing"))
            self.progress_window.connect("delete-event", self.dialog_delete_event)

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            self.progress_window.get_content_area().pack_start(box, True, True, 0)

            self.pkg_name = Gtk.Label(max_width_chars=45, wrap=True)
            box.pack_start(self.pkg_name, True, False, 6)
            spinner = Gtk.Spinner(active=True)
            spinner.set_size_request(36, 36)
            box.pack_start(spinner, True, False, 0)
            box.show_all()
            self.pkg_name.set_label(self.installer.get_display_name(pkginfo))

            self.progress_window.run()

    def dialog_delete_event(self, widget, event):
        self.installer.cancel_task(self.task)

    def on_installer_info_error(self, task):
        pass

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

    def on_uninstall_complete(self, task):
        if task.error_message:
            print("Could not remove %s: %s" % (task.pkginfo.name, task.error_message))

        if self.progress_window is not None:
            # let the window be visible long enough to know what it's doing (uninstalls are fast)
            Gdk.threads_add_timeout_seconds(GLib.PRIORITY_DEFAULT, 1, self.destroy_window, None)

        Gtk.main_quit()

    def destroy_window(self, data=None):
        self.progress_window.destroy()
        return False

if __name__ == "__main__":

    # Exit if the given path does not exist
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]) or not sys.argv[1].endswith(".desktop"):
        print("mintinstall-remove-app: Single argument required, the full path of a desktop file.")
        sys.exit(1)

    mainwin = AppUninstaller(sys.argv[1])
    Gtk.main()

    exit(1 if mainwin.error else 0)
