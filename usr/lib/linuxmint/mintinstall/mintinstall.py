#!/usr/bin/python2
# -*- coding: UTF-8 -*-

import Classes
import sys
import os
import commands
import gi
import thread
import gettext
import tempfile
import threading
import string
import Image
import StringIO
import ImageFont
import ImageDraw
import ImageOps
import time
import apt
import urllib
import urllib2
import thread
import dbus
import httplib
from urlparse import urlparse

from AptClient.AptClient import AptClient

from datetime import datetime
from subprocess import Popen, PIPE
import base64

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, GObject, GLib

HOME = os.path.expanduser("~")

ICON_SIZE = 48

# Don't let mintinstall run as root
#~ if os.getuid() == 0:
    #~ print "The software manager should not be run as root. Please run it in user mode."
    #~ sys.exit(1)
if os.getuid() != 0:
    print "The software manager should be run as root."
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

Gdk.threads_init()

COMMERCIAL_APPS = ["chromium-browser", "chromium-browser-l10n", "chromium-codecs-ffmpeg",
                   "chromium-codecs-ffmpeg-extra", "chromium-codecs-ffmpeg-extra",
                   "chromium-browser-dbg", "chromium-chromedriver", "chromium-chromedriver-dbg"]

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

def get_dbus_bus():
    bus = dbus.SystemBus()
    return bus


def convertImageToGtkPixbuf(image):
    buf = StringIO.StringIO()
    image.save(buf, format="PNG")
    bufString = buf.getvalue()
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(bufString)
    pixbuf = loader.get_pixbuf()
    loader.close()
    buf.close()
    return pixbuf

class DownloadReviews(threading.Thread):

    def __init__(self, application):
        threading.Thread.__init__(self)
        self.application = application

    def run(self):
        try:
            reviews_dir = HOME + "/.linuxmint/mintinstall"
            os.system("mkdir -p " + reviews_dir)
            reviews_path = reviews_dir + "/reviews.list"
            reviews_path_tmp = reviews_path + ".tmp"
            url = urllib.urlretrieve("http://community.linuxmint.com/data/reviews.list", reviews_path_tmp)
            numlines = 0
            numlines_new = 0
            if os.path.exists(reviews_path):
                numlines = int(commands.getoutput("cat " + reviews_path + " | wc -l"))
            if os.path.exists(reviews_path_tmp):
                numlines_new = int(commands.getoutput("cat " + reviews_path_tmp + " | wc -l"))
            if numlines_new > numlines:
                os.system("mv " + reviews_path_tmp + " " + reviews_path)
                print "Overwriting reviews file in " + reviews_path
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
                self.application.screenshots.append('addScreenshot("%s", "%s")' % (link, thumb))
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
                    thumb = "http://screenshots.debian.net%s" % image['src']
                    link = thumb.replace("_small", "_large")
                    num_screenshots += 1
                    self.application.screenshots.append('addScreenshot("%s", "%s")' % (link, thumb))
        except Exception, detail:
            print detail

        # try:
        #     GObject.idle_add(self.application.show_screenshots, self.pkg_name)
        # except Exception, detail:
        #     print detail


