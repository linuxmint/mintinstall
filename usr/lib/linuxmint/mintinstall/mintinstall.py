#!/usr/bin/python2
# -*- coding: UTF-8 -*-

import Classes
import sys
import os
import commands
import gi
import gettext
import tempfile
import threading
import time
import apt
import urllib
import urllib2
import thread
import httplib
from urlparse import urlparse

from datetime import datetime
from subprocess import Popen, PIPE

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib

import aptdaemon.client
from aptdaemon.enums import *
from aptdaemon.gtk3widgets import AptErrorDialog, AptConfirmDialog, AptProgressDialog, AptStatusIcon
import aptdaemon.errors

HOME = os.path.expanduser("~")

ICON_SIZE = 48

# Don't let mintinstall run as root
if os.getuid() == 0:
    print "The software manager should not be run as root. Please run it in user mode."
    sys.exit(1)

gi.require_version("Gtk", "3.0")

from configobj import ConfigObj

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

architecture = commands.getoutput("uname -a")
if (architecture.find("x86_64") >= 0):
    import ctypes
    libc = ctypes.CDLL('libc.so.6')
    libc.prctl(15, 'mintinstall', 0, 0, 0)
else:
    import dl
    if os.path.exists('/lib/libc.so.6'):
        libc = dl.open('/lib/libc.so.6')
        libc.call('prctl', 15, 'mintinstall', 0, 0, 0)
    elif os.path.exists('/lib/i386-linux-gnu/libc.so.6'):
        libc = dl.open('/lib/i386-linux-gnu/libc.so.6')
        libc.call('prctl', 15, 'mintinstall', 0, 0, 0)

# Gdk.threads_init()

CACHE_DIR = os.path.expanduser("~/.cache/mintinstall")
SCREENSHOT_DIR = os.path.join(CACHE_DIR, "screenshots")
REVIEWS_PATH = os.path.join(CACHE_DIR, "reviews.list")

# List of packages which are either broken or do not install properly in mintinstall
BROKEN_PACKAGES = ['pepperflashplugin-nonfree']

# List of aliases
ALIASES = {}
ALIASES['spotify-client'] = "spotify"
ALIASES['steam-launcher'] = "steam"
ALIASES['minecraft-installer'] = "minecraft"
ALIASES['virtualbox-qt'] = "virtualbox " # Added a space to force alias
ALIASES['virtualbox'] = "virtualbox (base)"
ALIASES['sublime-text'] = "sublime"
ALIASES['mint-meta-codecs'] = "Multimedia Codecs"
ALIASES['mint-meta-codecs-kde'] = "Multimedia Codecs for KDE"
ALIASES['mint-meta-debian-codecs'] = "Multimedia Codecs"

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
                if self.application.current_package.name == self.pkg_name:
                    self.add_screenshot(link, thumb, num_screenshots)
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
                    self.add_screenshot(link, thumb, num_screenshots)
        except Exception, detail:
            print detail

    def add_screenshot(self, link, thumb, number):
        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkg_name, number))
        local_thumb = os.path.join(SCREENSHOT_DIR, "thumb_%s_%s.png" % (self.pkg_name, number))
        if self.application.current_package.name == self.pkg_name:
            if not os.path.exists(local_name):
                urllib.urlretrieve (link, local_name)
            if not os.path.exists(local_thumb):
                urllib.urlretrieve (thumb, local_thumb)
        if self.application.current_package.name == self.pkg_name:
            if (number == 1):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, -1, 350)
                self.application.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)
            else:
                if (number == 2):
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % self.pkg_name), 100, -1)
                    event_box = Gtk.EventBox()
                    image = Gtk.Image.new_from_pixbuf(pixbuf)
                    event_box.add(image)
                    event_box.connect("button-release-event", self.on_screenshot_clicked, image, os.path.join(SCREENSHOT_DIR, "thumb_%s_1.png" % self.pkg_name), os.path.join(SCREENSHOT_DIR, "%s_1.png" % self.pkg_name))
                    self.application.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                    event_box.show_all()
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_thumb, 100, -1)
                event_box = Gtk.EventBox()
                image = Gtk.Image.new_from_pixbuf(pixbuf)
                event_box.add(image)
                event_box.connect("button-release-event", self.on_screenshot_clicked, image, local_thumb, local_name)
                self.application.builder.get_object("box_more_screenshots").pack_start(event_box, False, False, 0)
                event_box.show_all()

    def on_screenshot_clicked(self, eventbox, event, image, local_thumb, local_name):
        # Set main screenshot
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(local_name, -1, 350)
        self.application.builder.get_object("main_screenshot").set_from_pixbuf(pixbuf)

