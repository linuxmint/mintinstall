#!/usr/bin/python3
# encoding=utf-8
# -*- coding: UTF-8 -*-

import sys
import os
import gettext
import threading
import locale
import urllib.request, urllib.parse, urllib.error
import random
from datetime import datetime
import subprocess
import platform
import functools
import requests
import json
import re
import math
from pathlib import Path
import tempfile
import base64
import types

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('XApp', '1.0')
gi.require_version('AppStreamGlib', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib, Gio, XApp, AppStreamGlib, Pango
import cairo

from mintcommon.installer import installer
from mintcommon.installer import dialogs
import reviews
import housekeeping
from misc import print_timing, networking_available
from screenshot_window import ScreenshotWindow

ADDON_ICON_SIZE = 24
LIST_ICON_SIZE = 48
FEATURED_ICON_SIZE = 48
DETAILS_ICON_SIZE = 64
SCREENSHOT_HEIGHT = 351
SCREENSHOT_WIDTH = 624

from math import pi
DEGREES = pi / 180

FALLBACK_PACKAGE_ICON_PATH = "/usr/share/linuxmint/mintinstall/data/available.png"

#Hardcoded mouse back button key for button-press-event
#May not work on all mice
MOUSE_BACK_BUTTON = 8

# Gsettings keys
SEARCH_IN_SUMMARY = "search-in-summary"
SEARCH_IN_DESCRIPTION = "search-in-description"
INSTALLED_APPS = "installed-apps"
SEARCH_IN_CATEGORY = "search-in-category"
HAMONIKR_SCREENSHOTS = "hamonikr-screenshots"

# package type combobox columns
# index, label, icon-name, tooltip, pkginfo
PACKAGE_TYPE_COMBO_INDEX = 0
PACKAGE_TYPE_COMBO_LABEL = 1
PACKAGE_TYPE_COMBO_SUMMARY = 2
PACKAGE_TYPE_COMBO_ICON_NAME = 3
PACKAGE_TYPE_COMBO_PKGINFO = 4

# Don't let mintinstall run as root
if os.getuid() == 0:
    print("The software manager should not be run as root. Please run it in user mode.")
    sys.exit(1)

# i18n
APP = 'mintinstall'
LOCALE_DIR = "/usr/share/linuxmint/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

import setproctitle
setproctitle.setproctitle("mintinstall")

SCREENSHOT_DIR = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "screenshots")

Gtk.IconTheme.get_default().append_search_path("/usr/share/linuxmint/mintinstall")

# List of aliases
ALIASES = {}
ALIASES['spotify-client'] = "Spotify"
ALIASES['steam-launcher'] = "Steam"
ALIASES['minecraft-launcher'] = "Minecraft"
ALIASES['virtualbox-qt'] = "Virtualbox " # Added a space to force alias
ALIASES['virtualbox'] = "Virtualbox (base)"
ALIASES['sublime-text'] = "Sublime"
ALIASES['mint-meta-codecs'] = _("Multimedia Codecs")
ALIASES['mint-meta-codecs-kde'] = _("Multimedia Codecs for KDE")
ALIASES['mint-meta-debian-codecs'] = _("Multimedia Codecs")
ALIASES['firefox'] = "Firefox"
ALIASES['vlc'] = "VLC"
ALIASES['mpv'] = "Mpv"
ALIASES['gimp'] = "Gimp"
ALIASES['gnome-maps'] = "GNOME Maps"
ALIASES['thunderbird'] = "Thunderbird"
ALIASES['pia-manager'] = "PIA Manager"
ALIASES['skypeforlinux'] = "Skype"
ALIASES['google-earth-pro-stable'] = "Google Earth"
ALIASES['whatsapp-desktop'] = "WhatsApp"
ALIASES['wine-installer'] = "Wine"

libdir = os.path.join("/usr/lib/linuxmint/mintinstall")

with open(os.path.join(libdir, "apt_flatpak_match_data.info")) as f:
    match_data = json.load(f)

FLATPAK_EQUIVS = match_data["apt_flatpak_matches"]
DEB_EQUIVS = dict((v, k) for k,v in FLATPAK_EQUIVS.items())

KB = 1000
MB = KB * 1000

def get_size_for_display(size):
    if size == 0:
        return ""

    if size > (5 * MB):
        size = (size // MB) * MB
    elif size > KB:
        size = (size // KB) * KB

    formatted = GLib.format_size(size).replace(".0", "")
    return formatted

class NonScrollingComboBox(Gtk.ComboBox):
    def __init__(self, area):
        Gtk.ComboBox.__init__(self, cell_area=area, height_request=36)

    def do_scroll_event(self, event, data=None):
        # Skip Gtk.ComboBox's default handler.
        #
        # Connecting to a Gtk.ComboBox and stopping a scroll-event
        # prevents unintentional combobox changes, but also breaks
        # any scrollable parents when passing over the combobox.
        Gtk.Widget.do_scroll_event(self, event)

class AsyncImage(Gtk.Image):
    __gsignals__ = {
        'image-loaded': (GObject.SignalFlags.RUN_LAST, None, ()),
        'image-failed': (GObject.SignalFlags.RUN_LAST, None, ())
    }

    def __init__(self, icon_string=None, width=DETAILS_ICON_SIZE, height=DETAILS_ICON_SIZE):
        super(AsyncImage, self).__init__()

        self.path = None
        self.cancellable = None
        self.loader = None
        self.width = 1
        self.height = 1

        self.request_stream = None

        self.connect("destroy", self.on_destroyed)

        if icon_string:
            self.set_icon_string(icon_string, width, height)

    def on_destroyed(self, widget, data=None):
        if self.cancellable:
            self.cancellable.cancel()

    def set_icon_string(self, icon_string, width=DETAILS_ICON_SIZE, height=DETAILS_ICON_SIZE):
        theme = Gtk.IconTheme.get_default()

        self.original_width = width
        self.original_height = height

        # This keeps the icon's space occupied until loaded.
        self.set_size_request(width, height)

        if width != -1:
            self.width = width * self.get_scale_factor()
        else:
            self.width = width

        if height != -1:
            self.height = height * self.get_scale_factor()
        else:
            self.height = height

        self.cancellable = None
        file = None

        if os.path.isabs(icon_string):
            self.path = icon_string
            file = Gio.File.new_for_path(self.path)
        elif icon_string.startswith("http"):
            self.path = icon_string
            file = Gio.File.new_for_uri(self.path)
        elif theme.has_icon(icon_string):
                info = theme.lookup_icon_for_scale(icon_string,
                                                   self.height,
                                                   self.get_scale_factor(),
                                                   Gtk.IconLookupFlags.FORCE_SIZE)
                if info:
                    self.path = info.get_filename()
                    file = Gio.File.new_for_path(self.path)

        if file:
            self.cancellable = Gio.Cancellable()
            t = threading.Thread(target=self._fetch_url_thread, args=[file])
            t.start()
        else:
            self.set_icon_string(FALLBACK_PACKAGE_ICON_PATH, self.original_width, self.original_height)

    def _fetch_url_thread(self, file):
        data = None

        if file.get_uri().startswith("http"):
            try:
                r = requests.get(file.get_uri(), stream=True, timeout=10)

                if self.cancellable.is_cancelled():
                    return

                bdata = b''
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        bdata += chunk

                data = bdata
            except Exception as e:
                GLib.idle_add(self.emit_image_failed, str(e))
                return
        else:
            try:
                success, contents, etag = file.load_contents(self.cancellable)
                data =  bytes(contents)
            except GLib.Error as e:
                if e.code != Gio.IOErrorEnum.CANCELLED:
                    GLib.idle_add(self.emit_image_failed, e.message)
                return

        stream = Gio.MemoryInputStream.new_from_data(data, None)

        if self.cancellable.is_cancelled():
            return

        if stream:
            GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(stream,
                                                            self.width,
                                                            self.height,
                                                            True,
                                                            self.cancellable,
                                                            self.on_pixbuf_created)
        else:
            GLib.idle_add(self.emit_image_failed)

    def emit_image_failed(self, message=None):
        print("AsyncIcon could not read icon file contents for loading (%s): %s" % (self.path, message))

        self.cancellable.cancel()
        self.set_icon_string(FALLBACK_PACKAGE_ICON_PATH, self.original_width, self.original_height)
        self.emit("image-failed")

    def on_pixbuf_created(self, stream, result, data=None):
        if self.cancellable.is_cancelled():
            stream.close()
            return

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_finish(result)

            if pixbuf:
                scale = self.get_scale_factor()
                self.width = pixbuf.get_width() / scale
                self.height = pixbuf.get_height() / scale
                surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf,
                                                               scale,
                                                               self.get_window())
                self.set_from_surface(surface)
        except GLib.Error as e:
            self.emit_image_failed(e.message)
            return

        stream.close()

        # size request is whatever sizes we inputted, but those sizes are 'max' in either direction - the
        # final image may be different because of aspect ratios. We re-assigned self.width/height when we
        # made the pixbuf, so update our own size request to match.
        self.set_size_request(self.width, self.height)
        self.emit("image-loaded")

class ScreenshotDownloader(threading.Thread):
    def __init__(self, application, pkginfo):
        threading.Thread.__init__(self)
        self.application = application
        self.pkginfo = pkginfo
        self.settings = Gio.Settings(schema_id="com.linuxmint.install")

    def run(self):
        num_screenshots = 0
        self.application.screenshots = []
        # Add main screenshot

        if self.pkginfo.pkg_hash.startswith("f"):
            try:
                # Add additional screenshots from AppStream
                if len(self.application.installer.get_screenshots(self.pkginfo)) > 0:
                    for screenshot in self.pkginfo.screenshots:

                        image = screenshot.get_image(624, 351)

                        if requests.head(image.get_url(), timeout=5).status_code < 400:
                            num_screenshots += 1

                            local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))

                            source = screenshot.get_source()

                            source_url = source.get_url()
                            self.save_to_file(image.get_url(), source_url, local_name)

                            self.add_screenshot(self.pkginfo, local_name, num_screenshots)
            except Exception as e:
                print(e)

            if num_screenshots == 0:
                self.add_screenshot(self.pkginfo, None, 0)

            return
        try:
            link = "https://community.linuxmint.com/img/screenshots/%s.png" % self.pkginfo.name
            if requests.head(link, timeout=5).status_code < 400:
                num_screenshots += 1

                local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                self.save_to_file(link, None, local_name)

                self.add_screenshot(self.pkginfo, local_name, num_screenshots)
        except Exception as e:
            print(e)

        try:
            # Add additional screenshots from Debian
            from bs4 import BeautifulSoup
            page = BeautifulSoup(urllib.request.urlopen("http://screenshots.debian.net/package/%s" % self.pkginfo.name, timeout=5), "lxml")
            images = page.findAll('img')
            for image in images:
                if num_screenshots >= 4:
                    break
                if image['src'].startswith('/screenshots'):
                    num_screenshots += 1

                    thumb = "http://screenshots.debian.net%s" % image['src']
                    link = thumb.replace("_small", "_large")

                    local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                    self.save_to_file(link, None, local_name)

                    self.add_screenshot(self.pkginfo, local_name, num_screenshots)
        except Exception as e:
            pass
        
        if self.settings.get_boolean(HAMONIKR_SCREENSHOTS):
            try:
                # Add additional screenshots from Hamonikr
                from bs4 import BeautifulSoup
                hamonikrpkgname = self.pkginfo.name.replace("-","_")
                page = BeautifulSoup(urllib.request.urlopen("https://hamonikr.org/%s" % hamonikrpkgname, timeout=5), "lxml")
                images = page.findAll('img')
                for image in images:
                    if num_screenshots >= 4:
                        break
                    if image['src'].startswith('https://hamonikr.org'):
                        num_screenshots += 1

                        thumb = "%s" % image['src']
                        link = thumb

                        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                        self.save_to_file(link, None, local_name)

                        self.add_screenshot(self.pkginfo, local_name, num_screenshots)
            except Exception as e:
                pass

        if num_screenshots == 0:
            self.add_screenshot(self.pkginfo, None, 0)

    def save_to_file(self, url, source_url, path):
        r = requests.get(url, stream=True, timeout=10)

        with open(path, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)

        if source_url is None:
            source_url = path

        file = Gio.File.new_for_path(path)
        info = Gio.FileInfo.new()
        info.set_attribute_string("metadata::mintinstall-screenshot-source-url", source_url)
        try:
            file.set_attributes_from_info(info, Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error as e:
            logging.warning("Unable to store screenshot source url to metadata '%s': %s" % (source_url, e.message))

    def add_screenshot(self, pkginfo, name, num):
        GLib.idle_add(self.add_ss_idle, pkginfo, name, num)

    def add_ss_idle(self, pkginfo, name, num):
        self.application.add_screenshot(pkginfo, name, num)

class FlatpakAddonRow(Gtk.ListBoxRow):
    def __init__(self, app, parent_pkginfo, addon, name_size_group, button_size_group):
        Gtk.ListBoxRow.__init__(self)
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, margin_start=10, margin_end=10, margin_top=4, margin_bottom=4)
        self.add(self.box)

        self.app = app
        self.pkginfo = parent_pkginfo
        self.addon = addon

        self.spinner = Gtk.Spinner(active=True, no_show_all=True, visible=True)
        self.box.pack_start(self.spinner, False, False, 0)

        self.action = Gtk.Button(label="",
                                 sensitive=False,
                                 image=self.spinner,
                                 always_show_image=True,
                                 valign=Gtk.Align.CENTER,
                                 no_show_all=True)
        self.action.set_size_request(100, -1)
        button_size_group.add_widget(self.action)
        self.action.connect("clicked", self.action_clicked)
        self.box.pack_end(self.action, False, False, 0)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        self.box.pack_end(info_box, False, False, 4)

        self.size_label = Gtk.Label(use_markup=True, no_show_all=True)
        self.size_label.get_style_context().add_class("dim-label")
        info_box.pack_start(self.size_label, False, False, 0)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.pack_start(label_box, False, False, 0)

        name = Gtk.Label(label="<b>%s</b>" % addon.get_name(), use_markup=True, xalign=0.0, selectable=True)
        name_size_group.add_widget(name)
        label_box.pack_start(name, False, False, 0)

        summary = Gtk.Label(label=addon.get_comment(), xalign=0.0, wrap=True, max_width_chars=60, selectable=True)
        label_box.pack_start(summary, False, False, 0)

        if not self.app.installer.pkginfo_is_installed(self.pkginfo):
            self.action.hide()
            self.set_sensitive(False)
            return

        self.action.show()
        self.prepare_task()

    def prepare_task(self):
        self.app.installer.create_addon_task(self.addon, self.pkginfo.remote, self.pkginfo.remote_url,
                                             self.info_ready, self.info_error,
                                             self.installer_finished, self.installer_progress, use_mainloop=True)

    def info_ready(self, task):
        self.task = task

        if task.type == task.INSTALL_TASK:
            self.action.set_label(_("Add"))
            self.action.set_sensitive(True)
            self.action.get_style_context().add_class("suggested-action")
            self.action.get_style_context().remove_class("destructive-action")
            self.spinner.hide()
        elif task.type == task.UNINSTALL_TASK:
            self.action.set_label(_("Remove"))
            self.action.set_sensitive(True)
            self.action.get_style_context().add_class("destructive-action")
            self.action.get_style_context().remove_class("suggested-action")
            self.spinner.hide()

        # TODO - just size or say 'Size:' ?
        if task.freed_size > 0:
            self.size_label.set_label(get_size_for_display(task.freed_size))
        elif task.install_size > 0:
            self.size_label.set_label(get_size_for_display(task.install_size))

        self.size_label.show()

    def info_error(self, task):
        self.task = task

        self.spinner.hide()
        self.action.set_sensitive(False)
        self.action.set_label(_("Unavailable"))
        self.action.get_style_context().remove_class("suggested-action")
        self.action.get_style_context().remove_class("destructive-action")

    def action_clicked(self, widget):
        self.app.installer.execute_task(self.task)

        self.action.set_label("")
        self.app.update_activity_widgets()

    def installer_finished(self, task):
        self.app.update_activity_widgets()
        self.prepare_task()

    def installer_progress(self, pkginfo, progress, estimating, status_text=None):
        self.spinner.show()

