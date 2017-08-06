#!/usr/bin/python2
# -*- coding: UTF-8 -*-

import sys
import os
import commands
import gi
import gettext
import threading
import time
import apt
import urllib
import urllib2
import httplib
import random
from urlparse import urlparse
import configobj
from datetime import datetime
import subprocess

gi.require_version('Gtk', '3.0')
gi.require_version('AppStream', '1.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib, Gio, AppStream

import aptdaemon.client
from aptdaemon.enums import *
from aptdaemon.gtk3widgets import AptErrorDialog, AptConfirmDialog, AptProgressDialog, AptStatusIcon
import aptdaemon.errors

ICON_SIZE = 48

#Hardcoded mouse back button key for button-press-event
#May not work on all mice
MOUSE_BACK_BUTTON = 8

SEARCH_IN_SUMMARY = "search-in-summary"
SEARCH_IN_DESCRIPTION = "search-in-description"

# Don't let mintinstall run as root
if os.getuid() == 0:
    print "The software manager should not be run as root. Please run it in user mode."
    sys.exit(1)

def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print '%s took %0.3f ms' % (func.func_name, (t2 - t1) * 1000.0)
        return res
    return wrapper

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")


import setproctitle
setproctitle.setproctitle("mintinstall")

CACHE_DIR = os.path.expanduser("~/.cache/mintinstall")
SCREENSHOT_DIR = os.path.join(CACHE_DIR, "screenshots")
REVIEWS_PATH = os.path.join(CACHE_DIR, "reviews.list")

# List of packages which are either broken or do not install properly in mintinstall
BROKEN_PACKAGES = ['pepperflashplugin-nonfree']

# List of aliases
ALIASES = {}
ALIASES['spotify-client'] = "Spotify"
ALIASES['steam-launcher'] = "Steam"
ALIASES['minecraft-installer'] = "Minecraft"
ALIASES['virtualbox-qt'] = "Virtualbox " # Added a space to force alias
ALIASES['virtualbox'] = "Virtualbox (base)"
ALIASES['sublime-text'] = "Sublime"
ALIASES['mint-meta-codecs'] = "Multimedia Codecs"
ALIASES['mint-meta-codecs-kde'] = "Multimedia Codecs for KDE"
ALIASES['mint-meta-debian-codecs'] = "Multimedia Codecs"
ALIASES['firefox'] = "Firefox"
ALIASES['vlc'] = "VLC"
ALIASES['mpv'] = "Mpv"
ALIASES['gimp'] = "Gimp"
ALIASES['gnome-maps'] = "GNOME Maps"
ALIASES['thunderbird'] = "Thunderbird"

#Exceptions so packages like chromium-bsu don't get Chromium's
# icon and cause confusion
ICON_EXCEPTIONS = ["chromium-bsu"]


def list_header_func(row, before, user_data):
    if before and not row.get_header():
        row.set_header(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

class DownloadReviews(threading.Thread):

    def __init__(self, application):
        threading.Thread.__init__(self)
        self.application = application

    def run(self):
        try:
            reviews_path_tmp = REVIEWS_PATH + ".tmp"
            url = urllib.urlretrieve("http://community.linuxmint.com/data/new-reviews.list", reviews_path_tmp)
            numlines = 0
            numlines_new = 0
            if os.path.exists(REVIEWS_PATH):
                numlines = int(commands.getoutput("cat " + REVIEWS_PATH + " | wc -l"))
            if os.path.exists(reviews_path_tmp):
                numlines_new = int(commands.getoutput("cat " + reviews_path_tmp + " | wc -l"))
            if numlines_new > numlines:
                os.system("mv " + reviews_path_tmp + " " + REVIEWS_PATH)
                print "Overwriting reviews file in " + REVIEWS_PATH
                self.application.update_reviews()
        except Exception, detail:
            print detail

class ScreenshotDownloader(threading.Thread):

    def __init__(self, application, pkg_name):
        threading.Thread.__init__(self)
        self.application = application
        self.pkg_name = pkg_name

    def run(self):
        num_screenshots = 0
        self.screenshot_shown = None
        self.application.screenshots = []
        # Add main screenshot
        try:
            thumb = "http://community.linuxmint.com/thumbnail.php?w=250&pic=/var/www/community.linuxmint.com/img/screenshots/%s.png" % self.pkg_name
            link = "http://community.linuxmint.com/img/screenshots/%s.png" % self.pkg_name
            p = urlparse(link)
            conn = httplib.HTTPConnection(p.netloc)
            conn.request('HEAD', p.path)
            resp = conn.getresponse()
            if resp.status < 400:
                num_screenshots += 1
                local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkg_name, num_screenshots))
                local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkg_name, num_screenshots))
                urllib.urlretrieve (link, local_name)
                urllib.urlretrieve (thumb, local_thumb)
                self.application.add_screenshot(self.pkg_name, num_screenshots)
        except Exception, detail:
            print detail

        try:
            # Add additional screenshots
            from BeautifulSoup import BeautifulSoup
            page = BeautifulSoup(urllib2.urlopen("http://screenshots.debian.net/package/%s" % self.pkg_name))
            images = page.findAll('img')
            for image in images:
                if num_screenshots >= 4:
                    break
                if image['src'].startswith('/screenshots'):
                    num_screenshots += 1
                    thumb = "http://screenshots.debian.net%s" % image['src']
                    link = thumb.replace("_small", "_large")
                    local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkg_name, num_screenshots))
                    local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkg_name, num_screenshots))
                    urllib.urlretrieve (link, local_name)
                    urllib.urlretrieve (thumb, local_thumb)
                    self.application.add_screenshot(self.pkg_name, num_screenshots)
        except Exception, detail:
            print detail

