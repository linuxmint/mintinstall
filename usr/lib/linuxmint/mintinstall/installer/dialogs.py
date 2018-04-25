import gi
gi.require_version('XApp', '1.0')
from gi.repository import GLib, Gtk, GObject, Gdk, XApp, Flatpak

import gettext
APP = 'mintinstall'
LOCALE_DIR = "/usr/share/linuxmint/locale"
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

from aptdaemon.gtk3widgets import AptConfirmDialog

######################### Subclass Apt's dialog to keep consistency

class ChangesConfirmDialog(AptConfirmDialog):

    """Dialog to confirm the changes that would be required by a
    transaction.
    """

    def __init__(self, transaction, task):
        super(ChangesConfirmDialog, self).__init__(transaction, cache=None, parent=task.parent_window)

        self.task = task

    def _show_changes(self):
        """Show a message and the dependencies in the dialog."""
        self.treestore.clear()

        # Run parent method for apt
        if self.task.pkginfo.pkg_hash.startswith("a"):
            super(ChangesConfirmDialog, self)._show_changes()
        else:
            # flatpak
            self.set_title(_("Flatpaks"))

            if len(self.task.to_install) > 0:
                piter = self.treestore.append(None, ["<b>%s</b>" % _("Install")])

                for str_ref in self.task.to_install:
                    if self.task.pkginfo.refid == str_ref:
                        continue

                    self.treestore.append(piter, [Flatpak.Ref.parse(str_ref).get_name()])

            if len(self.task.to_remove) > 0:
                piter = self.treestore.append(None, ["<b>%s</b>" % _("Remove")])

                for str_ref in self.task.to_remove:
                    if self.task.pkginfo.refid == str_ref:
                        continue

                    self.treestore.append(piter, [Flatpak.Ref.parse(str_ref).get_name()])

            if len(self.task.to_update) > 0:
                piter = self.treestore.append(None, ["<b>%s</b>" % _("Upgrade")])

                for str_ref in self.task.to_update:
                    if self.task.pkginfo.refid == str_ref:
                        continue

                    self.treestore.append(piter, [Flatpak.Ref.parse(str_ref).get_name()])

            msg = _("Please take a look at the list of changes below.")

            if len(self.treestore) == 1:
                filtered_store = self.treestore.filter_new(
                    Gtk.TreePath.new_first())
                self.treeview.expand_all()
                self.treeview.set_model(filtered_store)
                self.treeview.set_show_expanders(False)

                if len(self.task.to_install) > 0:
                    title = _("Additional software has to be installed")
                elif len(self.task.to_remove) > 0:
                    title = _("Additional software has to be removed")
                elif len(self.task.to_update) > 0:
                    title = _("Additional software has to be upgraded")

                if len(filtered_store) < 6:
                    self.set_resizable(False)
                    self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC,
                                             Gtk.PolicyType.NEVER)
                else:
                    self.treeview.set_size_request(350, 200)
            else:
                title = _("Additional changes are required")
                self.treeview.set_size_request(350, 200)
                self.treeview.collapse_all()

            if self.task.download_size > 0:
                msg += "\n"
                msg += (_("%s will be downloaded in total.") %
                        GLib.format_size(self.task.download_size))
            if self.task.freed_size > 0:
                msg += "\n"
                msg += (_("%s of disk space will be freed.") %
                        GLib.format_size(self.task.freed_size))
            elif self.task.install_size > 0:
                msg += "\n"
                msg += (_("%s more disk space will be used.") %
                        GLib.format_size(self.task.install_size))
            self.label.set_markup("<b><big>%s</big></b>\n\n%s" % (title, msg))

    def render_package_desc(self, column, cell, model, iter, data):
        value = model.get_value(iter, 0)

        cell.set_property("markup", value)