class PackageTile(Gtk.Button):

    def __init__(self, package, icon, summary):
        self.package = package
        super(Gtk.Button, self).__init__()

        label_name = Gtk.Label(xalign=0)
        label_name.set_markup("<b>%s</b>" % package.name)
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
            installed_mark = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/linuxmint/mintinstall/data/emblem-installed.png", 15, 15)
            installed_mark = Gtk.Image.new_from_pixbuf(installed_mark)
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
        label_name.set_markup("<b>%s</b>" % package.name)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_border_width(6)

        vbox.pack_start(icon, False, False, 0)

        name_box = Gtk.Box()
        name_box.pack_start(label_name, True, True, 0)
        if package.pkg.is_installed:
            installed_mark = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/linuxmint/mintinstall/data/emblem-installed.png", 15, 15)
            installed_mark = Gtk.Image.new_from_pixbuf(installed_mark)
            name_box.pack_start(installed_mark, False, False, 3)

        vbox.pack_start(name_box, True, True, 0)

        self.add(vbox)

class ReviewTile(Gtk.Box):
    def __init__(self, username, date, comment, rating):
        super(Gtk.Box, self).__init__()

        box_stars = Gtk.Box()
        for i in range(rating):
            box_stars.pack_start(Gtk.Image.new_from_icon_name("starred", Gtk.IconSize.MENU), False, False, 0)
        for i in range(5-rating):
            box_stars.pack_start(Gtk.Image.new_from_icon_name("non-starred", Gtk.IconSize.MENU), False, False, 0)

        label_comment = Gtk.Label(xalign=0.0)
        label_comment.set_label(comment)

        label_name = Gtk.Label(xalign=0.0)
        label_name.set_markup("<small>%s (%s)</small>" % (username, date))

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_border_width(6)
        vbox.pack_start(label_comment, False, False, 0)
        vbox.pack_start(label_name, False, False, 0)

        hbox = Gtk.Box()
        hbox.pack_start(box_stars, True, True, 0)
        hbox.pack_start(vbox, True, True, 0)

        self.add(hbox)

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
    __slots__ = 'name', 'pkg', 'reviews', 'categories', 'score', 'avg_rating', 'num_reviews', '_candidate', 'candidate', '_summary', 'summary' #To remove __dict__ memory overhead

    def __init__(self, name, pkg):
        self.name = name
        self.pkg = pkg
        self.reviews = []
        self.categories = []
        self.score = 0
        self.avg_rating = 0
        self.num_reviews = 0

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
        if self.application.current_package.name == self.package.name:
            self.application.builder.get_object("notebook_progress").set_current_page(1)
            self.application.builder.get_object("application_progress").set_fraction(progress / 100.0)

        print(progress)

    def on_transaction_finish(self, transaction, exit_state):
        if (exit_state == aptdaemon.enums.EXIT_SUCCESS):
            name = self.package.name
            self.application.cache = apt.Cache() # reread cache
            self.package.pkg = self.application.cache[name] # update package
            if self.application.current_package.name == name:
                self.application.builder.get_object("notebook_progress").set_current_page(0)
                self.application.builder.get_object("application_progress").set_fraction(0 / 100.0)
                self.application.show_package(self.application.current_package, self.application.previous_page)

class CategoryListBoxRow(Gtk.ListBoxRow):
    def __init__(self, category):
        super(Gtk.ListBoxRow, self).__init__()
        self.category = category
        label = Gtk.Label(category.name, xalign=0, margin=10)
        self.add(label)

