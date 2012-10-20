#!/usr/bin/python
# -*- coding: UTF-8 -*-

import Classes
import sys, os, commands
import gtk
import gtk.glade
import pygtk
import thread
import gettext
import tempfile
import threading
import webkit
import string
import Image
import StringIO
import ImageFont, ImageDraw, ImageOps
import time
import apt
import urllib
import thread
import glib
import dbus
from AptClient.AptClient import AptClient

from datetime import datetime
from subprocess import Popen, PIPE
from widgets.pathbar2 import NavigationBar
from widgets.searchentry import SearchEntry
from user import home
import base64

# Don't let mintinstall run as root
#~ if os.getuid() == 0:
    #~ print "The software manager should not be run as root. Please run it in user mode."
    #~ sys.exit(1)
if os.getuid() != 0:
    print "The software manager should be run as root."
    sys.exit(1)

pygtk.require("2.0")

sys.path.append('/usr/lib/linuxmint/common')
from configobj import ConfigObj

def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print '%s took %0.3f ms' % (func.func_name, (t2-t1)*1000.0)
        return res
    return wrapper

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

# i18n for menu item
menuName = _("Software Manager")
menuComment = _("Install new applications")

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

gtk.gdk.threads_init()

COMMERCIAL_APPS = ["chromium-browser"]

def get_dbus_bus():
   bus = dbus.SystemBus()
   return bus

class DownloadReviews(threading.Thread):
    def __init__(self, application):
        threading.Thread.__init__(self)
        self.application = application

    def run(self):
        try:
            reviews_dir = home + "/.linuxmint/mintinstall"
            os.system("mkdir -p " + reviews_dir)
            reviews_path = reviews_dir + "/reviews.list"
            reviews_path_tmp = reviews_path + ".tmp"
            url=urllib.urlretrieve("http://community.linuxmint.com/data/reviews.list", reviews_path_tmp)
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

class APTProgressHandler(threading.Thread):
    def __init__(self, application, packages, wTree, apt_client):
        threading.Thread.__init__(self)
        self.application = application
        self.apt_client = apt_client
        self.wTree = wTree
        self.status_label = wTree.get_widget("label_ongoing")
        self.progressbar = wTree.get_widget("progressbar1")
        self.tree_transactions = wTree.get_widget("tree_transactions")
        self.packages = packages
        self.model = gtk.TreeStore(str, str, str, float, object)
        self.tree_transactions.set_model(self.model)
        self.tree_transactions.connect( "button-release-event", self.menuPopup )
        
        self.apt_client.connect("progress", self._on_apt_client_progress)
        self.apt_client.connect("task_ended", self._on_apt_client_task_ended)
    
    def _on_apt_client_progress(self, *args):
        self._update_display()

    def _on_apt_client_task_ended(self, *args):
        self._update_display()
    
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
                            if self.application.navigation_bar.get_active().get_label() == pkg_name:
                                self.application.show_package(package, None)

                    # Update apps tree  
                    tree_applications = self.wTree.get_widget("tree_applications")
                    if tree_applications:
                        model_apps = tree_applications.get_model()
                        if isinstance(model_apps, gtk.TreeModelFilter):
                            model_apps = model_apps.get_model()

                        if model_apps is not None:
                            iter_apps = model_apps.get_iter_first()
                            while iter_apps is not None:
                                package = model_apps.get_value(iter_apps, 3)
                                if package.pkg.name == pkg_name:
                                    try:
                                        model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.application.find_app_icon(package), 32, 32))
                                    except:
                                        try:
                                            model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.application.find_app_icon_alternative(package), 32, 32))
                                        except:
                                            model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_fallback_icon(package), 32, 32))
                                        
                                iter_apps = model_apps.iter_next(iter_apps)                    

                        # Update mixed apps tree                   
                        model_apps = self.wTree.get_widget("tree_mixed_applications").get_model()
                        if isinstance(model_apps, gtk.TreeModelFilter):
                            model_apps = model_apps.get_model()
                        if model_apps is not None:
                            iter_apps = model_apps.get_iter_first()
                            while iter_apps is not None:
                                package = model_apps.get_value(iter_apps, 3)
                                if package.pkg.name == pkg_name:
                                    try:
                                        model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.application.find_app_icon(package), 32, 32))
                                    except:
                                        try:
                                            model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.application.find_app_icon_alternative(package), 32, 32))
                                        except:
                                            model_apps.set_value(iter_apps, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_fallback_icon(package), 32, 32))
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

    def menuPopup( self, widget, event ):
        if event.button == 3:
            model, iter = self.tree_transactions.get_selection().get_selected()
            if iter is not None:
                task = model.get_value(iter, 4)
                menu = gtk.Menu()
                cancelMenuItem = gtk.MenuItem(_("Cancel the task: %s") % model.get_value(iter, 0))
                cancelMenuItem.set_sensitive(task["cancellable"])
                menu.append(cancelMenuItem)
                menu.show_all()
                cancelMenuItem.connect( "activate", self.cancelTask, task)
                menu.popup( None, None, None, event.button, event.time )

    def cancelTask(self, menu, task):
        self.apt_client.cancel_task(task["task_id"])
        self._update_display()
            
    def get_status_description(self, transaction):
        descriptions = {"waiting":_("Waiting"), "downloading":_("Downloading"), "running":_("Running"), "finished":_("Finished")}
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

class Package:

    def __init__(self, name, pkg):
        self.name = name
        self.pkg = pkg
        self.reviews = []
        self.categories = []
        self.score = 0
        self.avg_rating = 0
        self.num_reviews = 0

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

class Review:

    def __init__(self, packagename, date, username, rating, comment):
        self.date = date
        self.packagename = packagename
        self.username = username
        self.rating = int(rating)
        self.comment = comment
        self.package = None