class APTProgressHandler(threading.Thread):

    def __init__(self, application, packages, apt_client, builder):
        threading.Thread.__init__(self)
        self.application = application
        self.apt_client = apt_client
        self.builder = builder
        self.status_label = self.builder.get_object("label_ongoing")
        self.progressbar = self.builder.get_object("progressbar1")
        self.tree_transactions = self.builder.get_object("tree_transactions")
        self.packages = packages
        self.model = Gtk.TreeStore(str, str, str, float, object)
        self.tree_transactions.set_model(self.model)
        self.tree_transactions.connect("button-release-event", self.menuPopup)

        self.apt_client.connect("progress", self._on_apt_client_progress)
        self.apt_client.connect("task_ended", self._on_apt_client_task_ended)

    def _on_apt_client_progress(self, *args):
        self._update_display()

    def _on_apt_client_task_ended(self, aptClient, task_id, task_type, params, success, error):
        self._update_display()

        if error:
            if task_type == "install":
                title = _("The package '%s' could not be installed") % str(params["package_name"])
            elif task_type == "remove":
                title = _("The package '%s' could not be removed") % str(params["package_name"])
            else:
                # Fail silently for other task types (update, wait)
                return

            # By default assume there's a problem with the Internet connection
            text = str(error)

            # Check to see if no other APT process is running
            p1 = Popen(['ps', '-U', 'root', '-o', 'comm'], stdout=PIPE)
            p = p1.communicate()[0]
            running = None
            pslist = p.split('\n')
            for process in pslist:
                process_name = process.strip()
                if process_name in ["apt-get", "aptitude", "synaptic", "update-manager", "adept", "adept-notifier", "checkAPT.py"]:
                    running = process_name
                    text = "%s\n\n    <b>%s</b>" % (_("Another application is using APT:"), process_name)
                    break

            self.application.show_dialog_modal(title=title,
                                               text=text,
                                               type=Gtk.MessageType.ERROR,
                                               buttons=Gtk.ButtonsType.OK)

    def _update_display(self):
        progress_info = self.apt_client.get_progress_info()
        task_ids = []
        for task in progress_info["tasks"]:
            task_is_new = True
            task_ids.append(task["task_id"])
            iter = self.model.get_iter_first()
            while iter is not None:
                if self.model.get_value(iter, 4)["task_id"] == task["task_id"]:
                    self.model.set_value(iter, 1, self.get_status_description(task))
                    self.model.set_value(iter, 2, "%d %%" % task["progress"])
                    self.model.set_value(iter, 3, task["progress"])
                    task_is_new = False
                iter = self.model.iter_next(iter)
            if task_is_new:
                iter = self.model.insert_before(None, None)
                self.model.set_value(iter, 0, self.get_role_description(task))
                self.model.set_value(iter, 1, self.get_status_description(task))
                self.model.set_value(iter, 2, "%d %%" % task["progress"])
                self.model.set_value(iter, 3, task["progress"])
                self.model.set_value(iter, 4, task)
        iter = self.model.get_iter_first()
        while iter is not None:
            if self.model.get_value(iter, 4)["task_id"] not in task_ids:
                task = self.model.get_value(iter, 4)
                iter_to_be_removed = iter
                iter = self.model.iter_next(iter)
                self.model.remove(iter_to_be_removed)
                if task["role"] in ["install", "remove"]:
                    pkg_name = task["task_params"]["package_name"]
                    cache = apt.Cache()
                    new_pkg = cache[pkg_name]
                    # Update packages
                    for package in self.packages:
                        if package.pkg.name == pkg_name:
                            package.pkg = new_pkg
                            # If the user is currently viewing this package in the browser,
                            # refresh the view to show that the package has been installed or uninstalled.
                            #if self.application.back_button.get_active().get_label() == pkg_name:
                            #    self.application.show_package(package)

                    # Update apps tree
                    tree_applications = self.self.builder.get_object("tree_applications")
                    if tree_applications:
                        model_apps = tree_applications.get_model()
                        if isinstance(model_apps, Gtk.TreeModelFilter):
                            model_apps = model_apps.get_model()

                        if model_apps is not None:
                            iter_apps = model_apps.get_iter_first()
                            while iter_apps is not None:
                                package = model_apps.get_value(iter_apps, 3)
                                if package.pkg.name == pkg_name:
                                    model_apps.set_value(iter_apps, 0, self.application.get_package_pixbuf_icon(package))
                                iter_apps = model_apps.iter_next(iter_apps)
            else:
                iter = self.model.iter_next(iter)
        if progress_info["nb_tasks"] > 0:
            fraction = progress_info["progress"]
            progress = str(int(fraction)) + '%'
        else:
            fraction = 0
            progress = ""
        self.status_label.set_text(_("%d ongoing actions") % progress_info["nb_tasks"])
        self.progressbar.set_text(progress)
        self.progressbar.set_fraction(fraction / 100.)

    def menuPopup(self, widget, event):
        if event.button == 3:
            model, iter = self.tree_transactions.get_selection().get_selected()
            if iter is not None:
                task = model.get_value(iter, 4)
                menu = Gtk.Menu()
                cancelMenuItem = Gtk.MenuItem(_("Cancel the task: %s") % model.get_value(iter, 0))
                cancelMenuItem.set_sensitive(task["cancellable"])
                menu.append(cancelMenuItem)
                menu.show_all()
                cancelMenuItem.connect("activate", self.cancelTask, task)
                menu.popup(None, None, None, event.button, event.time)

    def cancelTask(self, menu, task):
        self.apt_client.cancel_task(task["task_id"])
        self._update_display()

    def get_status_description(self, transaction):
        descriptions = {"waiting": _("Waiting"), "downloading": _("Downloading"), "running": _("Running"), "finished": _("Finished")}
        if "status" in transaction:
            if transaction["status"] in descriptions.keys():
                return descriptions[transaction["status"]]
            else:
                return transaction["status"]
        else:
            return ""

    def get_role_description(self, transaction):
        if "role" in transaction:
            if transaction["role"] == "install":
                return _("Installing %s") % transaction["task_params"]["package_name"]
            elif transaction["role"] == "remove":
                return _("Removing %s") % transaction["task_params"]["package_name"]
            elif transaction["role"] == "update_cache":
                return _("Updating cache")
            else:
                return _("No role set")
        else:
            return _("No role set")

class PackageTile(Gtk.Button):

    def __init__(self, package, icon, summary):
        self.package = package
        super(Gtk.Button, self).__init__()

        label_name = Gtk.Label(xalign=0)
        label_name.set_markup("<b>%s</b>" % package.name)
        label_name.set_justify(Gtk.Justification.LEFT)
        label_summary = Gtk.Label(xalign=0)
        label_summary.set_markup("<small>%s</small>" % summary)
        label_summary.set_alignment
        label_summary.set_justify(Gtk.Justification.LEFT)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        name_box = Gtk.Box()
        name_box.pack_start(label_name, False, False, 3)
        if package.pkg.is_installed:
            installed_mark = GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/share/linuxmint/mintinstall/data/emblem-installed.png", 15, 15)
            installed_mark = Gtk.Image.new_from_pixbuf(installed_mark)
            name_box.pack_start(installed_mark, False, False, 3)

        vbox.pack_start(name_box, True, True, 3)
        vbox.pack_start(label_summary, True, True, 3)

        hbox = Gtk.Box()
        hbox.pack_start(icon, False, False, 3)
        hbox.pack_start(vbox, True, True, 3)

        self.add(hbox)