class FeatureTile(Gtk.Button):
    def __init__(self, package, background, color, text_shadow, border_color):
        self.package = package
        super(Gtk.Button, self).__init__()

        css = """
#FeatureTile
{
    background: %(background)s;
    color: %(color)s;
    text-shadow: %(text_shadow)s;
    border-color: %(border_color)s;
    -GtkWidget-focus-padding: 0;
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
        style_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        label_name = Gtk.Label(xalign=0.0)
        label_name.set_label(package.title)
        label_name.set_name("FeatureTitle")

        label_summary = Gtk.Label(xalign=0.0)
        label_summary.set_label(package.summary)
        label_summary.set_name("FeatureSummary")

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_border_width(6)

        vbox.pack_start(Gtk.Label(), False, False, 50)
        vbox.pack_start(label_name, False, False, 0)
        vbox.pack_start(label_summary, True, True, 0)

        hbox = Gtk.Box()
        label_left = Gtk.Label()
        hbox.pack_start(label_left, True, True, 200)
        hbox.pack_start(vbox, True, True, 0)

        self.add(hbox)

class PackageTile(Gtk.Button):

    def __init__(self, package, icon, summary):
        self.package = package
        super(Gtk.Button, self).__init__()

        label_name = Gtk.Label(xalign=0)
        label_name.set_markup("<b>%s</b>" % package.title)
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
        if package.pkg.is_installed:
            installed_mark = Gtk.Image.new_from_icon_name("emblem-installed", Gtk.IconSize.MENU)
            name_box.pack_start(installed_mark, False, False, 0)

        vbox.pack_start(name_box, False, False, 0)
        vbox.pack_start(label_summary, False, False, 0)

        hbox = Gtk.Box()
        hbox.pack_start(icon, False, False, 0)
        hbox.pack_start(vbox, False, False, 0)

        self.add(hbox)

class VerticalPackageTile(Gtk.Button):
    def __init__(self, package, icon):
        self.package = package
        super(Gtk.Button, self).__init__()

        label_name = Gtk.Label(xalign=0.5)
        label_name.set_markup("<b>%s</b>" % package.title)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_border_width(6)

        vbox.pack_start(icon, False, False, 0)

        name_box = Gtk.Box()
        name_box.pack_start(label_name, True, True, 0)
        if package.pkg.is_installed:
            installed_mark = Gtk.Image.new_from_icon_name("emblem-installed", Gtk.IconSize.MENU)
            name_box.pack_start(installed_mark, False, False, 3)

        vbox.pack_start(name_box, True, True, 0)

        self.add(vbox)

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
        self.packages = []
        self.matchingPackages = []
        if parent is not None:
            parent.subcategories.append(self)
        categories.append(self)
        cat = self
        while cat.parent is not None:
            cat = cat.parent


class Package(object):
    __slots__ = 'title', 'pkg', 'reviews', 'categories', 'score', 'avg_rating', 'num_reviews', '_candidate', 'candidate', '_summary', 'summary', 'pool_component' #To remove __dict__ memory overhead

    def __init__(self, pkg):
        self.title = pkg.name
        self.pkg = pkg
        self.reviews = []
        self.categories = []
        self.score = 0
        self.avg_rating = 0
        self.num_reviews = 0
        self.pool_component = None

    def _get_candidate(self):
        if not hasattr(self, "_candidate"):
            self._candidate = self.pkg.candidate
        return self._candidate
    candidate = property(_get_candidate)

    def _get_summary(self):
        if not hasattr(self, "_summary"):
            candidate = self.candidate
            if candidate is not None:
                self._summary = candidate.summary
            else:
                self._summary = None
        return self._summary
    summary = property(_get_summary)

    def update_stats(self):
        points = 0
        sum_rating = 0
        self.num_reviews = len(self.reviews)
        self.avg_rating = 0
        for review in self.reviews:
            points = points + (review.rating - 3)
            sum_rating = sum_rating + review.rating
        if self.num_reviews > 0:
            self.avg_rating = round(float(sum_rating) / float(self.num_reviews), 1)
        self.score = points


class Review(object):
    __slots__ = 'date', 'packagename', 'username', 'rating', 'comment', 'package' #To remove __dict__ memory overhead

    def __init__(self, packagename, date, username, rating, comment):
        self.date = date
        self.packagename = packagename
        self.username = username
        self.rating = int(rating)
        self.comment = comment
        self.package = None

class MetaTransaction():

    def __init__(self, application, transaction):
        self.application = application
        self.transaction = transaction
        self.package = self.application.current_package
        transaction.connect("progress-changed", self.on_transaction_progress)
        # transaction.connect("cancellable-changed", self.on_driver_changes_cancellable_changed)
        transaction.connect("finished", self.on_transaction_finish)
        # transaction.connect("error", self.on_driver_changes_error)
        transaction.run()

    def on_transaction_progress(self, transaction, progress):
        # self.status_label.set_text(transaction.status)
        # self.progressbar.set_fraction(progress / 100.0)
        if self.application.current_package.pkg.name == self.package.pkg.name:
            self.application.builder.get_object("notebook_progress").set_current_page(1)
            self.application.builder.get_object("application_progress").set_fraction(progress / 100.0)

    def on_transaction_finish(self, transaction, exit_state):
        if (exit_state == aptdaemon.enums.EXIT_SUCCESS):
            name = self.package.pkg.name
            self.application.cache = apt.Cache() # reread cache
            self.package.pkg = self.application.cache[name] # update package
            if self.application.current_package.pkg.name == name:
                self.application.builder.get_object("notebook_progress").set_current_page(0)
                self.application.builder.get_object("application_progress").set_fraction(0 / 100.0)
                self.application.show_package(self.application.current_package, self.application.previous_page)

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

class Application():

    PAGE_LANDING = 0
    PAGE_LIST = 1
    PAGE_PACKAGE = 2

    @print_timing
    def load_cache(self):
        self.cache = apt.Cache()
        self.pool = AppStream.Pool()
        self.pool.load()

    def run(self):
        self.loop.run()

    @print_timing
    def __init__(self):

        self.load_cache()

        self.add_categories()
        self.build_matched_packages()
        self.add_packages()
        self.process_matching_packages()

        self.current_package = None
        self.desktop_exec = None
        self.removals = []
        self.additions = []
        self.transactions = {}

        # Build the GUI
        glade_file = "/usr/share/linuxmint/mintinstall/mintinstall.glade"

        self.builder = Gtk.Builder()
        self.builder.add_from_file(glade_file)
        self.main_window = self.builder.get_object("main_window")
        self.main_window.set_title(_("Software Manager"))
        self.main_window.set_icon_name("mintinstall")
        self.main_window.connect("delete_event", self.close_application)
        self.main_window.connect("key-press-event", self.on_keypress)
        self.main_window.connect("button-press-event", self.on_buttonpress)

        self.status_label = self.builder.get_object("label_ongoing")
        self.progressbar = self.builder.get_object("progressbar1")

        self.ac = aptdaemon.client.AptClient()
        self.loop = GLib.MainLoop()

        self.add_reviews()
        downloadReviews = DownloadReviews(self)
        downloadReviews.start()

        if len(sys.argv) > 1 and sys.argv[1] == "list":
            # Print packages and their categories and exit
            self.export_listing()
            sys.exit(0)

        self.settings = Gio.Settings("com.linuxmint.install")

        # Build the menu
        file_menu = Gtk.MenuItem(_("_File"))
        file_menu.set_use_underline(True)
        file_submenu = Gtk.Menu()
        file_menu.set_submenu(file_submenu)
        close_menuitem = Gtk.ImageMenuItem.new_with_label(_("Close"))
        image = Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close_menuitem.set_image(image)
        close_menuitem.connect("activate", self.close_application)
        file_submenu.append(close_menuitem)

        edit_menu = Gtk.MenuItem(_("_Edit"))
        edit_menu.set_use_underline(True)
        edit_submenu = Gtk.Menu()
        edit_menu.set_submenu(edit_submenu)

        search_summary_menuitem = Gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
        search_summary_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_SUMMARY))
        search_summary_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_SUMMARY)

        search_description_menuitem = Gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
        search_description_menuitem.set_active(self.settings.get_boolean(SEARCH_IN_DESCRIPTION))
        search_description_menuitem.connect("toggled", self.set_search_filter, SEARCH_IN_DESCRIPTION)

        edit_submenu.append(search_summary_menuitem)
        edit_submenu.append(search_description_menuitem)

        help_menu = Gtk.MenuItem(_("_Help"))
        help_menu.set_use_underline(True)
        help_submenu = Gtk.Menu()
        help_menu.set_submenu(help_submenu)
        about_menuitem = Gtk.ImageMenuItem.new_with_label(_("About"))
        image = Gtk.Image.new_from_icon_name("help-about-symbolic", Gtk.IconSize.MENU)
        about_menuitem.set_image(image)
        about_menuitem.connect("activate", self.open_about)
        help_submenu.append(about_menuitem)

        self.builder.get_object("menubar1").append(file_menu)
        self.builder.get_object("menubar1").append(edit_menu)
        self.builder.get_object("menubar1").append(help_menu)

        self.flowbox_applications = Gtk.FlowBox()
        self.flowbox_applications.set_margin_start(12)
        self.flowbox_applications.set_margin_end(12)
        self.flowbox_applications.set_margin_top(6)
        self.flowbox_applications.set_min_children_per_line(1)
        self.flowbox_applications.set_max_children_per_line(3)
        self.flowbox_applications.set_row_spacing(6)
        self.flowbox_applications.set_column_spacing(6)
        self.flowbox_applications.set_homogeneous(True)
        self.flowbox_applications.set_valign(Gtk.Align.START)

        box = self.builder.get_object("scrolledwindow_applications")
        box.add(self.flowbox_applications)

        self.back_button = self.builder.get_object("back_button")
        self.back_button.connect("clicked", self.on_back_button_clicked)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(False)

        self.searchentry = self.builder.get_object("search_entry")
        self.searchentry.connect("changed", self.on_search_terms_changed)
        self.searchentry.connect("activate", self.on_search_entry_activated)

        self.notebook = self.builder.get_object("notebook1")

        self.generic_available_icon_path = "/usr/share/linuxmint/mintinstall/data/available.png"
        theme = Gtk.IconTheme.get_default()
        for icon_name in ["application-x-deb", "file-roller"]:
            if theme.has_icon(icon_name):
                iconInfo = theme.lookup_icon(icon_name, ICON_SIZE, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    self.generic_available_icon_path = iconInfo.get_filename()
                    break

        self.generic_available_icon_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(self.generic_available_icon_path, ICON_SIZE, ICON_SIZE)

        self.load_featured_on_landing()
        self.load_picks_on_landing()
        self.load_categories_on_landing()

        self.searchentry.grab_focus()

        self.builder.get_object("main_window").show_all()

        self.listbox_categories = Gtk.ListBox()
        self.listbox_categories.set_size_request(125, -1)
        self.builder.get_object("box_subcategories").pack_start(self.listbox_categories, False, False, 0)
        self.listbox_categories.connect('row-activated', self.on_row_activated)

        self.builder.get_object("action_button").connect("clicked", self.on_action_button_clicked)
        self.builder.get_object("launch_button").connect("clicked", self.on_launch_button_clicked)

    def add_screenshot(self, pkg_name, number):
        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (pkg_name, number))
        local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (pkg_name, number))
        if self.current_package.pkg.name == pkg_name:
            if (number == 1):
                if os.path.exists(local_name):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, 450, -1)
                    self.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)
                    self.builder.get_object("main_screenshot").show()
            else:
                if os.path.exists(local_name) and os.path.exists(local_thumb):
                    if (number == 2):
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % pkg_name), 100, -1)
                        event_box = Gtk.EventBox()
                        image = Gtk.Image.new_from_pixbuf(pixbuf)
                        event_box.add(image)
                        event_box.connect("button-release-event", self.on_screenshot_clicked, image, os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % pkg_name), os.path.join(SCREENSHOT_DIR, "%s_1.png" % pkg_name))
                        self.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                        event_box.show_all()
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_thumb, 100, -1)
                    event_box = Gtk.EventBox()
                    image = Gtk.Image.new_from_pixbuf(pixbuf)
                    event_box.add(image)
                    event_box.connect("button-release-event", self.on_screenshot_clicked, image, local_thumb, local_name)
                    self.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                    event_box.show_all()

    def on_screenshot_clicked(self, eventbox, event, image, local_thumb, local_name):
        # Set main screenshot
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, -1, 350)
        self.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)

    def on_transaction_progress(self, transaction, progress):
        self.status_label.set_text(transaction.status)
        self.progressbar.set_fraction(progress / 100.0)

    def on_transaction_finish(self, transaction, exit_state):
        self.status_label.set_text()
        self.progressbar.hide()

    def _run_transaction(self, transaction):
        self.transactions[self.current_package.pkg.name] = MetaTransaction(self, transaction)
        # dia = AptProgressDialog(transaction, parent=self.main_window)
        # dia.run(close_on_finished=True, show_error=True,
        #         reply_handler=lambda: True,
        #         error_handler=self._on_error)

    def _simulate_trans(self, trans):
        trans.simulate(reply_handler=lambda: self._confirm_deps(trans),
                       error_handler=self._on_error)

    def _confirm_deps(self, trans):
        try:
            if [pkgs for pkgs in trans.dependencies if pkgs]:
                dia = AptConfirmDialog(trans, parent=self.main_window)
                res = dia.run()
                dia.hide()
                if res != Gtk.ResponseType.OK:
                    return
            self._run_transaction(trans)
        except Exception as e:
            print(e)

    def _on_error(self, error):
        if isinstance(error, aptdaemon.errors.NotAuthorizedError):
            # Silently ignore auth failures
            return
        elif not isinstance(error, aptdaemon.errors.TransactionFailed):
            # Catch internal errors of the client
            error = aptdaemon.errors.TransactionFailed(ERROR_UNKNOWN,
                                                       str(error))
        dia = AptErrorDialog(error)
        dia.run()
        dia.hide()

    def load_featured_on_landing(self):
        box = self.builder.get_object("box_featured")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(1)
        flowbox.set_max_children_per_line(1)
        flowbox.set_row_spacing(12)
        flowbox.set_column_spacing(12)
        flowbox.set_homogeneous(True)

        featured = []
        with open("/usr/share/linuxmint/mintinstall/featured/featured.list", 'r') as f:
            for line in f:
                if line.startswith("#") or len(line.strip()) == 0:
                    continue
                elements = line.split("----")
                if len(elements) == 5:
                    featured.append(line)

        selected = random.sample(featured, 1)[0]
        (name, background, stroke, text, text_shadow) = selected.split('----')
        background = background.replace("@prefix@", "/usr/share/linuxmint/mintinstall/featured/")
        pkg = self.cache[name]
        package = Package(pkg)
        self.load_pool_component(package)
        tile = FeatureTile(package, background, text, text_shadow, stroke)
        tile.connect("clicked", self.on_package_tile_clicked, self.PAGE_LANDING)
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
        installed = []
        available = []
        for package in self.picks_category.packages:
            if package.pkg.is_installed:
                installed.append(package)
            else:
                available.append(package)
        random.shuffle(installed)
        random.shuffle(available)
        featured = 0
        for package in (available + installed):
            self.load_pool_component(package)
            icon = self.get_application_icon(package, ICON_SIZE)
            icon = Gtk.Image.new_from_pixbuf(icon)
            tile = VerticalPackageTile(package, icon)
            tile.connect("clicked", self.on_package_tile_clicked, self.PAGE_LANDING)
            flowbox.insert(tile, -1)
            featured += 1
            if featured >= 12:
                break
        box.pack_start(flowbox, True, True, 0)
        box.show_all()

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
            flowbox.insert(button, -1)
        # Add picks
        button = Gtk.Button()
        button.set_label(self.picks_category.name)
        button.connect("clicked", self.category_button_clicked, self.picks_category)
        flowbox.insert(button, -1)
        box.pack_start(flowbox, True, True, 0)

    def category_button_clicked(self, button, category):
        self.show_category(category)

    def on_search_entry_activated(self, searchentry):
        terms = searchentry.get_text()
        if terms != "":
            self.show_search_results(terms)

    def on_search_terms_changed(self, entry):
        terms = entry.get_text()
        if terms != "" and len(terms) >= 3:
            self.show_search_results(terms)

    def set_search_filter(self, checkmenuitem, key):
        self.settings.set_boolean(key, checkmenuitem.get_active())
        if (self.searchentry.get_text() != ""):
            self.show_search_results(self.searchentry.get_text())

    def close_window(self, widget, window):
        window.hide()

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
        except Exception, detail:
            print detail
        try:
            version = commands.getoutput("/usr/lib/linuxmint/common/version.py mintinstall")
            dlg.set_version(version)
        except Exception, detail:
            print detail

        dlg.set_icon_name("mintinstall")
        dlg.set_logo_icon_name("mintinstall")

        def close(w, res):
            if res == Gtk.ResponseType.CANCEL or res == Gtk.ResponseType.DELETE_EVENT:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    def export_listing(self):
        # packages
        for package in self.packages:
            if package.pkg.name.endswith(":i386") or package.pkg.name.endswith(":amd64"):
                root_name = package.pkg.name.split(":")[0]
                if root_name in self.packages_dict:
                    # foo is present in the cache, so ignore foo:i386 and foo:amd64
                    continue
                elif ("%s:i386" % root_name) in self.packages_dict and ("%s:amd64" % root_name) in self.packages_dict:
                    continue
            summary = package.summary
            if summary is None:
                summary = ""
            description = ""
            version = ""
            homepage = ""
            strSize = ""
            if package.pkg.candidate is not None:
                description = package.pkg.candidate.description
                version = package.pkg.candidate.version
                homepage = package.pkg.candidate.homepage
                strSize = str(package.pkg.candidate.size) + _("B")
                if (package.pkg.candidate.size >= 1000):
                    strSize = str(package.pkg.candidate.size / 1000) + _("KB")
                if (package.pkg.candidate.size >= 1000000):
                    strSize = str(package.pkg.candidate.size / 1000000) + _("MB")
                if (package.pkg.candidate.size >= 1000000000):
                    strSize = str(package.pkg.candidate.size / 1000000000) + _("GB")

            description = description.replace("\r\n", "<br>")
            description = description.replace("\n", "<br>")
            output = package.pkg.name + "#~#" + version + "#~#" + homepage + "#~#" + strSize + "#~#" + summary + "#~#" + description + "#~#"
            for category in package.categories:
                output = output + category.name + ":::"
            if output[-3:] == (":::"):
                output = output[:-3]
            print output

    def close_window(self, widget, window, extra=None):
        try:
            window.hide_all()
        except:
            pass

    def close_application(self, window, event=None):
        # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
        os.system("kill -9 %s &" % os.getpid())

    def on_action_button_clicked(self, button):
        package = self.current_package
        if package is not None:
            if len(self.removals) > 0:
                print("Warning, removals: " + " ".join(self.removals))
            if len(self.additions) > 0:
                print("Warning, removals: " + " ".join(self.additions))
            if package.pkg.is_installed:
                self.ac.remove_packages([package.pkg.name],
                                reply_handler=self._simulate_trans,
                                error_handler=self._on_error)
            else:
                if package.pkg.name not in BROKEN_PACKAGES:
                    self.ac.install_packages([package.pkg.name], reply_handler=self._simulate_trans, error_handler=self._on_error)

    def on_launch_button_clicked(self, button):
        if self.desktop_exec is not None:
            exec_array = self.desktop_exec.split()
            for element in exec_array:
                if element.startswith('%'):
                    exec_array.remove(element)
            if "sh" in exec_array:
                print("Launching app with OS: " % " ".join(exec_array))
                os.system("%s &" % " ".join(exec_array))
            else:
                print("Launching app with Popen: %s" % " ".join(exec_array))
                subprocess.Popen(exec_array)

    @print_timing
    def add_categories(self):
        self.categories = []
        self.sections = {}
        self.root_categories = {}

        self.picks_category = Category(_("Editors Picks"), None, self.categories)
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

    def file_to_array(self, filename):
        array = []
        f = open(filename)
        for line in f:
            line = line.replace("\n", "").replace("\r", "").strip()
            if line != "":
                array.append(line)
        return array

    @print_timing
    def build_matched_packages(self):
        # Build a list of matched packages
        self.matchedPackages = []
        for category in self.categories:
            self.matchedPackages.extend(category.matchingPackages)
        self.matchedPackages.sort()

    @print_timing
    def add_packages(self):
        self.packages = []
        self.packages_dict = {}

        for name in self.cache.keys():
            if name.startswith("lib") and not name.startswith("libreoffice"):
                continue
            if name.endswith("-dev"):
                continue
            if name.endswith("-dbg"):
               continue
            if name.endswith("-doc"):
                continue
            if name.endswith("-common"):
                continue
            if name.endswith("-data"):
                continue
            if name.endswith(":i386") and name != "steam:i386":
                continue
            if name.endswith("-perl"):
                continue
            if name.endswith("l10n"):
                continue

            pkg = self.cache[name]
            package = Package(pkg)
            self.packages.append(package)
            self.packages_dict[pkg.name] = package

            # If the package is not a "matching package", find categories with matching sections
            if (name not in self.matchedPackages):
                section = pkg.section
                if "/" in section:
                    section = section.split("/")[1]
                if section in self.sections:
                    category = self.sections[section]
                    self.add_package_to_category(package, category)

    @print_timing
    def process_matching_packages(self):
        # Process matching packages
        for category in self.categories:
            for package_name in category.matchingPackages:
                try:
                    package = self.packages_dict[package_name]
                    self.add_package_to_category(package, category)
                except Exception, detail:
                    pass
                    #print detail

    def add_package_to_category(self, package, category):
        if category not in package.categories:
            package.categories.append(category)
            category.packages.append(package)
        if category.parent is not None:
            self.add_package_to_category(package, category.parent)

    @print_timing
    def add_reviews(self):
        if not os.path.exists(REVIEWS_PATH):
            # No reviews found, use the ones from the packages itself
            os.system("cp /usr/share/linuxmint/mintinstall/reviews.list %s" % REVIEWS_PATH)
            print "First run detected, initial set of reviews used"

        with open(REVIEWS_PATH) as reviews:
            last_package = None
            for line in reviews:
                elements = line.split("~~~")
                if len(elements) == 5:
                    review = Review(elements[0], float(elements[1]), elements[2], elements[3], elements[4])
                    if last_package != None and last_package.pkg.name == elements[0]:
                        #Comment is on the same package as previous comment.. no need to search for the package
                        last_package.reviews.append(review)
                        review.package = last_package
                    else:
                        if last_package is not None:
                            last_package.update_stats()
                        if elements[0] in self.packages_dict:
                            package = self.packages_dict[elements[0]]
                            last_package = package
                            package.reviews.append(review)
                            review.package = package
            if last_package is not None:
                last_package.update_stats()

    @print_timing
    def update_reviews(self):
        if os.path.exists(REVIEWS_PATH):
            reviews = open(REVIEWS_PATH)
            last_package = None
            for line in reviews:
                elements = line.split("~~~")
                if len(elements) == 5:
                    review = Review(elements[0], float(elements[1]), elements[2], elements[3], elements[4])
                    if last_package != None and last_package.pkg.name == elements[0]:
                        #Comment is on the same package as previous comment.. no need to search for the package
                        alreadyThere = False
                        for rev in last_package.reviews:
                            if rev.username == elements[2]:
                                alreadyThere = True
                                break
                        if not alreadyThere:
                            last_package.reviews.append(review)
                            review.package = last_package
                            last_package.update_stats()
                    else:
                        if elements[0] in self.packages_dict:
                            package = self.packages_dict[elements[0]]
                            last_package = package
                            alreadyThere = False
                            for rev in package.reviews:
                                if rev.username == elements[2]:
                                    alreadyThere = True
                                    break
                            if not alreadyThere:
                                package.reviews.append(review)
                                review.package = package
                                package.update_stats()

    def show_dialog_modal(self, title, text, type, buttons):
        GObject.idle_add(self._show_dialog_modal_callback, title, text, type, buttons) #as this might not be called from the main thread

    def _show_dialog_modal_callback(self, title, text, type, buttons):
        dialog = Gtk.MessageDialog(self.main_window, flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT, type=type, buttons=buttons, message_format=title)
        dialog.format_secondary_markup(text)
        dialog.connect('response', self._show_dialog_modal_clicked, dialog)
        dialog.show()

    def _show_dialog_modal_clicked(self, dialog, *args):
        dialog.destroy()

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

    def on_back_button_clicked(self, button):
        self.go_back_action()

    def go_back_action(self):
        self.notebook.set_current_page(self.previous_page)
        if self.previous_page == self.PAGE_LANDING:
            self.back_button.set_sensitive(False)
        if self.previous_page == self.PAGE_LIST:
            self.previous_page = self.PAGE_LANDING
        self.searchentry.set_text("")

    @print_timing
    def show_category(self, category):

        self.notebook.set_current_page(self.PAGE_LIST)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)

        self.searchentry.set_text("")

        if category.parent == None:
            self.clear_category_list()
            self.show_subcategories(category)

        self.show_packages(category.packages)

    def clear_category_list(self):
        for child in self.listbox_categories.get_children():
            self.listbox_categories.remove(child)

    def show_subcategories(self, category):
        # Load subcategories
        box = self.builder.get_object("box_subcategories")
        if len(category.subcategories) > 0:
            row = CategoryListBoxRow(category, is_all=True)
            self.listbox_categories.add(row)

            for cat in category.subcategories:
                row = CategoryListBoxRow(cat)
                self.listbox_categories.add(row)
                box.show_all()
        else:
            box.hide()

    def on_row_activated(self, listbox, row):
        self.show_category(row.category)

    def get_application_icon(self, package, size):
        icon_path = "/usr/share/app-install/icons/%s" % package.pkg.name

        theme = Gtk.IconTheme.get_default()
        #Checks to make sure the package name ins't in icon exceptions
        if package.pkg.name not in ICON_EXCEPTIONS:
            #Helps add icons to package addons
            for name in [package.pkg.name.split(":")[0], package.pkg.name.split("-")[0]]:
                if theme.has_icon(name):
                    iconInfo = theme.lookup_icon(name, size, 0)
                    if iconInfo and os.path.exists(iconInfo.get_filename()):
                        return GdkPixbuf.Pixbuf.new_from_file_at_size(iconInfo.get_filename(), size, size)

        # Try app-install icons then
        for extension in ['svg', 'png', 'xpm']:
            icon_path = "/usr/share/app-install/icons/%s.%s" % (package.pkg.name, extension)
            if os.path.exists(icon_path):
                return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)

        return self.generic_available_icon_pixbuf

    @print_timing
    def show_search_results(self, terms):
        self.listbox_categories.hide()
        self.back_button.set_sensitive(True)
        self.previous_page = self.PAGE_LANDING
        self.notebook.set_current_page(self.PAGE_LIST)

        termsUpper = terms.upper()

        self._searched_packages = []

        search_in_summary = self.settings.get_boolean(SEARCH_IN_SUMMARY)
        search_in_description = self.settings.get_boolean(SEARCH_IN_DESCRIPTION)

        for package in self.packages:
            visible = False
            if termsUpper in package.pkg.name.upper():
                visible = True
            else:
                if (package.candidate is not None):
                    if (search_in_summary and termsUpper in package.summary.upper()):
                        visible = True
                    elif(search_in_description and termsUpper in package.candidate.description.upper()):
                        visible = True

            if visible:
                self._searched_packages.append(package)

        self.clear_category_list()
        self.show_packages(self._searched_packages)

    def on_package_tile_clicked(self, tile, previous_page):
        self.show_package(tile.package, previous_page)

    def load_pool_component(self, package):
        if package.pool_component is None:
            component = self.pool.get_components_by_id("%s.desktop" % package.pkg.name)
            if component is not None and len(component) > 0:
                package.pool_component = component[0]
                package._summary = package.pool_component.get_summary()
                package.title = package.pool_component.get_name()
        package_name = package.pkg.name.split(":")[0]
        if package_name in ALIASES and ALIASES[package_name] not in self.packages_dict:
            package.title = ALIASES[package_name]
        package.title = self.capitalize(package.title)
        package.title = package.title.replace(":i386", "")
        package._summary = self.capitalize(package.summary)

    def capitalize(self, string):
        if len(string) > 1:
            return (string[0].upper() + string[1:])
        else:
            return (string)

    def show_packages(self, packages):
        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        packages.sort(self.package_compare)
        packages = packages[0:200]

        self.builder.get_object("notebook_progress").set_current_page(0)

        for package in packages:

            self.load_pool_component(package)

            if ":" in package.pkg.name and package.pkg.name.split(":")[0] in self.packages_dict:
                # don't list arch packages when the root is represented in the cache
                continue

            icon = self.get_application_icon(package, ICON_SIZE)
            icon = Gtk.Image.new_from_pixbuf(icon)

            summary = ""
            if package.summary is not None:
                summary = package.summary
                summary = unicode(summary, 'UTF-8', 'replace')
                summary = summary.replace("<", "&lt;")
                summary = summary.replace("&", "&amp;")

            tile = PackageTile(package, icon, summary)
            tile.connect("clicked", self.on_package_tile_clicked, self.PAGE_LIST)

            self.flowbox_applications.insert(tile, -1)
            self.flowbox_applications.show_all()

    @print_timing
    def show_package(self, package, previous_page):

        self.notebook.set_current_page(self.PAGE_PACKAGE)
        self.previous_page = previous_page
        self.back_button.set_sensitive(True)

        self.searchentry.set_text("")
        self.current_package = package

        # Load package info
        score = 0

        if package.pool_component is not None:
            description = package.pool_component.get_description()
            description = description.replace("<p>", "").replace("</p>", "\n")
        else:
            description = package.pkg.candidate.description
        description = self.capitalize(description)

        impacted_packages = []
        self.removals = []
        self.installations = []

        pkg = package.pkg
        try:
            if pkg.is_installed:
                pkg.mark_delete(True, True)
            else:
                pkg.mark_install()
        except:
            if pkg.name not in BROKEN_PACKAGES:
                BROKEN_PACKAGES.append(pkg.name)

        changes = self.cache.get_changes()
        for pkg in changes:
            if pkg.name == package.pkg.name:
                continue
            if (pkg.is_installed):
                self.removals.append(pkg.name)
            else:
                self.installations.append(pkg.name)

        downloadSize = str(self.cache.required_download) + _("B")
        if (self.cache.required_download >= 1000):
            downloadSize = str(self.cache.required_download / 1000) + _("KB")
        if (self.cache.required_download >= 1000000):
            downloadSize = str(self.cache.required_download / 1000000) + _("MB")
        if (self.cache.required_download >= 1000000000):
            downloadSize = str(self.cache.required_download / 1000000000) + _("GB")

        required_space = self.cache.required_space
        if (required_space < 0):
            required_space = (-1) * required_space
        localSize = str(required_space) + _("B")
        if (required_space >= 1000):
            localSize = str(required_space / 1000) + _("KB")
        if (required_space >= 1000000):
            localSize = str(required_space / 1000000) + _("MB")
        if (required_space >= 1000000000):
            localSize = str(required_space / 1000000000) + _("GB")

        if package.pkg.is_installed:
            if self.cache.required_space < 0:
                sizeinfo = _("%(localSize)s of disk space freed") % {'localSize': localSize}
            else:
                sizeinfo = _("%(localSize)s of disk space required") % {'localSize': localSize}
        else:
            if self.cache.required_space < 0:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space freed") % {'downloadSize': downloadSize, 'localSize': localSize}
            else:
                sizeinfo = _("%(downloadSize)s to download, %(localSize)s of disk space required") % {'downloadSize': downloadSize, 'localSize': localSize}

        self.builder.get_object("application_size").set_label(sizeinfo)

        community_link = "https://community.linuxmint.com/software/view/%s" % package.pkg.name
        self.builder.get_object("label_community").set_markup(_("Click <a href='%s'>here</a> to add your own review.") % community_link)

        action_button = self.builder.get_object("action_button")
        style_context = action_button.get_style_context()

        if package.pkg.is_installed:
            action_button_label = _("Remove")
            style_context.remove_class("suggested-action")
            style_context.add_class("destructive-action")
            version = package.pkg.installed.version
            homepage = package.pkg.installed.homepage
            action_button_description = _("Installed")
            action_button.set_sensitive(True)
        else:
            if package.pkg.name in BROKEN_PACKAGES:
                action_button_label = _("Not available")
                style_context.remove_class("destructive-action")
                style_context.remove_class("suggested-action")
                action_button_description = _("Please use apt-get to install this package.")
                action_button.set_sensitive(False)
            else:
                action_button_label = _("Install")
                style_context.remove_class("destructive-action")
                style_context.add_class("suggested-action")
                action_button_description = _("Not installed")
                action_button.set_sensitive(True)
            version = package.pkg.candidate.version
            homepage = package.pkg.candidate.homepage

        action_button.set_label(action_button_label)
        action_button.set_tooltip_text(action_button_description)


        self.builder.get_object("application_version").set_label(version)

        label_num_reviews = self.builder.get_object("application_num_reviews")
        label_num_reviews.set_markup("<small><i>%s %s</i></small>" % (str(package.num_reviews), _("Reviews")))
        self.builder.get_object("application_avg_rating").set_label(str(package.avg_rating))

        box_reviews = self.builder.get_object("box_reviews")
        for child in box_reviews.get_children():
            box_reviews.remove(child)

        box_reviews.set_header_func(list_header_func, None)

        reviews = package.reviews
        reviews.sort(key=lambda x: x.date, reverse=True)
        i = 0
        for review in reviews:
            comment = review.comment.strip()
            comment = comment.replace("'", "\'")
            comment = comment.replace('"', '\"')
            comment = unicode(comment, 'UTF-8', 'replace')
            comment = self.capitalize(comment)
            review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
            tile = ReviewTile(review.username, review_date, comment, review.rating)
            # box_reviews.pack_start(tile, False, False, 0)
            box_reviews.add(tile)
            i = i +1
            if i >= 10:
                break
        box_reviews.show_all()

        box_stars = self.builder.get_object("box_stars")
        for child in box_stars.get_children():
            box_stars.remove(child)
        rating = package.avg_rating
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

        self.builder.get_object("application_icon").set_from_pixbuf(self.get_application_icon(package, 64))
        self.builder.get_object("application_name").set_label(package.title)
        self.builder.get_object("application_summary").set_label(package.summary)
        app_description = self.builder.get_object("application_description")
        app_description.set_label(description)
        app_description.set_line_wrap(True)

        if homepage is not None and homepage != "":
            self.builder.get_object("website_link").show()
            self.builder.get_object("website_link").set_markup("<a href='%s'>%s</a>" % (homepage, homepage))
        else:
            self.builder.get_object("website_link").hide()

        # Get data from app-install-data
        launch_button = self.builder.get_object("launch_button")
        launch_button.hide()

        self.builder.get_object("application_categories").set_label("")
        self.builder.get_object("label_categories").hide()
        self.desktop_exec = None
        bin_name = package.pkg.name.replace(":i386", "")
        if package.pkg.is_installed:
            for desktop_file in ["/usr/share/applications/%s.desktop" % bin_name, "/usr/share/app-install/desktop/%s:%s.desktop" % (bin_name, bin_name)]:
                if os.path.exists(desktop_file):
                    config = configobj.ConfigObj(desktop_file)
                    try:
                        self.desktop_exec = config['Desktop Entry']['Exec']
                        # TODO: Turn raw categories description into properly localized menu names..
                        #self.builder.get_object("application_categories").set_label(config['Desktop Entry']['Categories'])
                        #self.builder.get_object("label_categories").show()
                        launch_button.show()
                        break
                    except:
                        pass
            if self.desktop_exec is None and os.path.exists("/usr/bin/%s" % bin_name):
                self.desktop_exec = "/usr/bin/%s" % bin_name
                launch_button.show()

        # Screenshots
        box_more_screenshots = self.builder.get_object("box_more_screenshots")
        for child in box_more_screenshots.get_children():
            box_more_screenshots.remove(child)

        main_screenshot = os.path.join(SCREENSHOT_DIR, "%s_1.png" % package.pkg.name)
        main_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % package.pkg.name)
        if os.path.exists(main_screenshot) and os.path.exists(main_thumb):
            main_screenshot = GdkPixbuf.Pixbuf.new_from_file_at_size(main_screenshot, 450, -1)
            self.builder.get_object("main_screenshot").set_from_pixbuf(main_screenshot)
            self.builder.get_object("main_screenshot").show()
            for i in range(2, 5):
                self.add_screenshot(package.pkg.name, i)
        else:
            self.builder.get_object("main_screenshot").hide()
            downloadScreenshots = ScreenshotDownloader(self, package.pkg.name)
            downloadScreenshots.start()

    def package_compare(self, x, y):
        if x.score == y.score:
            if x.pkg.name < y.pkg.name:
                return -1
            elif x.pkg.name > y.pkg.name:
                return 1
            else:
                return 0

        if x.score > y.score:
            return -1
        else:  #x < y
            return 1

if __name__ == "__main__":
    os.system("mkdir -p %s" % SCREENSHOT_DIR)
    app = Application()
    app.run()