class Application():
        
    PAGE_CATEGORIES = 0
    PAGE_MIXED = 1
    PAGE_PACKAGES = 2
    PAGE_DETAILS = 3
    PAGE_SCREENSHOT = 4
    PAGE_WEBSITE = 5
    PAGE_SEARCH = 6
    PAGE_TRANSACTIONS = 7
    PAGE_REVIEWS = 8

    NAVIGATION_HOME = 1
    NAVIGATION_SEARCH = 2
    NAVIGATION_CATEGORY = 3
    NAVIGATION_SUB_CATEGORY = 4
    NAVIGATION_ITEM = 5
    NAVIGATION_SCREENSHOT = 6
    NAVIGATION_WEBSITE = 6
    NAVIGATION_REVIEWS = 6

    if os.path.exists("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"):
        FONT = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
    else:
        FONT = "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
        
    
    @print_timing    
    def __init__(self):
        self.add_categories()
        self.build_matched_packages()
        self.add_packages()
                    
        # Build the GUI
        gladefile = "/usr/lib/linuxmint/mintInstall/mintinstall.glade"
        wTree = gtk.glade.XML(gladefile, "main_window")
        wTree.get_widget("main_window").set_title(_("Software Manager"))
        wTree.get_widget("main_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
        wTree.get_widget("main_window").connect("delete_event", self.close_application)
        
        self.main_window = wTree.get_widget("main_window")

        self.apt_client = AptClient()
        self.apt_progress_handler = APTProgressHandler(self, self.packages, wTree, self.apt_client)
        
        self.add_reviews()
        downloadReviews = DownloadReviews(self)
        downloadReviews.start()

        if len(sys.argv) > 1 and sys.argv[1] == "list":
            # Print packages and their categories and exit
            self.export_listing()
            sys.exit(0)

        self.prefs = self.read_configuration()

        # Build the menu
        fileMenu = gtk.MenuItem(_("_File"))
        fileSubmenu = gtk.Menu()
        fileMenu.set_submenu(fileSubmenu)
        closeMenuItem = gtk.ImageMenuItem(gtk.STOCK_CLOSE)
        closeMenuItem.get_child().set_text(_("Close"))
        closeMenuItem.connect("activate", self.close_application)
        fileSubmenu.append(closeMenuItem)

        editMenu = gtk.MenuItem(_("_Edit"))
        editSubmenu = gtk.Menu()
        editMenu.set_submenu(editSubmenu)
        prefsMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
        prefsMenuItem.get_child().set_text(_("Preferences"))
        prefsMenu = gtk.Menu()
        prefsMenuItem.set_submenu(prefsMenu)

        searchInSummaryMenuItem = gtk.CheckMenuItem(_("Search in packages summary (slower search)"))
        searchInSummaryMenuItem.set_active(self.prefs["search_in_summary"])
        searchInSummaryMenuItem.connect("toggled", self.set_search_filter, "search_in_summary")

        searchInDescriptionMenuItem = gtk.CheckMenuItem(_("Search in packages description (even slower search)"))
        searchInDescriptionMenuItem.set_active(self.prefs["search_in_description"])
        searchInDescriptionMenuItem.connect("toggled", self.set_search_filter, "search_in_description")

        openLinkExternalMenuItem = gtk.CheckMenuItem(_("Open links using the web browser"))
        openLinkExternalMenuItem.set_active(self.prefs["external_browser"])
        openLinkExternalMenuItem.connect("toggled", self.set_external_browser)

        searchWhileTypingMenuItem = gtk.CheckMenuItem(_("Search while typing"))
        searchWhileTypingMenuItem.set_active(self.prefs["search_while_typing"])
        searchWhileTypingMenuItem.connect("toggled", self.set_search_filter, "search_while_typing")

        prefsMenu.append(searchInSummaryMenuItem)
        prefsMenu.append(searchInDescriptionMenuItem)
        prefsMenu.append(openLinkExternalMenuItem)
        prefsMenu.append(searchWhileTypingMenuItem)

        #prefsMenuItem.connect("activate", open_preferences, treeview_update, statusIcon, wTree)
        editSubmenu.append(prefsMenuItem)

        accountMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
        accountMenuItem.get_child().set_text(_("Account information"))
        accountMenuItem.connect("activate", self.open_account_info)
        editSubmenu.append(accountMenuItem)

        if os.path.exists("/usr/bin/software-properties-gtk") or os.path.exists("/usr/bin/software-properties-kde"):
            sourcesMenuItem = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
            sourcesMenuItem.set_image(gtk.image_new_from_file("/usr/lib/linuxmint/mintUpdate/icons/software-properties.png"))
            sourcesMenuItem.get_child().set_text(_("Software sources"))
            sourcesMenuItem.connect("activate", self.open_repositories)
            editSubmenu.append(sourcesMenuItem)

        viewMenu = gtk.MenuItem(_("_View"))
        viewSubmenu = gtk.Menu()
        viewMenu.set_submenu(viewSubmenu)

        availablePackagesMenuItem = gtk.CheckMenuItem(_("Available packages"))
        availablePackagesMenuItem.set_active(self.prefs["available_packages_visible"])
        availablePackagesMenuItem.connect("toggled", self.set_filter, "available_packages_visible")

        installedPackagesMenuItem = gtk.CheckMenuItem(_("Installed packages"))
        installedPackagesMenuItem.set_active(self.prefs["installed_packages_visible"])
        installedPackagesMenuItem.connect("toggled", self.set_filter, "installed_packages_visible")

        viewSubmenu.append(availablePackagesMenuItem)
        viewSubmenu.append(installedPackagesMenuItem)

        helpMenu = gtk.MenuItem(_("_Help"))
        helpSubmenu = gtk.Menu()
        helpMenu.set_submenu(helpSubmenu)
        aboutMenuItem = gtk.ImageMenuItem(gtk.STOCK_ABOUT)
        aboutMenuItem.get_child().set_text(_("About"))
        aboutMenuItem.connect("activate", self.open_about)
        helpSubmenu.append(aboutMenuItem)

        #browser.connect("activate", browser_callback)
        #browser.show()
        wTree.get_widget("menubar1").append(fileMenu)
        wTree.get_widget("menubar1").append(editMenu)
        wTree.get_widget("menubar1").append(viewMenu)
        wTree.get_widget("menubar1").append(helpMenu)

        # Build the applications tables
        self.tree_applications = wTree.get_widget("tree_applications")
        self.tree_mixed_applications = wTree.get_widget("tree_mixed_applications")
        self.tree_search = wTree.get_widget("tree_search")
        self.tree_transactions = wTree.get_widget("tree_transactions")

        self.build_application_tree(self.tree_applications)
        self.build_application_tree(self.tree_mixed_applications)
        self.build_application_tree(self.tree_search)
        self.build_transactions_tree(self.tree_transactions)

        self.navigation_bar = NavigationBar()
        self.searchentry = SearchEntry()
        self.searchentry.connect("terms-changed", self.on_search_terms_changed)
        self.searchentry.connect("activate", self.on_search_entry_activated)
        top_hbox = gtk.HBox()
        top_hbox.pack_start(self.navigation_bar, padding=6)
        top_hbox.pack_start(self.searchentry, expand=False, padding=6)
        wTree.get_widget("toolbar").pack_start(top_hbox, expand=False, padding=6)

        self.notebook = wTree.get_widget("notebook1")

        sans26  =  ImageFont.truetype ( self.FONT, 26 )
        sans10  =  ImageFont.truetype ( self.FONT, 12 )

        # Build the category browsers
        self.browser = webkit.WebView()
        template = open("/usr/lib/linuxmint/mintInstall/data/templates/CategoriesView.html").read()
        subs = {'header': _("Categories")}      
        subs['subtitle'] = _("Please choose a category")
        subs['package_num'] = _("%d packages are currently available") % len(self.packages)
        html = string.Template(template).safe_substitute(subs)
        self.browser.load_html_string(html, "file:/")
        self.browser.connect("load-finished", self._on_load_finished)
        self.browser.connect('title-changed', self._on_title_changed)
        wTree.get_widget("scrolled_categories").add(self.browser)

        self.browser2 = webkit.WebView()
        template = open("/usr/lib/linuxmint/mintInstall/data/templates/SubCategoriesView.html").read()
        subs = {'header': _("Categories")}
        subs['subtitle'] = _("Please choose a sub-category")
        html = string.Template(template).safe_substitute(subs)
        self.browser2.load_html_string(html, "file:/")
        self.browser2.connect('title-changed', self._on_title_changed)
        wTree.get_widget("scrolled_mixed_categories").add(self.browser2)

        self.packageBrowser = webkit.WebView()
        wTree.get_widget("scrolled_details").add(self.packageBrowser)

        self.packageBrowser.connect('title-changed', self._on_title_changed)

        self.screenshotBrowser = webkit.WebView()
        wTree.get_widget("scrolled_screenshot").add(self.screenshotBrowser)

        self.websiteBrowser = webkit.WebView()
        wTree.get_widget("scrolled_website").add(self.websiteBrowser)

        self.reviewsBrowser = webkit.WebView()
        wTree.get_widget("scrolled_reviews").add(self.reviewsBrowser)

        # kill right click menus in webkit views
        self.browser.connect("button-press-event", lambda w, e: e.button == 3)
        self.browser2.connect("button-press-event", lambda w, e: e.button == 3)
        self.packageBrowser.connect("button-press-event", lambda w, e: e.button == 3)
        self.screenshotBrowser.connect("button-press-event", lambda w, e: e.button == 3)
        self.reviewsBrowser.connect("button-press-event", lambda w, e: e.button == 3)

        wTree.get_widget("label_ongoing").set_text(_("No ongoing actions"))
        wTree.get_widget("label_transactions_header").set_text(_("Active tasks:"))
        wTree.get_widget("progressbar1").hide_all()

        wTree.get_widget("button_transactions").connect("clicked", self.show_transactions)

        wTree.get_widget("main_window").show_all()
        

    def on_search_entry_activated(self, searchentry):
        terms = searchentry.get_text()
        if terms != "":
            self.show_search_results(terms)
    
    def on_search_terms_changed(self, searchentry, terms):
        if terms != "" and self.prefs["search_while_typing"]:
            self.show_search_results(terms)

    def set_filter(self, checkmenuitem, configName):
        config = ConfigObj(home + "/.linuxmint/mintinstall.conf")
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
        config = ConfigObj(home + "/.linuxmint/mintinstall.conf")
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
        config = ConfigObj(home + "/.linuxmint/mintinstall.conf")
        config['external_browser'] = checkmenuitem.get_active()
        config.write()
        self.prefs = self.read_configuration()

    def read_configuration(self):

        config = ConfigObj(home + "/.linuxmint/mintinstall.conf")
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
            prefs["search_while_typing"] = True

        #External browser
        try:
            prefs["external_browser"] = (config['external_browser'] == "True")
        except:
            prefs["external_browser"] = False

        return prefs

    def open_repositories(self, widget):
        launcher = commands.getoutput("/usr/lib/linuxmint/common/mint-which-launcher.py")
        if os.path.exists("/usr/bin/software-properties-gtk"):
            os.system("%s /usr/bin/software-properties-gtk" % launcher)
        elif os.path.exists("/usr/bin/software-properties-kde"):
            os.system("%s /usr/bin/software-properties-kde" % launcher)
        self.close_application(None, None, 9) # Status code 9 means we want to restart ourselves

    def open_account_info(self, widget):
        gladefile = "/usr/lib/linuxmint/mintInstall/mintinstall.glade"
        wTree = gtk.glade.XML(gladefile, "window_account")
        wTree.get_widget("window_account").set_title(_("Account information"))
        wTree.get_widget("window_account").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
        wTree.get_widget("label1").set_label("<b>%s</b>" % _("Your community account"))
        wTree.get_widget("label1").set_use_markup(True)
        wTree.get_widget("label2").set_label("<i><small>%s</small></i>" % _("Fill in your account info to review applications"))
        wTree.get_widget("label2").set_use_markup(True)
        wTree.get_widget("label3").set_label(_("Username:"))
        wTree.get_widget("label4").set_label(_("Password:"))
        wTree.get_widget("entry_username").set_text(self.prefs["username"])
        wTree.get_widget("entry_password").set_text(base64.b64decode(self.prefs["password"]))
        wTree.get_widget("close_button").connect("clicked", self.close_window, wTree.get_widget("window_account"))
        wTree.get_widget("entry_username").connect("notify::text", self.update_account_info, "username")
        wTree.get_widget("entry_password").connect("notify::text", self.update_account_info, "password")
        wTree.get_widget("window_account").show_all()

    def close_window(self, widget, window):
        window.hide()

    def update_account_info(self, entry, prop, configName):
        config = ConfigObj(home + "/.linuxmint/mintinstall.conf")
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
        dlg = gtk.AboutDialog()
        dlg.set_title(_("About"))
        dlg.set_program_name("mintInstall")
        dlg.set_comments(_("Software Manager"))
        try:
            h = open('/usr/share/common-licenses/GPL','r')
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

        dlg.set_authors(["Clement Lefebvre <root@linuxmint.com>"])
        dlg.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
        dlg.set_logo(gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/icon.svg"))
        def close(w, res):
            if res == gtk.RESPONSE_CANCEL:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

    def export_listing(self):
        # packages
        for package in self.packages:
            if package.pkg.name.endswith(":i386") or package.pkg.name.endswith(":amd64"):
                continue
            summary = ""
            if package.pkg.candidate is not None:
                summary = package.pkg.candidate.summary
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
        column0 = gtk.TreeViewColumn(_("Icon"), gtk.CellRendererPixbuf(), pixbuf=0)
        column0.set_sort_column_id(0)
        column0.set_resizable(True)

        column1 = gtk.TreeViewColumn(_("Application"), gtk.CellRendererText(), markup=1)
        column1.set_sort_column_id(1)
        column1.set_resizable(True)
        column1.set_sizing(gtk.TREE_VIEW_COLUMN_FIXED)
        column1.set_min_width(350)
        column1.set_max_width(350)

        column2 = gtk.TreeViewColumn(_("Score"), gtk.CellRendererPixbuf(), pixbuf=2)
        column2.set_sort_column_id(2)
        column2.set_resizable(True)
        
        #prevents multiple load finished handlers being hooked up to packageBrowser in show_package
        self.loadHandlerID = -1
        self.acthread = threading.Thread(target=self.cache_apt)
        
        treeview.append_column(column0)
        treeview.append_column(column1)
        treeview.append_column(column2)
        treeview.set_headers_visible(False)
        treeview.connect("row-activated", self.show_selected)
        treeview.show()
        #treeview.connect("row_activated", self.show_more_info)

        selection = treeview.get_selection()
        selection.set_mode(gtk.SELECTION_BROWSE)

        #selection.connect("changed", self.show_selected)

    def build_transactions_tree(self, treeview):
        column0 = gtk.TreeViewColumn(_("Task"), gtk.CellRendererText(), text=0)
        column0.set_resizable(True)

        column1 = gtk.TreeViewColumn(_("Status"), gtk.CellRendererText(), text=1)
        column1.set_resizable(True)

        column2 = gtk.TreeViewColumn(_("Progress"), gtk.CellRendererProgress(), text=2, value=3)
        column2.set_resizable(True)

        treeview.append_column(column0)
        treeview.append_column(column1)
        treeview.append_column(column2)
        treeview.set_headers_visible(True)
        treeview.show()

    def show_selected(self, tree, path, column):
        self.main_window.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))   
        self.main_window.set_sensitive(False)
        model = tree.get_model()
        iter = model.get_iter(path)

        #poll for end of apt caching when idle
        glib.idle_add(self.show_package_if_apt_cached, model.get_value(iter, 3), tree)
        #cache apt in a separate thread as blocks gui update
        self.acthread.start()

    def show_package_if_apt_cached(self, pkg, tree):
        if (self.acthread.isAlive()):
            self.acthread.join()
        
        self.show_package(pkg, tree)
        self.acthread = threading.Thread(target=self.cache_apt) #rebuild here for speed
        return False #false will remove this from gtk's list of idle functions
        #return True

    def cache_apt(self):
        self.cache = apt.Cache()

    def show_more_info(self, tree, path, column):
        model = tree.get_model()
        iter = model.get_iter(path)
        self.selected_package = model.get_value(iter, 3)

    def navigate(self, button, destination):

        if (destination == "search"):
            self.notebook.set_current_page(self.PAGE_SEARCH)
        else:
            self.searchentry.set_text("")
            if isinstance(destination, Category):
                if len(destination.subcategories) > 0:
                    if len(destination.packages) > 0:
                        self.notebook.set_current_page(self.PAGE_MIXED)
                    else:
                        self.notebook.set_current_page(self.PAGE_CATEGORIES)
                else:
                    self.notebook.set_current_page(self.PAGE_PACKAGES)
            elif isinstance(destination, Package):
                self.notebook.set_current_page(self.PAGE_DETAILS)
            elif (destination == "screenshot"):
                self.notebook.set_current_page(self.PAGE_SCREENSHOT)
            elif (destination == "reviews"):
                self.notebook.set_current_page(self.PAGE_REVIEWS)
            else:
                self.notebook.set_current_page(self.PAGE_WEBSITE)


    def close_application(self, window, event=None, exit_code=0):
        self.apt_client.call_on_completion(lambda c: self.do_close_application(c), exit_code)
        window.hide()
    
    def do_close_application(self, exit_code):
        if exit_code == 0:
            # Not happy with Python when it comes to closing threads, so here's a radical method to get what we want.
            pid = os.getpid()
            os.system("kill -9 %s &" % pid)
        else:            
            gtk.main_quit()
            sys.exit(exit_code)

    def _on_load_finished(self, view, frame):
        # Get the categories
        self.show_category(self.root_category)

    def _on_package_load_finished(self, view, frame, reviews):
        #Add the reviews
        self.packageBrowser.execute_script('clearReviews()')
        reviews.sort(key=lambda x: x.date, reverse=True)
        if len(reviews) > 10:
            for review in reviews[0:10]:
                rating = "/usr/lib/linuxmint/mintInstall/data/small_" + str(review.rating) + ".png"
                comment = review.comment.strip()
                comment = comment.replace("'", "\'")
                comment = comment.replace('"', '\"')
                comment = comment.capitalize()
                review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")

                self.packageBrowser.execute_script('addReview("%s", "%s", "%s", "%s")' % (review_date, review.username, rating, comment))
            self.packageBrowser.execute_script('addLink("%s")' % _("See more reviews"))

        else:
            for review in reviews:
                rating = "/usr/lib/linuxmint/mintInstall/data/small_" + str(review.rating) + ".png"
                comment = review.comment.strip()
                comment = comment.replace("'", "\'")
                comment = comment.replace('"', '\"')
                comment = comment.capitalize()
                review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")

                self.packageBrowser.execute_script('addReview("%s", "%s", "%s", "%s")' % (review_date, review.username, rating, comment))
        self.main_window.set_sensitive(True)
        self.main_window.window.set_cursor(None)

    def on_category_clicked(self, name):
        for category in self.categories:
            if category.name == name:
                self.show_category(category)

    def on_button_clicked(self):        
        package = self.current_package
        if package is not None:             
            if package.pkg.is_installed:
                self.apt_client.remove_package(package.pkg.name)
            else:
                self.apt_client.install_package(package.pkg.name)
    
    def on_screenshot_clicked(self):
        package = self.current_package
        if package is not None:
            template = open("/usr/lib/linuxmint/mintInstall/data/templates/ScreenshotView.html").read()
            subs = {}
            subs['appname'] = self.current_package.pkg.name
            html = string.Template(template).safe_substitute(subs)
            self.screenshotBrowser.load_html_string(html, "file:/")
            self.navigation_bar.add_with_id(_("Screenshot"), self.navigate, self.NAVIGATION_SCREENSHOT, "screenshot")

    def on_website_clicked(self):
        package = self.current_package
        if package is not None:
            if self.prefs['external_browser']:
                os.system("xdg-open " + self.current_package.pkg.candidate.homepage + " &")
            else:
                self.websiteBrowser.open(self.current_package.pkg.candidate.homepage)
                self.navigation_bar.add_with_id(_("Website"), self.navigate, self.NAVIGATION_WEBSITE, "website")

    def on_reviews_clicked(self):
        package = self.current_package
        if package is not None:
            template = open("/usr/lib/linuxmint/mintInstall/data/templates/ReviewsView.html").read()
            subs = {}
            subs['appname'] = self.current_package.pkg.name
            subs['reviewsLabel'] = _("Reviews")
            font_description = gtk.Label("pango").get_pango_context().get_font_description()
            subs['font_family'] = font_description.get_family()
            try:
                subs['font_weight'] = font_description.get_weight().real
            except:
                subs['font_weight'] = font_description.get_weight()   
            subs['font_style'] = font_description.get_style().value_nick        
            subs['font_size'] = font_description.get_size() / 1024    
            html = string.Template(template).safe_substitute(subs)
            self.reviewsBrowser.load_html_string(html, "file:/")
            self.reviewsBrowser.connect("load-finished", self._on_reviews_load_finished, package.reviews)
            self.navigation_bar.add_with_id(_("Reviews"), self.navigate, self.NAVIGATION_REVIEWS, "reviews")

    def _on_reviews_load_finished(self, view, frame, reviews):
        #Add the reviews
        self.reviewsBrowser.execute_script('clearReviews()')
        reviews.sort(key=lambda x: x.date, reverse=True)
        for review in reviews:
            rating = "/usr/lib/linuxmint/mintInstall/data/small_" + str(review.rating) + ".png"
            comment = review.comment.strip()
            comment = comment.replace("'", "\'")
            comment = comment.replace('"', '\"')
            comment = comment.capitalize()
            review_date = datetime.fromtimestamp(review.date).strftime("%Y.%m.%d")
            self.reviewsBrowser.execute_script('addReview("%s", "%s", "%s", "%s")' % (review_date, review.username, rating, comment))

    def _on_title_changed(self, view, frame, title):
        # no op - needed to reset the title after a action so that
        #        the action can be triggered again
        if title.startswith("nop"):
            return
        # call directive looks like:
        #  "call:func:arg1,arg2"
        #  "call:func"
        if title.startswith("call:"):
            args_str = ""
            args_list = []
            # try long form (with arguments) first
            try:
                (t,funcname,args_str) = title.split(":")
            except ValueError:
                # now try short (without arguments)
                (t,funcname) = title.split(":")
            if args_str:
                args_list = args_str.split(",")
            # see if we have it and if it can be called
            f = getattr(self, funcname)
            if f and callable(f):
                f(*args_list)
            # now we need to reset the title
            self.browser.execute_script('document.title = "nop"')

    @print_timing
    def add_categories(self):
        self.categories = []
        self.root_category = Category(_("Categories"), "applications-other", None, None, self.categories)
        
        featured = Category(_("Featured"), "/usr/lib/linuxmint/mintInstall/data/templates/featured.svg", None, self.root_category, self.categories)
        featured.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/featured.list")
        
        self.category_all = Category(_("All Packages"), "applications-other", None, self.root_category, self.categories)
        
        internet = Category(_("Internet"), "applications-internet", None, self.root_category, self.categories)
        subcat = Category(_("Web"), "applications-internet", ("web", "net"), internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/internet-web.list")
        subcat = Category(_("Email"), "applications-internet", ("mail"), internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/internet-email.list")
        subcat = Category(_("Chat"), "applications-internet", None, internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/internet-chat.list")
        subcat = Category(_("File sharing"), "applications-internet", None, internet, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/internet-filesharing.list")
        
        cat = Category(_("Sound and video"), "applications-multimedia", ("multimedia", "video"), self.root_category, self.categories)
        cat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/sound-video.list")
        
        graphics = Category(_("Graphics"), "applications-graphics", ("graphics"), self.root_category, self.categories)
        graphics.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics.list")
        subcat = Category(_("3D"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-3d.list")
        subcat = Category(_("Drawing"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-drawing.list")
        subcat = Category(_("Photography"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-photography.list")
        subcat = Category(_("Publishing"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-publishing.list")
        subcat = Category(_("Scanning"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-scanning.list")
        subcat = Category(_("Viewers"), "applications-graphics", None, graphics, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/graphics-viewers.list")
        
        Category(_("Office"), "applications-office", ("office", "editors"), self.root_category, self.categories)
        
        games = Category(_("Games"), "applications-games", ("games"), self.root_category, self.categories)
        subcat = Category(_("Board games"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-board.list")
        subcat = Category(_("First-person shooters"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-fps.list")
        subcat = Category(_("Real-time strategy"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-rts.list")
        subcat = Category(_("Turn-based strategy"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-tbs.list")
        subcat = Category(_("Emulators"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-emulators.list")
        subcat = Category(_("Simulation and racing"), "applications-games", None, games, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/games-simulations.list")
        
        Category(_("Accessories"), "applications-utilities", ("accessories", "utils"), self.root_category, self.categories)

        cat = Category(_("System tools"), "applications-system", ("system", "admin"), self.root_category, self.categories)
        cat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/system-tools.list")

        subcat = Category(_("Fonts"), "applications-fonts", ("fonts"), self.root_category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/fonts.list")
               
        subcat = Category(_("Science and Education"), "applications-science", ("science", "math", "education"), self.root_category, self.categories)
        subcat.matchingPackages = self.file_to_array("/usr/lib/linuxmint/mintInstall/categories/education.list")

        Category(_("Programming"), "applications-development", ("devel"), self.root_category, self.categories)
        #self.category_other = Category(_("Other"), "applications-other", None, self.root_category, self.categories)        

    def file_to_array(self, filename):
        array = []
        f = open(filename)
        for line in f:
            line = line.replace("\n","").replace("\r","").strip();
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
            self.category_all.packages.append(package)

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
        if category.parent is not None:
            if category not in package.categories:
                package.categories.append(category)
                category.packages.append(package)
            self.add_package_to_category(package, category.parent)

    @print_timing
    def add_reviews(self):
        reviews_path = home + "/.linuxmint/mintinstall/reviews.list"
        if not os.path.exists(reviews_path):
            # No reviews found, use the ones from the packages itself
            os.system("cp /usr/lib/linuxmint/mintInstall/reviews.list %s" % reviews_path)
            print "First run detected, initial set of reviews used"
            
        reviews = open(reviews_path)
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
        reviews_path = home + "/.linuxmint/mintinstall/reviews.list"
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
    @print_timing
    def show_category(self, category):
        # Load subcategories
        if len(category.subcategories) > 0:
            if len(category.packages) == 0:
                # Show categories page
                browser = self.browser
                size = 64
            else:
                # Show mixed page
                browser = self.browser2
                size = 48

            browser.execute_script('clearCategories()')
            theme = gtk.icon_theme_get_default()
            for cat in category.subcategories:
                icon = None
                if theme.has_icon(cat.icon):
                    iconInfo = theme.lookup_icon(cat.icon, size, 0)
                    if iconInfo and os.path.exists(iconInfo.get_filename()):
                        icon = iconInfo.get_filename()              
                if icon == None:
                    if os.path.exists(cat.icon):
                        icon = cat.icon
                    else:
                        iconInfo = theme.lookup_icon("applications-other", size, 0)
                        if iconInfo and os.path.exists(iconInfo.get_filename()):
                            icon = iconInfo.get_filename()
                browser.execute_script('addCategory("%s", "%s", "%s")' % (cat.name, _("%d packages") % len(cat.packages), icon))

        # Load packages into self.tree_applications
        if (len(category.subcategories) == 0):
            # Show packages
            tree_applications = self.tree_applications
        else:
            tree_applications = self.tree_mixed_applications

        model_applications = gtk.TreeStore(gtk.gdk.Pixbuf, str, gtk.gdk.Pixbuf, object)

        self.model_filter = model_applications.filter_new()
        self.model_filter.set_visible_func(self.visible_func)


        sans26  =  ImageFont.truetype ( self.FONT, 26 )
        sans10  =  ImageFont.truetype ( self.FONT, 12 )

        category.packages.sort(self.package_compare)
        for package in category.packages[0:500]:
            
            if package.name in COMMERCIAL_APPS:
                continue
            
            iter = model_applications.insert_before(None, None)
            try:
                model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_app_icon(package), 32, 32))
            except:
                try:                
                    model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_app_icon_alternative(package), 32, 32))
                except:
                    model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_fallback_icon(package), 32, 32))
            summary = ""
            if package.pkg.candidate is not None:
                summary = package.pkg.candidate.summary
                summary = unicode(summary, 'UTF-8', 'replace')
                summary = summary.replace("<", "&lt;")
                summary = summary.replace("&", "&amp;")

            model_applications.set_value(iter, 1, "%s\n<small><span foreground='#555555'>%s</span></small>" % (package.name, summary.capitalize()))

            if package.num_reviews > 0:
                image = "/usr/lib/linuxmint/mintInstall/data/" + str(package.avg_rating) + ".png"
                im=Image.open(image)
                draw = ImageDraw.Draw(im)

                color = "#000000"
                if package.score < 0:
                    color = "#AA5555"
                elif package.score > 0:
                    color = "#55AA55"
                draw.text((34, 2), str(package.score), font=sans26, fill="#AAAAAA")
                draw.text((33, 1), str(package.score), font=sans26, fill="#555555")                 
                draw.text((32, 0), str(package.score), font=sans26, fill=color)
                draw.text((13, 33), u"%s" % (_("%d reviews") % package.num_reviews), font=sans10, fill="#555555")
                tmpFile = tempfile.NamedTemporaryFile(delete=False)
                im.save (tmpFile.name + ".png")
                model_applications.set_value(iter, 2, gtk.gdk.pixbuf_new_from_file(tmpFile.name + ".png"))

            model_applications.set_value(iter, 3, package)

        tree_applications.set_model(self.model_filter)
        first = model_applications.get_iter_first()
        del model_applications

        # Update the navigation bar
        if category == self.root_category:
            self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_HOME, category)
        elif category.parent == self.root_category:
            self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_CATEGORY, category)
        else:
            self.navigation_bar.add_with_id(category.name, self.navigate, self.NAVIGATION_SUB_CATEGORY, category)

    def find_fallback_icon(self, package):
        if package.pkg.is_installed:
            icon_path = "/usr/lib/linuxmint/mintInstall/data/installed.png"
        else:
            icon_path = "/usr/lib/linuxmint/mintInstall/data/available.png"
        return icon_path
            
    def find_app_icon_alternative(self, package):
        icon_path = None
        if package.pkg.is_installed:
            icon_path = "/usr/share/linuxmint/mintinstall/installed/%s" % package.name
            if os.path.exists(icon_path + ".png"):
                icon_path = icon_path + ".png"
            elif os.path.exists(icon_path + ".xpm"):
                icon_path = icon_path + ".xpm"
            else:
                # Else, default to generic icons
                icon_path = "/usr/lib/linuxmint/mintInstall/data/installed.png"
        else:          
            # Try the Icon theme first
            theme = gtk.icon_theme_get_default()
            if theme.has_icon(package.name):
                iconInfo = theme.lookup_icon(package.name, 32, 0)
                if iconInfo and os.path.exists(iconInfo.get_filename()):
                    icon_path = iconInfo.get_filename()
            else:
                # Try mintinstall-icons then
                icon_path = "/usr/share/linuxmint/mintinstall/icons/%s" % package.name
                if os.path.exists(icon_path + ".png"):
                    icon_path = icon_path + ".png"
                elif os.path.exists(icon_path + ".xpm"):
                    icon_path = icon_path + ".xpm"
                else:
                    # Else, default to generic icons
                    icon_path = "/usr/lib/linuxmint/mintInstall/data/available.png"
        return icon_path
    
    def find_app_icon(self, package):
        icon_path = None
        # Try the Icon theme first
        theme = gtk.icon_theme_get_default()
        if theme.has_icon(package.name):
            iconInfo = theme.lookup_icon(package.name, 32, 0)
            if iconInfo and os.path.exists(iconInfo.get_filename()):
                icon_path = iconInfo.get_filename()
            
        if icon_path is not None:
            if package.pkg.is_installed:
                im=Image.open(icon_path)
                bg_w,bg_h=im.size
                im2=Image.open("/usr/lib/linuxmint/mintInstall/data/emblem-installed.png")
                img_w,img_h=im2.size 
                offset=(17,17)         
                im.paste(im2, offset,im2)
                tmpFile = tempfile.NamedTemporaryFile(delete=False)
                im.save (tmpFile.name + ".png")             
                icon_path = tmpFile.name + ".png"               
        else:
            # Try mintinstall-icons then
            if package.pkg.is_installed:
                icon_path = "/usr/share/linuxmint/mintinstall/icons/installed/%s" % package.name
            else:
                icon_path = "/usr/share/linuxmint/mintinstall/icons/%s" % package.name
                
            if os.path.exists(icon_path + ".png"):
                icon_path = icon_path + ".png"
            elif os.path.exists(icon_path + ".xpm"):
                icon_path = icon_path + ".xpm"
            else:
                # Else, default to generic icons                
                if package.pkg.is_installed:
                    icon_path = "/usr/lib/linuxmint/mintInstall/data/installed.png"
                else:
                    icon_path = "/usr/lib/linuxmint/mintInstall/data/available.png"
                                            
        return icon_path
    
                
    def find_large_app_icon(self, package):
        theme = gtk.icon_theme_get_default()
        if theme.has_icon(package.name):
            iconInfo = theme.lookup_icon(package.name, 64, 0)
            if iconInfo and os.path.exists(iconInfo.get_filename()):
                return iconInfo.get_filename()
    
        iconInfo = theme.lookup_icon("applications-other", 64, 0)       
        return iconInfo.get_filename()

    def show_search_results(self, terms):
        # Load packages into self.tree_search
        model_applications = gtk.TreeStore(gtk.gdk.Pixbuf, str, gtk.gdk.Pixbuf, object)

        self.model_filter = model_applications.filter_new()
        self.model_filter.set_visible_func(self.visible_func)

        sans26  =  ImageFont.truetype ( self.FONT, 26 )
        sans10  =  ImageFont.truetype ( self.FONT, 12 )

        self.packages.sort(self.package_compare)
        for package in self.packages:
            visible = False
            if terms.upper() in package.pkg.name.upper():
                visible = True
            else:
                if (package.pkg.candidate is not None):
                    if (self.prefs["search_in_summary"] and terms.upper() in package.pkg.candidate.summary.upper()):
                        visible = True
                    elif(self.prefs["search_in_description"] and terms.upper() in package.pkg.candidate.description.upper()):
                        visible = True

            if visible:
                iter = model_applications.insert_before(None, None)
                try:
                    model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_app_icon(package), 32, 32))
                except:
                    try:
                        model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_app_icon_alternative(package), 32, 32))
                    except:
                        model_applications.set_value(iter, 0, gtk.gdk.pixbuf_new_from_file_at_size(self.find_fallback_icon(package), 32, 32))
                summary = ""
                if package.pkg.candidate is not None:
                    summary = package.pkg.candidate.summary
                    summary = unicode(summary, 'UTF-8', 'replace')
                    summary = summary.replace("<", "&lt;")
                    summary = summary.replace("&", "&amp;")

                model_applications.set_value(iter, 1, "%s\n<small><span foreground='#555555'>%s</span></small>" % (package.name, summary.capitalize()))

                if package.num_reviews > 0:
                    image = "/usr/lib/linuxmint/mintInstall/data/" + str(package.avg_rating) + ".png"
                    im=Image.open(image)
                    draw = ImageDraw.Draw(im)

                    color = "#000000"
                    if package.score < 0:
                        color = "#AA5555"
                    elif package.score > 0:
                        color = "#55AA55"
                    draw.text((34, 2), str(package.score), font=sans26, fill="#AAAAAA")
                    draw.text((33, 1), str(package.score), font=sans26, fill="#555555") 
                    draw.text((32, 0), str(package.score), font=sans26, fill=color)
                    draw.text((13, 33), u"%s" % (_("%d reviews") % package.num_reviews), font=sans10, fill="#555555")
                    tmpFile = tempfile.NamedTemporaryFile(delete=False)
                    im.save (tmpFile.name + ".png")
                    model_applications.set_value(iter, 2, gtk.gdk.pixbuf_new_from_file(tmpFile.name + ".png"))

                model_applications.set_value(iter, 3, package)

        self.tree_search.set_model(self.model_filter)
        del model_applications
        self.navigation_bar.add_with_id(_("Search results"), self.navigate, self.NAVIGATION_CATEGORY, "search")

    def visible_func(self, model, iter):
        package = model.get_value(iter, 3)
        if package is not None:
            if package.pkg is not None:
                if (package.pkg.is_installed and self.prefs["installed_packages_visible"] == True):
                    return True
                elif (package.pkg.is_installed == False and self.prefs["available_packages_visible"] == True):
                    return True
        return False

    @print_timing
    def show_package(self, package, tree):

        self.current_package = package
                
        # Load package info
        subs = {}
        subs['username'] = self.prefs["username"]
        subs['password'] = self.prefs["password"]
        subs['comment'] = ""
        subs['score'] = 0
        
        font_description = gtk.Label("pango").get_pango_context().get_font_description()
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

        subs['appname'] = package.name
        subs['pkgname'] = package.pkg.name
        subs['description'] = package.pkg.candidate.description
        subs['description'] = subs['description'].replace('\n','<br />\n')
        subs['summary'] = package.pkg.candidate.summary.capitalize()
        subs['label_score'] = _("Score:")
        subs['label_submit'] = _("Submit")
        subs['label_your_review'] = _("Your review")

        impacted_packages = []    
        pkg = self.cache[package.name]
        if package.pkg.is_installed:
            pkg.mark_delete(True, True)
        else:
            pkg.mark_install()
    
        changes = self.cache.get_changes()
        for pkg in changes:
            if (pkg.is_installed):
                impacted_packages.append(_("%s (removed)") % pkg.name)
            else:
                impacted_packages.append(_("%s (installed)") % pkg.name)
        
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
        subs['impactLabel'] = _("Impact on packages:")
        subs['reviewsLabel'] = _("Reviews")
        subs['yourReviewLabel'] = _("Your review:")
        subs['detailsLabel'] = _("Details")
        
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
            
        subs['packagesinfo'] = (', '.join(name for name in impacted_packages))

        if len(package.pkg.candidate.homepage) > 0:
            subs['homepage'] = package.pkg.candidate.homepage
            subs['homepage_button_visibility'] = "visible"
        else:
            subs['homepage'] = ""
            subs['homepage_button_visibility'] = "hidden"
        
        direction = gtk.widget_get_default_direction()
        if direction ==  gtk.TEXT_DIR_RTL:
            subs['text_direction'] = 'DIR="RTL"'
        elif direction ==  gtk.TEXT_DIR_LTR:
            subs['text_direction'] = 'DIR="LTR"'

        if package.pkg.is_installed:
            subs['action_button_label'] = _("Remove")
            subs['action_button_value'] = "remove"
            subs['version'] = package.pkg.installed.version
            subs['action_button_description'] = _("Installed")
            subs['iconstatus'] = "/usr/lib/linuxmint/mintInstall/data/installed.png"
        else:
            subs['action_button_label'] = _("Install")
            subs['action_button_value'] = "install"
            subs['version'] = package.pkg.candidate.version
            subs['action_button_description'] = _("Not installed")
            subs['iconstatus'] = "/usr/lib/linuxmint/mintInstall/data/available.png"

        if package.num_reviews > 0:
            sans26 = ImageFont.truetype(self.FONT, 26)
            sans10 = ImageFont.truetype(self.FONT, 12)
            image = "/usr/lib/linuxmint/mintInstall/data/" + str(package.avg_rating) + ".png"
            im=Image.open(image)
            draw = ImageDraw.Draw(im)
            color = "#000000"
            if package.score < 0:
                color = "#AA5555"
            elif package.score > 0:
                color = "#55AA55"
            draw.text((34, 2), str(package.score), font=sans26, fill="#AAAAAA")
            draw.text((33, 1), str(package.score), font=sans26, fill="#555555")
            draw.text((32, 0), str(package.score), font=sans26, fill=color)         
            draw.text((13, 33), u"%s" % (_("%d reviews") % package.num_reviews), font=sans10, fill="#555555")
            tmpFile = tempfile.NamedTemporaryFile(delete=False)
            im.save (tmpFile.name + ".png")
            subs['rating'] = tmpFile.name + ".png"
            subs['reviews'] = "<b>" + _("Reviews:") + "</b>"
        else:
            subs['rating'] = "/usr/lib/linuxmint/mintInstall/data/no-reviews.png"
            subs['reviews'] = ""

        template = open("/usr/lib/linuxmint/mintInstall/data/templates/PackageView.html").read()
        html = string.Template(template).safe_substitute(subs)
        self.packageBrowser.load_html_string(html, "file:/")
        
        if self.loadHandlerID != -1:
            self.packageBrowser.disconnect(self.loadHandlerID)
        
        self.loadHandlerID = self.packageBrowser.connect("load-finished", self._on_package_load_finished, package.reviews)       

        # Update the navigation bar
        self.navigation_bar.add_with_id(package.name, self.navigate, self.NAVIGATION_ITEM, package)


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
    os.system("mkdir -p " + home + "/.linuxmint/mintinstall/screenshots/")
    splash_process = Popen("/usr/lib/linuxmint/mintInstall/splash.py")
    model = Classes.Model()
    Application()
    os.system("kill -9 %d" % splash_process.pid)
    gtk.main()
