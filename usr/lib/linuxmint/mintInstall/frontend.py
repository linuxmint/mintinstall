#!/usr/bin/python

import urllib
import Classes
from xml.etree import ElementTree as ET
from user import home
import os
import commands

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf

import sys
import threading
import gettext
import tempfile

from subprocess import Popen, PIPE

Gdk.threads_init()

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

# i18n for menu item
menuName = _("Software Manager")
menuComment = _("Install new applications")

architecture = commands.getoutput("uname -a")
if (architecture.find("x86_64") >= 0):
	import ctypes
	libc = ctypes.CDLL('libc.so.6')
	libc.prctl(15, 'mintInstall', 0, 0, 0)
else:
	import dl
	libc = dl.open('/lib/libc.so.6')
	libc.call('prctl', 15, 'mintInstall', 0, 0, 0)

global cache
import apt
cache = apt.Cache()
global num_apps
num_apps = 0

def close_application(window, event=None):
	Gtk.main_quit()
	sys.exit(0)

def close_window(widget, window):
	window.hide_all()

def show_item(selection, model, builder, username):
	(model_applications, iter) = selection.get_selected()
	if (iter != None):
		builder.get_object("button_install").hide()
		builder.get_object("button_remove").hide()
		builder.get_object("button_cancel_change").hide()
		builder.get_object("label_install").set_text(_("Install"))
		builder.get_object("label_install").set_tooltip_text("")
		builder.get_object("label_remove").set_text(_("Remove"))
		builder.get_object("label_remove").set_tooltip_text("")
		builder.get_object("label_cancel_change").set_text(_("Cancel change"))
		builder.get_object("label_cancel_change").set_tooltip_text("")
		selected_item = model_applications.get_value(iter, 5)
		model.selected_application = selected_item
		if selected_item.version == "":
			builder.get_object("label_name").set_text("<b>" + selected_item.name + "</b>")
			builder.get_object("label_name").set_tooltip_text(selected_item.name)
		else:
			version = selected_item.version.split("+")[0]
			version = version.split("-")[0]
			builder.get_object("label_name").set_text("<b>" + selected_item.name + "</b> [" + version + "]")
			builder.get_object("label_name").set_tooltip_text(selected_item.name + " [" + selected_item.version + "]")
		builder.get_object("label_name").set_use_markup(True)
		builder.get_object("label_description").set_text("<i>" + selected_item.description + "</i>")
		builder.get_object("label_description").set_use_markup(True)
		str_size = str(selected_item.size) + _("MB")
		if selected_item.size == "0" or selected_item.size == 0:
			str_size = "--"
		builder.get_object("image_screenshot").clear()
		if (selected_item.screenshot != None):
			if (os.path.exists(selected_item.screenshot)):
				try:
					builder.get_object("image_screenshot").set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(selected_item.screenshot, 200, 200))
				except Exception, detail:
					print detail
			else:
				downloadScreenshot = DownloadScreenshot(selected_item, builder, model)
				downloadScreenshot.start()

		tree_reviews = builder.get_object("tree_reviews")
		model_reviews = Gtk.TreeStore(str, int, str, object)
		for review in selected_item.reviews:
			iter = model_reviews.insert_before(None, None)
			model_reviews.set_value(iter, 0, review.username)
			model_reviews.set_value(iter, 1, review.rating)
			model_reviews.set_value(iter, 2, review.comment)
			model_reviews.set_value(iter, 3, review)
		model_reviews.set_sort_column_id( 1, Gtk.SortType.DESCENDING )
		tree_reviews.set_model(model_reviews)

		first = model_reviews.get_iter_first()
		if (first != None):
			tree_reviews.get_selection().select_iter(first)
			tree_reviews.scroll_to_cell(model_reviews.get_path(first))

		del model_reviews
		if selected_item.is_special:
			builder.get_object("button_install").show()
		else:
			if selected_item.status == "available":
				builder.get_object("button_install").show()
			elif selected_item.status == "installed":
				builder.get_object("button_remove").show()
			elif selected_item.status == "add":
				builder.get_object("button_cancel_change").show()
				builder.get_object("label_cancel_change").set_text(_("Cancel installation"))
 			elif selected_item.status == "remove":
				builder.get_object("button_cancel_change").show()
				builder.get_object("label_cancel_change").set_text(_("Cancel removal"))

	update_statusbar(builder, model)

def show_category(selection, model, builder):
	(model_categories, iter) = selection.get_selected()
	if (iter != None):
		selected_category = model_categories.get_value(iter, 1)
		model.selected_category = selected_category
		show_applications(builder, model, True)

def filter_search(widget, wbuilder, model):
	keyword = widget.get_text()
	model.keyword = keyword
	show_applications(builder, model, True)

def open_search(widget, username):
	os.system("/usr/lib/linuxmint/mintInstall/mintInstall.py " + username + " &")

