#!/usr/bin/python3
# encoding=utf8
# -*- coding: UTF-8 -*-

import sys
import os
import gi
import gettext
import threading
import time
import locale
import urllib.request, urllib.parse, urllib.error
import random
from datetime import datetime
import subprocess
import functools
import requests
import configobj

gi.require_version('Gtk', '3.0')
gi.require_version('AppStream', '1.0')
gi.require_version('XApp', '1.0')
gi.require_version('Flatpak', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib, Gio, Flatpak, AppStream, XApp

from installer import installer
import reviews

ICON_SIZE = 48

#Hardcoded mouse back button key for button-press-event
#May not work on all mice
MOUSE_BACK_BUTTON = 8

# Gsettings keys
SEARCH_IN_SUMMARY = "search-in-summary"
SEARCH_IN_DESCRIPTION = "search-in-description"
INSTALLED_APPS = "installed-apps"
SEARCH_IN_CATEGORY = "search-in-category"

# Don't let mintinstall run as root
if os.getuid() == 0:
    print("The software manager should not be run as root. Please run it in user mode.")
    sys.exit(1)

# Used as a decorator to time functions
def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print('%s took %0.3f ms' % (func.__name__, (t2 - t1) * 1000.0))
        return res
    return wrapper

# Used as a decorator to run things in the main loop, from another thread
def idle(func):
    def wrapper(*args):
        GObject.idle_add(func, *args)
    return wrapper

# i18n
APP = 'mintinstall'
LOCALE_DIR = "/usr/share/linuxmint/locale"
locale.bindtextdomain(APP, LOCALE_DIR)
gettext.bindtextdomain(APP, LOCALE_DIR)
gettext.textdomain(APP)
_ = gettext.gettext

import setproctitle
setproctitle.setproctitle("mintinstall")

CACHE_DIR = os.path.join(GLib.get_user_cache_dir(), "mintinstall")
SCREENSHOT_DIR = os.path.join(CACHE_DIR, "screenshots")


# List of aliases
ALIASES = {}
ALIASES['spotify-client'] = "Spotify"
ALIASES['steam-launcher'] = "Steam"
ALIASES['minecraft-installer'] = "Minecraft"
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

class ScreenshotDownloader(threading.Thread):
    def __init__(self, application, pkginfo):
        threading.Thread.__init__(self)
        self.application = application
        self.pkginfo = pkginfo

    def run(self):
        num_screenshots = 0
        self.application.screenshots = []
        # Add main screenshot
        try:
            thumb = "https://community.linuxmint.com/thumbnail.php?w=250&pic=/var/www/community.linuxmint.com/img/screenshots/%s.png" % self.pkginfo.name
            link = "https://community.linuxmint.com/img/screenshots/%s.png" % self.pkginfo.name
            if requests.head(link).status_code < 400:
                num_screenshots += 1

                local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkginfo.name, num_screenshots))

                self.save_to_file(link, local_name)
                self.save_to_file(thumb, local_thumb)

                self.application.add_screenshot(self.pkginfo.name, num_screenshots)
        except Exception as e:
            print(e)

        try:
            # Add additional screenshots from Debian
            from bs4 import BeautifulSoup
            page = BeautifulSoup(urllib.request.urlopen("http://screenshots.debian.net/package/%s" % self.pkginfo.name), "lxml")
            images = page.findAll('img')
            for image in images:
                if num_screenshots >= 4:
                    break
                if image['src'].startswith('/screenshots'):
                    num_screenshots += 1

                    thumb = "http://screenshots.debian.net%s" % image['src']
                    link = thumb.replace("_small", "_large")

                    local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                    local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkginfo.name, num_screenshots))

                    self.save_to_file(link, local_name)
                    self.save_to_file(thumb, local_thumb)

                    self.application.add_screenshot(self.pkginfo.name, num_screenshots)
        except Exception as e:
            pass

        try:
            # Add additional screenshots from AppStream
            if len(self.application.installer.get_screenshots(self.pkginfo)) > 0:
                for screenshot_url in self.pkginfo.screenshots:
                    if num_screenshots >= 4:
                        return

                    if requests.head(screenshot_url).status_code < 400:
                        num_screenshots += 1

                        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                        local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkginfo.name, num_screenshots))

                        self.save_to_file(screenshot_url, local_name)
                        self.save_to_file(screenshot_url, local_thumb)

                        self.application.add_screenshot(self.pkginfo.name, num_screenshots)
        except Exception as e:
            print(e)

    def save_to_file(self, url, path):
        r = requests.get(url, stream=True)

        with open(path, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)


class FeatureTile(Gtk.Button):
    def __init__(self, pkginfo, installer, background, color, text_shadow, border_color):
        super(Gtk.Button, self).__init__()

        self.pkginfo = pkginfo
        self.installer = installer

        css = """
#FeatureTile
{
    background: %(background)s;
    color: %(color)s;
    text-shadow: %(text_shadow)s;
    border-color: %(border_color)s;
    padding: 4px;
    outline-color: alpha(%(color)s, 0.75);
    outline-style: dashed;
    outline-offset: 2px;
}

#FeatureTitle {
    color: %(color)s;
    text-shadow: %(text_shadow)s;
    font-weight: bold;
    font-size: 24px;
}

#FeatureSummary {
    color: %(color)s;
    text-shadow: %(text_shadow)s;
    font-weight: bold;
    font-size: 12px;
}
""" % {'background':background, 'color':color, 'text_shadow':text_shadow, 'border_color':border_color}

        self.set_name("FeatureTile")
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(str.encode(css))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        label_name = Gtk.Label(xalign=0.0)
        label_name.set_label(self.installer.get_display_name(pkginfo))
        label_name.set_name("FeatureTitle")

        label_summary = Gtk.Label(xalign=0.0)
        label_summary.set_label(self.installer.get_summary(pkginfo))
        label_summary.set_name("FeatureSummary")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_border_width(6)

        vbox.pack_start(Gtk.Label(), False, False, 30)
        vbox.pack_start(label_name, False, False, 0)
        vbox.pack_start(label_summary, True, True, 0)

        hbox = Gtk.Box()
        label_left = Gtk.Label()
        hbox.pack_start(label_left, True, True, 200)
        hbox.pack_start(vbox, True, True, 0)

        self.add(hbox)