class SaneProgressBar(Gtk.DrawingArea):
    def __init__(self):
        super(Gtk.DrawingArea, self).__init__(width_request=-1,
                                              height_request=8,
                                              margin_top=1, #???  to align better with the stars and count
                                              hexpand=True,
                                              valign=Gtk.Align.CENTER,
                                              visible=True)
        self.connect("draw", self.draw_bar)
        self.fraction = 0

    def update_colors(self):
        context = self.get_style_context()

        ret, self.fill_color = context.lookup_color("fg_color")
        if not ret:
            self.fill_color = Gdk.RGBA()
            self.fill_color.parse("grey")
        ret, self.trough_color = context.lookup_color("bg_color")
        if not ret:
            self.trough_color = Gdk.RGBA()
            self.trough_color.parse("white")

        ret, self.border_color = context.lookup_color("borders_color")
        if not ret:
            self.border_color = Gdk.RGBA()
            self.border_color.parse("grey")

    def draw_bar(self, widget, cr):
        self.update_colors()

        allocation = self.get_allocation()

        cr.set_antialias(cairo.ANTIALIAS_SUBPIXEL)
        cr.save()
        cr.set_line_width(1)

        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.clip()

        Gdk.cairo_set_source_rgba(cr, self.trough_color)
        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.fill()

        Gdk.cairo_set_source_rgba(cr, self.fill_color)
        self.rounded_rect(cr, -20, 1, allocation.width * self.fraction + 20, allocation.height - 2)
        cr.fill()

        Gdk.cairo_set_source_rgba(cr, self.border_color)
        self.rounded_rect(cr, 1, 1, allocation.width - 2, allocation.height - 2)
        cr.stroke()

        cr.restore()

        return True

    def rounded_rect(self, cr, x, y, width, height):
        radius = 3
        cr.new_sub_path()
        cr.arc(x + radius, y + radius, radius, 180 * DEGREES, 270 * DEGREES)
        cr.arc(x + width - radius, y + radius, radius, -90 * DEGREES, 0 * DEGREES)
        cr.arc(x + width - radius, y + height - radius, radius, 0 * DEGREES, 90 * DEGREES)
        cr.arc(x + radius, y + height - radius, radius, 90 * DEGREES, 180 * DEGREES)
        cr.close_path()

    def set_fraction(self, fraction):
        self.fraction = fraction
        self.queue_draw()


class FeatureTile(Gtk.Button):
    def __init__(self, pkginfo, installer, featured):
        super(Gtk.Button, self).__init__()

        self.pkginfo = pkginfo
        self.installer = installer

        image_uri = (f"/usr/share/linuxmint/mintinstall/featured/{featured.image}")
        background = featured.background
        border_color = featured.border_color
        color = featured.text_color

        self.connect("realize", self.set_cursor)

        css = """
#FeatureTile {
    background: %(background)s;
    color: %(color)s;
    border-color: %(border_color)s;
    padding: 12px;
    outline-color: alpha(%(color)s, 0.75);
    outline-style: dashed;
    outline-offset: 2px;
}

#FeatureTitle {
    color: %(color)s;
    font-weight: bold;
    font-size: 24px;
}

#FeatureSummary {
    color: %(color)s;
    font-weight: normal;
    font-size: 16px;
}
""" % {'background':background, 'border_color':border_color, 'color':color}

        self.set_name("FeatureTile")
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(str.encode(css))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),
                                                 style_provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        label_name = Gtk.Label(xalign=0)
        label_name.set_label(self.installer.get_display_name(pkginfo))
        label_name.set_name("FeatureTitle")

        label_summary = Gtk.Label(xalign=0)
        label_summary.set_label(self.installer.get_summary(pkginfo))
        label_summary.set_name("FeatureSummary")

        image = Gtk.Image.new_from_file(image_uri)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.START)
        vbox.set_border_width(6)

        vbox.pack_start(label_name, False, False, 0)
        vbox.pack_start(label_summary, False, False, 0)

        hbox = Gtk.Box()
        hbox.pack_end(image, True, True, 0)
        hbox.pack_end(vbox, True, True, 0)

        self.add(hbox)

    def set_cursor(self, widget, data=None):
        hand = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "pointer")
        self.get_window().set_cursor(hand)