def open_featured(widget):
        builder = Gtk.Builder()
        builder.add_from_file("/usr/lib/linuxmint/mintInstall/frontend.ui")
	treeview_featured = builder.get_object("treeview_featured")
	builder.get_object("featured_window").set_title(_("Featured applications"))
	builder.get_object("featured_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	builder.get_object("button_close").connect("clicked", close_window, builder.get_object("featured_window"))
	builder.get_object("button_apply").connect("clicked", install_featured, builder, treeview_featured, builder.get_object("featured_window"))
	builder.get_object("featured_window").show_all()

	builder.get_object("lbl_intro").set_label(_("These popular applications can be installed on your system:"))

	# the treeview
	cr = Gtk.CellRendererToggle()
	cr.connect("toggled", toggled, treeview_featured)
	column1 = Gtk.TreeViewColumn(_("Install"), cr)
	column1.set_cell_data_func(cr, celldatafunction_checkbox)
	column1.set_sort_column_id(1)
	column1.set_resizable(True)
	column2 = Gtk.TreeViewColumn(_("Application"), Gtk.CellRendererText(), text=2)
	column2.set_sort_column_id(2)
	column2.set_resizable(True)
	column3 = Gtk.TreeViewColumn(_("Icon"), Gtk.CellRendererPixbuf(), pixbuf=3)
	column3.set_sort_column_id(3)
	column3.set_resizable(True)
	column4 = Gtk.TreeViewColumn(_("Description"), Gtk.CellRendererText(), text=4)
	column4.set_sort_column_id(4)
	column4.set_resizable(True)
	column5 = Gtk.TreeViewColumn(_("Size"), Gtk.CellRendererText(), text=5)
	column5.set_sort_column_id(5)
	column5.set_resizable(True)

	treeview_featured.append_column(column1)
	treeview_featured.append_column(column3)
	treeview_featured.append_column(column2)
	treeview_featured.append_column(column4)
	treeview_featured.append_column(column5)
	treeview_featured.set_headers_clickable(False)
	treeview_featured.set_reorderable(False)
	treeview_featured.show()

	model = Gtk.TreeStore(str, str, str, GdkPixbuf.Pixbuf, str, str)
	import string
	applications = open("/usr/share/linuxmint/mintinstall/featured_applications/list.txt", "r")
	for application in applications:
		application = application.strip()
		application_details = string.split(application, "=")
		if len(application_details) == 3:
			application_pkg = application_details[0]
			application_name = application_details[1]
			application_icon = application_details[2]
			try:
				global cache
				pkg = cache[application_pkg]

				if ((not pkg.is_installed) and (pkg.candidate.summary != "")):
					strSize = str(pkg.candidate.size) + _("B")
					if (pkg.candidate.size >= 1000):
						strSize = str(pkg.candidate.size / 1000) + _("KB")
					if (pkg.candidate.size >= 1000000):
						strSize = str(pkg.candidate.size / 1000000) + _("MB")
					if (pkg.candidate.size >= 1000000000):
						strSize = str(pkg.candidate.size / 1000000000) + _("GB")
					iter = model.insert_before(None, None)
					model.set_value(iter, 0, application_pkg)
					model.set_value(iter, 1, "false")
					model.set_value(iter, 2, application_name)
					model.set_value(iter, 3, GdkPixbuf.Pixbuf.new_from_file("/usr/share/linuxmint/mintinstall/featured_applications/" + application_icon))
					model.set_value(iter, 4, pkg.candidate.summary)
					model.set_value(iter, 5, strSize)

			except Exception, detail:
				#Package isn't in repositories
				print detail

	treeview_featured.set_model(model)
	del model

def install_featured(widget, builder, treeview_featured, window):
	vbox = builder.get_object("vbox1")
	socket = Gtk.Socket()
	vbox.pack_start(socket)
	socket.show()
	window_id = repr(socket.get_id())
	command = "gksu mint-synaptic-install " + window_id
	model = treeview_featured.get_model()
	iter = model.get_iter_first()
	while iter != None:
		if (model.get_value(iter, 1) == "true"):
			pkg = model.get_value(iter, 0)
			command = command + " " + pkg
		iter = model.iter_next(iter)
	os.system(command)
	close_window(widget, window)

def toggled(renderer, path, treeview):
    model = treeview.get_model()
    iter = model.get_iter(path)
    if (iter != None):
	    checked = model.get_value(iter, 1)
	    if (checked == "true"):
		model.set_value(iter, 1, "false")
	    else:
		model.set_value(iter, 1, "true")

def celldatafunction_checkbox(column, cell, model, iter):
        cell.set_property("activatable", True)
	checked = model.get_value(iter, 1)
	if (checked == "true"):
		cell.set_property("active", True)
	else:
		cell.set_property("active", False)

def show_screenshot(widget, model):
	#Set the Glade file
	if model.selected_application != None:
		gladefile = "/usr/lib/linuxmint/mintInstall/frontend.glade"
                builder = Gtk.Builder()
                builder.add_from_file(gladefile)
		builder.get_object("screenshot_window").set_title(model.selected_application.name)
		builder.get_object("screenshot_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
		builder.get_object("screenshot_window").connect("delete_event", close_window, builder.get_object("screenshot_window"))
		builder.get_object("button_screen_close").connect("clicked", close_window, builder.get_object("screenshot_window"))
		builder.get_object("image_screen").set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file(model.selected_application.screenshot))
		builder.get_object("button_screen").connect("clicked", close_window, builder.get_object("screenshot_window"))
		builder.get_object("screenshot_window").show_all()

def fetch_apt_details(model):
	global cache
	if os.path.exists("/usr/share/linuxmint/mintinstall/data/details/packages.list"):
		packagesFile = open("/usr/share/linuxmint/mintinstall/data/details/packages.list", "r")
		lines = packagesFile.readlines()
		for line in lines:
			items = line.strip().split()
			key = items[0]
			packages = items[1:]
			item = None
			for portal in model.portals:
				if item is None:
					item = portal.find_item(key)
			if item is not None:
				item.status = "installed"
				for package in packages:
					try:
						pkg = cache[package]
						if not pkg.is_installed:
							item.status = "available"
							item.version = pkg.candidate.version
						else:
							item.version = pkg.installed.version
						item.packages.append(pkg)
						item.is_special = False
						item.long_description = pkg.candidate.raw_description
					except Exception, details:
						print details
			packagesFile.close()

def show_more_info_wrapper(widget, path, column, model):
	show_more_info(widget, model)

def show_more_info(widget, model):
	if model.selected_application != None:
		if not os.path.exists((model.selected_application.mint_file)):
			os.system("zenity --error --text=\"" + _("The mint file for this application was not successfully downloaded. Click on refresh to fix the problem.") + "\"")
		else:
			directory = home + "/.linuxmint/mintInstall/tmp/mintFile"
			os.system("mkdir -p " + directory)
			os.system("rm -rf " + directory + "/*")
			os.system("cp " + model.selected_application.mint_file + " " + directory + "/file.mint")
			os.system("tar zxf " + directory + "/file.mint -C " + directory)
			steps = int(commands.getoutput("ls -l " + directory + "/steps/ | wc -l"))
			steps = steps -1
			repositories = []
			packages = []
			for i in range(steps + 1):
				if (i > 0):
					openfile = open(directory + "/steps/"+str(i), 'r' )
				        datalist = openfile.readlines()
					for j in range( len( datalist ) ):
					    if (str.find(datalist[j], "INSTALL") > -1):
						install = datalist[j][8:]
						install = str.strip(install)
						packages.append(install)
					    if (str.find(datalist[j], "SOURCE") > -1):
						source = datalist[j][7:]
						source = source.rstrip()
						self.repositories.append(source)
					openfile.close()
			gladefile = "/usr/lib/linuxmint/mintInstall/frontend.glade"
                        builder = Gtk.Builder()
                        builder.add_from_file(gladefile)
			w = builder.get_object("more_info_window")
                        w.set_title(model.selected_application.name)
                        w.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
			builder.get_object("button_versions_close").connect("clicked", close_window, builder.get_object("more_info_window"))

			tree_repositories = builder.get_object("treeview_repositories")
			column1 = Gtk.TreeViewColumn(_("Repository"), Gtk.CellRendererText(), text=0)
			column1.set_sort_column_id(0)
			column1.set_resizable(True)
			tree_repositories.append_column(column1)
			tree_repositories.set_headers_clickable(True)
			tree_repositories.set_reorderable(False)
			tree_repositories.show()
			model_repositories = Gtk.TreeStore(str)
			if len(repositories) == 0:
				iter = model_repositories.insert_before(None, None)
				model_repositories.set_value(iter, 0, _("Default repositories"))
			for repository in repositories:
				iter = model_repositories.insert_before(None, None)
				model_repositories.set_value(iter, 0, repository)
			model_repositories.set_sort_column_id( 0, Gtk.SortType.ASCENDING )
			tree_repositories.set_model(model_repositories)
			del model_repositories

			tree_packages = builder.get_object("treeview_packages")
			column1 = Gtk.TreeViewColumn(_("Package"), Gtk.CellRendererText(), text=0)
			column1.set_sort_column_id(0)
			column1.set_resizable(True)
			column2 = Gtk.TreeViewColumn(_("Installed version"), Gtk.CellRendererText(), text=1)
			column2.set_sort_column_id(1)
			column2.set_resizable(True)
			column3 = Gtk.TreeViewColumn(_("Available version"), Gtk.CellRendererText(), text=2)
			column3.set_sort_column_id(2)
			column3.set_resizable(True)
			column4 = Gtk.TreeViewColumn(_("Size"), Gtk.CellRendererText(), text=3)
			column4.set_sort_column_id(3)
			column4.set_resizable(True)
			tree_packages.append_column(column1)
			tree_packages.append_column(column2)
			tree_packages.append_column(column3)
			tree_packages.append_column(column4)
			tree_packages.set_headers_clickable(True)
			tree_packages.set_reorderable(False)
			tree_packages.show()
			model_packages = Gtk.TreeStore(str, str, str, str)

			description = ""
			strSize = ""
			for package in packages:
				installedVersion = ""
				candidateVersion = ""
				try:
					global cacke
					pkg = cache[package]
					description = pkg.candidate.raw_description
					if pkg.installed is not None:
						installedVersion = pkg.installed.version
					if pkg.candidate is not None:
						candidateVersion = pkg.candidate.version
					size = int(pkg.candidate.size)
					strSize = str(size) + _("B")
					if (size >= 1000):
						strSize = str(size / 1000) + _("KB")
					if (size >= 1000000):
						strSize = str(size / 1000000) + _("MB")
					if (size >= 1000000000):
						strSize = str(size / 1000000000) + _("GB")
				except Exception, detail:
					print detail
				iter = model_packages.insert_before(None, None)
				model_packages.set_value(iter, 0, package)
				model_packages.set_value(iter, 1, installedVersion)
				model_packages.set_value(iter, 2, candidateVersion)
				model_packages.set_value(iter, 3, strSize)
			model_packages.set_sort_column_id( 0, Gtk.SortType.ASCENDING )
			tree_packages.set_model(model_packages)
			del model_packages

			builder.get_object("lbl_license").set_text(_("License:"))
			builder.get_object("lbl_homepage").set_text(_("Website") + ":")
			builder.get_object("lbl_portal").set_text(_("Portal URL") + ":")
			builder.get_object("lbl_description").set_text(_("Description:"))

			builder.get_object("txt_license").set_text(model.selected_application.license)
			builder.get_object("txt_description").set_text(description)
			builder.get_object("button_website").connect("clicked", visit_website, model, username)
			builder.get_object("button_website").set_label(model.selected_application.website)
			builder.get_object("button_portal").connect("clicked", visit_web, model, username)
			builder.get_object("button_portal").set_label(model.selected_application.link)
			builder.get_object("more_info_window").show_all()

def visit_web(widget, model, username):
	if model.selected_application != None:
		os.system("sudo -u " + username + " /usr/lib/linuxmint/common/launch_browser_as.py \"" + model.selected_application.link + "\"")

def visit_website(widget, model, username):
	if model.selected_application != None:
		os.system("sudo -u " + username + " /usr/lib/linuxmint/common/launch_browser_as.py \"" + model.selected_application.website + "\"")

def install(widget, model, builder, username):
	if model.selected_application != None:
		if model.selected_application.is_special:
			if not os.path.exists((model.selected_application.mint_file)):
				os.system("zenity --error --text=\"" + _("The mint file for this application was not successfully downloaded. Click on refresh to fix the problem.") + "\"")
			else:
				os.system("mintInstall " + model.selected_application.mint_file)
				show_item(builder.get_object("tree_applications").get_selection(), model, builder, username)
				global cache
				cache = apt.Cache()
				show_applications(builder, model, False)
		else:
			for package in model.selected_application.packages:
				if package not in model.packages_to_install:
					model.packages_to_install.append(package)
			model.selected_application.status = "add"
			builder.get_object("toolbutton_apply").set_sensitive(True)
			model_applications, iter = builder.get_object("tree_applications").get_selection().get_selected()
			model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/add.png"))
			model_applications.set_value(iter, 8, 1)
			show_item(builder.get_object("tree_applications").get_selection(), model, builder, username)


def remove(widget, model, builder, username):
	if model.selected_application != None:
		if model.selected_application.is_special:
			if not os.path.exists((model.selected_application.mint_file)):
				os.system("zenity --error --text=\"" + _("The mint file for this application was not successfully downloaded. Click on refresh to fix the problem.") + "\"")
			else:
				os.system("/usr/lib/linuxmint/mintInstall/remove.py " + model.selected_application.mint_file)
				show_item(builder.get_object("tree_applications").get_selection(), model, builder, username)
				global cache
				cache = apt.Cache()
				show_applications(builder, model, False)
		else:
			for package in model.selected_application.packages:
				if package not in model.packages_to_remove:
					model.packages_to_remove.append(package)
			model.selected_application.status = "remove"
			builder.get_object("toolbutton_apply").set_sensitive(True)
			model_applications, iter = builder.get_object("tree_applications").get_selection().get_selected()
			model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/remove.png"))
			model_applications.set_value(iter, 8, 2)
			show_item(builder.get_object("tree_applications").get_selection(), model, builder, username)

def cancel_change(widget, model, builder, username):
	if model.selected_application != None:
		model_applications, iter = builder.get_object("tree_applications").get_selection().get_selected()
		if model.selected_application.status == "add":
			for package in model.selected_application.packages:
				if package in model.packages_to_install:
					model.packages_to_install.remove(package)
			model.selected_application.status = "available"
			model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/available.png"))
			model_applications.set_value(iter, 8, 4)
		elif model.selected_application.status == "remove":
			for package in model.selected_application.packages:
				if package in model.packages_to_remove:
					model.packages_to_remove.remove(package)
			model.selected_application.status = "installed"
			model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/installed.png"))
			model_applications.set_value(iter, 8, 3)

		if len(model.packages_to_install) == 0 and len(model.packages_to_remove) == 0:
			builder.get_object("toolbutton_apply").set_sensitive(False)

		show_item(builder.get_object("tree_applications").get_selection(), model, builder, username)

def apply(widget, model, builder, username):
	builder.get_object("main_window").window.set_cursor(GdkCursor(Gdk.CursorType.WATCH))
	builder.get_object("main_window").set_sensitive(False)
	cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window", "--non-interactive"]
	cmd.append("--progress-str")
	cmd.append("\"" + _("Please wait, this can take some time") + "\"")
	cmd.append("--finish-str")
	cmd.append("\"" + _("The changes are complete") + "\"")

	f = tempfile.NamedTemporaryFile()

	for pkg in model.packages_to_install:
	    f.write("%s\tinstall\n" % pkg.name)
	for pkg in model.packages_to_remove:
	    f.write("%s\tdeinstall\n" % pkg.name)

	cmd.append("--set-selections-file")
	cmd.append("%s" % f.name)
	f.flush()
	comnd = Popen(' '.join(cmd), shell=True)
	returnCode = comnd.wait()
        #sts = os.waitpid(comnd.pid, 0)
	f.close()

	model.packages_to_install = []
	model.packages_to_remove = []

	builder.get_object("main_window").window.set_cursor(None)
	builder.get_object("main_window").set_sensitive(True)
	builder.get_object("toolbutton_apply").set_sensitive(False)

	global cache
	cache = apt.Cache()

	fetch_apt_details(model)
	show_applications(builder, model, True)


def show_applications(builder, model, scrollback):

	matching_statuses = []
	if model.filter_applications == "available":
		matching_statuses.append("available")
		matching_statuses.append("add")
		matching_statuses.append("special")
	elif model.filter_applications == "installed":
		matching_statuses.append("installed")
		matching_statuses.append("remove")
	elif model.filter_applications == "changes":
		matching_statuses.append("add")
		matching_statuses.append("remove")
	elif model.filter_applications == "all":
		matching_statuses.append("available")
		matching_statuses.append("installed")
		matching_statuses.append("special")
		matching_statuses.append("add")
		matching_statuses.append("remove")
	global num_apps
	num_apps = 0
	category_keys = []
	if (model.selected_category == None):
		#The All category is selected
		for portal in model.portals:
			for category in portal.categories:
				category_keys.append(category.key)
	else:
		category_keys.append(model.selected_category.key)
		for subcategory in model.selected_category.subcategories:
			category_keys.append(subcategory.key)

	tree_applications = builder.get_object("tree_applications")
	new_selection = None
	model_applications = Gtk.TreeStore(str, str, int, int, str, object, int, GdkPixbuf.Pixbuf, int)
	for portal in model.portals:
		for item in portal.items:
			if (item.category.key in category_keys):
				if item.status in matching_statuses and (model.keyword == None
					or item.name.upper().count(model.keyword.upper()) > 0
					or item.description.upper().count(model.keyword.upper()) > 0
					or item.long_description.upper().count(model.keyword.upper()) > 0):
					iter = model_applications.insert_before(None, None)
					model_applications.set_value(iter, 0, item.name)
					model_applications.set_value(iter, 1, item.average_rating)
					model_applications.set_value(iter, 2, len(item.reviews))
					model_applications.set_value(iter, 3, item.views)
					model_applications.set_value(iter, 4, item.added)
					model_applications.set_value(iter, 5, item)
					model_applications.set_value(iter, 6, float(item.average_rating) * len(item.reviews) + (item.views / 1000))
					if item.is_special:
						model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/special.png"))
						model_applications.set_value(iter, 8, 9)

					else:
						if item.status == "available":
							model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/available.png"))
							model_applications.set_value(iter, 8, 4)
						elif item.status == "installed":
							model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/installed.png"))
							model_applications.set_value(iter, 8, 3)
						elif item.status == "add":
							model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/add.png"))
							model_applications.set_value(iter, 8, 1)
						elif item.status == "remove":
							model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/remove.png"))
							model_applications.set_value(iter, 8, 2)

					if model.selected_application == item:
						new_selection = iter

					num_apps = num_apps + 1
	model_applications.set_sort_column_id( 6, Gtk.SortType.DESCENDING )
	tree_applications.set_model(model_applications)
	if scrollback:
		first = model_applications.get_iter_first()
		if (first != None):
			tree_applications.get_selection().select_iter(first)
			tree_applications.scroll_to_cell(model_applications.get_path(first))
	else:
		if new_selection is not None:
			tree_applications.get_selection().select_iter(new_selection)
			tree_applications.scroll_to_cell(model_applications.get_path(new_selection))
	del model_applications
	update_statusbar(builder, model)

def update_statusbar(builder, model):
	global num_apps
	statusbar = builder.get_object("statusbar")
	context_id = statusbar.get_context_id("mintInstall")
	statusbar.push(context_id,  _("%(applications)d applications listed, %(install)d to install, %(remove)d to remove") % {'applications':num_apps, 'install':len(model.packages_to_install), 'remove':len(model.packages_to_remove)})

def filter_applications(combo, builder, model):
	combomodel = combo.get_model()
	comboindex = combo.get_active()
        model.filter_applications = combomodel[comboindex][1]
	show_applications(builder, model, True)

def build_GUI(model, username):

	#Set the Glade file
	gladefile = "/usr/lib/linuxmint/mintInstall/frontend.ui"
        builder = Gtk.Builder()
        builder.add_from_file(gladefile)
	w = builder.get_object("main_window")
        w.set_title(_("Software Manager"))
        w.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
        w.connect("delete_event", close_application)

	builder.get_object("image_screenshot").clear()

	#i18n
	builder.get_object("label5").set_text(_("Quick search:"))
	builder.get_object("label2").set_text(_("More info"))
	builder.get_object("label1").set_text(_("Show:"))
	builder.get_object("button_search_online").set_label(_("Search"))

	builder.get_object("lbl_featured").set_label(_("Featured applications"))

	# Filter
	model.filter_applications = "all"
	combo = builder.get_object("filter_combo")
	store = Gtk.ListStore(str, str)
	store.append([_("All software"), "all"])
	store.append([_("Available software"), "available"])
	store.append([_("Installed software"), "installed"])
	store.append([_("Your changes"), "changes"])
	combo.set_model(store)
	combo.set_active(0)
	combo.connect('changed', filter_applications, builder, model)

	# Build categories tree
	tree_categories = builder.get_object("tree_categories")
	pix = Gtk.CellRendererPixbuf()
	pix.set_property('xalign', 0.0)
	column1 = Gtk.TreeViewColumn(_("Category"), pix, pixbuf=2)
	column1.set_alignment(0.0)
	cell = Gtk.CellRendererText()
	column1.pack_start(cell, True)
	column1.add_attribute(cell, 'text', 0)
	cell.set_property('xalign', 0.1)

	tree_categories.append_column(column1)
	tree_categories.set_headers_clickable(True)
	tree_categories.set_reorderable(False)
	tree_categories.show()
	model_categories = Gtk.TreeStore(str, object)
	tree_categories.set_model(model_categories)
	del model_categories

	#Build applications table
	tree_applications = builder.get_object("tree_applications")
	column1 = Gtk.TreeViewColumn(_("Application"), Gtk.CellRendererText(), text=0)
	column1.set_sort_column_id(0)
	column1.set_resizable(True)

	column2 = Gtk.TreeViewColumn(_("Average rating"), Gtk.CellRendererText(), text=1)
	column2.set_sort_column_id(1)
	column2.set_resizable(True)

	column3 = Gtk.TreeViewColumn(_("Reviews"), Gtk.CellRendererText(), text=2)
	column3.set_sort_column_id(2)
	column3.set_resizable(True)

	column4 = Gtk.TreeViewColumn(_("Views"), Gtk.CellRendererText(), text=3)
	column4.set_sort_column_id(3)
	column4.set_resizable(True)

	column5 = Gtk.TreeViewColumn(_("Added"), Gtk.CellRendererText(), text=4)
	column5.set_sort_column_id(4)
	column5.set_resizable(True)

	column6 = Gtk.TreeViewColumn(_("Score"), Gtk.CellRendererText(), text=6)
	column6.set_sort_column_id(6)
	column6.set_resizable(True)

	column7 = Gtk.TreeViewColumn(_("Status"), Gtk.CellRendererPixbuf(), pixbuf=7)
	column7.set_sort_column_id(8)
	column7.set_resizable(True)

	tree_applications.append_column(column7)
	tree_applications.append_column(column6)
	tree_applications.append_column(column1)
	tree_applications.append_column(column2)
	tree_applications.append_column(column3)
	tree_applications.append_column(column4)
	tree_applications.append_column(column5)
	tree_applications.set_headers_clickable(True)
	tree_applications.set_reorderable(False)
	tree_applications.show()
	model_applications = Gtk.TreeStore(str, int, int, int, str, object, int, GdkPixbuf.Pixbuf, int)
	tree_applications.set_model(model_applications)
	del model_applications

	tree_applications.connect("row_activated", show_more_info_wrapper, model)

	#Build reviews table
	tree_reviews = builder.get_object("tree_reviews")
	column1 = Gtk.TreeViewColumn(_("Reviewer"), Gtk.CellRendererText(), text=0)
	column1.set_sort_column_id(0)
	column1.set_resizable(True)

	column2 = Gtk.TreeViewColumn(_("Rating"), Gtk.CellRendererText(), text=1)
	column2.set_sort_column_id(1)
	column2.set_resizable(True)

	column3 = Gtk.TreeViewColumn(_("Review"), Gtk.CellRendererText(), text=2)
	column3.set_sort_column_id(2)
	column3.set_resizable(True)

	tree_reviews.append_column(column1)
	tree_reviews.append_column(column2)
	tree_reviews.append_column(column3)

	tree_reviews.set_headers_clickable(True)
	tree_reviews.set_reorderable(False)
	tree_reviews.show()
	model_reviews = Gtk.TreeStore(str, int, str, object)
	tree_reviews.set_model(model_reviews)
	del model_reviews

	selection = tree_applications.get_selection()
	selection.connect("changed", show_item, model, builder, username)

	entry_search = builder.get_object("entry_search")
	entry_search.connect("changed", filter_search, builder, model)

	builder.get_object("button_search_online").connect("clicked", open_search, username)
	builder.get_object("button_feature").connect("clicked", open_featured)
	builder.get_object("button_screenshot").connect("clicked", show_screenshot, model)
	builder.get_object("button_install").connect("clicked", install, model, builder, username)
	builder.get_object("button_remove").connect("clicked", remove, model, builder, username)
	builder.get_object("button_cancel_change").connect("clicked", cancel_change, model, builder, username)
	builder.get_object("button_show").connect("clicked", show_more_info, model)

	builder.get_object("toolbutton_apply").connect("clicked", apply, model, builder, username)

	fileMenu = Gtk.MenuItem(_("_File"))
	fileSubmenu = Gtk.Menu()
	fileMenu.set_submenu(fileSubmenu)
	closeMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_CLOSE)
	closeMenuItem.get_child().set_text(_("Quit"))
	closeMenuItem.connect("activate", close_application)
	fileSubmenu.append(closeMenuItem)
	closeMenuItem.show()

	editMenu = Gtk.MenuItem(_("_Edit"))
	editSubmenu = Gtk.Menu()
	editMenu.set_submenu(editSubmenu)
	cancelMenuItem = Gtk.MenuItem(_("Cancel all changes"))
	cancelMenuItem.connect("activate", cancel_changes, builder, model)
	editSubmenu.append(cancelMenuItem)
	cancelMenuItem.show()

	helpMenu = Gtk.MenuItem(_("_Help"))
	helpSubmenu = Gtk.Menu()
	helpMenu.set_submenu(helpSubmenu)
	aboutMenuItem = Gtk.ImageMenuItem(Gtk.STOCK_ABOUT)
	aboutMenuItem.get_child().set_text(_("About"))
	aboutMenuItem.show()
	aboutMenuItem.connect("activate", open_about)
	helpSubmenu.append(aboutMenuItem)
        fileMenu.show()
	editMenu.show()
	helpMenu.show()
	builder.get_object("menubar1").append(fileMenu)
	builder.get_object("menubar1").append(editMenu)
	builder.get_object("menubar1").append(helpMenu)

	return builder