class Tile(Gtk.Button):

    def __init__(self, pkginfo, installer):
        super(Gtk.Button, self).__init__()
        self.pkginfo = pkginfo
        self.installed_mark = Gtk.Image()
        self.installer = installer

    def refresh_state(self):
        self.installed = self.installer.pkginfo_is_installed(self.pkginfo)

        if self.installed:
            self.installed_mark.set_from_icon_name("emblem-installed", Gtk.IconSize.MENU)
        else:
            self.installed_mark.clear()

class PackageTile(Tile):
    def __init__(self, pkginfo, icon, summary, installer, review_info=None, show_more_info=False):
        Tile.__init__(self, pkginfo, installer)

        label_name = Gtk.Label(xalign=0)
        if show_more_info:
            if pkginfo.pkg_hash.startswith("f"):
                label_name.set_markup("<b>%s (%s)</b>" % (self.installer.get_display_name(pkginfo), pkginfo.remote))
            else:
                label_name.set_markup("<b>%s</b>" % self.installer.get_display_name(pkginfo))
        else:
            label_name.set_markup("<b>%s</b>" % self.installer.get_display_name(pkginfo))
        label_name.set_justify(Gtk.Justification.LEFT)
        label_summary = Gtk.Label()
        label_summary.set_markup("<small>%s</small>" % summary)
        label_summary.set_alignment(0.0, 0.0)
        label_summary.set_line_wrap(True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_margin_start(6)
        vbox.set_margin_top(1)
        vbox.set_spacing(2)

        name_box = Gtk.Box()
        name_box.set_spacing(6)
        name_box.pack_start(label_name, False, False, 0)

        name_box.pack_start(self.installed_mark, False, False, 0)

        vbox.pack_start(name_box, False, False, 0)
        vbox.pack_start(label_summary, False, False, 0)
        vbox.set_valign(Gtk.Align.CENTER)

        hbox = Gtk.Box()
        hbox.pack_start(icon, False, False, 0)
        hbox.pack_start(vbox, False, False, 0)

        if review_info:
            hbox.pack_end(self.get_rating_widget(review_info), False, False, 0)

        self.add(hbox)

        self.refresh_state()

    def get_rating_widget(self, review_info):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        star_and_average_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        box_stars = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        rating = review_info.avg_rating
        remaining_stars = 5
        while rating >= 1.0:
            box_stars.pack_start(Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            rating -= 1
            remaining_stars -= 1
        if rating > 0.0:
            box_stars.pack_start(Gtk.Image.new_from_icon_name("semi-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            remaining_stars -= 1
        for i in range (remaining_stars):
            box_stars.pack_start(Gtk.Image.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        box_stars.show_all()

        star_and_average_box.pack_start(box_stars, False, False, 2)

        average_rating_label = Gtk.Label()
        average_rating_label.set_markup("<b>%s</b>" % str(review_info.avg_rating))
        star_and_average_box.pack_start(average_rating_label, False, False, 2)

        label_num_reviews = Gtk.Label()
        label_num_reviews.set_markup("<small><i>%s %s</i></small>" % (str(review_info.num_reviews), _("Reviews")))

        vbox.pack_start(star_and_average_box, False, False, 2)
        vbox.pack_start(label_num_reviews, False, False, 2)
        vbox.set_valign(Gtk.Align.CENTER)

        vbox.show_all()
        return vbox

class VerticalPackageTile(Tile):
    def __init__(self, pkginfo, icon, installer):
        Tile.__init__(self, pkginfo, installer)

        label_name = Gtk.Label(xalign=0.5)
        label_name.set_markup("<b>%s</b>" % self.installer.get_display_name(pkginfo))
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_border_width(6)

        vbox.pack_start(icon, False, False, 0)

        overlay = Gtk.Overlay()
        overlay.add(vbox)

        name_box = Gtk.Box()
        name_box.pack_start(label_name, True, True, 0)

        vbox.pack_start(name_box, True, True, 0)

        self.installed_mark.set_valign(Gtk.Align.START)
        self.installed_mark.set_halign(Gtk.Align.END)
        self.installed_mark.set_margin_start(6)
        overlay.add_overlay(self.installed_mark)

        self.add(overlay)

        self.refresh_state()

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
        label_name.set_markup("<small>%s</small>" % username)
        ratings_box.pack_start(label_name, False, False, 0)

        label_date = Gtk.Label(xalign=0.0)
        label_date.set_markup("<small>%s</small>" % date)
        ratings_box.pack_start(label_date, False, False, 0)

        label_comment = Gtk.Label(xalign=0.0)
        label_comment.set_label(comment)
        label_comment.set_line_wrap(True)

        comment_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        comment_box.set_margin_start(12)
        comment_box.pack_start(label_comment, False, False, 0)

        main_box.pack_start(ratings_box, False, False, 0)
        main_box.pack_start(comment_box, True, True, 0)

        self.add(main_box)

class Category:
    def __init__(self, name, parent, categories):
        self.name = name
        self.parent = parent
        self.subcategories = []
        self.pkginfos = []
        self.matchingPackages = []
        self.landing_widget = None
        if parent is not None:
            parent.subcategories.append(self)
        if categories is not None:
            categories.append(self)
        cat = self
        while cat.parent is not None:
            cat = cat.parent

class CategoryListBoxRow(Gtk.ListBoxRow):
    def __init__(self, category, is_all=False):
        super(Gtk.ListBoxRow, self).__init__()

        self.category = category

        if is_all:
            label = Gtk.Label(_("All"), xalign=0, margin=10)
            self.add(label)
        else:
            label = Gtk.Label(category.name, xalign=0, margin=10)
            self.add(label)

class Application(Gtk.Application):
    (ACTION_TAB, PROGRESS_TAB, SPINNER_TAB) = list(range(3))

    PAGE_LANDING = "landing"
    PAGE_LIST = "list"
    PAGE_PACKAGE = "details"
    PAGE_LOADING = "loading"

    @print_timing
    def __init__(self):
        super(Application, self).__init__(application_id='com.linuxmint.mintinstall', flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

        self.gui_ready = False

        self.settings = Gio.Settings("com.linuxmint.install")
        self.arch = Flatpak.get_default_arch()

        print("MintInstall: Detected system architecture: '%s'" % self.arch)

        self.locale = os.getenv('LANGUAGE')
        if self.locale is None:
            self.locale = "C"
        else:
            self.locale = self.locale.split("_")[0]

        self.installer = installer.Installer()

        self.install_on_startup_file = None

        self.review_cache = None
        self.current_pkginfo = None
        self.current_category = None

        self.picks_tiles = []
        self.category_tiles = []

        self.one_package_idle_timer = 0
        self.installer_pulse_timer = 0
        self.search_changed_timer = 0
        self.search_idle_timer = 0

        self.action_button_signal_id = 0
        self.launch_button_signal_id = 0
        self.listbox_categories_selected_id = 0

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
        self.installer.get_pkginfo_from_ref_file(file.get_uri(), self.on_pkginfo_from_uri_complete)

    def on_pkginfo_from_uri_complete(self, pkginfo):
        self.show_package(pkginfo, self.PAGE_LANDING)

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
        self.main_window.set_icon_name("mintinstall")
        self.main_window.connect("delete_event", self.close_application)
        self.main_window.connect("key-press-event", self.on_keypress)
        self.main_window.connect("button-press-event", self.on_buttonpress)

        self.status_label = self.builder.get_object("label_ongoing")
        self.progressbar = self.builder.get_object("progressbar1")
        self.progress_box = self.builder.get_object("progress_box")
        self.action_button = self.builder.get_object("action_button")
        self.launch_button = self.builder.get_object("launch_button")
        self.active_tasks_button = self.builder.get_object("active_tasks_button")
        self.active_tasks_spinner = self.builder.get_object("active_tasks_spinner")
        self.no_packages_found_label = self.builder.get_object("no_packages_found_label")

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

        self.installed_menuitem = Gtk.MenuItem(_("Show installed applications"))
        self.installed_menuitem.connect("activate", self.show_installed_apps)
        self.installed_menuitem.show()
        submenu.append(self.installed_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        search_summary_menuitem = Gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
        search_summary_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_SUMMARY))
        search_summary_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_SUMMARY)
        search_summary_menuitem.show()
        submenu.append(search_summary_menuitem)

        search_description_menuitem = Gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
        search_description_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_DESCRIPTION))
        search_description_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_DESCRIPTION)
        search_description_menuitem.show()
        submenu.append(search_description_menuitem)

        separator = Gtk.SeparatorMenuItem()
        separator.show()
        submenu.append(separator)

        about_menuitem = Gtk.MenuItem(_("About"))
        about_menuitem.connect("activate", self.open_about)
        about_menuitem.show()
        submenu.append(about_menuitem)

        menu_button = self.builder.get_object("menu_button")
        menu_button.connect("clicked", self.on_menu_button_clicked, submenu)

        self.flowbox_applications = Gtk.FlowBox()
        self.flowbox_applications.set_margin_start(6)
        self.flowbox_applications.set_margin_end(6)
        self.flowbox_applications.set_margin_top(6)
        self.flowbox_applications.set_margin_bottom(6)
        self.flowbox_applications.set_min_children_per_line(1)
        self.flowbox_applications.set_max_children_per_line(1)
        self.flowbox_applications.set_row_spacing(6)
        self.flowbox_applications.set_column_spacing(6)
        self.flowbox_applications.set_homogeneous(True)
        self.flowbox_applications.set_valign(Gtk.Align.START)
        self.flowbox_applications.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LIST)
        self.flowbox_applications.connect("selected-children-changed", self.on_navigate_flowbox)

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

        self.app_list_stack = self.builder.get_object("app_list_stack")

        self.generic_available_icon_path = "/usr/share/linuxmint/mintinstall/data/available.png"
        theme = Gtk.IconTheme.get_default()
        for icon_name in ["application-x-deb", "file-roller"]:
            if theme.has_icon(icon_name):
                iconInfo = theme.lookup_icon(icon_name, ICON_SIZE, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    self.generic_available_icon_path = iconInfo.get_filename()
                    break

        self.generic_available_icon_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(self.generic_available_icon_path, ICON_SIZE, ICON_SIZE)

        self.searchentry.grab_focus()

        self.listbox_categories = Gtk.ListBox()
        self.listbox_categories.set_size_request(125, -1)
        self.builder.get_object("box_subcategories").pack_start(self.listbox_categories, False, False, 0)
        self.listbox_categories_selected_id = self.listbox_categories.connect('row-activated', self.on_row_activated)

    def on_installer_ready(self):
        self.build_matched_packages()
        self.process_matching_packages()

        self.apply_aliases()

        self.load_featured_on_landing()
        self.load_picks_on_landing()
        self.load_categories_on_landing()


        self.sync_installed_apps()
        self.update_conditional_widgets()
        self.finished_loading_packages()

        # Can take some time, don't block for it (these are categorizing packages based on apt info, not our listings)
        GObject.idle_add(self.process_unmatched_packages)

        self.review_cache = reviews.ReviewCache()

    def load_featured_on_landing(self):
        box = self.builder.get_object("box_featured")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(1)
        flowbox.set_max_children_per_line(1)
        flowbox.set_row_spacing(12)
        flowbox.set_column_spacing(12)
        flowbox.set_homogeneous(True)

        flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)

        featured = []
        with open("/usr/share/linuxmint/mintinstall/featured/featured.list", 'r') as f:
            for line in f:
                if line.startswith("#") or len(line.strip()) == 0:
                    continue
                elements = line.split("----")
                if len(elements) == 5:
                    featured.append(line)

        tries = 0
        pkginfo = None

        while True:
            selected = random.sample(featured, 1)[0]
            (name, background, stroke, text, text_shadow) = selected.split('----')
            background = background.replace("@prefix@", "/usr/share/linuxmint/mintinstall/featured/")

            pkginfo = self.installer.cache.find_pkginfo(name, 'a')

            if pkginfo != None:
                break
            else:
                tries += 1

            if tries >= 10:
                print("Something wrong on featured loading")
                break

        tile = FeatureTile(pkginfo, self.installer, background, text, text_shadow, stroke)

        if pkginfo != None:
            tile.connect("clicked", self.on_flowbox_item_clicked, pkginfo.pkg_hash)

        flowbox.insert(tile, -1)
        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    def load_picks_on_landing(self):
        box = self.builder.get_object("box_picks")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(6)
        flowbox.set_max_children_per_line(6)
        flowbox.set_row_spacing(12)
        flowbox.set_column_spacing(12)
        flowbox.set_homogeneous(True)

        flowbox.connect("child-activated", self.on_flowbox_child_activated, self.PAGE_LANDING)

        installed = []
        available = []
        for name in self.picks_category.matchingPackages:
            pkginfo = self.installer.cache.find_pkginfo(name, 'a') # If we add flatpak favorites, remove the a to find both types

            if pkginfo == None:
                continue

            if self.installer.pkginfo_is_installed(pkginfo):
                installed.append(pkginfo)
            else:
                available.append(pkginfo)

        random.shuffle(installed)
        random.shuffle(available)
        featured = 0
        for pkginfo in (available + installed):
            icon = self.get_application_icon(pkginfo, ICON_SIZE)
            icon = Gtk.Image.new_from_pixbuf(icon)
            tile = VerticalPackageTile(pkginfo, icon, self.installer)
            tile.connect("clicked", self.on_flowbox_item_clicked, pkginfo.pkg_hash)
            flowbox.insert(tile, -1)
            self.picks_tiles.append(tile)
            featured += 1
            if featured >= 12:
                break
        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    @print_timing
    def load_categories_on_landing(self):
        box = self.builder.get_object("box_categories")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(4)
        flowbox.set_max_children_per_line(4)
        flowbox.set_row_spacing(6)
        flowbox.set_column_spacing(6)
        flowbox.set_homogeneous(True)
        for name in sorted(self.root_categories.keys()):
            category = self.root_categories[name]
            button = Gtk.Button()
            button.set_label(category.name)
            button.connect("clicked", self.category_button_clicked, category)
            category.landing_widget = button
            flowbox.insert(button, -1)

        # Add picks
        button = Gtk.Button()
        button.set_label(self.picks_category.name)
        button.connect("clicked", self.category_button_clicked, self.picks_category)
        self.picks_category.landing_widget = button
        flowbox.insert(button, -1)

        # Add flatpaks
        button = Gtk.Button()
        button.set_label(self.flatpak_category.name)
        button.connect("clicked", self.category_button_clicked, self.flatpak_category)
        self.flatpak_category.landing_widget = button

        flowbox.insert(button, -1)
        box.pack_start(flowbox, True, True, 0)
        box.show_all()

    def update_conditional_widgets(self):
        sensitive = len(self.installed_category.pkginfos) > 0 and \
            not ((self.page_stack.get_visible_child_name() == self.PAGE_LIST) and (self.current_category == self.installed_category))

        self.installed_menuitem.set_sensitive(sensitive)

        sensitive = self.current_category != None and self.page_stack.get_visible_child_name() == self.PAGE_LIST
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

        if self.current_category == self.active_tasks_category and self.page_stack.get_visible_child_name() == self.PAGE_LIST:
            self.show_active_tasks() # Refresh the view, remove old items

    def update_state(self, pkginfo):
        self.update_activity_widgets()

        installed_packages = self.settings.get_strv(INSTALLED_APPS)
        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.name not in installed_packages:
                installed_packages.append(pkginfo.name)
                self.installed_category.pkginfos.append(pkginfo)
        else:
            if pkginfo.name in installed_packages:
                installed_packages.remove(pkginfo.name)
                for iter_package in self.installed_category.pkginfos:
                    if iter_package.name == pkginfo.name:
                        self.installed_category.pkginfos.remove(iter_package)

        self.settings.set_strv(INSTALLED_APPS, installed_packages)

        if self.current_pkginfo is not None and self.current_pkginfo.name == pkginfo.name:
            self.show_package(self.current_pkginfo, self.previous_page)

        for tile in (self.picks_tiles + self.category_tiles):
            if tile.pkginfo == pkginfo:
                tile.refresh_state()

        for fbchild in self.flowbox_applications.get_children():
            try:
                fbchild.get_child().refresh_state()
            except Exception as e:
                print(e)

    def sync_installed_apps(self):
        # garbage collect any stale packages in this list (uninstalled somewhere else)

        installed_packages = self.settings.get_strv(INSTALLED_APPS)
        l = len(installed_packages)

        for name in installed_packages:
            pkginfo = self.installer.find_pkginfo(name)
            if pkginfo:
                if not self.installer.pkginfo_is_installed(pkginfo):
                    installed_packages.remove(name)
                    try:
                        self.installed_category.pkginfos.remove(pkginfo)
                    except ValueError:
                        pass
            else:
                installed_packages.remove(name)
                try:
                    self.installed_category.pkginfos.remove(pkginfo)
                except ValueError:
                    pass

        self.settings.set_strv(INSTALLED_APPS, installed_packages)

    def show_installed_apps(self, menuitem):
        self.show_category(self.installed_category)

    def add_screenshot(self, pkg_name, number):
        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (pkg_name, number))
        local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (pkg_name, number))
        if self.current_pkginfo is not None and self.current_pkginfo.name == pkg_name:
            if (number == 1):
                if os.path.exists(local_name):
                    try:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, 625, -1)
                        self.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)
                        self.builder.get_object("main_screenshot").show()
                    except Exception:
                        self.builder.get_object("main_screenshot").hide()
                        print("Invalid picture %s, deleting." % local_name)
                        os.unlink(local_name)
                        os.unlink(local_thumb)
            else:
                if os.path.exists(local_name) and os.path.exists(local_thumb):
                    if (number == 2):
                        try:
                            name = os.path.join(SCREENSHOT_DIR, "%s_1.png" % pkg_name)
                            thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % pkg_name)
                            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(thumb, 100, -1)
                            event_box = Gtk.EventBox()
                            image = Gtk.Image.new_from_pixbuf(pixbuf)
                            event_box.add(image)
                            event_box.connect("button-release-event", self.on_screenshot_clicked, image, thumb, name)
                            self.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                            event_box.show_all()
                        except Exception:
                            pass
                    try:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_thumb, 100, -1)
                        event_box = Gtk.EventBox()
                        image = Gtk.Image.new_from_pixbuf(pixbuf)
                        event_box.add(image)
                        event_box.connect("button-release-event", self.on_screenshot_clicked, image, local_thumb, local_name)
                        self.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                        event_box.show_all()
                    except Exception:
                        print("Invalid picture %s, deleting." % local_name)
                        os.unlink(local_name)
                        os.unlink(local_thumb)

    def on_screenshot_clicked(self, eventbox, event, image, local_thumb, local_name):
        # Set main screenshot
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, 625, -1)
        self.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)

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
            self.show_search_results(terms);

    def on_entry_text_changed(self, entry):
        if self.search_changed_timer > 0:
            GObject.source_remove(self.search_changed_timer)
            self.search_changed_timer = 0

        self.search_changed_timer = GObject.timeout_add(175, self.on_search_changed, entry)

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
        try:
            version = subprocess.check_output(["/usr/lib/linuxmint/common/version.py", "mintinstall"]).decode()
            dlg.set_version(version)
        except Exception as e:
            print(e)

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

        from xapp.pkgCache import cache

        self.installer.cache = cache.PkgCache()
        self.installer.cache.force_new_cache()
        self.installer.initialize_appstream()

        self.add_categories()
        self.build_matched_packages()
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
            url = self.installer.get_url(pkginfo)

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

        # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
        os.system("kill -9 %s &" % os.getpid())

    def on_action_button_clicked(self, button, task):
        self.on_installer_progress(task.pkginfo, 0, True)

        self.installer.execute_task(task,
                                    self.on_installer_finished,
                                    self.on_installer_progress)

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
            with open("/etc/linuxmint/info") as f:
                config = dict([line.strip().split("=") for line in f])
                edition = config['EDITION']
        except:
            pass
        if "KDE" in edition:
            self.picks_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/picks-kde.list")
        else:
            self.picks_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/picks.list")

        self.flatpak_category = Category("Flatpak", None, self.categories)

        # INTERNET
        category = Category(_("Internet"), None, self.categories)

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
        category = Category(_("Sound and video"), None, self.categories)
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/sound-video.list")
        subcat = Category(_("Sound"), category, self.categories)
        self.sections["sound"] = subcat
        subcat = Category(_("Video"), category, self.categories)
        self.sections["video"] = subcat
        self.root_categories[category.name] = category

        # GRAPHICS
        category = Category(_("Graphics"), None, self.categories)
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
        category = Category(_("Office"), None, self.categories)
        self.sections["office"] = category
        self.sections["editors"] = category
        self.root_categories[category.name] = category

        # GAMES
        category = Category(_("Games"), None, self.categories)
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
        category = Category(_("Accessories"), None, self.categories)
        self.sections["accessories"] = category
        self.sections["utils"] = category
        self.root_categories[category.name] = category

        # SYSTEM TOOLS
        category = Category(_("System tools"), None, self.categories)
        self.sections["system"] = category
        self.sections["admin"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/system-tools.list")
        self.root_categories[category.name] = category

        # FONTS
        category = Category(_("Fonts"), None, self.categories)
        self.sections["fonts"] = category
        category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/fonts.list")
        self.root_categories[category.name] = category

        # EDUCATION
        category = Category(_("Science and Education"), None, self.categories)
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
        category = Category(_("Programming"), None, self.categories)
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

    @print_timing
    def build_matched_packages(self):
        # Build a list of matched packages
        self.matchedPackages = []
        for category in self.categories:
            self.matchedPackages.extend(category.matchingPackages)
        self.matchedPackages.sort()

    def add_pkginfo_to_category(self, pkginfo, category):
            try:
                if category not in pkginfo.categories:
                    pkginfo.categories.append(category)
                    category.pkginfos.append(pkginfo)

                    if category.parent:
                        self.add_pkginfo_to_category(pkginfo, category.parent)
            except AttributeError:
                pass

    @idle
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
            self.add_pkginfo_to_category(pkginfo, self.installed_category)

        for key in self.installer.cache.get_subset_of_type("f"):
            self.add_pkginfo_to_category(self.installer.cache[key], self.flatpak_category)

    @print_timing
    def process_unmatched_packages(self):
        cache_sections = self.installer.cache.sections

        for section in self.sections.keys():
            if section in cache_sections.keys():
                for pkg_hash in cache_sections[section]:
                    self.add_pkginfo_to_category(self.installer.cache[pkg_hash], self.sections[section])

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
        if self.main_window.get_focus() != self.searchentry and event.keyval in [Gdk.KEY_BackSpace, Gdk.KEY_Home]:
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

    def reset_scroll_view(self, scrolledwindow, flowbox=None):
        adjustment = scrolledwindow.get_vadjustment()
        adjustment.set_value(adjustment.get_lower())

        if not flowbox:
            return

        try:
            first = flowbox.get_children()[0]
            flowbox.select_child(first)
        except IndexError:
            pass

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

        self.current_pkginfo = None
        self.page_stack.set_visible_child_name(self.previous_page)
        if self.previous_page == self.PAGE_LANDING:
            self.back_button.set_sensitive(False)
            self.searchentry.grab_focus()
            self.searchentry.set_text("")
            self.current_category = None
            if self.one_package_idle_timer > 0:
                GObject.source_remove(self.one_package_idle_timer)
                self.one_package_idle_timer = 0

        if self.previous_page == self.PAGE_LIST:
            self.previous_page = self.PAGE_LANDING
            if self.current_category == self.installed_category:
                # special case, when going back to the installed-category, refresh it in case we removed something
                self.show_category(self.installed_category)
            elif self.current_category == self.active_tasks_category:
                self.show_active_tasks()
            else:
                try:
                    fc = self.flowbox_applications.get_selected_children()[0]
                    fc.grab_focus()
                except IndexError:
                    pass

        self.update_conditional_widgets()

    @print_timing
    def show_category(self, category):
        self.current_pkginfo = None

        label = self.builder.get_object("label_cat_name")

        self.current_category = category

        self.page_stack.set_visible_child_name(self.PAGE_LIST)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)

        label.set_text(self.current_category.name)
        label.show()

        self.clear_category_list()

        if category.parent:
            self.show_subcategories(category.parent)
        else:
            self.show_subcategories(category)

        self.show_packages(category.pkginfos)

        self.update_conditional_widgets()

    def clear_category_list(self):
        for child in self.listbox_categories.get_children():
            self.listbox_categories.remove(child)

    def show_subcategories(self, category):
        # Load subcategories
        box = self.builder.get_object("box_subcategories")
        if len(category.subcategories) > 0:
            row = CategoryListBoxRow(category, is_all=True)
            self.listbox_categories.add(row)
            if self.current_category == category:
                self.listbox_categories.handler_block(self.listbox_categories_selected_id)
                self.listbox_categories.select_row(row)
                self.listbox_categories.handler_unblock(self.listbox_categories_selected_id)

            for cat in category.subcategories:
                if len(cat.pkginfos) > 0:
                    row = CategoryListBoxRow(cat)
                    self.listbox_categories.add(row)
                    if self.current_category == cat:
                        self.listbox_categories.handler_block(self.listbox_categories_selected_id)
                        self.listbox_categories.select_row(row)
                        self.listbox_categories.handler_unblock(self.listbox_categories_selected_id)

            box.show_all()
        else:
            box.hide()

    def on_row_activated(self, listbox, row):
        self.show_category(row.category)

    def get_application_icon(self, pkginfo, size):
        # Look in the icon theme first
        theme = Gtk.IconTheme.get_default()

        try:
            for name in [pkginfo.name, pkginfo.name.split(":")[0], pkginfo.name.split("-")[0], pkginfo.name.split(".")[-1].lower()]:
                if theme.has_icon(name):
                    iconInfo = theme.lookup_icon(name, size, 0)
                    if iconInfo and os.path.exists(iconInfo.get_filename()):
                        return GdkPixbuf.Pixbuf.new_from_file_at_size(iconInfo.get_filename(), size, size)

            # For Flatpak, look in Appstream and mintinstall provided flatpak icons
            if pkginfo.pkg_hash.startswith("f"):
                icon_path = "/var/lib/flatpak/appstream/%s/%s/active/icons/64x64/%s.png" % (pkginfo.remote, pkginfo.arch, pkginfo.name)
                if os.path.exists(icon_path):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)

                icon_path = "/usr/share/linuxmint/mintinstall/flatpak/icons/64x64/%s.png" % pkginfo.name
                if os.path.exists(icon_path):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)

            # Look in app-install-data and pixmaps
            for extension in ['svg', 'png', 'xpm']:
                icon_path = "/usr/share/app-install/icons/%s.%s" % (pkginfo.name, extension)
                if os.path.exists(icon_path):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)

                icon_path = "/usr/share/pixmaps/%s.%s" % (pkginfo.name, extension)
                if os.path.exists(icon_path):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)
        except GLib.Error:
            pass

        return self.generic_available_icon_pixbuf

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

        self.listbox_categories.hide()
        self.back_button.set_sensitive(True)
        self.previous_page = self.PAGE_LANDING
        self.page_stack.set_visible_child_name(self.PAGE_LIST)

        termsUpper = terms.upper()

        searched_packages = []

        if self.search_idle_timer > 0:
            GObject.source_remove(self.search_idle_timer)
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
                if termsUpper in pkginfo.name.upper():
                    searched_packages.append(pkginfo)
                    break
                if (search_in_summary and termsUpper in self.installer.get_summary(pkginfo, for_search=True).upper()):
                    searched_packages.append(pkginfo)
                    break
                if(search_in_description and termsUpper in self.installer.get_description(pkginfo, for_search=True).upper()):
                    searched_packages.append(pkginfo)
                    break
                break

            # Repeat until empty
            if len(pkginfos) > 0:
                return True

            self.search_idle_timer = 0

            GObject.idle_add(self.on_search_results_complete, searched_packages)
            return False

        self.search_idle_timer = GObject.idle_add(idle_search_one_package, list(listing))

    def on_search_results_complete(self, results):
        self.clear_category_list()
        self.show_packages(results)

    def on_flowbox_item_clicked(self, tile, data=None):
        # This ties the GtkButton.clicked signal for the Tile class
        # to the flowbox mechanics.  Clicks would be handled by
        # GtkFlowBox.child-activated if we weren't using a GtkButton
        # as each flowbox entry.  This could probably fixed eventually
        # but we like the button styling and highlighting.
        tile.get_parent().activate()

    def on_flowbox_child_activated(self, flowbox, child, previous_page):
        flowbox.select_child(child)

        self.show_package(child.get_child().pkginfo, previous_page)

    def on_navigate_flowbox(self, box, data=None):
        sw = self.builder.get_object("scrolledwindow_applications")

        try:
            selected = box.get_selected_children()[0]
        except IndexError:
            return

        adj = sw.get_vadjustment()
        current = adj.get_value()
        sel_box = selected.get_allocation()
        sw_box = sw.get_allocation()

        unit = sel_box.height + box.get_row_spacing()

        if (sel_box.y + unit) > (current + sw_box.height):
            adj.set_value((sel_box.y + unit) - sw_box.height + box.get_row_spacing())
        elif sel_box.y < current:
            adj.set_value(sel_box.y)

    def capitalize(self, string):
        if len(string) > 1:
            return (string[0].upper() + string[1:])
        else:
            return (string)

    def show_packages(self, pkginfos):
        if self.one_package_idle_timer > 0:
            GObject.source_remove(self.one_package_idle_timer)
            self.one_package_idle_timer = 0

        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        self.category_tiles = []
        if len(pkginfos) == 0:
            self.app_list_stack.set_visible_child_name("no-results")
            if self.current_category == self.active_tasks_category:
                text = _("All operations complete")
            else:
                text = _("No matching packages found")

            self.no_packages_found_label.set_markup("<big><b>%s</b></big>" % text)
        else:
            self.app_list_stack.set_visible_child_name("results")

        def package_compare(pkga, pkgb):
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
                if pkga.name < pkgb.name:
                    return -1
                elif pkga.name > pkgb.name:
                    return 1
                else:
                    return 0

            if score_a > score_b:
                return -1
            else:  # score_a < score_b
                return 1

        pkginfos.sort(key=functools.cmp_to_key(package_compare))

        pkginfos = pkginfos[0:200]

        # Identify name collisions (to show more info when multiple apps have the same name)
        package_titles = []
        collisions = []

        bad_ones = []
        for pkginfo in pkginfos:
            try:
                title = self.installer.get_display_name(pkginfo).lower()
                if title in package_titles and title not in collisions:
                    collisions.append(title)
                package_titles.append(title)
            except:
                bad_ones.append(pkginfo)

        for bad in bad_ones:
            pkginfos.remove(bad)

        self.one_package_idle_timer = GObject.idle_add(self.idle_show_one_package, pkginfos, collisions)
        self.flowbox_applications.show_all()

    def idle_show_one_package(self, pkginfos, collisions):
        try:
            pkginfo = pkginfos.pop(0)
        except IndexError:
            self.one_package_idle_timer = 0
            return False

        icon = self.get_application_icon(pkginfo, ICON_SIZE)
        icon = Gtk.Image.new_from_pixbuf(icon)

        summary = self.installer.get_summary(pkginfo)
        summary = summary.replace("<", "&lt;")
        summary = summary.replace("&", "&amp;")

        tile = PackageTile(pkginfo, icon, summary,
                           installer=self.installer,
                           review_info=self.review_cache[pkginfo.name],
                           show_more_info=(self.installer.get_display_name(pkginfo).lower() in collisions))
        tile.connect("clicked", self.on_flowbox_item_clicked, pkginfo.pkg_hash)

        box = Gtk.FlowBoxChild(child=tile)
        box.show_all()

        self.flowbox_applications.insert(box, -1)
        self.category_tiles.append(tile)

        # Repeat until empty
        if len(pkginfos) > 0:
            return True

        self.reset_scroll_view(self.builder.get_object("scrolledwindow_applications"), self.flowbox_applications)
        self.one_package_idle_timer = 0
        return False

    @print_timing
    def show_package(self, pkginfo, previous_page):
        self.page_stack.set_visible_child_name(self.PAGE_PACKAGE)
        self.previous_page = previous_page
        self.back_button.set_sensitive(True)

        self.update_conditional_widgets()

        # self.reset_apt_cache_now()
        # self.searchentry.set_text("")

        if self.action_button_signal_id > 0:
            self.action_button.disconnect(self.action_button_signal_id)
            self.action_button_signal_id = 0

        if self.launch_button_signal_id > 0:
            self.launch_button.disconnect(self.launch_button_signal_id)
            self.launch_button_signal_id = 0

        # Reset the position of our scrolled window back to the top
        self.reset_scroll_view(self.builder.get_object("scrolled_details"), None)

        self.current_pkginfo = pkginfo

        # Set to busy while the installer figures out what to do
        self.builder.get_object("notebook_progress").set_current_page(self.SPINNER_TAB)

        # Set source-agnostic things

        self.builder.get_object("application_icon").set_from_pixbuf(self.get_application_icon(pkginfo, 64))
        self.builder.get_object("application_name").set_label(self.installer.get_display_name(pkginfo))
        self.builder.get_object("application_summary").set_label(self.installer.get_summary(pkginfo))
        self.builder.get_object("application_package").set_label(pkginfo.name)

        description = self.installer.get_description(pkginfo)
        app_description = self.builder.get_object("application_description")
        app_description.set_label(description)
        app_description.set_line_wrap(True)

        homepage = self.installer.get_url(pkginfo)
        if homepage is not None and homepage != "":
            self.builder.get_object("website_link").show()
            self.builder.get_object("website_link").set_markup("<a href='%s'>%s</a>" % (homepage, homepage))
        else:
            self.builder.get_object("website_link").hide()

        review_info = self.review_cache[pkginfo.name]

        label_num_reviews = self.builder.get_object("application_num_reviews")
        label_num_reviews.set_markup("<small><i>%s %s</i></small>" % (str(review_info.num_reviews), _("Reviews")))
        self.builder.get_object("application_avg_rating").set_label(str(review_info.avg_rating))

        box_stars = self.builder.get_object("box_stars")
        for child in box_stars.get_children():
            box_stars.remove(child)
        rating = review_info.avg_rating
        remaining_stars = 5
        while rating >= 1.0:
            box_stars.pack_start(Gtk.Image.new_from_icon_name("starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            rating -= 1
            remaining_stars -= 1
        if rating > 0.0:
            box_stars.pack_start(Gtk.Image.new_from_icon_name("semi-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
            remaining_stars -= 1
        for i in range (remaining_stars):
            box_stars.pack_start(Gtk.Image.new_from_icon_name("non-starred-symbolic", Gtk.IconSize.MENU), False, False, 0)
        box_stars.show_all()

        box_reviews = self.builder.get_object("box_reviews")

        for child in box_reviews.get_children():
            box_reviews.remove(child)

        frame_reviews = self.builder.get_object("frame_reviews")
        label_reviews = self.builder.get_object("label_reviews")

        reviews = review_info.reviews
        reviews.sort(key=lambda x: x.date, reverse=True)

        if len(reviews) > 0:
            label_reviews.set_text(_("Reviews"))
            i = 0
            for review in reviews:
                comment = review.comment.strip()
                comment = comment.replace("'", "\'")
                comment = comment.replace('"', '\"')
                comment = self.capitalize(comment)
                review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
                tile = ReviewTile(review.username, review_date, comment, review.rating)
                box_reviews.add(tile)
                i = i +1
                if i >= 10:
                    break
            frame_reviews.show()
            box_reviews.show_all()
        else:
            label_reviews.set_text(_("No reviews available"))
            frame_reviews.hide()

        community_link = "https://community.linuxmint.com/software/view/%s" % pkginfo.name
        self.builder.get_object("label_community").set_markup(_("Click <a href='%s'>here</a> to add your own review.") % community_link)

        # Screenshots
        box_more_screenshots = self.builder.get_object("box_more_screenshots")
        for child in box_more_screenshots.get_children():
            box_more_screenshots.remove(child)

        main_screenshot = os.path.join(SCREENSHOT_DIR, "%s_1.png" % pkginfo.name)
        main_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % pkginfo.name)
        if os.path.exists(main_screenshot) and os.path.exists(main_thumb):
            try:
                main_screenshot = GdkPixbuf.Pixbuf.new_from_file_at_size(main_screenshot, 625, -1)
                self.builder.get_object("main_screenshot").set_from_pixbuf(main_screenshot)
                self.builder.get_object("main_screenshot").show()
            except:
                self.builder.get_object("main_screenshot").hide()
                os.unlink(main_screenshot)
            for i in range(2, 5):
                self.add_screenshot(pkginfo.name, i)
        else:
            self.builder.get_object("main_screenshot").hide()
            downloadScreenshots = ScreenshotDownloader(self, pkginfo)
            downloadScreenshots.start()

        # Hide some widgets that may or may not be used when the task is ready
        self.builder.get_object("application_remote").hide()
        self.builder.get_object("label_remote").hide()
        self.builder.get_object("application_architecture").hide()
        self.builder.get_object("label_architecture").hide()
        self.builder.get_object("application_branch").hide()
        self.builder.get_object("label_branch").hide()
        self.builder.get_object("application_version").hide()
        self.builder.get_object("label_version").hide()
        self.builder.get_object("application_size").hide()
        self.builder.get_object("label_size").hide()

        # Call the installer to get the rest of the information
        self.installer.select_pkginfo(pkginfo, self.on_installer_task_ready)

    def on_installer_task_ready(self, task):
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

        if task.info_ready_status == task.STATUS_OK:
            if task.type == "remove":
                action_button_label = _("Remove")
                style_context.remove_class("suggested-action")
                style_context.add_class("destructive-action")
                action_button_description = _("Installed")
                self.action_button.set_sensitive(True)
                self.progress_label.set_text(_("Removing"))
            else:
                action_button_label = _("Install")
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

        self.action_button.set_label(action_button_label)
        self.action_button.set_tooltip_text(action_button_description)

        self.builder.get_object("application_remote").set_label(task.remote)
        self.builder.get_object("application_architecture").set_label(task.arch)
        self.builder.get_object("application_branch").set_label(task.branch)
        self.builder.get_object("application_version").set_label(task.version)

        sizeinfo = ""

        if self.installer.pkginfo_is_installed(pkginfo):
            if task.freed_size > 0:
                sizeinfo = _("%(localSize)s of disk space freed") \
                                 % {'localSize': GLib.format_size(task.freed_size)}
            elif task.install_size > 0:
                sizeinfo = _("%(localSize)s of disk space required") \
                                 % {'localSize': GLib.format_size(task.install_size)}
        else:
            if task.freed_size > 0:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space freed") \
                                 % {'downloadSize': GLib.format_size(task.download_size), 'localSize': GLib.format_size(task.freed_size)}
            else:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space required") \
                                 % {'downloadSize': GLib.format_size(task.download_size), 'localSize': GLib.format_size(task.install_size)}

        self.builder.get_object("label_size").show()
        self.builder.get_object("application_size").show()
        self.builder.get_object("application_size").set_label(sizeinfo)

        self.builder.get_object("application_remote").set_visible(task.remote != "")
        self.builder.get_object("label_remote").set_visible(task.remote != "")
        self.builder.get_object("application_architecture").set_visible(task.arch != "")
        self.builder.get_object("label_architecture").set_visible(task.arch != "")
        self.builder.get_object("application_branch").set_visible(task.branch != "")
        self.builder.get_object("label_branch").set_visible(task.branch != "")
        self.builder.get_object("application_version").set_visible(task.version != "")
        self.builder.get_object("label_version").set_visible(task.version != "")

        self.action_button_signal_id = self.action_button.connect("clicked",
                                                                  self.on_action_button_clicked,
                                                                  task)

        bin_name = pkginfo.name.replace(":i386", "")
        exec_string = None

        if self.installer.pkginfo_is_installed(pkginfo):
            if pkginfo.pkg_hash.startswith("a"):
                for desktop_file in ["/usr/share/applications/%s.desktop" % bin_name, "/usr/share/app-install/desktop/%s:%s.desktop" % (bin_name, bin_name)]:
                    if os.path.exists(desktop_file):
                        config = configobj.ConfigObj(desktop_file)
                        try:
                            exec_string = config['Desktop Entry']['Exec']
                            break
                        except:
                            pass
                if exec_string is None and os.path.exists("/usr/bin/%s" % bin_name):
                    exec_string = "/usr/bin/%s" % bin_name
            else:
                exec_string = "flatpak run %s" % pkginfo.name

        if exec_string != None:
            task.exec_string = exec_string
            self.launch_button.show()
            self.launch_button_signal_id = self.launch_button.connect("clicked",
                                                                      self.on_launch_button_clicked,
                                                                      task)
        else:
            self.launch_button.hide()

    def on_installer_progress(self, pkginfo, progress, estimating):
        if self.current_pkginfo is not None and self.current_pkginfo.name == pkginfo.name:
            self.builder.get_object("notebook_progress").set_current_page(self.PROGRESS_TAB)

            if estimating:
                self.start_progress_pulse()
            else:
                self.stop_progress_pulse()

                self.builder.get_object("application_progress").set_fraction(progress / 100.0)
                XApp.set_window_progress(self.main_window, progress)
                self.progress_label.tick()

    def on_installer_finished(self, pkginfo, error):
        if self.current_pkginfo is not None and self.current_pkginfo.name == pkginfo.name:
            self.stop_progress_pulse()

            self.builder.get_object("notebook_progress").set_current_page(self.ACTION_TAB)
            self.builder.get_object("application_progress").set_fraction(0 / 100.0)
            XApp.set_window_progress(self.main_window, 0)

        self.update_state(pkginfo)

    def start_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            return

        self.builder.get_object("application_progress").pulse()
        self.installer_pulse_timer = GObject.timeout_add(1050, self.installer_pulse_tick)

    def installer_pulse_tick(self):
        p = self.builder.get_object("application_progress")

        p.pulse()

        return GLib.SOURCE_CONTINUE

    def stop_progress_pulse(self):
        if self.installer_pulse_timer > 0:
            GObject.source_remove(self.installer_pulse_timer)
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