class PackageRow(Gtk.ListBoxRow):
    def __init__(self, pkginfo, icon, summary, installer, from_search=False, review_info=None):
        super(Gtk.ListBoxRow, self).__init__()
        self.pkginfo = pkginfo
        self.installed_mark = Gtk.Image()
        self.installer = installer
        self.asapp = self.installer.get_appstream_app_for_pkginfo(pkginfo)

        glade_file = "/usr/share/linuxmint/mintinstall/package-row.glade"
        self.builder = Gtk.Builder()
        self.builder.add_from_file(glade_file)

        self.main_box = self.builder.get_object("package_row")
        self.add(self.main_box)
        self.main_box.connect("button-press-event", lambda w, e: Gdk.EVENT_PROPAGATE)
        self.main_box.connect("button-release-event", lambda w, e: Gdk.EVENT_PROPAGATE)

        self.app_icon_holder = self.builder.get_object("app_icon_holder")
        self.app_display_name = self.builder.get_object("app_display_name")
        self.app_summary = self.builder.get_object("app_summary")
        self.flatpak_badge = self.builder.get_object("flatpak_badge")
        self.category_label = self.builder.get_object("category_label")
        self.installed_mark = self.builder.get_object("installed_mark")

        self.app_icon_holder.add(icon)

        display_name = self.installer.get_display_name(pkginfo)
        display_name = GLib.markup_escape_text(display_name)

        if pkginfo.pkg_hash.startswith("f"):
            self.flatpak_badge.show()
        else:
            self.flatpak_badge.hide()

        self.app_display_name.set_label(display_name)
        self.app_summary.set_label(summary)
        self.show_all()

        if review_info:
            self.fill_rating_widget(review_info)

        self.refresh_state()

    def refresh_state(self):
        self.installed = self.installer.pkginfo_is_installed(self.pkginfo)

        if self.installed:
            self.installed_mark.set_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        else:
            self.installed_mark.clear()

    def fill_rating_widget(self, review_info):
        review_info_box = self.builder.get_object("review_info_box")

        stars_box = self.builder.get_object("stars_box")

        rating = review_info.avg_rating
        remaining_stars = 5
        while rating >= 1.0:
            stars_box.pack_start(Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            rating -= 1
            remaining_stars -= 1
        if rating > 0.0:
            stars_box.pack_start(Gtk.Image.new_from_icon_name("semi-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            remaining_stars -= 1
        for i in range (remaining_stars):
            stars_box.pack_start(Gtk.Image.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        stars_box.show_all()

        num_reviews_label = self.builder.get_object("num_reviews_label")

        # TRANSLATORS: showing specific number of reviews in the list view and the header of the package details.
        review_text = gettext.ngettext("%d Review", "%d Reviews", review_info.num_reviews) % review_info.num_reviews
        num_reviews_label.set_label(review_text)

class VerticalPackageTile(Gtk.FlowBoxChild):
    def __init__(self, pkginfo, icon, installer, show_package_type=False, review_info=None):
        super(VerticalPackageTile, self).__init__()

        self.button = Gtk.Button();
        self.button.connect("clicked", self._activate_fb_child)
        self.button.set_can_focus(False)
        self.add(self.button)

        self.pkginfo = pkginfo
        self.installer = installer

        self.pkg_category = ''
        if len(pkginfo.categories) > 0:
            if len(pkginfo.categories) == 1:
                self.pkg_category = pkginfo.categories[0]
            else:
                self.pkg_category = pkginfo.categories[1]


        glade_file = "/usr/share/linuxmint/mintinstall/vertical-tile.glade"
        self.builder = Gtk.Builder()
        self.builder.add_from_file(glade_file)

        self.overlay = self.builder.get_object("vertical_package_tile")
        self.button.add(self.overlay)

        self.icon_holder = self.builder.get_object("icon_holder")
        self.package_label = self.builder.get_object("package_label")
        self.package_summary = self.builder.get_object("package_summary")
        self.package_type_box = self.builder.get_object("package_type_box")
        self.package_type_emblem = self.builder.get_object("package_type_emblem")
        self.package_type_name = self.builder.get_object("package_type_name")
        self.installed_mark = self.builder.get_object("installed_mark")

        self.icon_holder.add(icon)

        display_name = self.installer.get_display_name(pkginfo)
        self.package_label.set_label(display_name)

        if show_package_type:
            if pkginfo.pkg_hash.startswith("f"):

                remote_info = None

                try:
                    remote_info = self.installer.get_remote_info_for_name(pkginfo.remote)
                    if remote_info:
                        self.package_type_name.set_label(remote_info.title)
                except:
                    pass

                if remote_info is None:
                    self.package_type_name.set_label(pkginfo.remote.capitalize())

                self.package_type_box.set_tooltip_text(_("This package is a Flatpak"))
                self.package_type_emblem.set_from_icon_name("mintinstall-package-flatpak-symbolic", Gtk.IconSize.MENU)
                self.package_type_box.show()
            else:
                self.package_type_name.hide()
                self.package_type_emblem.hide()

            summary = self.installer.get_summary(pkginfo)
        else:
            summary = self.pkg_category.name if self.pkg_category else None

        if review_info:
            self.fill_rating_widget(review_info)

        self.package_summary.set_label(summary)

        self.show_all()
        self.refresh_state()

    def _activate_fb_child(self, widget):
        self.activate()

    def refresh_state(self):
        self.installed = self.installer.pkginfo_is_installed(self.pkginfo)

        if self.installed:
            self.installed_mark.set_from_icon_name("emblem-installed", Gtk.IconSize.MENU)
        else:
            self.installed_mark.clear()

    def fill_rating_widget(self, review_info):
        rating = str(review_info.avg_rating)
        num_reviews_label = self.builder.get_object("num_reviews_label")
        num_reviews_label.set_label(rating)

class ReviewTile(Gtk.ListBoxRow):
    def __init__(self, username, date, comment, rating):
        super(Gtk.ListBoxRow, self).__init__()

        main_box = Gtk.Box()
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)
        main_box.set_margin_top(12)
        main_box.set_margin_bottom(12)

        ratings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stars_box = Gtk.Box()
        for i in range(rating):
            stars_box.pack_start(Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        for i in range(5 - rating):
            stars_box.pack_start(Gtk.Image.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        ratings_box.pack_start(stars_box, False, False, 0)

        label_name = Gtk.Label(xalign=0.0)
        label_name.set_markup("<small>%s</small>" % GLib.markup_escape_text(username))
        ratings_box.pack_start(label_name, False, False, 0)

        label_date = Gtk.Label(xalign=0.0)
        label_date.set_markup("<small>%s</small>" % GLib.markup_escape_text(date))
        ratings_box.pack_start(label_date, False, False, 0)

        label_comment = Gtk.Label(xalign=0.0, selectable=True)
        label_comment.set_label(comment)
        label_comment.set_line_wrap(True)

        comment_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        comment_box.set_margin_start(12)
        comment_box.pack_start(label_comment, False, False, 0)

        main_box.pack_start(ratings_box, False, False, 0)
        main_box.pack_start(comment_box, True, True, 0)

        self.add(main_box)

class Category:
    def __init__(self, name, parent, categories, icon_name=""):
        self.name = name
        self.parent = parent
        self.icon_name = icon_name
        self.subcategories = []
        self.pkginfos = []
        self.matchingPackages = []
        if parent is not None:
            parent.subcategories.append(self)
        if categories is not None:
            categories.append(self)
        cat = self
        while cat.parent is not None:
            cat = cat.parent

class SubcategoryFlowboxChild(Gtk.FlowBoxChild):
    def __init__(self, category, is_all=False, active=False):
        super(Gtk.FlowBoxChild, self).__init__()

        self.category = category

        if is_all:
            cat_name = _("All")
        else:
            cat_name = category.name

        self.button = Gtk.ToggleButton(label=cat_name, active=active)
        self.add(self.button)

        self.button.connect("clicked", self._activate_fb_child)

    def _activate_fb_child(self, widget):
        self.activate()

class CategoryButton(Gtk.Button):
    def __init__(self, category):
        super(Gtk.Button, self).__init__()

        self.category = category

        self.set_can_focus(False)
        self.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.START)
        image = Gtk.Image(icon_name=category.icon_name, icon_size=Gtk.IconSize.MENU)
        label = Gtk.Label(label=category.name)
        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)
        box.show_all()

        self.add(box)

class Application(Gtk.Application):
    (ACTION_TAB, PROGRESS_TAB, SPINNER_TAB) = list(range(3))

    PAGE_LANDING = "landing"
    PAGE_LIST = "list"
    PAGE_DETAILS = "details"
    PAGE_LOADING = "loading"
    PAGE_SEARCHING = "searching"

    def __init__(self):
        super(Application, self).__init__(application_id='com.linuxmint.mintinstall',
                                          flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

        self.gui_ready = False

        self.low_res = self.get_low_res_screen()

        self.settings = Gio.Settings(schema_id="com.linuxmint.install")
        self.arch = platform.machine()

        print("MintInstall: Detected system architecture: '%s'" % self.arch)

        self.locale = os.getenv('LANGUAGE')
        if self.locale is None:
            self.locale = "C"
        else:
            self.locale = self.locale.split("_")[0]

        self.installer = installer.Installer()
        self.task_cancellable = None
        self.current_task = None
        self.recursion_buster = False

        self.install_on_startup_file = None

        self.review_cache = None
        self.current_pkginfo = None
        self.current_category = None

        self.flatpak_remote_categories = {}

        self.picks_tiles = []
        self.category_tiles = []

        self.one_package_idle_timer = 0
        self.installer_pulse_timer = 0
        self.search_changed_timer = 0
        self.search_idle_timer = 0

        self.action_button_signal_id = 0
        self.launch_button_signal_id = 0

        self.add_categories()

        self.main_window = None

    def do_activate(self):
        if self.main_window == None:
            if self.installer.init_sync():
                self.create_window(self.PAGE_LANDING)
                self.on_installer_ready()
            else:
                self.installer.init(self.on_installer_ready)
                self.create_window(self.PAGE_LOADING)

            self.add_window(self.main_window)

        self.main_window.present()

    def do_command_line(self, command_line, data=None):
        Gtk.Application.do_command_line(self, command_line)
        args = command_line.get_arguments()

        num = len(args)

        if num > 1 and args[1] == "list":
            sys.exit(self.export_listing(flatpak_only=False))
        elif num > 1 and args[1] == "list-flatpak":
            sys.exit(self.export_listing(flatpak_only=True))
        elif num == 3 and args[1] == "install":
            for try_method in (Gio.File.new_for_path, Gio.File.new_for_uri):
                file = try_method(args[2])

                if file.query_exists(None):
                    self.open([file], "")
                    self.activate()
                    return 0

            print("MintInstall: file not found", args[2])
            sys.exit(1)
        elif num > 1:
            print("MintInstall: Unknown arguments", args[1:])
            sys.exit(1)

        self.activate()
        return 0

    def do_open(self, files, num, hint):
        if self.gui_ready:
            self.handle_command_line_install(files[0])
        else:
            self.install_on_startup_file = files[0]

    def handle_command_line_install(self, file):
        if file.get_path().endswith(".flatpakrepo"):
            if self.installer.is_busy():
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.WARNING,
                                           Gtk.ButtonsType.OK,
                                           _("Cannot process this file while there are active operations.\nPlease try again after they finish."))
                res = dialog.run()
                dialog.destroy()
                return

            self.start_add_new_flatpak_remote(file)
        elif file.get_path().endswith(".flatpakref"):
            self.installer.get_pkginfo_from_ref_file(file, self.on_pkginfo_from_uri_complete)

    def start_add_new_flatpak_remote(self, file):
        self.builder.get_object("loading_spinner").start()
        self.page_stack.set_visible_child_name(self.PAGE_LOADING)
        self.installer.add_remote_from_repo_file(file, self.add_new_flatpak_remote_finished)

    def add_new_flatpak_remote_finished(self, file=None, error=None):
        if error:
            if error == "exists":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.WARNING,
                                           Gtk.ButtonsType.OK,
                                           _("The Flatpak repo you are trying to add already exists."))
                res = dialog.run()
                dialog.destroy()
            elif error == "error":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("An error occurred attempting to add the Flatpak repo."))
                res = dialog.run()
                dialog.destroy()
            elif error == "no-flatpak-support":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("Flatpak support is not currently available. Try installing flatpak."))
                res = dialog.run()
                dialog.destroy()
            elif error == "cancel":
                pass

            self.finish_loading_visual()
            return

        self.add_categories()
        self.installer.init(self.on_installer_ready)

    def on_pkginfo_from_uri_complete(self, pkginfo, error=None):
        if error:
            if error == "no-flatpak-support":
                dialog = Gtk.MessageDialog(self.main_window,
                                           Gtk.DialogFlags.MODAL,
                                           Gtk.MessageType.ERROR,
                                           Gtk.ButtonsType.OK,
                                           _("Flatpak support is not currently available. Try installing flatpak and gir1.2-flatpak-1.0."))
                res = dialog.run()
                dialog.destroy()
                self.finish_loading_visual()
                return
        if pkginfo:
            self.show_package(pkginfo, self.PAGE_LANDING)

    def get_low_res_screen(self):
        display = Gdk.Display.get_default()
        pointer = display.get_default_seat().get_pointer()

        height = 9999

        if pointer:
            position = pointer.get_position()
            monitor = display.get_monitor_at_point(position.x, position.y)
            height = monitor.get_geometry().height

        # If it's less than our threshold than consider us 'low res'. The workarea being used is in
        # app pixels, so hidpi will also be affected here regardless of device resolution.
        if height < 768:
            print("MintInstall: low resolution detected (%dpx height), limiting window height." % (height))
            return True

        return False

    def create_window(self, starting_page):
        if self.main_window != None:
            print("MintInstall: create_window called, but we already had one!")
            return

        # Build the GUI
        glade_file = "/usr/share/linuxmint/mintinstall/mintinstall.glade"

        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP)
        self.builder.add_from_file(glade_file)

        self.main_window = self.builder.get_object("main_window")
        self.main_window.set_title(_("Software Manager"))
        GLib.set_application_name(_("Software Manager"))

        self.main_window.set_icon_name("mintinstall")
        self.main_window.connect("delete_event", self.close_application)
        self.main_window.connect("key-press-event", self.on_keypress)
        self.main_window.connect("button-press-event", self.on_buttonpress)

        theme = Gtk.IconTheme.get_default()
        for icon_name in ["application-x-deb", "file-roller"]:
            if theme.has_icon(icon_name):
                iconInfo = theme.lookup_icon_for_scale(icon_name,
                                                       LIST_ICON_SIZE,
                                                       self.main_window.get_scale_factor(),
                                                       0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    global FALLBACK_PACKAGE_ICON_PATH
                    FALLBACK_PACKAGE_ICON_PATH = iconInfo.get_filename()
                    break

        self.detail_view_icon = AsyncImage()
        self.detail_view_icon.show()
        self.builder.get_object("application_icon_holder").add(self.detail_view_icon)

        self.status_label = self.builder.get_object("label_ongoing")
        self.progressbar = self.builder.get_object("progressbar1")
        self.progress_box = self.builder.get_object("progress_box")
        self.action_button = self.builder.get_object("action_button")
        self.launch_button = self.builder.get_object("launch_button")
        self.active_tasks_button = self.builder.get_object("active_tasks_button")
        self.active_tasks_spinner = self.builder.get_object("active_tasks_spinner")
        self.no_packages_found_label = self.builder.get_object("no_packages_found_label")

        self.no_packages_found_refresh_button = self.builder.get_object("no_packages_found_refresh_button")
        self.no_packages_found_refresh_button.connect("clicked", self.on_refresh_cache_clicked)

        self.progress_label = DottedProgressLabel()
        self.progress_box.pack_start(self.progress_label, False, False, 0)
        self.progress_label.show()

        box_reviews = self.builder.get_object("box_reviews")

        def list_header_func(row, before, user_data=None):
            if before and not row.get_header():
                row.set_header(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        box_reviews.set_header_func(list_header_func, None)

        # Build the menu
        submenu = Gtk.Menu()

        self.installed_menuitem = Gtk.MenuItem(label=_("Show installed applications"))
        self.installed_menuitem.connect("activate", self.show_installed_apps)
        self.installed_menuitem.show()
        submenu.append(self.installed_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        search_summary_menuitem = Gtk.CheckMenuItem(label=_("Search in packages summary (slower search)"))
        search_summary_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_SUMMARY))
        search_summary_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_SUMMARY)
        search_summary_menuitem.show()
        submenu.append(search_summary_menuitem)

        search_description_menuitem = Gtk.CheckMenuItem(label=_("Search in packages description (even slower search)"))
        search_description_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_DESCRIPTION))
        search_description_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_DESCRIPTION)
        search_description_menuitem.show()
        submenu.append(search_description_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        self.refresh_cache_menuitem = Gtk.MenuItem(label=_("Refresh the list of packages"))
        self.refresh_cache_menuitem.connect("activate", self.on_refresh_cache_clicked)
        self.refresh_cache_menuitem.show()
        self.refresh_cache_menuitem.set_sensitive(False)
        submenu.append(self.refresh_cache_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        about_menuitem = Gtk.MenuItem(label=_("About"))
        about_menuitem.connect("activate", self.open_about)
        about_menuitem.show()
        submenu.append(about_menuitem)

        menu_button = self.builder.get_object("menu_button")
        menu_button.connect("clicked", self.on_menu_button_clicked, submenu)

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(3)
        flowbox.set_max_children_per_line(10)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(True)
        flowbox.connect("child-activated", self.on_app_row_activated, self.PAGE_LIST)
        flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_applications"))
        self.flowbox_applications = flowbox

        box = self.builder.get_object("box_cat_page")
        box.add(self.flowbox_applications)

        self.back_button = self.builder.get_object("back_button")
        self.back_button.connect("clicked", self.on_back_button_clicked)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(False)

        self.searchentry = self.builder.get_object("search_entry")
        self.searchentry.connect("changed", self.on_entry_text_changed)
        self.searchentry.connect("activate", self.on_search_entry_activated)

        self.subsearch_toggle = self.builder.get_object("subsearch_toggle")
        self.subsearch_toggle.set_active(self.settings.get_boolean(SEARCH_IN_CATEGORY))
        self.subsearch_toggle.connect("toggled", self.on_subsearch_toggled)

        self.active_tasks_button.connect("clicked", self.on_active_tasks_button_clicked)
        self.update_activity_widgets()

        self.page_stack = self.builder.get_object("page_stack")
        self.page_stack.set_visible_child_name(starting_page)

        self.addons_listbox = self.builder.get_object("box_addons")
        self.addons_listbox.set_header_func(list_header_func, None)
        self.package_details_listbox = self.builder.get_object("package_details_listbox")

        self.app_list_stack = self.builder.get_object("app_list_stack")

        self.flatpak_details_vgroup = XApp.VisibilityGroup.new(True, True,
            (
                self.builder.get_object("branch_row"),
                self.builder.get_object("remote_row")
            )
        )

        self.screenshot_controls_vgroup = XApp.VisibilityGroup.new(False, True,
            [
                self.builder.get_object("previous_ss_button"),
                self.builder.get_object("next_ss_button"),
            ]
        )

        self.flowbox_popular = None

        self.package_type_store = Gtk.ListStore(int, str, str, str, object) # index, label, summary, icon-name, remotename, pkginfo

        box = Gtk.CellAreaBox(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        cell = Gtk.CellRendererPixbuf(stock_size=Gtk.IconSize.BUTTON)
        box.pack_start(cell, False, False, True)
        box.add_attribute(cell, "icon-name", PACKAGE_TYPE_COMBO_ICON_NAME)
        cell = Gtk.CellRendererText(xalign=0.0)
        box.pack_start(cell, False, False,  True)
        box.add_attribute(cell, "text", PACKAGE_TYPE_COMBO_LABEL)

        self.package_type_combo = NonScrollingComboBox(box)
        self.package_type_combo.set_model(self.package_type_store)
        self.package_type_combo.show_all()
        self.package_type_combo_container = self.builder.get_object("package_type_combo_container")
        self.package_type_combo_container.pack_start(self.package_type_combo, False, False, 0)
        self.single_version_package_type_box = self.builder.get_object("single_version_package_type_box")
        self.single_version_package_type_icon = self.builder.get_object("single_version_package_type_icon")
        self.single_version_package_type_label = self.builder.get_object("single_version_package_type_label")

        review_breakdown_grid = self.builder.get_object("review_breakdown_grid")
        self.star_bars = []

        for i in range(5, 0, -1):
            bar = SaneProgressBar()
            review_breakdown_grid.attach(bar, 1, i - 1, 1, 1)
            self.star_bars.append(bar)

        self.screenshot_stack = self.builder.get_object("screenshot_stack")
        self.screenshot_stack.connect("notify::visible-child", self.on_screenshot_shown)

        self.select_cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), "pointer")
        self.screenshot_window = None

        self.builder.get_object("previous_ss_button").connect("clicked", self.navigate_screenshot, Gtk.DirectionType.TAB_BACKWARD)
        self.builder.get_object("next_ss_button").connect("clicked", self.navigate_screenshot, Gtk.DirectionType.TAB_FORWARD)
        self.ss_swipe_handler = Gtk.GestureSwipe.new(self.screenshot_stack)
        self.ss_swipe_handler.connect("swipe", self.screenshot_stack_swiped, self.screenshot_stack)
        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.NONE)

        # This is only for the screenshot stack at the moment, as I can't get key events from the stack, even
        # with an event controller.
        self.main_window.connect("key-press-event", self.on_window_key_press)

        self.searchentry.grab_focus()

        box = self.builder.get_object("box_subcategories")

        self.subcat_flowbox = Gtk.FlowBox(homogeneous=True)
        self.subcat_flowbox.set_min_children_per_line(1)
        self.subcat_flowbox.set_max_children_per_line(4)
        self.subcat_flowbox.set_row_spacing(0)
        self.subcat_flowbox.set_column_spacing(0)

        box.pack_start(self.subcat_flowbox, True, True, 0)
        self.subcat_flowbox.connect("child-activated", self.on_subcategory_selected)

    def refresh_cache(self):
        self.builder.get_object("loading_spinner").start()
        self.refresh_cache_menuitem.set_sensitive(False)

        self.page_stack.set_visible_child_name(self.PAGE_LOADING)

        self.installer.force_new_cache(self._on_refresh_cache_complete)

    def _on_refresh_cache_complete(self):
        self.add_categories()
        self.installer.init(self.on_installer_ready)

    def on_refresh_cache_clicked(self, widget, data=None):
        self.refresh_cache()

    def on_installer_ready(self):
        try:
            self.process_matching_packages()
            self.refresh_cache_menuitem.set_sensitive(True)

            self.apply_aliases()

            self.load_featured_on_landing()

            self.review_cache = reviews.ReviewCache()
            self.review_cache.connect("reviews-updated", self.update_review_widgets)

            self.load_picks_on_landing()
            self.load_top_rated_on_landing()
            self.load_categories_on_landing()

            self.sync_installed_apps()
            self.update_conditional_widgets()

            GLib.idle_add(self.finished_loading_packages)

            # Can take some time, don't block for it (these are categorizing packages based on apt info, not our listings)
            GLib.idle_add(self.process_unmatched_packages)

            housekeeping.run()
        except Exception as e:
            print("Loading error: %s" % e)
            GLib.idle_add(self.refresh_cache)

    def load_featured_on_landing(self):
        box = self.builder.get_object("box_featured")

        if self.low_res:
            box.hide()

            # This overrides the glade 800x600 defaults. 300 is excessively small so the window works
            # out its own minimum height.
            self.main_window.set_default_geometry(800, 300)
            return

        for child in box.get_children():
            child.destroy()

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(1)
        flowbox.set_max_children_per_line(1)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(True)

        flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)

        featureds = []
        featured_items = json.load(open("/usr/share/linuxmint/mintinstall/featured/featured.json", "r"))

        for featured_item in featured_items:
            featureds.append(types.SimpleNamespace(**featured_item))

        tries = 0
        pkginfo = None

        while True:
            featured = random.sample(featureds, 1)[0]
            pkginfo = self.installer.cache.find_pkginfo(featured.name, 'a')

            if pkginfo != None:
                if self.installer.pkginfo_is_installed(pkginfo) and tries < 10:
                    tries += 1
                    continue
                break
            else:
                tries += 1

            if tries > 10:
                print("Something wrong on featured loading")
                box.hide()
                return

        tile = FeatureTile(pkginfo, self.installer, featured)

        if pkginfo != None:
            tile.connect("clicked", self.on_featured_clicked, pkginfo)

        flowbox.insert(tile, -1)
        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    def on_featured_clicked(self, button, pkginfo):
        self.show_package(pkginfo, self.PAGE_LANDING)

    def load_picks_on_landing(self):
        box = self.builder.get_object("box_picks")

        label = self.builder.get_object("label_picks")
        label.set_text(_("Popular"))
        label.show()

        if self.flowbox_popular is None:
            flowbox = Gtk.FlowBox()
            flowbox.set_min_children_per_line(3)
            flowbox.set_max_children_per_line(10)
            flowbox.set_row_spacing(0)
            flowbox.set_column_spacing(0)
            flowbox.set_homogeneous(False)
            flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)
            flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))
            self.flowbox_popular = flowbox
            box.add(flowbox)

        for child in self.flowbox_popular:
            child.destroy()

        apps = [info for info in self.all_category.pkginfos if info.refid == "" or info.refid.startswith("app")]
        apps.sort(key=functools.cmp_to_key(self.package_compare))

        apps = list(filter(lambda app: self.installer.get_icon(app, FEATURED_ICON_SIZE) is not None, apps))
        apps = apps[0:30]
        random.shuffle(apps)
        apps.sort(key=lambda app: self.installer.pkginfo_is_installed(app))

        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for pkginfo in apps:
            if self.review_cache:
                review_info = self.review_cache[pkginfo.name]
            else:
                review_info = None
            icon = self.get_application_icon(pkginfo, FEATURED_ICON_SIZE)
            tile = VerticalPackageTile(pkginfo, icon, self.installer, show_package_type=False, review_info=review_info)
            size_group.add_widget(tile)
            self.flowbox_popular.insert(tile, -1)
            self.picks_tiles.append(tile)
        box.show_all()

    def load_top_rated_on_landing(self):
        box = self.builder.get_object("box_top_rated")

        label = self.builder.get_object("label_top_rated")
        label.set_text(_("Top Rated"))
        label.show()

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(3)
        flowbox.set_max_children_per_line(10)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(False)
        flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)
        flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))
        self.flowbox_top_rated = flowbox
        box.add(flowbox)

        for child in self.flowbox_top_rated:
            child.destroy()

        apps = [info for info in self.all_category.pkginfos if info.refid == "" or info.refid.startswith("app")]
        apps.sort(key=functools.cmp_to_key(self.package_compare))

        apps = list(filter(lambda app: self.installer.get_icon(app, FEATURED_ICON_SIZE) is not None, apps))
        apps = apps[0:8]
        random.shuffle(apps)
        apps.sort(key=lambda app: self.installer.pkginfo_is_installed(app))

        size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for pkginfo in apps:
            if self.review_cache:
                review_info = self.review_cache[pkginfo.name]
            else:
                review_info = None
            icon = self.get_application_icon(pkginfo, FEATURED_ICON_SIZE)
            tile = VerticalPackageTile(pkginfo, icon, self.installer, show_package_type=False, review_info=review_info)
            size_group.add_widget(tile)
            self.flowbox_top_rated.insert(tile, -1)
            self.picks_tiles.append(tile)
        box.show_all()

    @print_timing
    def load_categories_on_landing(self):
        box = self.builder.get_object("box_categories")
        for child in box.get_children():
            child.destroy()

        label = self.builder.get_object("label_categories_landing")
        label.set_text(_("Categories"))
        label.show()

        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(4)
        flowbox.set_max_children_per_line(4)
        flowbox.set_row_spacing(0)
        flowbox.set_column_spacing(0)
        flowbox.set_homogeneous(True)
        flowbox.connect("selected-children-changed", self.navigate_flowbox, self.builder.get_object("scrolledwindow_landing"))

        for name in sorted(self.root_categories.keys()):
            category = self.root_categories[name]
            button = CategoryButton(category)
            button.connect("clicked", self.category_button_clicked, category)
            flowbox.insert(button, -1)

        if self.installer.list_flatpak_remotes():
            # Add flatpaks
            button = CategoryButton(self.flatpak_category)
            button.connect("clicked", self.category_button_clicked, self.flatpak_category)
            flowbox.insert(button, -1)

        button = CategoryButton(self.all_category)
        button.connect("clicked", self.category_button_clicked, self.all_category)
        flowbox.insert(button, -1)

        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    def update_review_widgets(self, rcache):
        self.load_picks_on_landing()

    def update_conditional_widgets(self):
        sensitive = len(self.installed_category.pkginfos) > 0 \
                    and not ((self.page_stack.get_visible_child_name() == self.PAGE_LIST) \
                    and (self.current_category == self.installed_category))

        self.installed_menuitem.set_sensitive(sensitive)

        sensitive = self.current_category != None \
                    and self.page_stack.get_visible_child_name() == self.PAGE_LIST

        self.subsearch_toggle.set_sensitive(sensitive)

    def update_activity_widgets(self):
        num_tasks = self.installer.get_task_count()

        if num_tasks > 0:
            self.active_tasks_button.show()

            text = gettext.ngettext("%d task running", "%d tasks running", num_tasks) % num_tasks

            self.active_tasks_button.set_tooltip_text(text)
            self.active_tasks_spinner.start()
        else:
            self.active_tasks_button.hide()
            self.active_tasks_spinner.stop()

        if self.current_category == self.active_tasks_category \
                                    and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            self.show_active_tasks() # Refresh the view, remove old items

    def update_state(self, pkginfo):
        self.update_activity_widgets()

        installed_packages = self.settings.get_strv(INSTALLED_APPS)
        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.pkg_hash not in installed_packages:
                installed_packages.append(pkginfo.pkg_hash)
                if pkginfo not in self.installed_category.pkginfos:
                    self.installed_category.pkginfos.append(pkginfo)
        else:
            if pkginfo.pkg_hash in installed_packages:
                installed_packages.remove(pkginfo.pkg_hash)
                for iter_package in self.installed_category.pkginfos:
                    if iter_package.pkg_hash == pkginfo.pkg_hash:
                        self.installed_category.pkginfos.remove(iter_package)

        self.settings.set_strv(INSTALLED_APPS, installed_packages)

        if self.current_pkginfo is not None and self.current_pkginfo.pkg_hash == pkginfo.pkg_hash:
            # flatpaks added by flatpakref files auto-remove their remotes when uninstalled
            # (this doesn't apply to flatpakref files that were refs off of an already-existing
            # remote - like those installed from flathub, for instance.)  So, we can't assume
            # the remote still exists, and will get errors if we try to display the app.  We will
            # just remove it from the cache at this point.
            can_show = False
            if pkginfo.pkg_hash.startswith("f"):
                remotes = self.installer.list_flatpak_remotes()
                for remote in remotes:
                    if remote.name == pkginfo.remote:
                        can_show = True
                        break
            else:
                can_show = True

            if can_show:
                if self.recursion_buster:
                    self.recursion_buster = False
                    return
                self.show_package(self.current_pkginfo, self.previous_page)
            else:
                del self.installer.cache[pkginfo.pkg_hash]
                self.previous_page = self.PAGE_LANDING
                self.go_back_action()

        for tile in (self.picks_tiles + self.category_tiles):
            if tile.pkginfo == pkginfo:
                tile.refresh_state()

        for tile in self.flowbox_applications.get_children():
            try:
                tile.refresh_state()
            except Exception as e:
                print(e)

    def modernize_installed_list(self, packages):
        """
        We can not rely on just the name of a package to guarantee uniqueness.
        This works for apt but not flatpaks.  So we need to upgrade existing keys
        to store pkg_hashes rather than simple names.
        """
        return_list = []

        for item in packages:
            if item.startswith(("apt:", "fp:")):
                # pkg_hashes start with apt: or fp:, if items have this, they're up-to-date.
                return_list.append(item)
                continue

            # Must be an old one, look it up by name (possibly incorrectly if there have been multiple remotes added)
            pkginfo = self.installer.find_pkginfo(item)

            if pkginfo:
                return_list.append(pkginfo.pkg_hash)
                continue

        return return_list

    def sync_installed_apps(self):
        """ garbage collect any stale packages in this list (uninstalled somewhere else) """

        installed_packages = self.installer.cache.get_manually_installed_packages()
        if not installed_packages:
            installed_packages = self.settings.get_strv(INSTALLED_APPS)
            installed_packages = self.modernize_installed_list(installed_packages)

        new_installed_packages = []
        for pkg_hash in installed_packages:
            try:
                pkginfo = self.installer.cache[pkg_hash]
            except KeyError:
                continue

            if self.installer.pkginfo_is_installed(pkginfo):
                if pkginfo not in self.installed_category.pkginfos:
                    self.installed_category.pkginfos.append(pkginfo)
                new_installed_packages.append(pkg_hash)
            else:
                try:
                    self.installed_category.pkginfos.remove(pkginfo)
                except ValueError:
                    pass

        self.settings.set_strv(INSTALLED_APPS, new_installed_packages)

    def show_installed_apps(self, menuitem):
        self.show_category(self.installed_category)

    def add_screenshots(self, pkginfo):
        ss_dir = Path(SCREENSHOT_DIR)

        n = 0
        for ss_path in ss_dir.glob("%s_*.png" % pkginfo.name):
            n += 1
            self.add_screenshot(pkginfo, ss_path, n)

        if n == 0:
            downloadScreenshots = ScreenshotDownloader(self, pkginfo)
            downloadScreenshots.start()

    def add_screenshot(self, pkginfo, ss_path, n):
        if pkginfo != self.current_pkginfo:
            return

        try:
            self.screenshot_stack.get_child_by_name("spinner").destroy()
        except AttributeError:
            pass

        if ss_path is None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
            image = Gtk.Image(icon_name="face-uncertain-symbolic", icon_size=Gtk.IconSize.DIALOG)
            label = Gtk.Label(label=_("No screenshots available"))
            box.pack_start(image, False, False, 0)
            box.pack_start(label, False, False, 0)
            box.show_all()
            self.screenshot_stack.add_named(box, "no-screenshots")
            self.screenshot_stack.get_window().set_cursor(None)
            return

        screenshot = AsyncImage(str(ss_path), SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT)

        self.screenshot_stack.add_named(screenshot, str(n))
        self.screenshot_stack.last = n
        self.screenshot_stack.show_all()
        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        self.screenshot_controls_vgroup.set_visible(n > 1)
        self.screenshot_stack.get_window().set_cursor(self.select_cursor)

    def on_screenshot_shown(self, stack, pspec):
        screenshot = stack.get_visible_child()

    def navigate_screenshot(self, button, direction):
        new = current = int(self.screenshot_stack.get_visible_child_name())

        if direction == Gtk.DirectionType.TAB_BACKWARD:
            new = current - 1 if current > 1 else self.screenshot_stack.last
            trans = Gtk.StackTransitionType.SLIDE_RIGHT
        elif direction == Gtk.DirectionType.TAB_FORWARD:
            new = current + 1 if current < self.screenshot_stack.last else 1
            trans = Gtk.StackTransitionType.SLIDE_LEFT

        self.screenshot_stack.set_visible_child_full(str(new), trans)

    def screenshot_stack_swiped(self, handler, vx, vy, stack):
        if vx == 0 and vy == 0:
            if self.screenshot_window is None or not self.screenshot_window.get_visible():
                self.enlarge_screenshot(stack.get_visible_child())
            return

        if vx < 0:
            self.navigate_screenshot(None, Gtk.DirectionType.TAB_FORWARD)
        elif vx > 0:
            self.navigate_screenshot(None, Gtk.DirectionType.TAB_BACKWARD)

    def on_window_key_press(self, stack, event, data=None):
        if self.page_stack.get_visible_child_name() != self.PAGE_DETAILS:
            return Gdk.EVENT_PROPAGATE
        if not self.screenshot_controls_vgroup.get_visible():
            return Gdk.EVENT_PROPAGATE

        got_keyval, keyval = event.get_keyval()
        direction = None

        if got_keyval:
            if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
                direction = Gtk.DirectionType.TAB_BACKWARD
            elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
                direction = Gtk.DirectionType.TAB_FORWARD

        if direction is not None:
            self.navigate_screenshot(None, direction)
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def get_screenshot_source_from_metadata(self, screenshot):
        file = Gio.File.new_for_path(screenshot.path)

        try:
            info = file.query_info("metadata::mintinstall-screenshot-source-url", Gio.FileQueryInfoFlags.NONE, None)
            url = info.get_attribute_string("metadata::mintinstall-screenshot-source-url")
            if url is not None:
                return url
        except GLib.Error as e:
            print("Could not retrieve source metadata for screenshot (%s): %s" % (ss_path, e.message))

        return None

    def enlarge_screenshot(self, screenshot):
        source_url = self.get_screenshot_source_from_metadata(screenshot)
        if source_url is not None:
            image_location = source_url
        else:
            image_location = screenshot.path

        if self.screenshot_window is not None:
            if self.screenshot_window.has_image(source_url):
                self.screenshot_window.show_all()
                self.screenshot_window.present()
                return
        else:
            multiple_images = len(self.installer.get_screenshots(self.current_pkginfo)) > 1
            self.screenshot_window = ScreenshotWindow(self.main_window, multiple_images)
            self.screenshot_window.connect("next-image", self.next_enlarged_screenshot_requested)
            self.screenshot_window.connect("destroy", self.enlarged_screenshot_window_destroyed)

        monitor = Gdk.Display.get_default().get_monitor_at_window(self.main_window.get_window())

        work_area = monitor.get_workarea()
        enlarged = AsyncImage(image_location, work_area.width * .8, work_area.height * .8)
        enlarged.connect("image-loaded", self.enlarged_image_ready)
        enlarged.connect("image-failed", self.enlarged_image_failed)
        return Gdk.EVENT_STOP

    def enlarged_image_ready(self, image):
        self.screenshot_window.add_image(image, image.path)

    def enlarged_image_failed(self, image):
        # AsyncImage will be trying to load a fallback image next, make sure we don't get signaled for it.
        image.disconnect_by_func(self.enlarged_image_ready)
        image.destroy()

        self.screenshot_window.set_busy(False)

        # If a screenshot failed and it's the first one, there's an empty, invisible screenshot window
        # in front of the main window, so destroy it.
        if not self.screenshot_window.any_images():
            self.screenshot_window.destroy()

    def enlarged_screenshot_window_destroyed(self, window):
        self.screenshot_window = None

    def next_enlarged_screenshot_requested(self, window, direction):
        if len(self.screenshot_stack.get_children()) < 2:
            self.screenshot_window.destroy()
            return False

        self.navigate_screenshot(None, direction)
        screenshot = self.screenshot_stack.get_visible_child()
        source_url = self.get_screenshot_source_from_metadata(screenshot)

        if source_url is not None:
            image_location = source_url
        else:
            image_location = screenshot.path

        if self.screenshot_window.has_image(image_location):
            self.screenshot_window.show_image(image_location)
            return False

        self.enlarge_screenshot(screenshot)
        return True

    def destroy_screenshot_window(self):
        if self.screenshot_window is not None:
            self.screenshot_window.destroy()
            self.screenshot_window = None

    def category_button_clicked(self, button, category):
        self.show_category(category)

    def on_menu_button_clicked(self, button, menu):
        menu.popup_at_pointer(None)

    def on_subsearch_toggled(self, button):
        self.settings.set_boolean(SEARCH_IN_CATEGORY, button.get_active())

        if button.get_active():
            return
        else:
            self.on_search_changed(self.searchentry)

    def on_search_entry_activated(self, searchentry):
        terms = searchentry.get_text()

        if terms != "":
            self.show_search_results(terms)

    def on_entry_text_changed(self, entry):
        if self.search_changed_timer > 0:
            GLib.source_remove(self.search_changed_timer)
            self.search_changed_timer = 0

        self.search_changed_timer = GLib.timeout_add(175, self.on_search_changed, entry)

    def on_search_changed(self, searchentry):
        terms = searchentry.get_text()

        if self.subsearch_toggle.get_active() and self.current_category != None and terms == "":
            self.show_category(self.current_category)
        elif terms != "" and len(terms) >= 3:
            self.show_search_results(terms)

        self.search_changed_timer = 0
        return False

    def set_search_filter(self, checkmenuitem, key):
        self.settings.set_boolean(key, checkmenuitem.get_active())

        terms = self.searchentry.get_text()

        if (self.searchentry.get_text() != ""):
            self.show_search_results(terms)

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.main_window)
        dlg.set_title(_("About"))
        dlg.set_program_name("mintinstall")
        dlg.set_comments(_("Software Manager"))
        try:
            h = open('/usr/share/common-licenses/GPL', 'r')
            s = h.readlines()
            gpl = ""
            for line in s:
                gpl += line
            h.close()
            dlg.set_license(gpl)
        except Exception as e:
            print(e)

        dlg.set_version("__DEB_VERSION__")
        dlg.set_icon_name("mintinstall")
        dlg.set_logo_icon_name("mintinstall")

        def close(w, res):
            if res == Gtk.ResponseType.CANCEL or res == Gtk.ResponseType.DELETE_EVENT:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    def export_listing(self, flatpak_only=False):
        if not flatpak_only:
            for filename in os.listdir("/var/lib/apt/lists/"):
                if "i18n" in filename and not filename.endswith("-en"):
                    print("Your APT cache is localized. Please remove all translations first.")
                    print("sudo rm -rf /var/lib/apt/lists/*Translation%s" % filename[-3:])
                    return 1
        if (os.getenv('LANGUAGE') != "C"):
            print("Please prefix this command with LANGUAGE=C, to prevent content from being translated in the host's locale.")
            return 1
        self.locale = "C"

        self.installer = installer.Installer()

        from mintcommon.installer import cache

        self.installer.cache = cache.PkgCache(self.installer.have_flatpak)
        self.installer.force_new_cache()
        self.installer.backend_table = {}

        self.installer.initialize_appstream()
        self.installer.generate_uncached_pkginfos(self.installer.cache)

        self.add_categories()
        self.process_matching_packages()
        self.process_unmatched_packages()

        if flatpak_only:
            pkginfos = self.installer.cache.get_subset_of_type("f")
        else:
            pkginfos = self.installer.cache

        for pkg_hash in pkginfos.keys():
            pkginfo = self.installer.cache[pkg_hash]

            description = self.installer.get_description(pkginfo)
            description = description.replace("\r\n", "<br>")
            description = description.replace("\n", "<br>")

            summary = self.installer.get_summary(pkginfo)
            url = ""
            try:
                url = self.installer.get_homepage_url(pkginfo)
            except:
                pass

            categories = []
            for category in pkginfo.categories:
                categories.append(category.name)

            try:
                output = "#~#".join([pkginfo.name, url, summary, description, ":::".join(categories)])
            except Exception as e:
                print (e)
                print(pkginfo.name, url, summary, description)
                return 1
            print(output)

        return 0

    def close_application(self, window, event=None):
        if self.installer.is_busy():
            dialog = Gtk.MessageDialog(self.main_window,
                                       Gtk.DialogFlags.MODAL,
                                       Gtk.MessageType.WARNING,
                                       Gtk.ButtonsType.YES_NO,
                                       _("There are currently active operations.\nAre you sure you want to quit?"))
            res = dialog.run()
            dialog.destroy()
            if res == Gtk.ResponseType.NO:
                return True

        # kill -9 won't kill mp subprocesses, we have to do them ourselves.
        housekeeping.kill()
        if self.review_cache:
            self.review_cache.kill()

        # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
        os.system("kill -9 %s &" % os.getpid())

    def on_action_button_clicked(self, button, task):
        if task.info_ready_status == task.STATUS_UNKNOWN:
            self.show_package(self.current_pkginfo, self.previous_page)
            return

        if not self.installer.confirm_task(task):
            return

        self.on_installer_progress(task.pkginfo, 0, True)

        self.installer.execute_task(task)

        self.update_activity_widgets()

    def on_launch_button_clicked(self, button, task):
        if task.exec_string is not None:
            exec_array = task.exec_string.split()
            for element in exec_array:
                if element.startswith('%'):
                    exec_array.remove(element)
            if "sh" in exec_array:
                print("Launching app with OS: " % " ".join(exec_array))
                os.system("%s &" % " ".join(exec_array))
            else:
                print("Launching app with Popen: %s" % " ".join(exec_array))
                subprocess.Popen(exec_array)

    def file_to_array(self, filename):
        array = []

        with open(filename) as f:
            for line in f:
                line = line.replace("\n", "").replace("\r", "").strip()
                if line != "":
                    array.append(line)

        return array

    @print_timing
    def add_categories(self):
        self.categories = []
        self.sections = {}
        self.root_categories = {}

        self.installed_category = Category(_("Installed Applications"), None, self.categories)
        self.installed_category.matchingPackages = self.settings.get_strv(INSTALLED_APPS)

        self.active_tasks_category = Category(_("Currently working on the following packages"), None, None)

        self.picks_category = Category(_("Editors' Picks"), None, self.categories)

        edition = ""
        try:
            with open("/etc/os-release") as f:
                config = dict([line.strip().split("=") for line in f])
                edition = config['NAME']
        except:
            pass
        if "LMDE" in edition:
            self.picks_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/picks-lmde.list")
        else:
            self.picks_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/picks.list")

        self.flatpak_category = Category("Flatpak", None, self.categories, "mintinstall-package-flatpak-symbolic")

        # ALL
        self.all_category = Category(_("All Applications"), None, self.categories, "view-grid-symbolic")
        with os.scandir("/usr/share/linuxmint/mintinstall/categories/") as it:
            for entry in it:
                if entry.path.endswith(".list"):
                    self.all_category.matchingPackages.extend(self.file_to_array(entry.path))
                    sorted(self.all_category.matchingPackages)

        # INTERNET
        category = Category(_("Internet"), None, self.categories, "web-browser-symbolic")

        subcat = Category(_("Web"), category, self.categories)
        self.sections["web"] = subcat
        self.sections["net"] = subcat
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-web.list")

        subcat = Category(_("Email"), category, self.categories)
        self.sections["mail"] = subcat
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-email.list")

        subcat = Category(_("Chat"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-chat.list")

        subcat = Category(_("File sharing"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-filesharing.list")

        self.root_categories[category.name] = category

        # SOUND AND VIDEO
        category = Category(_("Sound and video"), None, self.categories, "emblem-music-symbolic")
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/sound-video.list")
        subcat = Category(_("Sound"), category, self.categories)
        self.sections["sound"] = subcat
        subcat = Category(_("Video"), category, self.categories)
        self.sections["video"] = subcat
        self.root_categories[category.name] = category

        # GRAPHICS
        category = Category(_("Graphics"), None, self.categories, "applications-graphics-symbolic")
        self.sections["graphics"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics.list")

        subcat = Category(_("3D"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-3d.list")
        subcat = Category(_("Drawing"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-drawing.list")
        subcat = Category(_("Photography"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-photography.list")
        subcat = Category(_("Publishing"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-publishing.list")
        subcat = Category(_("Scanning"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-scanning.list")
        subcat = Category(_("Viewers"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-viewers.list")
        self.root_categories[category.name] = category

        # OFFICE
        category = Category(_("Office"), None, self.categories, "x-office-presentation-symbolic")
        self.sections["office"] = category
        self.sections["editors"] = category
        self.root_categories[category.name] = category

        # GAMES
        category = Category(_("Games"), None, self.categories, "applications-games-symbolic")
        self.sections["games"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games.list")

        subcat = Category(_("Board games"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-board.list")
        subcat = Category(_("First-person"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-fps.list")
        subcat = Category(_("Real-time strategy"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-rts.list")
        subcat = Category(_("Turn-based strategy"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-tbs.list")
        subcat = Category(_("Emulators"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-emulators.list")
        subcat = Category(_("Simulation and racing"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-simulations.list")
        self.root_categories[category.name] = category

        # ACCESSORIES
        category = Category(_("Accessories"), None, self.categories, "plugins")
        self.sections["accessories"] = category
        self.sections["utils"] = category
        self.root_categories[category.name] = category

        # SYSTEM TOOLS
        category = Category(_("System tools"), None, self.categories, "settings-configure")
        self.sections["system"] = category
        self.sections["admin"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/system-tools.list")
        self.root_categories[category.name] = category

        # FONTS
        category = Category(_("Fonts"), None, self.categories, "font-x-generic-symbolic")
        self.sections["fonts"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/fonts.list")
        self.root_categories[category.name] = category

        # EDUCATION
        category = Category(_("Science and Education"), None, self.categories, "applications-science-symbolic")
        subcat = Category(_("Science"), category, self.categories)
        self.sections["science"] = subcat
        subcat = Category(_("Maths"), category, self.categories)
        self.sections["math"] = subcat
        subcat = Category(_("Education"), category, self.categories)
        self.sections["education"] = subcat
        subcat = Category(_("Electronics"), category, self.categories)
        self.sections["electronics"] = subcat
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/education.list")
        self.root_categories[category.name] = category

        # PROGRAMMING
        category = Category(_("Programming"), None, self.categories, "format-text-code")
        self.sections["devel"] = category
        subcat = Category(_("Java"), category, self.categories)
        self.sections["java"] = subcat
        subcat = Category(_("PHP"), category, self.categories)
        self.sections["php"] = subcat
        subcat = Category(_("Python"), category, self.categories)
        self.sections["python"] = subcat
        subcat = Category(_("Essentials"), category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/development-essentials.list")
        self.root_categories[category.name] = category

    def add_pkginfo_to_category(self, pkginfo, category):
            try:
                if category not in pkginfo.categories:
                    pkginfo.categories.append(category)
                    category.pkginfos.append(pkginfo)

                    if category.parent:
                        self.add_pkginfo_to_category(pkginfo, category.parent)
            except AttributeError:
                pass

    def finished_loading_packages(self):
        self.finish_loading_visual()

        self.gui_ready = True

        if self.install_on_startup_file != None:
            self.handle_command_line_install(self.install_on_startup_file)

        return False

    @print_timing
    def process_matching_packages(self):
        # Process matching packages
        for category in self.categories:
            for package_name in category.matchingPackages:
                pkginfo = self.installer.find_pkginfo(package_name, "a")

                self.add_pkginfo_to_category(pkginfo, category)

        for package_name in self.installed_category.matchingPackages:
            pkginfo = self.installer.find_pkginfo(package_name, "f")
            self.add_pkginfo_to_category(pkginfo,
                                         self.installed_category)

        self.flatpak_remote_categories = {}
        self.flatpak_category.subcategories = []

        for key in self.installer.cache.get_subset_of_type("f"):
            remote_name = self.installer.cache[key].remote
            remote_info = self.installer.cache.flatpak_remote_infos[remote_name]

            self.add_pkginfo_to_category(self.installer.cache[key],
                                         self.flatpak_category)

            # Remotes marked noenumerate don't get a category, their apps show only in
            # the installed category and the main flatpak category.  They are auto-removed
            # then the app is uninstalled generally (usually they're -origin remotes, only added
            # when a .flatpakref file is installed.)  However, their addition/removal, purposely,
            # will not trigger a rebuild of the cache, so we don't want to be caught showing an
            # empty category as a reuslt.
            if remote_info.noenumerate:
                continue

            if remote_name not in self.flatpak_remote_categories.keys():
                self.flatpak_remote_categories[remote_name] = Category(remote_info.title, self.flatpak_category, None)

            self.add_pkginfo_to_category(self.installer.cache[key],
                                         self.flatpak_remote_categories[remote_name])

    @print_timing
    def process_unmatched_packages(self):
        cache_sections = self.installer.cache.sections

        for section in self.sections.keys():
            if section in cache_sections.keys():
                for pkg_hash in cache_sections[section]:
                    self.add_pkginfo_to_category(self.installer.cache[pkg_hash],
                                                 self.sections[section])

    def apply_aliases(self):
        for pkg_name in ALIASES.keys():
            pkginfo = self.installer.cache.find_pkginfo(pkg_name, 'a') # aliases currently only apply to apt

            if pkginfo:
                # print("Applying aliases: ", ALIASES[pkg_name], self.installer.get_display_name(pkginfo))
                pkginfo.display_name = ALIASES[pkg_name]

    def finish_loading_visual(self):
        self.builder.get_object("loading_spinner").stop()

        if self.page_stack.get_visible_child_name() != self.PAGE_LANDING:
            self.page_stack.set_visible_child_name(self.PAGE_LANDING)

    #Copied from the Cinnamon Project cinnamon-settings.py
    #Goes back when the Backspace or Home key on the keyboard is typed
    def on_keypress(self, widget, event):
        if self.main_window.get_focus() != self.searchentry and (event.keyval in [Gdk.KEY_BackSpace, Gdk.KEY_Home]):
            self.go_back_action()
            return True
        return False

    #Copied from the Cinnamon Project cinnamon-settings.py
    #Goes back when the back button on the mouse is clicked
    def on_buttonpress(self, widget, event):
        if event.button == MOUSE_BACK_BUTTON:
            self.go_back_action()
            return True
        return False

    def reset_scroll_view(self, scrolledwindow):
        adjustment = scrolledwindow.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())

    def on_active_tasks_button_clicked(self, button):
        self.show_active_tasks()

    def show_active_tasks(self):
        self.current_pkginfo = None

        self.active_tasks_category.pkginfos = self.installer.get_active_pkginfos()

        self.show_category(self.active_tasks_category)

    def on_back_button_clicked(self, button):
        self.go_back_action()

    def go_back_action(self):
        XApp.set_window_progress(self.main_window, 0)
        self.stop_progress_pulse()

        # If we're still loading details (and simulating), there's no task yet,
        # but we can cancel it via cancellable the installer gave us initially.
        if self.task_cancellable is not None:
            self.task_cancellable.cancel()
            self.task_cancellable = None

        # If we have a task, we're viewing a package and it's been 'loaded' fully.
        # Cancel it directly.
        elif self.current_task:
            if not self.installer.task_running(self.current_task):
                self.installer.cancel_task(self.current_task)
            self.current_task = None

        self.current_pkginfo = None
        self.page_stack.set_visible_child_name(self.previous_page)
        if self.previous_page == self.PAGE_LANDING:
            self.back_button.set_sensitive(False)
            self.searchentry.grab_focus()
            self.searchentry.set_text("")
            self.current_category = None
            if self.one_package_idle_timer > 0:
                GLib.source_remove(self.one_package_idle_timer)
                self.one_package_idle_timer = 0
            try:
                tile = self.flowbox_popular.get_selected_children()[0]
                tile.grab_focus()
            except IndexError:
                pass

        if self.previous_page == self.PAGE_LIST:
            self.previous_page = self.PAGE_LANDING
            if self.current_category == self.installed_category:
                # special case, when going back to the installed-category, refresh it in case we removed something
                self.show_category(self.installed_category)
            elif self.current_category == self.active_tasks_category:
                self.show_active_tasks()
            else:
                try:
                    tile = self.flowbox_applications.get_selected_children()[0]
                    tile.grab_focus()
                except IndexError:
                    pass

        if self.screenshot_stack.get_realized():
            self.screenshot_stack.get_window().set_cursor(None)
        self.update_conditional_widgets()

    def show_category(self, category):
        self.current_pkginfo = None

        label = self.builder.get_object("label_cat_name")

        self.current_category = category

        self.page_stack.set_visible_child_name(self.PAGE_LIST)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)

        label.set_text(self.current_category.name)
        label.show()

        if category.parent:
            self.show_subcategories(category.parent)
        else:
            self.show_subcategories(category)

        self.show_packages(category.pkginfos, from_search=False)

        self.update_conditional_widgets()

    def show_subcategories(self, category):
        # Load subcategories
        for child in self.subcat_flowbox.get_children():
            child.destroy()

        if category == self.flatpak_category or len(category.subcategories) == 0:
            self.subcat_flowbox.hide()
            return

        child = SubcategoryFlowboxChild(category, is_all=True, active=self.current_category == category)
        self.subcat_flowbox.add(child)

        for cat in category.subcategories:
            if len(cat.pkginfos) > 0:
                child = SubcategoryFlowboxChild(cat, is_all=False, active=self.current_category == cat)
                self.subcat_flowbox.add(child)

        self.subcat_flowbox.show_all()

    def on_subcategory_selected(self, flowbox, child, data=None):
        self.show_category(child.category)

    def get_application_icon_string(self, pkginfo, size):
        string = self.installer.get_icon(pkginfo, size)

        if not string:
            string = FALLBACK_PACKAGE_ICON_PATH

        return string

    def get_application_icon(self, pkginfo, size):
        icon_string = self.get_application_icon_string(pkginfo, size)

        return AsyncImage(icon_string, size, size)

    @print_timing
    def show_search_results(self, terms):
        label = self.builder.get_object("label_cat_name")
        label.hide()

        XApp.set_window_progress(self.main_window, 0)
        self.stop_progress_pulse()
        self.current_pkginfo = None

        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        if self.subsearch_toggle.get_active()  \
            and self.current_category != None  \
            and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            listing = self.current_category.pkginfos
        else:
            listing = self.installer.cache.values()
            self.current_category = None

        self.subcat_flowbox.hide()
        self.back_button.set_sensitive(True)
        self.previous_page = self.PAGE_LANDING
        if self.page_stack.get_visible_child_name() != self.PAGE_SEARCHING:
            self.builder.get_object("loading_spinner").start()
            self.page_stack.set_visible_child_name(self.PAGE_SEARCHING)

        termsUpper = terms.upper()
        termsSplit = re.split(r'\W+', termsUpper)

        searched_packages = []

        if self.search_idle_timer > 0:
            GLib.source_remove(self.search_idle_timer)
            self.search_idle_timer = 0

        search_in_summary = self.settings.get_boolean(SEARCH_IN_SUMMARY)
        search_in_description = self.settings.get_boolean(SEARCH_IN_DESCRIPTION)

        def idle_search_one_package(pkginfos):
            try:
                pkginfo = pkginfos.pop(0)
            except IndexError:
                self.search_idle_timer = 0
                return False

            while True:
                if all(piece in pkginfo.name.upper() for piece in termsSplit):
                    searched_packages.append(pkginfo)
                    break
                if (search_in_summary and termsUpper in self.installer.get_summary(pkginfo, for_search=True).upper()):
                    searched_packages.append(pkginfo)
                    break
                if(search_in_description and termsUpper in self.installer.get_description(pkginfo, for_search=True).upper()):
                    searched_packages.append(pkginfo)
                    break
                # pkginfo.name for flatpaks is their id (org.foo.BarMaker), which
                # may not actually contain the app's name. In this case their display
                # names are better. The 'name' is still checked first above, because
                # it's static - get_display_name() may involve a lookup with appstream.
                fp = pkginfo.pkg_hash.startswith("f")
                if fp and all(piece in self.installer.get_display_name(pkginfo).upper() for piece in termsSplit):
                    searched_packages.append(pkginfo)
                    break
                break

            # Repeat until empty
            if len(pkginfos) > 0:
                return True

            self.search_idle_timer = 0

            GLib.idle_add(self.on_search_results_complete, searched_packages)
            return False

        self.search_idle_timer = GLib.idle_add(idle_search_one_package, list(listing))

    def on_search_results_complete(self, results):
        self.page_stack.set_visible_child_name(self.PAGE_LIST)
        self.builder.get_object("loading_spinner").stop()
        self.show_packages(results, from_search=True)

    def on_app_row_activated(self, listbox, row, previous_page):
        self.show_package(row.pkginfo, previous_page)

    def on_flowbox_item_clicked(self, tile, data=None):
        # This ties the GtkButton.clicked signal for the Tile class
        # to the flowbox mechanics.  Clicks would be handled by
        # GtkFlowBox.child-activated if we weren't using a GtkButton
        # as each flowbox entry.  This could probably fixed eventually
        # but we like the button styling and highlighting.
        tile.get_parent().activate()

    def on_flowbox_child_activated(self, flowbox, child, previous_page):
        flowbox.select_child(child)

        self.show_package(child.pkginfo, previous_page)

    def navigate_flowbox(self, flowbox, scrolled_window):
        try:
            selected = flowbox.get_selected_children()[0]
        except IndexError:
            return

        adj = scrolled_window.get_vadjustment()
        current = adj.get_value()
        sel_box = selected.get_allocation()
        fb_box = flowbox.get_allocation()
        sw_box = scrolled_window.get_allocation()

        unit = sel_box.height
        if (sel_box.y + sw_box.y + fb_box.y + unit) > (current + sw_box.height):
            adj.set_value((sel_box.y + fb_box.y + unit) - sw_box.height)
        elif sel_box.y + fb_box.y < current:
            adj.set_value(sel_box.y + fb_box.y)

    def capitalize(self, string):
        if len(string) > 1:
            return (string[0].upper() + string[1:])
        else:
            return (string)

    def package_compare(self, pkga, pkgb):
        score_a = 0
        score_b = 0

        try:
            score_a = self.review_cache[pkga.name].score
        except:
            pass

        try:
            score_b = self.review_cache[pkgb.name].score
        except:
            pass

        if score_a == score_b:
            # A flatpak's 'name' may not even have the app's name in it.
            # It's better to compare by their display names
            if pkga.pkg_hash.startswith("f"):
                name_a = self.installer.get_display_name(pkga)
            else:
                name_a = pkga.name
            if pkgb.pkg_hash.startswith("f"):
                name_b = self.installer.get_display_name(pkgb)
            else:
                name_b = pkgb.name

            if name_a < name_b:
                return -1
            elif name_a > name_b:
                return 1
            else:
                return 0

        if score_a > score_b:
            return -1
        else:  # score_a < score_b
            return 1

    def show_packages(self, pkginfos, from_search=False):
        if self.one_package_idle_timer > 0:
            GLib.source_remove(self.one_package_idle_timer)
            self.one_package_idle_timer = 0

        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        self.category_tiles = []
        if len(pkginfos) == 0:
            self.app_list_stack.set_visible_child_name("no-results")

            if self.current_category == self.active_tasks_category:
                text = _("All operations complete")
                self.no_packages_found_refresh_button.hide()
            else:
                if from_search:
                    text = _("No matching packages found")
                    self.no_packages_found_refresh_button.hide()
                else:
                    text = _("No packages to show.\nThis may indicate a problem - try refreshing the cache.")
                    self.no_packages_found_refresh_button.show()

            self.no_packages_found_label.set_markup("<big><b>%s</b></big>" % text)
        else:
            self.app_list_stack.set_visible_child_name("results")

        apps = [info for info in pkginfos if info.refid == "" or info.refid.startswith("app")]
        apps.sort(key=functools.cmp_to_key(self.package_compare))

        apps = apps[0:201]

        # Identify name collisions (to show more info when multiple apps have the same name)
        package_titles = []
        collisions = []

        bad_ones = []
        for pkginfo in apps:
            try:
                title = self.installer.get_display_name(pkginfo).lower()
                if title in package_titles and title not in collisions:
                    collisions.append(title)
                package_titles.append(title)
            except:
                bad_ones.append(pkginfo)

        for bad in bad_ones:
            apps.remove(bad)

        self.one_package_idle_timer = GLib.idle_add(self.idle_show_one_package,
                                                    apps,
                                                    collisions)

        self.flowbox_applications.show_all()

    def idle_show_one_package(self, pkginfos, collisions):
        try:
            pkginfo = pkginfos.pop(0)
        except IndexError:
            self.one_package_idle_timer = 0
            return False

        icon = self.get_application_icon(pkginfo, LIST_ICON_SIZE)

        summary = self.installer.get_summary(pkginfo)
        summary = summary.replace("<", "&lt;")
        summary = summary.replace("&", "&amp;")

        if self.review_cache:
            review_info = self.review_cache[pkginfo.name]
        else:
            review_info = None

        tile = VerticalPackageTile(pkginfo, icon, self.installer, show_package_type=True, review_info=review_info)
        self.flowbox_applications.insert(tile, -1)
        self.category_tiles.append(tile)

        # Repeat until empty
        if len(pkginfos) > 0:
            return True

        self.reset_scroll_view(self.builder.get_object("scrolledwindow_applications"))
        self.one_package_idle_timer = 0
        return False

    def on_tile_keypress(self, row, event, data=None):
        if event.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.searchentry.grab_focus()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def package_type_combo_changed(self, combo):
        iter = combo.get_active_iter()
        if iter:
            pkginfo = combo.get_model().get_value(iter, PACKAGE_TYPE_COMBO_PKGINFO)
            self.show_package(pkginfo, self.previous_page)

    @print_timing
    def show_package(self, pkginfo, previous_page):
        self.page_stack.set_visible_child_name(self.PAGE_DETAILS)
        self.builder.get_object("details_notebook").set_current_page(0)
        self.previous_page = previous_page
        self.back_button.set_sensitive(True)

        self.update_conditional_widgets()

        # Reset the position of our scrolled window back to the top
        self.reset_scroll_view(self.builder.get_object("scrolled_details"))

        self.current_pkginfo = pkginfo

        # Set to busy while the installer figures out what to do
        self.builder.get_object("notebook_progress").set_current_page(self.SPINNER_TAB)

        # Set source-agnostic things

        icon_string = self.get_application_icon_string(pkginfo, DETAILS_ICON_SIZE)
        self.detail_view_icon.set_icon_string(icon_string)

        self.package_type_store.clear()
        self.package_type_combo.set_button_sensitivity(Gtk.SensitivityType.AUTO)

        try:
            self.package_type_combo.disconnect_by_func(self.package_type_combo_changed)
        except TypeError:
            pass

        self.package_type_store.clear()

        i = 0
        to_use_iter = None
        row_pkginfo = None
        row = None
        tooltip = None

        # add system if this is a system package, or one exists in our match table.
        if pkginfo.pkg_hash.startswith("a"):
            row_pkginfo = pkginfo
        else:
            match = self.get_deb_for_flatpak(pkginfo)
            if match is not None:
                row_pkginfo = match

        if row_pkginfo:
            row = [i, _("System Package"), _("Your system's package manager"), "linuxmint-logo-badge-symbolic", row_pkginfo]
            iter = self.package_type_store.append(row)
            if pkginfo == row_pkginfo:
                to_use_iter = iter
                tooltip = row[PACKAGE_TYPE_COMBO_SUMMARY]
            i += 1

        if pkginfo.pkg_hash.startswith("f") or self.get_flatpak_for_deb(pkginfo) is not None:
            a_flatpak = self.get_flatpak_for_deb(pkginfo) or pkginfo
            for remote in self.installer.list_flatpak_remotes():
                row_pkginfo = self.installer.find_pkginfo(a_flatpak.name, remote=remote.name)
                if row_pkginfo:
                    row = [i, _("Flatpak (%s)") % remote.title, remote.summary, "mintinstall-package-flatpak-symbolic", row_pkginfo]
                    iter = self.package_type_store.append(row)
                    if pkginfo == row_pkginfo:
                        to_use_iter = iter
                        tooltip = row[PACKAGE_TYPE_COMBO_SUMMARY]
                    i += 1

        if i == 1:
            self.package_type_combo_container.hide()
            self.single_version_package_type_box.show()
            self.single_version_package_type_label.set_label(row[PACKAGE_TYPE_COMBO_LABEL])
            self.single_version_package_type_icon.set_from_icon_name(row[PACKAGE_TYPE_COMBO_ICON_NAME], Gtk.IconSize.BUTTON)
            self.single_version_package_type_box.set_tooltip_text(row[PACKAGE_TYPE_COMBO_SUMMARY])
        else:
            self.single_version_package_type_box.hide()
            self.package_type_combo_container.show()
            self.package_type_combo.set_active_iter(to_use_iter)
            self.package_type_combo.set_tooltip_text(tooltip)

        if pkginfo.pkg_hash.startswith("f"):
            self.flatpak_details_vgroup.show()
            # We don't know flatpak versions until the task reports back, apt we know immediately.
            self.builder.get_object("application_version").set_label("")
        else:
            self.flatpak_details_vgroup.hide()
            self.builder.get_object("application_version").set_label(self.installer.get_version(pkginfo))

        self.package_type_combo.connect("changed", self.package_type_combo_changed)

        app_name = self.installer.get_display_name(pkginfo)

        self.builder.get_object("application_name").set_label(app_name)
        self.builder.get_object("application_summary").set_label(self.installer.get_summary(pkginfo))
        self.builder.get_object("application_package").set_label(pkginfo.name)
        self.builder.get_object("application_size").set_markup("")
        self.builder.get_object("application_remote").set_markup("")
        self.builder.get_object("application_branch").set_markup("")

        homepage_url = self.installer.get_homepage_url(pkginfo)
        if homepage_url not in ('', None):
            self.builder.get_object("application_homepage").show()
            homepage_label = _("Homepage")
            self.builder.get_object("application_homepage").set_markup("<a href='%s'>%s</a>" % (homepage_url, homepage_label))
            self.builder.get_object("application_homepage").set_tooltip_text(homepage_url)
        else:
            self.builder.get_object("application_homepage").hide()

        helppage_url = self.installer.get_help_url(pkginfo)
        if helppage_url not in ('', None):
            self.builder.get_object("application_help_page").show()
            helppage_label = _("Documentation")
            self.builder.get_object("application_help_page").set_markup("<a href='%s'>%s</a>" % (helppage_url, helppage_label))
            self.builder.get_object("application_help_page").set_tooltip_text(helppage_url)
        else:
            self.builder.get_object("application_help_page").hide()

        description = self.installer.get_description(pkginfo)

        if self.settings.get_boolean(HAMONIKR_SCREENSHOTS):
            try:
                from bs4 import BeautifulSoup
                hamonikrpkgname = pkginfo.name.replace("-","_")
                page = BeautifulSoup(urllib.request.urlopen("https://hamonikr.org/%s" % hamonikrpkgname, timeout=5), "lxml")
                texts = page.find("div","xe_content")
                text = texts.get_text()
                if text is not None:
                    description = text
            except Exception as e:
                pass

        app_description = self.builder.get_object("application_description")

        if description not in (None, ''):
            subbed = re.sub(r'\n+', '\n\n', description).rstrip()
            app_description.set_label(subbed)
            app_description.show()
        else:
            app_description.hide()

        review_info = self.review_cache[pkginfo.name]

        label_num_reviews = self.builder.get_object("application_num_reviews")

        # TRANSLATORS: showing specific number of reviews in the list view and the header of the package details.
        review_text = gettext.ngettext("%d Review", "%d Reviews", review_info.num_reviews) % review_info.num_reviews
        label_num_reviews.set_label(review_text)

        self.builder.get_object("application_avg_rating").set_label(str(review_info.avg_rating))

        box_stars = self.builder.get_object("box_stars")
        for child in box_stars.get_children():
            box_stars.remove(child)
        rating = review_info.avg_rating
        remaining_stars = 5
        while rating >= 1.0:
            box_stars.pack_start(Gtk.Image(icon_name="starred-symbolic", pixel_size=16), False, False, 0)
            rating -= 1
            remaining_stars -= 1
        if rating > 0.0:
            box_stars.pack_start(Gtk.Image(icon_name="semi-starred-symbolic", pixel_size=16), False, False, 0)
            remaining_stars -= 1
        for i in range(remaining_stars):
            box_stars.pack_start(Gtk.Image(icon_name="non-starred-symbolic", pixel_size=16), False, False, 0)

        box_stars.show_all()

        box_reviews = self.builder.get_object("box_reviews")

        for child in box_reviews.get_children():
            box_reviews.remove(child)

        for i in range(0, 5):
            self.star_bars[i].set_fraction(0.0)

        reviews = review_info.reviews
        reviews.sort(key=lambda x: x.date, reverse=True)

        stars = [0, 0, 0, 0, 0]
        n_reviews = len(reviews)

        if n_reviews > 0:
            # TRANSLATORS: reviews heading in package details view
            # label_reviews.set_text(_("Reviews"))
            i = 0
            for review in reviews:
                if i < 10:
                    comment = review.comment.strip()
                    comment = comment.replace("'", "\'")
                    comment = comment.replace('"', '\"')
                    comment = self.capitalize(comment)
                    review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
                    tile = ReviewTile(review.username, review_date, comment, review.rating)
                    box_reviews.add(tile)
                    i = i +1

                stars[review.rating - 1] += 1

            for i in range(0, 5):
                widget_idx = i + 1
                label = self.builder.get_object("stars_count_%s" % widget_idx)
                bar = self.builder.get_object("stars_bar_%s" % widget_idx)

                label.set_label(str(stars[i]))
                self.star_bars[i].set_fraction(stars[i] / n_reviews)

        add_your_own = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        add_your_own.set_margin_start(12)
        add_your_own.set_margin_end(12)
        add_your_own.set_margin_top(12)
        add_your_own.set_margin_bottom(12)

        community_link = "https://community.linuxmint.com/software/view/%s" % pkginfo.name
        label = Gtk.Label(xalign=0.0, use_markup=True, label=_("Click <a href='%s'>here</a> to add your own review.") % community_link)
        add_your_own.pack_start(label, True, True, 0)
        box_reviews.add(add_your_own)
        box_reviews.show_all()

        # Screenshots
        self.destroy_screenshot_window()
        for child in self.screenshot_stack.get_children():
            child.destroy()

        self.ss_swipe_handler.set_propagation_phase(Gtk.PropagationPhase.NONE)
        self.screenshot_stack.last = 0
        self.screenshot_stack.add_named(Gtk.Spinner(active=True), "spinner")
        self.add_screenshots(pkginfo)
        self.screenshot_stack.show_all()
        self.screenshot_stack.grab_focus()

        # Call the installer to get the rest of the information
        self.task_cancellable = self.installer.select_pkginfo(pkginfo,
                                                              self.on_installer_info_ready, self.on_installer_info_error,
                                                              self.on_installer_finished, self.on_installer_progress,
                                                              use_mainloop=True)

        self.populate_addons(pkginfo)

    def on_package_type_button_clicked(self, button, pkginfo):
        self.show_package(pkginfo, self.previous_page)

    def get_flatpak_for_deb(self, pkginfo):
        try:
            fp_name = FLATPAK_EQUIVS[pkginfo.name]
            return self.installer.find_pkginfo(fp_name, installer.PKG_TYPE_FLATPAK)
        except:
            return None

    def get_deb_for_flatpak(self, pkginfo):
        try:
            deb_name = DEB_EQUIVS[pkginfo.name]
            return self.installer.find_pkginfo(deb_name, installer.PKG_TYPE_APT)
        except:
            return None

    def on_installer_info_error(self, task):
        if networking_available():
            if task.info_ready_status != task.STATUS_FORBIDDEN:
                dialogs.show_error(task.error_message)
        else:
            dialogs.show_error(_("Unable to communicate with servers. Check your Internet connection and try again."))

        self.recursion_buster = True
        # The error ui changes can be handled in the normal callback
        self.on_installer_info_ready(task)

    def on_installer_info_ready(self, task):
        self.current_task = task
        self.task_cancellable = None

        pkginfo = task.pkginfo

        if pkginfo != self.current_pkginfo and (not self.installer.task_running(task)):
            return

        if self.installer.task_running(task):
            self.builder.get_object("notebook_progress").set_current_page(self.PROGRESS_TAB)
        else:
            self.builder.get_object("notebook_progress").set_current_page(self.ACTION_TAB)
            task.parent_window = self.main_window

        # Load package info
        style_context = self.action_button.get_style_context()

        action_button_description = ""
        action_button_icon = None

        if task.info_ready_status == task.STATUS_OK:
            if task.type == "remove":
                action_button_label = _("Remove")
                action_button_icon = None
                style_context.remove_class("suggested-action")
                style_context.add_class("destructive-action")
                action_button_description = _("Installed")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text(_("Removing"))
            else:
                action_button_label = _("Install")
                if pkginfo.pkg_hash.startswith("f"):
                    action_button_icon = "mintinstall-package-flatpak-symbolic"
                else:
                    action_button_icon = "linuxmint-logo-badge-symbolic"

                style_context.remove_class("destructive-action")
                style_context.add_class("suggested-action")
                action_button_description = _("Not installed")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text(_("Installing"))
        else:
            if task.info_ready_status == task.STATUS_FORBIDDEN:
                if task.type == "remove":
                    action_button_label = _("Cannot remove")
                    action_button_description = _("Removing this package could cause irreparable damage to your system.")
                else:
                    action_button_label = _("Cannot install")
                    action_button_description = _("Installing this package could cause irreparable damage to your system.")

                    style_context.remove_class("suggested-action")
                    style_context.add_class("destructive-action")

                self.action_button.set_sensitive(False)
                self.progress_label.set_text("")
            elif task.info_ready_status == task.STATUS_BROKEN:
                action_button_label = _("Not available")
                style_context.remove_class("destructive-action")
                style_context.remove_class("suggested-action")
                action_button_description = _("Please use apt-get to install this package.")
                self.action_button.set_sensitive(False)
            elif task.info_ready_status == task.STATUS_UNKNOWN:
                action_button_label = _("Try again")
                style_context.remove_class("destructive-action")
                style_context.add_class("suggested-action")
                action_button_description = _("Something went wrong. Click to try again.")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text("")
            action_button_icon = None

        self.action_button.set_label(action_button_label)
        self.action_button.set_tooltip_text(action_button_description)

        try:
            self.builder.get_object("application_remote").set_label(self.flatpak_remote_categories[task.remote].name)
        except (KeyError, AttributeError):
            self.builder.get_object("application_remote").set_label(task.remote)

        self.builder.get_object("application_branch").set_label(task.branch)

        try:
            self.builder.get_object("application_version").set_label(task.version)
        except TypeError:
            self.builder.get_object("application_version").set_label("")

        sizeinfo = ""

        if self.installer.pkginfo_is_installed(pkginfo):
            if task.freed_size > 0:
                sizeinfo = _("%(localSize)s of disk space freed") \
                                 % {'localSize': get_size_for_display(task.freed_size)}
            elif task.install_size > 0:
                sizeinfo = _("%(localSize)s of disk space required") \
                                 % {'localSize': get_size_for_display(task.install_size)}
        else:
            if task.freed_size > 0:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space freed") \
                               % {'downloadSize': get_size_for_display(task.download_size), 'localSize': get_size_for_display(task.freed_size)}
            else:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space required") \
                               % {'downloadSize': get_size_for_display(task.download_size), 'localSize': get_size_for_display(task.install_size)}

        if task.info_ready_status != task.STATUS_UNKNOWN:
            self.builder.get_object("application_size").set_label(sizeinfo)
            self.flatpak_details_vgroup.set_visible(task.branch != "")


        if self.action_button_signal_id > 0:
            self.action_button.disconnect(self.action_button_signal_id)
            self.action_button_signal_id = 0

        self.action_button_signal_id = self.action_button.connect("clicked",
                                                                  self.on_action_button_clicked,
                                                                  task)

        bin_name = pkginfo.name.replace(":i386", "")
        exec_string = None

        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.pkg_hash.startswith("a"):
                for desktop_file in [
                    # foo.desktop
                    "/usr/share/applications/%s.desktop" % bin_name,
                    # foo in foo-bar.desktop
                    "/usr/share/applications/%s.desktop" % bin_name.split("-")[0],
                    # foo in org.bar.Foo.desktop
                    "/usr/share/applications/%s.desktop" % bin_name.split(".")[-1],
                    "/usr/share/app-install/desktop/%s:%s.desktop" % (bin_name, bin_name)
                    ]:

                    if os.path.exists(desktop_file):
                        try:
                            info = Gio.DesktopAppInfo.new_from_filename(desktop_file)
                            exec_string = info.get_commandline()
                            if exec_string is not None:
                                break
                        except Exception as e:
                            print(e)
                if exec_string is None and os.path.exists("/usr/bin/%s" % bin_name):
                    exec_string = "/usr/bin/%s" % bin_name
            else:
                launchables = self.installer.get_flatpak_launchables(pkginfo)
                if launchables:
                    for launchable in launchables:
                        if launchable.get_kind() == AppStreamGlib.LaunchableKind.DESKTOP_ID:
                            desktop_id = launchable.get_value()
                            desktop_file = os.path.join(self.installer.get_flatpak_root_path(), "exports/share/applications", desktop_id)
                            print(desktop_file)
                            try:
                                info = Gio.DesktopAppInfo.new_from_filename(desktop_file)
                            except TypeError:
                                info = Gio.DesktopAppInfo.new_from_filename(desktop_file + ".desktop")
                            exec_string = info.get_commandline()
                            break

        if exec_string != None:
            task.exec_string = exec_string
            self.launch_button.show()

            if self.launch_button_signal_id > 0:
                self.launch_button.disconnect(self.launch_button_signal_id)
                self.launch_button_signal_id = 0

            self.launch_button_signal_id = self.launch_button.connect("clicked",
                                                                      self.on_launch_button_clicked,
                                                                      task)
        else:
            self.launch_button.hide()

    def populate_addons(self, pkginfo):
        for row in self.addons_listbox.get_children():
            row.destroy()

        addons = self.installer.get_addons(pkginfo)
        if addons is None:
            self.builder.get_object("addons_page").hide()
            return

        name_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        button_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)

        first = True
        for addon in addons:
            print("Discovered addon: %s" % addon.get_name())
            first = False

            row = FlatpakAddonRow(self, pkginfo, addon, name_size_group, button_size_group)
            self.addons_listbox.insert(row, -1)
            self.builder.get_object("addons_page").show_all()

    def on_installer_progress(self, pkginfo, progress, estimating, status_text=None):
        if self.current_pkginfo is not None and self.current_pkginfo.name == pkginfo.name:
            self.builder.get_object("notebook_progress").set_current_page(self.PROGRESS_TAB)

            if estimating:
                self.start_progress_pulse()
            else:
                self.stop_progress_pulse()

                self.builder.get_object("application_progress").set_fraction(progress / 100.0)
                XApp.set_window_progress(self.main_window, progress)
                self.progress_label.tick()

    def on_installer_finished(self, task):
        if self.current_pkginfo is not None and self.current_pkginfo.name == task.pkginfo.name:
            self.stop_progress_pulse()

            self.builder.get_object("notebook_progress").set_current_page(self.ACTION_TAB)
            self.builder.get_object("application_progress").set_fraction(0 / 100.0)
            XApp.set_window_progress(self.main_window, 0)

        self.update_state(task.pkginfo)

    def start_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            return

        self.builder.get_object("application_progress").pulse()
        self.installer_pulse_timer = GLib.timeout_add(1050, self.installer_pulse_tick)

    def installer_pulse_tick(self):
        p = self.builder.get_object("application_progress")

        p.pulse()

        return GLib.SOURCE_CONTINUE

    def stop_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            GLib.source_remove(self.installer_pulse_timer)
            self.installer_pulse_timer = 0

class DottedProgressLabel(Gtk.Fixed):
    """
    Centers a label's base text, adds ... as a progress/
    activity indicator, without the text getting repositioned.
    """
    def __init__(self):
        super(DottedProgressLabel, self).__init__()

        self.real_text = ""
        self.label = Gtk.Label()
        self.num_dots = 0

        self.add(self.label)
        self.label.show()

    def set_text(self, text):
        self.real_text = text

        self.label.set_text(text)
        self._adjust_position()

    def tick(self):
        if self.num_dots < 5:
            self.num_dots += 1
        else:
            self.num_dots = 0

        new_string = self.real_text

        i = 0

        while i < self.num_dots:
            new_string += "."
            i += 1

        self.label.set_text(new_string)

    def _adjust_position(self):
        layout = self.label.create_pango_layout()

        layout.set_text(self.real_text, -1)
        w, h = layout.get_pixel_size()

        parent_width = self.get_allocated_width()

        x_offset = (parent_width - w) / 2

        self.move(self.label, x_offset, 0)

if __name__ == "__main__":
    os.system("mkdir -p %s" % SCREENSHOT_DIR)
    app = Application()
    app.run(sys.argv)