class Category:

    def __init__(self, name, icon, sections, parent, categories):
        self.name = name
        self.icon = icon
        self.parent = parent
        self.subcategories = []
        self.packages = []
        self.sections = sections
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
            self.avg_rating = int(round(sum_rating / self.num_reviews))
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
    PAGE_TRANSACTIONS = 3

    FONT = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"

    @print_timing
    def __init__(self):
        self.packageLabel = Gtk.Label()

        self.add_categories()
        self.build_matched_packages()
        self.add_packages()

        self.screenshots = []

        # Build the GUI
        glade_file = "/usr/share/linuxmint/mintinstall/mintinstall.glade"

        self.builder = Gtk.Builder()
        self.builder.add_from_file(glade_file)
        self.main_window = self.builder.get_object("main_window")
        self.main_window.set_title(_("Software Manager"))
        self.main_window.set_icon_name("mintinstall")
        self.main_window.connect("delete_event", self.close_application)

        self.apt_client = AptClient()
        self.apt_progress_handler = APTProgressHandler(self, self.packages, self.apt_client, self.builder)

        self.add_reviews()
        downloadReviews = DownloadReviews(self)
        downloadReviews.start()

        if len(sys.argv) > 1 and sys.argv[1] == "list":
            # Print packages and their categories and exit
            self.export_listing()
            sys.exit(0)

        self.prefs = self.read_configuration()

        # Build the menu
        fileMenu = Gtk.MenuItem(_("_File"))
        fileSubmenu = Gtk.Menu()
        fileMenu.set_submenu(fileSubmenu)
        closeMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_CLOSE)
        closeMenuItem.get_child().set_text(_("Close"))
        closeMenuItem.connect("activate", self.close_application)
        fileSubmenu.append(closeMenuItem)

        editMenu = Gtk.MenuItem(_("_Edit"))
        editSubmenu = Gtk.Menu()
        editMenu.set_submenu(editSubmenu)
        prefsMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_PREFERENCES)
        prefsMenuItem.get_child().set_text(_("Preferences"))
        prefsMenu = Gtk.Menu()
        prefsMenuItem.set_submenu(prefsMenu)

        searchInSummaryMenuItem = Gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
        searchInSummaryMenuItem.set_active(self.prefs["search_in_summary"])
        searchInSummaryMenuItem.connect("toggled", self.set_search_filter, "search_in_summary")

        searchInDescriptionMenuItem = Gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
        searchInDescriptionMenuItem.set_active(self.prefs["search_in_description"])
        searchInDescriptionMenuItem.connect("toggled", self.set_search_filter, "search_in_description")

        openLinkExternalMenuItem = Gtk.CheckMenuItem(_("Open links using the web browser"))
        openLinkExternalMenuItem.set_active(self.prefs["external_browser"])
        openLinkExternalMenuItem.connect("toggled", self.set_external_browser)

        searchWhileTypingMenuItem = Gtk.CheckMenuItem(_("Search while typing"))
        searchWhileTypingMenuItem.set_active(self.prefs["search_while_typing"])
        searchWhileTypingMenuItem.connect("toggled", self.set_search_filter, "search_while_typing")

        prefsMenu.append(searchInSummaryMenuItem)
        prefsMenu.append(searchInDescriptionMenuItem)
        # prefsMenu.append(openLinkExternalMenuItem)
        prefsMenu.append(searchWhileTypingMenuItem)

        #prefsMenuItem.connect("activate", open_preferences, treeview_update, statusIcon, wTree)
        editSubmenu.append(prefsMenuItem)

        accountMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_PREFERENCES)
        accountMenuItem.get_child().set_text(_("Account information"))
        accountMenuItem.connect("activate", self.open_account_info)
        editSubmenu.append(accountMenuItem)

        if os.path.exists("/usr/bin/software-sources") or os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
            sourcesMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_PREFERENCES)
            sourcesMenuItem.set_image(Gtk.Image.new_from_icon_name("software-properties", Gtk.IconSize.MENU))
            sourcesMenuItem.get_child().set_text(_("Software sources"))
            sourcesMenuItem.connect("activate", self.open_repositories)
            editSubmenu.append(sourcesMenuItem)

        viewMenu = Gtk.MenuItem(_("_View"))
        viewSubmenu = Gtk.Menu()
        viewMenu.set_submenu(viewSubmenu)

        availablePackagesMenuItem = Gtk.CheckMenuItem(_("Available packages"))
        availablePackagesMenuItem.set_active(self.prefs["available_packages_visible"])
        availablePackagesMenuItem.connect("toggled", self.set_filter, "available_packages_visible")

        installedPackagesMenuItem = Gtk.CheckMenuItem(_("Installed packages"))
        installedPackagesMenuItem.set_active(self.prefs["installed_packages_visible"])
        installedPackagesMenuItem.connect("toggled", self.set_filter, "installed_packages_visible")

        viewSubmenu.append(availablePackagesMenuItem)
        viewSubmenu.append(installedPackagesMenuItem)

        helpMenu = Gtk.MenuItem(_("_Help"))
        helpSubmenu = Gtk.Menu()
        helpMenu.set_submenu(helpSubmenu)
        aboutMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_ABOUT)
        aboutMenuItem.get_child().set_text(_("About"))
        aboutMenuItem.connect("activate", self.open_about)
        helpSubmenu.append(aboutMenuItem)

        #prevents multiple load finished handlers being hooked up to packageBrowser in show_package
        self.loadHandlerID = -1
        self.acthread = threading.Thread(target=self.cache_apt)
        self.acthread.start()

        #browser.connect("activate", browser_callback)
        #browser.show()
        self.builder.get_object("menubar1").append(fileMenu)
        self.builder.get_object("menubar1").append(editMenu)
        self.builder.get_object("menubar1").append(viewMenu)
        self.builder.get_object("menubar1").append(helpMenu)

        # Build the applications tables
        self.tree_transactions = self.builder.get_object("tree_transactions")

        self.flowbox_applications = Gtk.FlowBox()
        self.flowbox_applications.set_min_children_per_line(1)
        self.flowbox_applications.set_max_children_per_line(3)
        self.flowbox_applications.set_row_spacing(6)
        self.flowbox_applications.set_column_spacing(6)
        self.flowbox_applications.set_homogeneous(True)

        box = self.builder.get_object("scrolledwindow_applications")
        box.add(self.flowbox_applications)

        self.build_transactions_tree(self.tree_transactions)

        self.back_button = self.builder.get_object("back_button")
        self.back_button.connect("clicked", self.on_back_button_clicked)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(False)

        self.searchentry = self.builder.get_object("search_entry")
        self.searchentry.connect("changed", self.on_search_terms_changed)
        self.searchentry.connect("activate", self.on_search_entry_activated)

        self._search_in_category = self.root_category
        self._current_search_terms = ""

        self.notebook = self.builder.get_object("notebook1")

        sans26 = ImageFont.truetype(self.FONT, 26)
        sans10 = ImageFont.truetype(self.FONT, 12)

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

        self.builder.get_object("scrolled_details").add(self.packageLabel)

        self.builder.get_object("label_ongoing").set_text(_("No ongoing actions"))
        self.builder.get_object("label_transactions_header").set_text(_("Active tasks:"))
        self.builder.get_object("progressbar1").hide()

        self.builder.get_object("button_transactions").connect("clicked", self.show_transactions)

        self._load_more_timer = None

        self.searchentry.grab_focus()

        # self.builder.get_object("scrolled_search").get_vadjustment().connect("value-changed", self._on_search_applications_scrolled)
        self._load_more_search_timer = None
        self.initial_search_display = 200 #number of packages shown on first search
        self.scroll_search_display = 300 #number of packages added after scrolling

        self.builder.get_object("main_window").show_all()

        self.listbox_categories = Gtk.ListBox()
        self.builder.get_object("box_subcategories").pack_start(self.listbox_categories, False, False, 0)
        self.listbox_categories.connect('row-activated', self.on_row_activated)

    def load_picks_on_landing(self):
        box = self.builder.get_object("box_picks")
        flowbox = Gtk.FlowBox()
        flowbox.set_min_children_per_line(4)
        flowbox.set_max_children_per_line(4)
        flowbox.set_row_spacing(6)
        flowbox.set_column_spacing(6)
        flowbox.set_homogeneous(True)
        featured = 0
        for package in self.featured_category.packages:
            if not package.pkg.is_installed:
                icon = self.get_package_pixbuf_icon(package)
                icon = Gtk.Image.new_from_pixbuf(icon)
                tile = PackageTile(package, icon, package.summary)
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
        for cat in self.root_category.subcategories:
            button = Gtk.Button()
            button.set_label(cat.name)
            button.connect("clicked", self.category_button_clicked, cat)
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
        if terms != "" and self.prefs["search_while_typing"] and len(terms) >= 3:
            if terms != self._current_search_terms:
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

    def set_external_browser(self, checkmenuitem):
        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        config['external_browser'] = checkmenuitem.get_active()
        config.write()
        self.prefs = self.read_configuration()

    def read_configuration(self):

        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        prefs = {}

        #Read account info
        try:
            prefs["username"] = config['account']['username']
            prefs["password"] = config['account']['password']
        except:
            prefs["username"] = ""
            prefs["password"] = ""

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
        try:
            prefs["search_while_typing"] = (config['search']['search_while_typing'] == "True")
        except:
            prefs["search_while_typing"] = False

        #External browser
        try:
            prefs["external_browser"] = (config['external_browser'] == "True")
        except:
            prefs["external_browser"] = False

        return prefs

    def open_repositories(self, widget):
        if os.path.exists("/usr/bin/software-sources"):
            os.system("/usr/bin/software-sources")
        elif os.path.exists("/usr/bin/software-properties-gtk"):
            os.system("/usr/bin/software-properties-gtk")
        elif os.path.exists("/usr/bin/software-properties-kde"):
            os.system("/usr/bin/software-properties-kde")
        self.close_application(None, None, 9) # Status code 9 means we want to restart ourselves

    def open_account_info(self, widget):
        window = self.builder.get_object("window_account")
        window.set_title(_("Account information"))
        window.set_icon_name("mintinstall")
        self.builder.get_object("label111").set_label("<b>%s</b>" % _("Your community account"))
        self.builder.get_object("label111").set_use_markup(True)
        self.builder.get_object("label222").set_label("<i><small>%s</small></i>" % _("Fill in your account info to review applications"))
        self.builder.get_object("label222").set_use_markup(True)
        self.builder.get_object("label333").set_label(_("Username:"))
        self.builder.get_object("label444").set_label(_("Password:"))
        self.builder.get_object("entry_username").set_text(self.prefs["username"])
        self.builder.get_object("entry_password").set_text(base64.b64decode(self.prefs["password"]))
        self.builder.get_object("close_button").connect("clicked", self.close_window, self.builder.get_object("window_account"))
        self.builder.get_object("entry_username").connect("notify::text", self.update_account_info, "username")
        self.builder.get_object("entry_password").connect("notify::text", self.update_account_info, "password")
        window.show_all()

    def close_window(self, widget, window):
        window.hide()

    def update_account_info(self, entry, prop, configName):
        config = ConfigObj(HOME + "/.linuxmint/mintinstall.conf")
        if (not config.has_key('account')):
            config['account'] = {}

        if (configName == "password"):
            text = base64.b64encode(entry.props.text)
        else:
            text = entry.props.text

        config['account'][configName] = text
        config.write()
        self.prefs = self.read_configuration()

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

    def show_transactions(self, widget):
        self.notebook.set_current_page(self.PAGE_TRANSACTIONS)

    def close_window(self, widget, window, extra=None):
        try:
            window.hide_all()
        except:
            pass

    def build_application_tree(self, treeview):
        column0 = Gtk.TreeViewColumn(_("Icon"), Gtk.CellRendererPixbuf(), pixbuf=0)
        column0.set_sort_column_id(0)
        column0.set_resizable(True)

        column1 = Gtk.TreeViewColumn(_("Application"), Gtk.CellRendererText(), markup=1)
        column1.set_sort_column_id(1)
        column1.set_resizable(True)
        column1.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column1.set_min_width(350)
        column1.set_max_width(350)

        column2 = Gtk.TreeViewColumn(_("Score"), Gtk.CellRendererPixbuf(), pixbuf=2)
        column2.set_sort_column_id(2)
        column2.set_resizable(True)

        treeview.append_column(column0)
        treeview.append_column(column1)
        treeview.append_column(column2)
        treeview.set_headers_visible(False)
        treeview.connect("row-activated", self.show_selected)
        treeview.show()
        #treeview.connect("row_activated", self.show_more_info)

        selection = treeview.get_selection()
        selection.set_mode(Gtk.SelectionMode.BROWSE)

        #selection.connect("changed", self.show_selected)

    def build_transactions_tree(self, treeview):
        column0 = Gtk.TreeViewColumn(_("Task"), Gtk.CellRendererText(), text=0)
        column0.set_resizable(True)

        column1 = Gtk.TreeViewColumn(_("Status"), Gtk.CellRendererText(), text=1)
        column1.set_resizable(True)

        column2 = Gtk.TreeViewColumn(_("Progress"), Gtk.CellRendererProgress(), text=2, value=3)
        column2.set_resizable(True)

        treeview.append_column(column0)
        treeview.append_column(column1)
        treeview.append_column(column2)
        treeview.set_headers_visible(True)
        treeview.show()

    def show_selected(self, tree, path, column):
        #self.main_window.window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.WATCH))
        #self.main_window.set_sensitive(False)
        model = tree.get_model()
        iter = model.get_iter(path)

        #poll for end of apt caching when idle
        GLib.idle_add(self.show_package_if_apt_cached, model.get_value(iter, 3), tree)
        #cache apt in a separate thread as blocks gui update
        self.acthread.start()

    def show_package_if_apt_cached(self, pkg, tree):
        if (self.acthread.isAlive()):
            self.acthread.join()

        self.show_package(pkg)
        self.acthread = threading.Thread(target=self.cache_apt) #rebuild here for speed
        return False #false will remove this from gtk's list of idle functions
        #return True

    def cache_apt(self):
        self.cache = apt.Cache()

    def show_more_info(self, tree, path, column):
        model = tree.get_model()
        iter = model.get_iter(path)
        self.selected_package = model.get_value(iter, 3)

    def close_application(self, window, event=None, exit_code=0):
        self.apt_client.call_on_completion(lambda c: self.do_close_application(c), exit_code)
        window.hide()

    def do_close_application(self, exit_code):
        if exit_code == 0:
            # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
            pid = os.getpid()
            os.system("kill -9 %s &" % pid)
        else:
            Gtk.main_quit()
            sys.exit(exit_code)

    def on_button_clicked(self):
        package = self.current_package
        if package is not None:
            if package.pkg.is_installed:
                self.apt_client.remove_package(package.pkg.name)
            else:
                if package.pkg.name not in BROKEN_PACKAGES:
                    self.apt_client.install_package(package.pkg.name)

    def on_screenshot_clicked(self, url):
        package = self.current_package
        if package is not None:
            print("SHOW %s" % url)

    @print_timing
    def add_categories(self):
        self.categories = []
        self.root_category = Category(_("Categories"), "applications-other", None, None, self.categories)

        self.featured_category = Category(_("Featured"), "applications-featured", None, None, self.categories)
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

        internet = Category(_("Internet"), "applications-internet", None, self.root_category, self.categories)
        subcat = Category(_("Web"), "web-browser", ("web", "net"), internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-web.list")
        subcat = Category(_("Email"), "applications-mail", ("mail"), internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-email.list")
        subcat = Category(_("Chat"), "xchat", None, internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-chat.list")
        subcat = Category(_("File sharing"), "transmission", None, internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/internet-filesharing.list")

        cat = Category(_("Sound and video"), "applications-multimedia", ("multimedia", "video"), self.root_category, self.categories)
        cat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/sound-video.list")

        graphics = Category(_("Graphics"), "applications-graphics", ("graphics"), self.root_category, self.categories)
        graphics.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics.list")
        subcat = Category(_("3D"), "blender", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-3d.list")
        subcat = Category(_("Drawing"), "gimp", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-drawing.list")
        subcat = Category(_("Photography"), "shotwell", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-photography.list")
        subcat = Category(_("Publishing"), "scribus", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-publishing.list")
        subcat = Category(_("Scanning"), "flegita", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-scanning.list")
        subcat = Category(_("Viewers"), "gthumb", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/graphics-viewers.list")

        Category(_("Office"), "applications-office", ("office", "editors"), self.root_category, self.categories)

        games = Category(_("Games"), "applications-games", ("games"), self.root_category, self.categories)
        games.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games.list")
        subcat = Category(_("Board games"), "gnome-glchess", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-board.list")
        subcat = Category(_("First-person shooters"), "UrbanTerror", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-fps.list")
        subcat = Category(_("Real-time strategy"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-rts.list")
        subcat = Category(_("Turn-based strategy"), "wormux", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-tbs.list")
        subcat = Category(_("Emulators"), "wine", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-emulators.list")
        subcat = Category(_("Simulation and racing"), "torcs", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/games-simulations.list")

        Category(_("Accessories"), "applications-utilities", ("accessories", "utils"), self.root_category, self.categories)

        cat = Category(_("System tools"), "applications-system", ("system", "admin"), self.root_category, self.categories)
        cat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/system-tools.list")

        subcat = Category(_("Fonts"), "applications-fonts", ("fonts"), self.root_category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/fonts.list")

        subcat = Category(_("Science and Education"), "applications-science", ("science", "math", "education"), self.root_category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/share/linuxmint/mintinstall/categories/education.list")

        Category(_("Programming"), "applications-development", ("devel", "java"), self.root_category, self.categories)
        #self.category_other = Category(_("Other"), "applications-other", None, self.root_category, self.categories)

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
        cache = apt.Cache()

        for pkg in cache:
            package = Package(pkg.name, pkg)
            self.packages.append(package)
            self.packages_dict[pkg.name] = package

            # If the package is not a "matching package", find categories with matching sections
            if (pkg.name not in self.matchedPackages):
                section = pkg.section
                if "/" in section:
                    section = section.split("/")[1]
                for category in self.categories:
                    if category.sections is not None:
                        if section in category.sections:
                            self.add_package_to_category(package, category)

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
        reviews_path = HOME + "/.linuxmint/mintinstall/reviews.list"
        if not os.path.exists(reviews_path):
            # No reviews found, use the ones from the packages itself
            os.system("cp /usr/share/linuxmint/mintinstall/reviews.list %s" % reviews_path)
            print "First run detected, initial set of reviews used"

        with open(reviews_path) as reviews:
            last_package = None
            for line in reviews:
                elements = line.split("~~~")
                if len(elements) == 5:
                    review = Review(elements[0], float(elements[1]), elements[2], elements[3], elements[4])
                    if last_package != None and last_package.name == elements[0]:
                        #Comment is on the same package as previous comment.. no need to search for the package
                        last_package.reviews.append(review)
                        review.package = last_package
                        last_package.update_stats()
                    else:
                        if elements[0] in self.packages_dict:
                            package = self.packages_dict[elements[0]]
                            last_package = package
                            package.reviews.append(review)
                            review.package = package
                            package.update_stats()

    @print_timing
    def update_reviews(self):
        reviews_path = HOME + "/.linuxmint/mintinstall/reviews.list"
        if os.path.exists(reviews_path):
            reviews = open(reviews_path)
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

    @print_timing
    def show_category(self, category):

        self.notebook.set_current_page(self.PAGE_LIST)
        self.previous_page = self.PAGE_LANDING
        self.back_button.set_sensitive(True)

        self.searchentry.set_text("")
        self._search_in_category = category

        if category.parent == self.root_category:
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
                icon = None
                if theme.has_icon(cat.icon):
                    iconInfo = theme.lookup_icon(cat.icon, 64, 0)
                    if iconInfo and os.path.exists(iconInfo.get_filename()):
                        icon = iconInfo.get_filename()
                if icon == None:
                    if os.path.exists(cat.icon):
                        icon = cat.icon
                    else:
                        iconInfo = theme.lookup_icon("applications-other", 64, 0)
                        if iconInfo and os.path.exists(iconInfo.get_filename()):
                            icon = iconInfo.get_filename()
                #self.browser2.execute_script('addCategory("%s", "%s", "%s")' % (cat.name, _("%d packages") % len(cat.packages), icon))
                row = CategoryListBoxRow(cat)
                self.listbox_categories.add(row)
                self.listbox_categories.show_all()

    def on_row_activated(self, listbox, row):
        self.show_category(row.category)

    def get_package_pixbuf_icon(self, package):
        icon_path = None

        package_name = package.name.split(":")[0] # If this is an arch package, like "foo:i386", only consider "foo"
        icon_path = None
        # Try the Icon theme first
        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(package_name):
            iconInfo = theme.lookup_icon(package_name, ICON_SIZE, 0)
            if iconInfo and os.path.exists(iconInfo.get_filename()):
                icon_path = iconInfo.get_filename()

        # If - is in the name, try the first part of the name (for instance "steam" instead of "steam-launcher")
        if icon_path is None and "-" in package_name:
            name = package_name.split("-")[0]
            if theme.has_icon(name):
                iconInfo = theme.lookup_icon(name, ICON_SIZE, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    icon_path = iconInfo.get_filename()

        if icon_path is None:
            # Try app-install icons then
            icon_path = "/usr/share/app-install/icons/%s" % package_name

            if os.path.exists(icon_path + ".svg"):
                icon_path = icon_path + ".svg"
            elif os.path.exists(icon_path + ".png"):
                icon_path = icon_path + ".png"
            elif os.path.exists(icon_path + ".xpm"):
                icon_path = icon_path + ".xpm"
            else:
                # Else, default to generic icons
                icon_path = self.generic_available_icon_path


        #get cached generic icons, so they aren't converted repetitively
        if icon_path == self.generic_available_icon_path:
            return self.generic_available_icon_pixbuf

        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, ICON_SIZE, ICON_SIZE)
        except:
            return self.generic_available_icon_pixbuf

    def find_large_app_icon(self, package):
        package_name = package.name.split(":")[0] # If this is an arch package, like "foo:i386", only consider "foo"
        theme = Gtk.IconTheme.get_default()
        if theme.has_icon(package_name):
            iconInfo = theme.lookup_icon(package_name, 64, 0)
            if iconInfo and os.path.exists(iconInfo.get_filename()):
                return iconInfo.get_filename()

        # If - is in the name, try the first part of the name (for instance "steam" instead of "steam-launcher")
        if "-" in package_name:
            name = package_name.split("-")[0]
            if theme.has_icon(name):
                iconInfo = theme.lookup_icon(name, 64, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    return iconInfo.get_filename()

        iconInfo = theme.lookup_icon("applications-other", 64, 0)
        return iconInfo.get_filename()

    def _show_all_search_results(self):
        self._search_in_category = self.root_category
        self.show_search_results(self._current_search_terms)

    def _on_search_applications_scrolled(self, adjustment):
        if self._load_more_search_timer:
            GObject.source_remove(self._load_more_search_timer)
        self._load_more_search_timer = GObject.timeout_add(500, self._load_more_search_packages)

    @print_timing
    def show_search_results(self, terms):
        self.listbox_categories.hide()
        self.back_button.set_sensitive(True)
        self.previous_page = self.PAGE_LANDING
        self.notebook.set_current_page(self.PAGE_LIST)

        self._current_search_terms = terms

        sans26 = ImageFont.truetype(self.FONT, 26)
        sans10 = ImageFont.truetype(self.FONT, 12)

        termsUpper = terms.upper()

        if self._search_in_category == self.root_category:
            packages = self.packages
        else:
            packages = self._search_in_category.packages

        self._searched_packages = []

        for package in packages:
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

        # # Load packages into self.tree_applications
        # model = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, GdkPixbuf.Pixbuf, object)

        # self.model_filter = model.filter_new()
        # self.model_filter.set_visible_func(self.visible_func)

        packages.sort(self.package_compare)
        packages = packages[0:200]

        # sans26 = ImageFont.truetype(self.FONT, 26)
        # sans10 = ImageFont.truetype(self.FONT, 12)

        for package in packages:
            # if (package.name in COMMERCIAL_APPS):
            #     continue

            if ":" in package.name and package.name.split(":")[0] in self.packages_dict:
                # don't list arch packages when the root is represented in the cache
                continue

            if ":" in package.name and package.name.split(":")[0] in self.packages_dict:
                # don't list arch packages when the root is represented in the cache
                continue

            package_name = self.get_simple_name(package.name)

            icon = self.get_package_pixbuf_icon(package)
            icon = Gtk.Image.new_from_pixbuf(icon)

            tile = PackageTile(package, icon, package.summary)
            tile.connect("clicked", self.on_package_tile_clicked, self.PAGE_LIST)

            self.flowbox_applications.insert(tile, -1)
            self.flowbox_applications.show_all()

        #     iter = model.insert_before(None, None)
        #     model.set_value(iter, 0, self.get_package_pixbuf_icon(package))
        #     summary = ""
        #     if package.summary is not None:
        #         summary = package.summary
        #         summary = unicode(summary, 'UTF-8', 'replace')
        #         summary = summary.replace("<", "&lt;")
        #         summary = summary.replace("&", "&amp;")

        #     model.set_value(iter, 1, "%s\n<small><span foreground='#555555'>%s</span></small>" % (package_name, summary.capitalize()))

        #     if package.num_reviews > 0:
        #         image = "/usr/share/linuxmint/mintinstall/data/" + str(package.avg_rating) + ".png"
        #         im = Image.open(image)
        #         draw = ImageDraw.Draw(im)

        #         color = "#000000"
        #         if package.score < 0:
        #             color = "#AA5555"
        #         elif package.score > 0:
        #             color = "#55AA55"
        #         draw.text((87, 9), str(package.score), font=sans26, fill="#AAAAAA")
        #         draw.text((86, 8), str(package.score), font=sans26, fill="#555555")
        #         draw.text((85, 7), str(package.score), font=sans26, fill=color)
        #         draw.text((13, 33), u"%s" % (_("%d reviews") % package.num_reviews), font=sans10, fill="#555555")

        #         model.set_value(iter, 2, convertImageToGtkPixbuf(im))

        #     model.set_value(iter, 3, package)

        # self.tree_applications.set_model(self.model_filter)

    @print_timing
    def show_package(self, package, previous_page):

        self.notebook.set_current_page(self.PAGE_PACKAGE)
        self.previous_page = previous_page
        self.back_button.set_sensitive(True)

        self.searchentry.set_text("")
        self.current_package = package

        # Load package info
        subs = {}
        subs['username'] = self.prefs["username"]
        subs['password'] = self.prefs["password"]
        subs['comment'] = ""
        subs['score'] = 0

        font_description = Gtk.Label(label="pango").get_pango_context().get_font_description()
        subs['font_family'] = font_description.get_family()
        try:
            subs['font_weight'] = font_description.get_weight().real
        except:
            subs['font_weight'] = font_description.get_weight()
        subs['font_style'] = font_description.get_style().value_nick
        subs['font_size'] = font_description.get_size() / 1024

        if self.prefs["username"] != "":
            for review in package.reviews:
                if review.username == self.prefs["username"]:
                    subs['comment'] = review.comment
                    subs['score'] = review.rating

        score_options = ["", _("Hate it"), _("Not a fan"), _("So so"), _("Like it"), _("Awesome!")]
        subs['score_options'] = ""
        for score in range(6):
            if (score == subs['score']):
                option = "<option value=%d %s>%s</option>" % (score, "SELECTED", score_options[score])
            else:
                option = "<option value=%d %s>%s</option>" % (score, "", score_options[score])

            subs['score_options'] = subs['score_options'] + option

        subs['iconbig'] = self.find_large_app_icon(package)

        subs['appname'] = self.get_simple_name(package.name)
        subs['pkgname'] = package.name
        subs['description'] = package.pkg.candidate.description
        subs['description'] = subs['description'].replace('\n', '<br />\n')
        subs['summary'] = package.summary.capitalize()
        subs['label_score'] = _("Score:")
        subs['label_submit'] = _("Submit")
        subs['label_your_review'] = _("Your review")

        impacted_packages = []
        js_removals = []
        removals = []
        installations = []

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
            if pkg.name == package.name:
                continue
            if (pkg.is_installed):
                js_removals.append("'%s'" % pkg.name)
                removals.append(pkg.name)
            else:
                installations.append(pkg.name)

        subs['removals'] = ", ".join(js_removals)

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

        subs['sizeLabel'] = _("Size:")
        subs['versionLabel'] = _("Version:")
        subs['reviewsLabel'] = _("Reviews")
        subs['yourReviewLabel'] = _("Your review:")
        subs['detailsLabel'] = _("Details")

        subs['warning_label'] = _("This will remove the following packages:")
        subs['warning_cancel'] = _("Cancel")
        subs['warning_confirm'] = _("Confirm")

        if package.pkg.is_installed:
            if self.cache.required_space < 0:
                subs['sizeinfo'] = _("%(localSize)s of disk space freed") % {'localSize': localSize}
            else:
                subs['sizeinfo'] = _("%(localSize)s of disk space required") % {'localSize': localSize}
        else:
            if self.cache.required_space < 0:
                subs['sizeinfo'] = _("%(downloadSize)s to download, %(localSize)s of disk space freed") % {'downloadSize': downloadSize, 'localSize': localSize}
            else:
                subs['sizeinfo'] = _("%(downloadSize)s to download, %(localSize)s of disk space required") % {'downloadSize': downloadSize, 'localSize': localSize}

        if (len(installations) > 0):
            impacted_packages.append("<li>%s %s</li>" % (_("The following packages would be installed: "), ', '.join(installations)))
        if (len(removals) > 0):
            impacted_packages.append("<li><font color=red>%s %s</font></li>" % (_("The following packages would be removed: "), ', '.join(removals)))

        if (len(installations) > 0 or len(removals) > 0):
            subs['packagesinfo'] = '<b>%s</b><ul>%s</ul>' % (_("Impact on packages:"), '<br>'.join(impacted_packages))
        else:
            subs['packagesinfo'] = ''

        subs['homepage'] = ""
        subs['homepage_button_visibility'] = "hidden"

        if package.pkg.is_installed:
            subs['action_button_label'] = _("Remove")
            subs['version'] = package.pkg.installed.version
            subs['action_button_description'] = _("Installed")
            subs['iconstatus'] = "/usr/share/linuxmint/mintinstall/data/installed.png"
        else:
            if package.pkg.name in BROKEN_PACKAGES:
                subs['action_button_label'] = _("Not available")
                subs['version'] = package.pkg.candidate.version
                subs['action_button_description'] = _("Please use apt-get to install this package.")
                subs['iconstatus'] = "/usr/share/linuxmint/mintinstall/data/available.png"
            else:
                subs['action_button_label'] = _("Install")
                subs['version'] = package.pkg.candidate.version
                subs['action_button_description'] = _("Not installed")
                subs['iconstatus'] = "/usr/share/linuxmint/mintinstall/data/available.png"

        if package.num_reviews > 0:
            sans26 = ImageFont.truetype(self.FONT, 26)
            sans10 = ImageFont.truetype(self.FONT, 12)
            image = "/usr/share/linuxmint/mintinstall/data/" + str(package.avg_rating) + ".png"
            im = Image.open(image)
            draw = ImageDraw.Draw(im)
            color = "#000000"
            if package.score < 0:
                color = "#AA5555"
            elif package.score > 0:
                color = "#55AA55"
            draw.text((87, 9), str(package.score), font=sans26, fill="#AAAAAA")
            draw.text((86, 8), str(package.score), font=sans26, fill="#555555")
            draw.text((85, 7), str(package.score), font=sans26, fill=color)
            draw.text((13, 33), u"%s" % (_("%d reviews") % package.num_reviews), font=sans10, fill="#555555")
            tmpFile = tempfile.NamedTemporaryFile(delete=True)
            im.save(tmpFile.name + ".png")
            subs['rating'] = tmpFile.name + ".png"
            subs['reviews'] = "<b>" + _("Reviews:") + "</b>"
        else:
            subs['rating'] = "/usr/share/linuxmint/mintinstall/data/no-reviews.png"
            subs['reviews'] = ""

        reviews = package.reviews
        reviews.sort(key=lambda x: x.date, reverse=True)
        if len(reviews) > 10:
            for review in reviews[0:10]:
                rating = "/usr/share/linuxmint/mintinstall/data/small_" + str(review.rating) + ".png"
                comment = review.comment.strip()
                comment = comment.replace("'", "\'")
                comment = comment.replace('"', '\"')
                comment = comment.capitalize()
                comment = unicode(comment, 'UTF-8', 'replace')
                review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")

                #self.packageBrowser.execute_script('addReview("%s", "%s", "%s", "%s")' % (review_date, review.username, rating, comment))
        else:
            for review in reviews:
                rating = "/usr/share/linuxmint/mintinstall/data/small_" + str(review.rating) + ".png"
                comment = review.comment.strip()
                comment = comment.replace("'", "\'")
                comment = comment.replace('"', '\"')
                comment = comment.capitalize()
                comment = unicode(comment, 'UTF-8', 'replace')
                review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")

        #self.main_window.set_sensitive(True)
        #self.main_window.window.set_cursor(None)

        self.packageLabel.set_label(package.name)

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
    os.system("mkdir -p " + HOME + "/.linuxmint/mintinstall/screenshots/")
    model = Classes.Model()
    Application()
    Gdk.threads_enter()
    Gtk.main()
    Gdk.threads_leave()