class FlatpakProgressWindow(Gtk.Dialog):
    """
    Progress dialog for standalone flatpak installs, removals, updates.
    Intended to be used when not working as part of a parent app (like mintinstall)
    """

    def __init__(self, task, parent=None):
        Gtk.Dialog.__init__(self, parent=parent)

        self.task = task
        self.finished = False

        # Progress goes directly to this window
        task.client_progress_cb = self.window_client_progress_cb

        # finished callbacks route thru the installer
        # but we want to see them in this window also.
        self.final_finished_cb = task.client_finished_cb
        task.client_finished_cb = self.window_client_finished_cb

        self.pulse_timer = 0
        self.active_task_state = task.progress_state

        self.real_progress_text = None
        self.num_dots = 0

        # Setup the dialog
        self.set_border_width(6)
        self.set_resizable(False)
        self.get_content_area().set_spacing(6)
        # Setup the cancel button
        self.button = Gtk.Button.new_from_stock(Gtk.STOCK_CANCEL)
        self.button.set_use_stock(True)
        self.get_action_area().pack_start(self.button, False, False, 0)
        self.button.connect("clicked", self.on_button_clicked)
        self.button.show()

        # labels and progressbar
        hbox = Gtk.HBox()
        hbox.set_spacing(12)
        hbox.set_border_width(6)
        vbox = Gtk.VBox()
        vbox.set_spacing(12)

        self.phase_label = Gtk.Label()
        vbox.pack_start(self.phase_label, False, False, 0)
        self.phase_label.set_halign(Gtk.Align.START)

        vbox_progress = Gtk.VBox()
        vbox_progress.set_spacing(6)
        self.progress = Gtk.ProgressBar()
        vbox_progress.pack_start(self.progress, False, True, 0)

        self.progress_label = Gtk.Label()
        vbox_progress.pack_start(self.progress_label, False, False, 0)
        self.progress_label.set_halign(Gtk.Align.START)
        self.progress_label.set_line_wrap(True)
        self.progress_label.set_max_width_chars(60)

        vbox.pack_start(vbox_progress, False, True, 0)
        hbox.pack_start(vbox, True, True, 0)

        self.get_content_area().pack_start(hbox, True, True, 0)

        self.set_title(_("Flatpak Progress"))
        XApp.set_window_icon_name(self, "system-software-installer")

        hbox.show_all()
        self.realize()

        self.progress.set_size_request(350, -1)
        functions = Gdk.WMFunction.MOVE | Gdk.WMFunction.RESIZE
        try:
            self.get_window().set_functions(functions)
        except TypeError:
            # workaround for older and broken GTK typelibs
            self.get_window().set_functions(Gdk.WMFunction(functions))

        self.update_labels()

        # catch ESC and behave as if cancel was clicked
        self.connect("delete-event", self._on_dialog_delete_event)

    def set_progress_text(self, text):
        if text != self.real_progress_text:
            self.real_progress_text = text
            self.progress_label.set_text(text)
        else:
            self.tick()

    def tick(self):
        if self.num_dots < 5:
            self.num_dots += 1
        else:
            self.num_dots = 0

        new_string = self.real_progress_text

        i = 0

        while i < self.num_dots:
            new_string += "."
            i += 1

        self.progress_label.set_text(new_string)

    def update_labels(self):
        phase_label = ""

        if self.task.cancellable.is_cancelled():
            phase_label = _("Cancelled")
            self.set_progress_text(_("The operation was cancelled before it could complete."))
        elif self.task.progress_state == self.task.PROGRESS_STATE_INIT:
            phase_label = _("Initializing")
            self.set_progress_text("")
        elif self.task.progress_state == self.task.PROGRESS_STATE_INSTALLING:
            phase_label = _("Installing flatpaks")
            self.set_progress_text(_("Installing: %s") % self.task.current_package_name)
        elif self.task.progress_state == self.task.PROGRESS_STATE_REMOVING:
            phase_label = _("Removing flatpaks")
            self.set_progress_text(_("Removing: %s") % self.task.current_package_name)
        elif self.task.progress_state == self.task.PROGRESS_STATE_UPDATING:
            phase_label = _("Updating flatpaks")
            self.set_progress_text(_("Updating: %s") % self.task.current_package_name)
        elif self.task.progress_state == self.task.PROGRESS_STATE_FINISHED:
            phase_label = _("Finished")
            self.set_progress_text(_("Operation completed successfully"))
        elif self.task.progress_state == self.task.PROGRESS_STATE_FAILED:
            phase_label = _("Failed")
            self.set_progress_text(_("An error occurred:\n\n%s") % self.task.error_message)

        self.phase_label.set_markup("<big><b>%s</b></big>" % phase_label)
        self.set_title(phase_label)

    def start_progress_pulse(self):
        if self.pulse_timer > 0:
            return

        self.progress.pulse()
        self.pulse_timer = GObject.timeout_add(1050, self.progress_pulse_tick)

    def progress_pulse_tick(self):
        self.progress.pulse()

        return GLib.SOURCE_CONTINUE

    def stop_progress_pulse(self):
        if self.pulse_timer > 0:
            GObject.source_remove(self.pulse_timer)
            self.pulse_timer = 0

    def _on_dialog_delete_event(self, dialog, event):
        self.button.clicked()
        return True

    def window_client_progress_cb(self, pkginfo, progress, estimating):
        if estimating:
            self.start_progress_pulse()
        else:
            self.stop_progress_pulse()

            self.progress.set_fraction(progress / 100.0)
            XApp.set_window_progress(self, progress)
            self.tick()

        self.update_labels()

    def window_client_finished_cb(self, pkginfo, error_message):
        self.finished = True

        XApp.set_window_progress(self, 0)
        self.stop_progress_pulse()

        self.progress.set_fraction(1.0)

        self.update_labels()

        if error_message:
            self.set_urgency_hint(True)
            self.button.set_label(Gtk.STOCK_CLOSE)
        else:
            self.destroy()
            self.final_finished_cb(self.task.pkginfo, error_message)

    def on_button_clicked(self, button):
        if not self.finished:
            self.task.cancellable.cancel()
        else:
            self.destroy()
            self.final_finished_cb(self.task.pkginfo, self.task.error_message)

def show_flatpak_error(message):
    GObject.idle_add(_show_flatpak_error_mainloop, message, priority=GLib.PRIORITY_DEFAULT)

def _show_flatpak_error_mainloop(message):

    dialog = Gtk.MessageDialog(None,
                               Gtk.DialogFlags.DESTROY_WITH_PARENT,
                               Gtk.MessageType.ERROR,
                               Gtk.ButtonsType.OK,
                               "")

    text = _("An error occurred")
    dialog.set_markup("<big><b>%s</b></big>" % text)
    message_label = Gtk.Label(message)
    dialog.get_message_area().pack_start(message_label, False, False, 6)
    message_label.set_line_wrap(True)
    message_label.set_max_width_chars(60)
    message_label.show()

    dialog.run()
    dialog.hide()

    return False