class Application():

    PAGE_LANDING = 0
    PAGE_LIST = 1
    PAGE_PACKAGE = 2

    FONT = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"

    @print_timing
    def load_cache(self):
        self.cache = apt.Cache()

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

        self.prefs = self.read_configuration()

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
        prefs_menuitem = Gtk.ImageMenuItem.new_with_label(_("Preferences"))
        image = Gtk.Image.new_from_icon_name("preferences-other-symbolic", Gtk.IconSize.MENU)
        prefs_menuitem.set_image(image)
        prefs_menu = Gtk.Menu()
        prefs_menuitem.set_submenu(prefs_menu)

        search_summary_menuitem = Gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
        search_summary_menuitem.set_active(self.prefs["search_in_summary"])
        search_summary_menuitem.connect("toggled", self.set_search_filter, "search_in_summary")

        search_description_menuitem = Gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
        search_description_menuitem.set_active(self.prefs["search_in_description"])
        search_description_menuitem.connect("toggled", self.set_search_filter, "search_in_description")

        prefs_menu.append(search_summary_menuitem)
        prefs_menu.append(search_description_menuitem)

        edit_submenu.append(prefs_menuitem)

        if os.path.exists("/usr/bin/software-sources") or os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
            sources_menuitem = Gtk.ImageMenuItem(Gtk.STOCK_PREFERENCES)
            sources_menuitem.set_image(Gtk.Image.new_from_icon_name("software-properties", Gtk.IconSize.MENU))
            sources_menuitem.get_child().set_text(_("Software sources"))
            sources_menuitem.connect("activate", self.open_repositories)
            edit_submenu.append(sources_menuitem)

        view_menu = Gtk.MenuItem(_("_View"))
        view_menu.set_use_underline(True)
        view_submenu = Gtk.Menu()
        view_menu.set_submenu(view_submenu)

        available_packages_menuitem = Gtk.CheckMenuItem(_("Available packages"))
        available_packages_menuitem.set_active(self.prefs["available_packages_visible"])
        available_packages_menuitem.connect("toggled", self.set_filter, "available_packages_visible")

        installed_packages_menuitem = Gtk.CheckMenuItem(_("Installed packages"))
        installed_packages_menuitem.set_active(self.prefs["installed_packages_visible"])
        installed_packages_menuitem.connect("toggled", self.set_filter, "installed_packages_visible")

        view_submenu.append(available_packages_menuitem)
        view_submenu.append(installed_packages_menuitem)

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
        self.builder.get_object("menubar1").append(view_menu)
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

        self.load_picks_on_landing()
        self.load_categories_on_landing()

        self.searchentry.grab_focus()

        self.builder.get_object("main_window").show_all()

        self.listbox_categories = Gtk.ListBox()
        self.builder.get_object("box_subcategories").pack_start(self.listbox_categories, False, False, 0)
        self.listbox_categories.connect('row-activated', self.on_row_activated)

        self.builder.get_object("website_button").connect("clicked", self.on_website_button_clicked)
        self.builder.get_object("action_button").connect("clicked", self.on_action_button_clicked)

    def on_transaction_progress(self, transaction, progress):
        self.status_label.set_text(transaction.status)
        self.progressbar.set_fraction(progress / 100.0)

    def on_transaction_finish(self, transaction, exit_state):
        self.status_label.set_text()
        self.progressbar.hide()

    def _run_transaction(self, transaction):
        self.transactions[self.current_package.name] = MetaTransaction(self, transaction)
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

    def on_website_button_clicked(self, button):
        if self.current_package is not None:
            if self.current_package.pkg.is_installed:
                homepage = self.current_package.pkg.installed.homepage
            else:
                homepage = self.current_package.pkg.candidate.homepage
            os.system("xdg-open %s" % homepage)

    def load_picks_on_landing(self):
        box = self.builder.get_object("box_picks")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(6)
        flowbox.set_max_children_per_line(6)
        flowbox.set_row_spacing(12)
        flowbox.set_column_spacing(12)
        flowbox.set_homogeneous(True)
        featured = 0
        for package in self.featured_category.packages:
            if not package.pkg.is_installed:
                icon = self.get_application_icon(package, ICON_SIZE)
                icon = Gtk.Image.new_from_pixbuf(icon)
                tile = VerticalPackageTile(package, icon)
                tile.connect("clicked", self.on_package_tile_clicked, self.PAGE_LANDING)
                flowbox.insert(tile, -1)
                featured = featured + 1
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
        box.pack_start(flowbox, True, True, 0)

    def category_button_clicked(self, button, category):
        self.show_category(category)

    def on_search_entry_activated(self, searchentry):
        terms = searchentry.get_text()
        if terms != "":
            self.show_search_results(terms)

    def on_search_terms_changed(self, entry):
        terms = entry.get_text()
        print(terms)
        if terms != "" and len(terms) >= 3:
            self.show_search_results(terms)

    def set_filter(self, checkmenuitem, configName):
        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        if (config.has_key('filter')):
            config['filter'][configName] = checkmenuitem.get_active()
        else:
            config['filter'] = {}
            config['filter'][configName] = checkmenuitem.get_active()
        config.write()
        self.prefs = self.read_configuration()
        if self.model_filter is not None:
            self.model_filter.refilter()

    def set_search_filter(self, checkmenuitem, configName):
        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        if (config.has_key('search')):
            config['search'][configName] = checkmenuitem.get_active()
        else:
            config['search'] = {}
            config['search'][configName] = checkmenuitem.get_active()
        config.write()
        self.prefs = self.read_configuration()
        if (self.searchentry.get_text() != ""):
            self.show_search_results(self.searchentry.get_text())

    def read_configuration(self):

        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        prefs = {}

        #Read filter info
        try:
            prefs["available_packages_visible"] = (config['filter']['available_packages_visible'] == "True")
        except:
            prefs["available_packages_visible"] = True
        try:
            prefs["installed_packages_visible"] = (config['filter']['installed_packages_visible'] == "True")
        except:
            prefs["installed_packages_visible"] = True

        #Read search info
        try:
            prefs["search_in_summary"] = (config['search']['search_in_summary'] == "True")
        except:
            prefs["search_in_summary"] = True
        try:
            prefs["search_in_description"] = (config['search']['search_in_description'] == "True")
        except:
            prefs["search_in_description"] = False

        return prefs

    def open_repositories(self, widget):
        if os.path.exists("/usr/bin/software-sources"):
            os.system("/usr/bin/software-sources")
        elif os.path.exists("/usr/bin/software-properties-gtk"):
            os.system("/usr/bin/software-properties-gtk")
        elif os.path.exists("/usr/bin/software-properties-kde"):
            os.system("/usr/bin/software-properties-kde")
        self.close_application(None, None, 9) # Status code 9 means we want to restart ourselves

    def close_window(self, widget, window):
        window.hide()

    def open_about(self, widget):
        dlg = Gtk.AboutDialog()
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
        dlg.set_logo(GdkPixbuf.Pixbuf.new_from_file("/usr/share/pixmaps/mintinstall.svg"))

        def close(w, res):
            if res == Gtk.ResponseType.CANCEL:
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
            summary = summary.capitalize()
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

            description = description.capitalize()
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

    def close_application(self, window, event=None, exit_code=0):
        self.do_close_application(exit_code)

    def do_close_application(self, exit_code):
        if exit_code == 0:
            # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
            pid = os.getpid()
            os.system("kill -9 %s &" % pid)
        else:
            #Gtk.main_quit()
            self.loop.quit()
            sys.exit(exit_code)

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

    @print_timing
    def add_categories(self):
        self.categories = []
        self.sections = {}
        self.root_categories = {}

        self.featured_category = Category(_("Featured"), None, self.categories)
        edition = ""
        try:
            with open("/etc/linuxmint/info") as f:
                config = dict([line.strip().split("=") for line in f])
                edition = config['EDITION']
        except:
            pass
        if "KDE" in edition:
            self.featured_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/featured-kde.list")
        else:
            self.featured_category.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/featured.list")

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
        subcat = Category(_("First-person shooters"), category, self.categories)
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
        self.sections["java"] = category
        self.sections["php"] = category
        self.sections["python"] = category
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
            if name.endswith(":i386"):
                continue
            if name.endswith("-perl"):
                continue

            pkg = self.cache[name]
            package = Package(name, pkg)
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
                    if last_package != None and last_package.name == elements[0]:
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
                    if last_package != None and last_package.name == elements[0]:
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

    def get_simple_name(self, package_name):
        package_name = package_name.split(":")[0]
        if package_name in ALIASES and ALIASES[package_name] not in self.packages_dict:
            package_name = ALIASES[package_name]
        return package_name.capitalize()

    def on_back_button_clicked(self, button):
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
        if len(category.subcategories) > 0:
            theme = Gtk.IconTheme.get_default()
            for cat in category.subcategories:
                row = CategoryListBoxRow(cat)
                self.listbox_categories.add(row)
                self.listbox_categories.show_all()

    def on_row_activated(self, listbox, row):
        self.show_category(row.category)

    def get_application_icon(self, package, size):
        icon_path = None

        theme = Gtk.IconTheme.get_default()
        for name in [package.name.split(":")[0], package.name.split("-")[0]]:
            if theme.has_icon(name):
                iconInfo = theme.lookup_icon(name, size, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    return GdkPixbuf.Pixbuf.new_from_file_at_size(iconInfo.get_filename(), size, size)

        # Try app-install icons then
        icon_path = "/usr/share/app-install/icons/%s" % package.name
        for extension in ['svg', 'png', 'xpm']:
            icon_path = "/usr/share/app-install/icons/%s.%s" % (package.name, extension)
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

        for package in self.packages:
            visible = False
            if termsUpper in package.name.upper():
                visible = True
            else:
                if (package.candidate is not None):
                    if (self.prefs["search_in_summary"] and termsUpper in package.summary.upper()):
                        visible = True
                    elif(self.prefs["search_in_description"] and termsUpper in package.candidate.description.upper()):
                        visible = True

            if visible:
                self._searched_packages.append(package)

        self.clear_category_list()
        self.show_packages(self._searched_packages)

    def visible_func(self, model, iter, data):
        package = model.get_value(iter, 3)
        if package is not None:
            if package.pkg is not None:
                if (package.pkg.is_installed and self.prefs["installed_packages_visible"] == True):
                    return True
                elif (package.pkg.is_installed == False and self.prefs["available_packages_visible"] == True):
                    return True
        return False

    def on_package_tile_clicked(self, tile, previous_page):
        self.show_package(tile.package, previous_page)

    def show_packages(self, packages):
        for child in self.flowbox_applications.get_children():
            self.flowbox_applications.remove(child)

        packages.sort(self.package_compare)
        packages = packages[0:200]

        self.builder.get_object("notebook_progress").set_current_page(0)

        for package in packages:

            if ":" in package.name and package.name.split(":")[0] in self.packages_dict:
                # don't list arch packages when the root is represented in the cache
                continue

            if ":" in package.name and package.name.split(":")[0] in self.packages_dict:
                # don't list arch packages when the root is represented in the cache
                continue

            package_name = self.get_simple_name(package.name)

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

        self.builder.get_object("main_screenshot").set_from_file("/usr/share/linuxmint/mintinstall/data/no-screenshot.png")
        box_more_screenshots = self.builder.get_object("box_more_screenshots")
        for child in box_more_screenshots.get_children():
            box_more_screenshots.remove(child)

        # Load package info
        score = 0
        appname = self.get_simple_name(package.name)

        description = package.pkg.candidate.description
        summary = package.summary.capitalize()

        impacted_packages = []
        self.removals = []
        self.installations = []

        pkg = self.cache[package.name]
        try:
            if package.pkg.is_installed:
                pkg.mark_delete(True, True)
            else:
                pkg.mark_install()
        except:
            if pkg.name not in BROKEN_PACKAGES:
                BROKEN_PACKAGES.append(pkg.name)

        changes = self.cache.get_changes()
        for pkg in changes:
            print(pkg.name)
            if pkg.name == package.name:
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

        action_button = self.builder.get_object("action_button")

        if package.pkg.is_installed:
            action_button_label = _("Remove")
            version = package.pkg.installed.version
            homepage = package.pkg.installed.homepage
            action_button_description = _("Installed")
            iconstatus = "/usr/share/linuxmint/mintinstall/data/installed.png"
            action_button.set_sensitive(True)
        else:
            if package.pkg.name in BROKEN_PACKAGES:
                action_button_label = _("Not available")
                action_button_description = _("Please use apt-get to install this package.")
                action_button.set_sensitive(False)
            else:
                action_button_label = _("Install")
                action_button_description = _("Not installed")
                action_button.set_sensitive(True)
            version = package.pkg.candidate.version
            iconstatus = "/usr/share/linuxmint/mintinstall/data/available.png"
            homepage = package.pkg.candidate.homepage

        action_button.set_label(action_button_label)
        action_button.set_tooltip_text(action_button_description)


        self.builder.get_object("application_version").set_label(version)

        self.builder.get_object("application_num_reviews").set_label(str(package.num_reviews))
        self.builder.get_object("application_avg_rating").set_label(str(package.avg_rating))

        box_reviews = self.builder.get_object("box_reviews")
        for child in box_reviews.get_children():
            box_reviews.remove(child)

        reviews = package.reviews
        reviews.sort(key=lambda x: x.date, reverse=True)
        i = 0
        for review in reviews:
            comment = review.comment.strip()
            comment = comment.replace("'", "\'")
            comment = comment.replace('"', '\"')
            comment = comment.capitalize()
            comment = unicode(comment, 'UTF-8', 'replace')
            review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
            tile = ReviewTile(review.username, review_date, comment, review.rating)
            box_reviews.pack_start(tile, False, False, 0)
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
        self.builder.get_object("application_name").set_label(appname)
        self.builder.get_object("application_summary").set_label(summary)
        self.builder.get_object("application_description").set_label(description)

        if homepage is not None and homepage != "":
            self.builder.get_object("website_button").show()
        else:
            self.builder.get_object("website_button").hide()

        downloadScreenshots = ScreenshotDownloader(self, package.name)
        downloadScreenshots.start()

    def package_compare(self, x, y):
        if x.score == y.score:
            if x.name < y.name:
                return -1
            elif x.name > y.name:
                return 1
            else:
                return 0

        if x.score > y.score:
            return -1
        else:  #x < y
            return 1

if __name__ == "__main__":
    os.system("mkdir -p %s" % SCREENSHOT_DIR)
    model = Classes.Model()
    app = Application()
    app.run()
    # Gdk.threads_enter()
    # Gtk.main()
    # Gdk.threads_leave()