def cancel_changes(widget, builder, model):
	for portal in model.portals:
		for item in portal.items:
			if item.status == "add":
				item.status = "available"
			elif item.status == "remove":
				item.status = "installed"
	model.packages_to_install = []
	model.packages_to_remove = []
	builder.get_object("toolbutton_apply").set_sensitive(False)
	show_applications(builder, model, True)

def open_about(widget):
	dlg = Gtk.AboutDialog()
	dlg.set_version(commands.getoutput("/usr/lib/linuxmint/common/version.py mintinstall"))
	dlg.set_name("mintInstall")
	dlg.set_comments(_("Software manager"))
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
        dlg.set_authors(["Clement Lefebvre <root@linuxmint.com>"])
	dlg.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	dlg.set_logo(GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/icon.svg"))
        def close(w, res):
            if res == Gtk.ResponseType.CANCEL:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

class DownloadScreenshot(threading.Thread):

	def __init__(self, selected_item, builder, model):
		threading.Thread.__init__(self)
		self.selected_item = selected_item
		self.builder = builder
		self.model = model

	def run(self):
		try:
			import urllib
			urllib.urlretrieve (self.selected_item.screenshot_url, "/usr/share/linuxmint/mintinstall/data/screenshots/" + self.selected_item.key)
			Gdk.threads_enter()
			if (self.model.selected_application == self.selected_item):
				self.builder.get_object("image_screenshot").set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(self.selected_item.screenshot, 200, 200))
			Gdk.threads_leave()
		except Exception, detail:
			pass

class RefreshThread(threading.Thread):

	def __init__(self, builder, refresh, model, username):
		threading.Thread.__init__(self)
		self.builder = builder
		self.refresh = refresh
		self.directory = "/usr/share/linuxmint/mintinstall/data"
		self.model = model
		self.username = username

	def run(self):
		try:

			self.initialize()
			del self.model.portals[:]
			self.model = self.register_portals(self.model)
			Gdk.threads_enter()
			self.builder.get_object("main_window").set_sensitive(False)
			self.builder.get_object("main_window").window.set_cursor(Gdk.Cursor(Gdk.CursorType.WATCH))
			Gdk.threads_leave()
			if (self.refresh):
				for portal in self.model.portals:
					self.download_portal(portal)
			try:
				global num_apps
				num_apps = 0
				for portal in self.model.portals:
					self.build_portal(self.model, portal)
					num_apps = num_apps + len(portal.items)

				# Reconciliation of categories hierarchy
				for portal in self.model.portals:
					for category in portal.categories:
						if (category.parent == "0"):
							category.parent = None
						else:
							parentKey = category.parent
							parent = portal.find_category(parentKey)
							parent.add_subcategory(category)

				Gdk.threads_enter()
				update_statusbar(builder, model)
				Gdk.threads_leave()
			except Exception, details:
				print details
				allPortalsHere = True
				for portal in model.portals:
					if not os.path.exists(self.directory + "/xml/" + portal.key + ".xml"):
						allPortalsHere = False
				if allPortalsHere:
					print details
					os.system("zenity --error --text=\"" + _("The data used by mintInstall is corrupted or out of date. Click on refresh to fix the problem :") + " " + str(details) + "\"")
				else:
					Gdk.threads_enter()
					dialog = Gtk.MessageDialog(self.builder.get_object("main_window"), Gtk.DialogFlags.MODAL, Gtk.MessageType.INFO, Gtk.ButtonType.NONE, _("Please refresh mintInstall by clicking on the Refresh button"))
					dialog.set_title("mintInstall")
					dialog.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
					dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
					dialog.connect('response', lambda dialog, response: dialog.destroy())
					dialog.show()
					Gdk.threads_leave()

				del self.model.portals[:]
				self.model = self.register_portals(self.model)

			Gdk.threads_enter()
			self.load_model_in_GUI(self.builder, self.model)
			self.builder.get_object("main_window").window.set_cursor(None)
			self.builder.get_object("main_window").set_sensitive(True)
			Gdk.threads_leave()
		except Exception, detail:
			print detail

	def initialize(self):
		#if self.refresh:
		#	os.system("rm -rf " + self.directory + "/tmp/*")
		os.system("mkdir -p " + self.directory + "/icons/categories")
		os.system("mkdir -p " + self.directory + "/mintfiles")
		os.system("mkdir -p " + self.directory + "/screenshots")
		os.system("mkdir -p " + self.directory + "/xml")
		#os.system("mkdir -p " + self.directory + "/etc")
		#if not os.path.exists(self.directory + "/etc/portals.list"):
		#	os.system("cp /etc/linuxmint/version/mintinstall/portals.list " + self.directory + "/etc/portals.list")

	def register_portals(self, model):
		portalsFile = open("/usr/share/linuxmint/mintinstall/portals.list")
		for line in portalsFile:
			array = line.split(";")
			if len(array) == 6:
				portal = Classes.Portal(array[0], array[1], array[2], array[3], array[4], array[5])
				model.portals.append(portal)
		portalsFile.close()
		return model

	def download_portal(self, portal):
		Gdk.threads_enter()
		statusbar = builder.get_object("statusbar")
		context_id = statusbar.get_context_id("mintInstall")
		portal.update_url = portal.update_url.strip()
		statusbar.push(context_id, _("Downloading data for %s") % (portal.name))
		Gdk.threads_leave()
		webFile = urllib.urlopen(portal.update_url)
		localFile = open(self.directory + "/xml/" + portal.key + ".xml", 'w')
		localFile.write(webFile.read())
		webFile.close()
		localFile.close()

	def build_portal(self, model, portal):
		fileName = self.directory + "/xml/" + portal.key + ".xml"
		numItems = commands.getoutput("grep -c \"<item\" " + fileName)
		numReviews = commands.getoutput("grep -c \"<review\" " + fileName)
		numScreenshots = commands.getoutput("grep -c \"<screenshot\" " + fileName)
		numCategories = commands.getoutput("grep -c \"<category\" " + fileName)
		numTotal = int(numItems) + int(numReviews) + int(numScreenshots) + int(numCategories)
		progressbar = builder.get_object("progressbar")
		progressbar.set_fraction(0)
		progressbar.set_text("0%")
		processed_categories = 0
		processed_items = 0
		processed_screenshots = 0
		processed_reviews = 0
		processed_total = 0
		xml = ET.parse(fileName)
		root = xml.getroot()
		Gdk.threads_enter()
		statusbar = builder.get_object("statusbar")
		context_id = statusbar.get_context_id("mintInstall")
		Gdk.threads_leave()
		for element in root:
			if element.tag == "category":
				category = Classes.Category(portal, element.attrib["id"], element.attrib["name"], element.attrib["description"], element.attrib["vieworder"], element.attrib["parent"], element.attrib["logo"])
				category.name = category.name.replace("ANDAND", "&")
				if self.refresh:
					os.chdir(self.directory + "/icons/categories")
					os.system("wget -nc -O" + category.key + " " + category.logo)
					os.chdir("/usr/lib/linuxmint/mintInstall")
				category.logo = GdkPixbuf.Pixbuf.new_from_file_at_size(self.directory + "/icons/categories/" + category.key, 16, 16)
				category.name = _(category.name)
				portal.categories.append(category)
				Gdk.threads_enter()
				processed_categories = int(processed_categories) + 1
				statusbar.push(context_id, _("%d categories loaded") % processed_categories)
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				Gdk.threads_leave()

			elif element.tag == "item":
				item = Classes.Item(portal, element.attrib["id"], element.attrib["link"], element.attrib["mint_file"], element.attrib["category"], element.attrib["name"], element.attrib["description"], "", element.attrib["added"], element.attrib["views"], element.attrib["license"], element.attrib["size"], element.attrib["website"], element.attrib["repository"], element.attrib["average_rating"])
				item.average_rating = item.average_rating[:3]
				if item.average_rating.endswith("0"):
					item.average_rating = item.average_rating[0]
				item.views = int(item.views)
				item.link = item.link.replace("ANDAND", "&")
				if self.refresh:
					os.chdir(self.directory + "/mintfiles")
					os.system("wget -nc -O" + item.key + ".mint -T10 \"" + item.mint_file + "\"")
					os.chdir("/usr/lib/linuxmint/mintInstall")
				item.mint_file = self.directory + "/mintfiles/" + item.key + ".mint"

				if item.repository == "":
					item.repository = _("Default repositories")
				portal.items.append(item)
				portal.find_category(item.category).add_item(item)
				Gdk.threads_enter()
				processed_items = int(processed_items) + 1
				statusbar.push(context_id, _("%d applications loaded") % processed_items)
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				Gdk.threads_leave()

			elif element.tag == "screenshot":
				screen_item = element.attrib["item"]
				screen_img = element.attrib["img"]
				item = portal.find_item(screen_item)
				if item != None:
					try:
						if self.refresh:
							os.chdir(self.directory + "/screenshots")
							os.system("wget -nc -O" + screen_item + " -T10 \"" + screen_img + "\"")
							os.chdir("/usr/lib/linuxmint/mintInstall")
						item.screenshot = self.directory + "/screenshots/" + screen_item
						item.screenshot_url = screen_img
						Gdk.threads_enter()
						processed_screenshots = int(processed_screenshots) + 1
						statusbar.push(context_id, _("%d screenshots loaded") % processed_screenshots)
						Gdk.threads_leave()
					except:
						pass
				Gdk.threads_enter()
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				Gdk.threads_leave()

			elif element.tag == "review":
				item = portal.find_item(element.attrib["item"])
				if (item != None):
					review = Classes.Review(portal, item, element.attrib["rating"], element.attrib["comment"], element.attrib["user_id"], element.attrib["user_name"])
					if "@" in review.username:
						elements = review.username.split("@")
						firstname = elements[0]
						secondname = elements[1]
						firstname = firstname[0:1] + "..." + firstname [-2:-1]
						review.username = firstname + "@" + secondname
					review.rating = int(review.rating)
					item.add_review(review)
					portal.reviews.append(review)
					Gdk.threads_enter()
					processed_reviews = int(processed_reviews) + 1
					statusbar.push(context_id, _("%d reviews loaded") % processed_reviews)
					Gdk.threads_leave()

				Gdk.threads_enter()
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				Gdk.threads_leave()

		fetch_apt_details(model)

		Gdk.threads_enter()
		progressbar.set_fraction(0)
		progressbar.set_text("")
		Gdk.threads_leave()

	def load_model_in_GUI(self, builder, model):
		# Build categories tree
		tree_categories = builder.get_object("tree_categories")
		model_categories = Gtk.TreeStore(str, object, GdkPixbuf.Pixbuf)
		#Add the "All" category
		iter = model_categories.insert_before(None, None)
		model_categories.set_value(iter, 0, _("All applications"))
		model_categories.set_value(iter, 1, None)
		model_categories.set_value(iter, 2, GdkPixbuf.Pixbuf.new_from_file_at_size("/usr/lib/linuxmint/mintInstall/icon.svg", 16, 16))
		for portal in model.portals:
			for category in portal.categories:
				if (category.parent == None or category.parent == "None"):
					iter = model_categories.insert_before(None, None)
					model_categories.set_value(iter, 0, category.name)
					model_categories.set_value(iter, 1, category)
					model_categories.set_value(iter, 2, category.logo)
					for subcategory in category.subcategories:
						subiter = model_categories.insert_before(iter, None)
						model_categories.set_value(subiter, 0, subcategory.name)
						model_categories.set_value(subiter, 1, subcategory)
						model_categories.set_value(subiter, 2, subcategory.logo)
		tree_categories.set_model(model_categories)
		del model_categories
		selection = tree_categories.get_selection()
		selection.connect("changed", show_category, model, builder)

		#Build applications table
		tree_applications = builder.get_object("tree_applications")
		model_applications = Gtk.TreeStore(str, str, int, int, str, object, int, GdkPixbuf.Pixbuf, int)
		for portal in model.portals:
			for item in portal.items:
				iter = model_applications.insert_before(None, None)
				model_applications.set_value(iter, 0, item.name)
				model_applications.set_value(iter, 1, item.average_rating)
				model_applications.set_value(iter, 2, len(item.reviews))
				model_applications.set_value(iter, 3, item.views)
				model_applications.set_value(iter, 4, item.added)
				model_applications.set_value(iter, 5, item)
				model_applications.set_value(iter, 6, float(item.average_rating) * len(item.reviews) + (item.views / 1000))
				if item.is_special:
					model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/special.png"))
					model_applications.set_value(iter, 8, 9)
				else:
					if item.status == "available":
						model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/available.png"))
						model_applications.set_value(iter, 8, 4)
					elif item.status == "installed":
						model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/installed.png"))
						model_applications.set_value(iter, 8, 3)
					elif item.status == "add":
						model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/add.png"))
						model_applications.set_value(iter, 8, 1)
					elif item.status == "remove":
						model_applications.set_value(iter, 7, GdkPixbuf.Pixbuf.new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/remove.png"))
						model_applications.set_value(iter, 8, 2)
		model_applications.set_sort_column_id( 6, Gtk.SortType.DESCENDING )
		tree_applications.set_model(model_applications)
		first = model_applications.get_iter_first()
		if (first != None):
			tree_applications.get_selection().select_iter(first)
		del model_applications

if __name__ == "__main__":
	#i18n (force categories to make it to the pot file)
	i18n = _("Games")
	i18n = _("First person shooters")
	i18n = _("Turn-based strategy")
	i18n = _("Real time strategy")
	i18n = _("Internet")
	i18n = _("Emulators")
	i18n = _("Simulation & racing")
	i18n = _("Email")
	i18n = _("Accessories")
	i18n = _("Text editors")
	i18n = _("Sound & Video")
	i18n = _("Audio players")
	i18n = _("Video players")
	i18n = _("Burning tools")
	i18n = _("Office")
	i18n = _("Office suites")
	i18n = _("Collection managers")
	i18n = _("Document viewers")
	i18n = _("Finance")
	i18n = _("Graphics")
	i18n = _("2D")
	i18n = _("Image viewers")
	i18n = _("Photo")
	i18n = _("Scanning tools")
	i18n = _("Tools")
	i18n = _("Web browsers")
	i18n = _("Word processors")
	i18n = _("Spreadsheets")
	i18n = _("Publishing")
	i18n = _("Graph and flowcharts")
	i18n = _("Databases")
	i18n = _("Mind mapping")
	i18n = _("Instant messengers")
	i18n = _("Internet Relay Chat")
	i18n = _("Programming")
	i18n = _("Education")
	i18n = _("System Tools")
	i18n = _("FTP")
	i18n = _("Desktop components")
	i18n = _("Package management")
	i18n = _("P2P and torrent")
	i18n = _("Firewall")
	i18n = _("Drivers")
	i18n = _("Upstream")

	username = sys.argv[1]
	os.system("sudo -u " + username + " xhost +root")
	model = Classes.Model()
	builder = build_GUI(model, username)
	refresh = RefreshThread(builder, False, model, username)
	refresh.start()
	Gtk.main()
