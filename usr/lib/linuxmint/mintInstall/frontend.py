#!/usr/bin/python

import urllib
import Classes
from xml.etree import ElementTree as ET
from user import home
import os
import commands
import gtk
import gtk.glade
import pygtk
import sys
import threading
import gettext
import tempfile
pygtk.require("2.0")

from subprocess import Popen, PIPE

gtk.gdk.threads_init()

# i18n
gettext.install("messages", "/usr/lib/linuxmint/mintInstall/locale")

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

def close_application(window, event=None):	
	gtk.main_quit()
	sys.exit(0)

def close_window(widget, window):	
	window.hide_all()

def show_item(selection, model, wTree, username):
	(model_applications, iter) = selection.get_selected()
	if (iter != None):
		wTree.get_widget("button_install").hide()
		wTree.get_widget("button_remove").hide()
		wTree.get_widget("label_install").set_text(_("Install"))
		wTree.get_widget("label_install").set_tooltip_text("")
		wTree.get_widget("label_remove").set_text(_("Remove"))
		wTree.get_widget("label_remove").set_tooltip_text("")
		selected_item = model_applications.get_value(iter, 5)
		model.selected_application = selected_item		
		if selected_item.version == "":
			wTree.get_widget("label_name").set_text("<b>" + selected_item.name + "</b>")
			wTree.get_widget("label_name").set_tooltip_text(selected_item.name)
		else:
			version = selected_item.version.split("+")[0]
			version = version.split("-")[0]
			wTree.get_widget("label_name").set_text("<b>" + selected_item.name + "</b> [" + version + "]")
			wTree.get_widget("label_name").set_tooltip_text(selected_item.name + " [" + selected_item.version + "]")		
		wTree.get_widget("label_name").set_use_markup(True)
		wTree.get_widget("label_description").set_text("<i>" + selected_item.description + "</i>")
		wTree.get_widget("label_description").set_use_markup(True)		
		str_size = str(selected_item.size) + _("MB")		
		if selected_item.size == "0" or selected_item.size == 0:						
			str_size = "--"
		wTree.get_widget("image_screenshot").clear()
		if (selected_item.screenshot != None):
			if (os.path.exists(selected_item.screenshot)):
				try:
					wTree.get_widget("image_screenshot").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(selected_item.screenshot, 200, 200))
				except Exception, detail:
					print detail
			else:							
				downloadScreenshot = DownloadScreenshot(selected_item, wTree, model)
				downloadScreenshot.start()				
			
		tree_reviews = wTree.get_widget("tree_reviews")
		model_reviews = gtk.TreeStore(str, int, str, object)
		for review in selected_item.reviews:
			iter = model_reviews.insert_before(None, None)						
			model_reviews.set_value(iter, 0, review.username)						
			model_reviews.set_value(iter, 1, review.rating)
			model_reviews.set_value(iter, 2, review.comment)
			model_reviews.set_value(iter, 3, review)
		model_reviews.set_sort_column_id( 1, gtk.SORT_DESCENDING )
		tree_reviews.set_model(model_reviews)	

		first = model_reviews.get_iter_first()
		if (first != None):
			tree_reviews.get_selection().select_iter(first)
			tree_reviews.scroll_to_cell(model_reviews.get_path(first))
					
		del model_reviews			
		if selected_item.is_special:
			wTree.get_widget("button_install").show()
		else:
			if selected_item.status == "available":
				wTree.get_widget("button_install").show()
			elif selected_item.status == "installed": 					
				wTree.get_widget("button_remove").show()

def show_category(selection, model, wTree):	
	(model_categories, iter) = selection.get_selected()
	if (iter != None):
		selected_category = model_categories.get_value(iter, 1)
		model.selected_category = selected_category
		show_applications(wTree, model, True)					

def filter_search(widget, wTree, model):
	keyword = widget.get_text()
	model.keyword = keyword
	show_applications(wTree, model, True)	

def open_search(widget, username):
	os.system("/usr/lib/linuxmint/mintInstall/mintInstall.py " + username + " &")

def open_featured(widget):
	gladefile = "/usr/lib/linuxmint/mintInstall/frontend.glade"
	wTree = gtk.glade.XML(gladefile, "featured_window")
	treeview_featured = wTree.get_widget("treeview_featured")
	wTree.get_widget("featured_window").set_title(_("Featured applications"))
	wTree.get_widget("featured_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")	
	wTree.get_widget("button_close").connect("clicked", close_window, wTree.get_widget("featured_window"))
	wTree.get_widget("button_apply").connect("clicked", install_featured, wTree, treeview_featured, wTree.get_widget("featured_window"))		
	wTree.get_widget("featured_window").show_all()	

	wTree.get_widget("lbl_intro").set_label(_("These popular applications can be installed on your system:"))

	# the treeview 
	cr = gtk.CellRendererToggle()
	cr.connect("toggled", toggled, treeview_featured)
	column1 = gtk.TreeViewColumn(_("Install"), cr)
	column1.set_cell_data_func(cr, celldatafunction_checkbox)
	column1.set_sort_column_id(1)
	column1.set_resizable(True)  
	column2 = gtk.TreeViewColumn(_("Application"), gtk.CellRendererText(), text=2)
	column2.set_sort_column_id(2)
	column2.set_resizable(True)  
	column3 = gtk.TreeViewColumn(_("Icon"), gtk.CellRendererPixbuf(), pixbuf=3)
	column3.set_sort_column_id(3)
	column3.set_resizable(True)  	
	column4 = gtk.TreeViewColumn(_("Description"), gtk.CellRendererText(), text=4)
	column4.set_sort_column_id(4)
	column4.set_resizable(True)  
	column5 = gtk.TreeViewColumn(_("Size"), gtk.CellRendererText(), text=5)
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

	model = gtk.TreeStore(str, str, str, gtk.gdk.Pixbuf, str, str)
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
				
				if ((not pkg.isInstalled) and (pkg.summary != "")):
					strSize = str(pkg.candidateInstalledSize) + _("B")
					if (pkg.candidateInstalledSize >= 1000):
						strSize = str(pkg.candidateInstalledSize / 1000) + _("KB")
					if (pkg.candidateInstalledSize >= 1000000):
						strSize = str(pkg.candidateInstalledSize / 1000000) + _("MB")
					if (pkg.candidateInstalledSize >= 1000000000):
						strSize = str(pkg.candidateInstalledSize / 1000000000) + _("GB")
					iter = model.insert_before(None, None)						
					model.set_value(iter, 0, application_pkg)
					model.set_value(iter, 1, "false")
					model.set_value(iter, 2, application_name)
					model.set_value(iter, 3, gtk.gdk.pixbuf_new_from_file("/usr/share/linuxmint/mintinstall/featured_applications/" + application_icon))						
					model.set_value(iter, 4, pkg.summary)
					model.set_value(iter, 5, strSize)

			except Exception, detail:
				#Package isn't in repositories
				print detail				

	treeview_featured.set_model(model)
	del model

def install_featured(widget, wTree, treeview_featured, window):
	vbox = wTree.get_widget("vbox1")
	socket = gtk.Socket()
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
		wTree = gtk.glade.XML(gladefile, "screenshot_window")
		wTree.get_widget("screenshot_window").set_title(model.selected_application.name)
		wTree.get_widget("screenshot_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
		wTree.get_widget("screenshot_window").connect("delete_event", close_window, wTree.get_widget("screenshot_window"))
		wTree.get_widget("button_screen_close").connect("clicked", close_window, wTree.get_widget("screenshot_window"))
		wTree.get_widget("image_screen").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file(model.selected_application.screenshot))	
		wTree.get_widget("button_screen").connect("clicked", close_window, wTree.get_widget("screenshot_window"))	
		wTree.get_widget("screenshot_window").show_all()

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
						if not pkg.isInstalled:
							item.status = "available"
							item.version = pkg.candidateVersion
						else:
							item.version = pkg.installedVersion
						item.packages.append(pkg)
						item.is_special = False
						item.long_description = pkg.rawDescription
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
			wTree = gtk.glade.XML(gladefile, "more_info_window")
			wTree.get_widget("more_info_window").set_title(model.selected_application.name)
			wTree.get_widget("more_info_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
			wTree.get_widget("button_versions_close").connect("clicked", close_window, wTree.get_widget("more_info_window"))

			tree_repositories = wTree.get_widget("treeview_repositories")
			column1 = gtk.TreeViewColumn(_("Repository"), gtk.CellRendererText(), text=0)
			column1.set_sort_column_id(0)
			column1.set_resizable(True)
			tree_repositories.append_column(column1)
			tree_repositories.set_headers_clickable(True)
			tree_repositories.set_reorderable(False)
			tree_repositories.show()
			model_repositories = gtk.TreeStore(str)
			if len(repositories) == 0:
				iter = model_repositories.insert_before(None, None)						
				model_repositories.set_value(iter, 0, _("Default repositories"))	
			for repository in repositories:				
				iter = model_repositories.insert_before(None, None)						
				model_repositories.set_value(iter, 0, repository)						
			model_repositories.set_sort_column_id( 0, gtk.SORT_ASCENDING )	
			tree_repositories.set_model(model_repositories)
			del model_repositories	

			tree_packages = wTree.get_widget("treeview_packages")
			column1 = gtk.TreeViewColumn(_("Package"), gtk.CellRendererText(), text=0)
			column1.set_sort_column_id(0)
			column1.set_resizable(True)
			column2 = gtk.TreeViewColumn(_("Installed version"), gtk.CellRendererText(), text=1)
			column2.set_sort_column_id(1)
			column2.set_resizable(True)
			column3 = gtk.TreeViewColumn(_("Available version"), gtk.CellRendererText(), text=2)
			column3.set_sort_column_id(2)
			column3.set_resizable(True)
			column4 = gtk.TreeViewColumn(_("Size"), gtk.CellRendererText(), text=3)
			column4.set_sort_column_id(3)
			column4.set_resizable(True)
			tree_packages.append_column(column1)
			tree_packages.append_column(column2)
			tree_packages.append_column(column3)
			tree_packages.append_column(column4)
			tree_packages.set_headers_clickable(True)
			tree_packages.set_reorderable(False)
			tree_packages.show()
			model_packages = gtk.TreeStore(str, str, str, str)

			description = ""
			strSize = ""	
			for package in packages:
				installedVersion = ""
				candidateVersion = ""
				try:
					global cacke
					pkg = cache[package]
					description = pkg.rawDescription
					installedVersion = pkg.installedVersion	
					candidateVersion = pkg.candidateVersion				
					size = int(pkg.packageSize)
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
			model_packages.set_sort_column_id( 0, gtk.SORT_ASCENDING )		
			tree_packages.set_model(model_packages)
			del model_packages	

			wTree.get_widget("lbl_license").set_text(_("License:"))
			wTree.get_widget("lbl_homepage").set_text(_("Website") + ":")
			wTree.get_widget("lbl_portal").set_text(_("Portal URL") + ":")
			wTree.get_widget("lbl_description").set_text(_("Description:"))

			wTree.get_widget("txt_license").set_text(model.selected_application.license)
			wTree.get_widget("txt_description").set_text(description)
			wTree.get_widget("button_website").connect("clicked", visit_website, model, username)
			wTree.get_widget("button_website").set_label(model.selected_application.website)	
			wTree.get_widget("button_portal").connect("clicked", visit_web, model, username)
			wTree.get_widget("button_portal").set_label(model.selected_application.link)					
			wTree.get_widget("more_info_window").show_all()

def visit_web(widget, model, username):
	if model.selected_application != None:
		if os.path.exists("/usr/bin/gconftool-2"):
			browser = commands.getoutput("gconftool-2 --get /desktop/gnome/url-handlers/http/command")		
		        browser = browser.replace("\"%s\"", model.selected_application.link)
			browser = browser.replace("%s", model.selected_application.link) 
		else:
			browser = "firefox " + model.selected_application.link	
		launcher = commands.getoutput("/usr/bin/mint-which-launcher")
		os.system(launcher + " -u " + username + " \"" + browser + "\" &")

def visit_website(widget, model, username):
	if model.selected_application != None:
		if os.path.exists("/usr/bin/gconftool-2"):
			browser = commands.getoutput("gconftool-2 --get /desktop/gnome/url-handlers/http/command")		
		        browser = browser.replace("\"%s\"", model.selected_application.website)
			browser = browser.replace("%s", model.selected_application.website) 
		else:
			browser = "firefox " + model.selected_application.website	
		launcher = commands.getoutput("/usr/bin/mint-which-launcher")	
		os.system(launcher + " -u " + username + " \"" + browser + "\" &")		

def install(widget, model, wTree, username):	
	if model.selected_application != None:
		if model.selected_application.is_special:
			if not os.path.exists((model.selected_application.mint_file)):
				os.system("zenity --error --text=\"" + _("The mint file for this application was not successfully downloaded. Click on refresh to fix the problem.") + "\"")
			else:
				os.system("mintInstall " + model.selected_application.mint_file)
				show_item(wTree.get_widget("tree_applications").get_selection(), model, wTree, username)
				global cache
				cache = apt.Cache()
		else:
			for package in model.selected_application.packages:
				if package not in model.packages_to_install:
					model.packages_to_install.append(package)
			model.selected_application.status = "add"
			wTree.get_widget("toolbutton_apply").set_sensitive(True)
		show_applications(wTree, model, False)

def remove(widget, model, wTree, username):
	if model.selected_application != None:
		if model.selected_application.is_special:
			if not os.path.exists((model.selected_application.mint_file)):
				os.system("zenity --error --text=\"" + _("The mint file for this application was not successfully downloaded. Click on refresh to fix the problem.") + "\"")
			else:
				os.system("/usr/lib/linuxmint/mintInstall/remove.py " + model.selected_application.mint_file)
				show_item(wTree.get_widget("tree_applications").get_selection(), model, wTree, username)
				global cache
				cache = apt.Cache()
		else:
			for package in model.selected_application.packages:
				if package not in model.packages_to_remove:
					model.packages_to_remove.append(package)
			model.selected_application.status = "remove"
			wTree.get_widget("toolbutton_apply").set_sensitive(True)
		show_applications(wTree, model, False)

def apply(widget, model, wTree, username):
	wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
	wTree.get_widget("main_window").set_sensitive(False)
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

	wTree.get_widget("main_window").window.set_cursor(None)
	wTree.get_widget("main_window").set_sensitive(True)
	wTree.get_widget("toolbutton_apply").set_sensitive(False)

	global cache
	cache = apt.Cache()

	fetch_apt_details(model)
	show_applications(wTree, model, True)
	

def show_applications(wTree, model, scrollback):	

	matching_statuses = []
	if model.filter_applications == "available":
		matching_statuses.append("available")
		matching_statuses.append("special")
	elif model.filter_applications == "installed":
		matching_statuses.append("installed")	
	elif model.filter_applications == "changes":
		matching_statuses.append("add")	
		matching_statuses.append("remove")	
	elif model.filter_applications == "all":
		matching_statuses.append("available")	
		matching_statuses.append("installed")	
		matching_statuses.append("special")	
		matching_statuses.append("add")	
		matching_statuses.append("remove")	

	num_applications = 0
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

	tree_applications = wTree.get_widget("tree_applications")
	new_selection = None
	model_applications = gtk.TreeStore(str, str, int, int, str, object, int, gtk.gdk.Pixbuf, int)
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
						model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/special.png"))	
						model_applications.set_value(iter, 8, 9)

					else:	
						if item.status == "available":
							model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/available.png"))		
							model_applications.set_value(iter, 8, 4)				
						elif item.status == "installed":
							model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/installed.png"))
							model_applications.set_value(iter, 8, 3)
						elif item.status == "add":
							model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/add.png"))		
							model_applications.set_value(iter, 8, 1)
						elif item.status == "remove":
							model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/remove.png"))		
							model_applications.set_value(iter, 8, 2)

					if model.selected_application == item:						
						new_selection = iter
						
					num_applications = num_applications + 1
	model_applications.set_sort_column_id( 6, gtk.SORT_DESCENDING )
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
	statusbar = wTree.get_widget("statusbar")
	context_id = statusbar.get_context_id("mintInstall")	
	statusbar.push(context_id,  _("%d applications listed") % num_applications)

def filter_applications(combo, wTree, model):
	combomodel = combo.get_model()
	comboindex = combo.get_active()
        model.filter_applications = combomodel[comboindex][1]
	show_applications(wTree, model, True)

def build_GUI(model, username):

	#Set the Glade file
	gladefile = "/usr/lib/linuxmint/mintInstall/frontend.glade"
	wTree = gtk.glade.XML(gladefile, "main_window")
	wTree.get_widget("main_window").set_title(_("Software Manager"))
	wTree.get_widget("main_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	wTree.get_widget("main_window").connect("delete_event", close_application)

	wTree.get_widget("image_screenshot").clear()

	#i18n
	wTree.get_widget("label5").set_text(_("Quick search:"))
	wTree.get_widget("label2").set_text(_("More info"))
	wTree.get_widget("label1").set_text(_("Show:"))
	wTree.get_widget("button_search_online").set_label(_("Search"))

	wTree.get_widget("lbl_featured").set_label(_("Featured applications"))	

	# Filter
	model.filter_applications = "all"
	combo = wTree.get_widget("filter_combo")
	store = gtk.ListStore(str, str)
	store.append([_("All software"), "all"])
	store.append([_("Available software"), "available"])
	store.append([_("Installed software"), "installed"])
	store.append([_("Your changes"), "changes"])
	combo.set_model(store)
	combo.set_active(0)
	combo.connect('changed', filter_applications, wTree, model)		

	# Build categories tree
	tree_categories = wTree.get_widget("tree_categories")	
	pix = gtk.CellRendererPixbuf()
	pix.set_property('xalign', 0.0)
	column1 = gtk.TreeViewColumn(_("Category"), pix, pixbuf=2)
	column1.set_alignment(0.0)
	cell = gtk.CellRendererText()
	column1.pack_start(cell, True)
	column1.add_attribute(cell, 'text', 0)
	cell.set_property('xalign', 0.1)
	
	tree_categories.append_column(column1)
	tree_categories.set_headers_clickable(True)
	tree_categories.set_reorderable(False)
	tree_categories.show()
	model_categories = gtk.TreeStore(str, object)	
	tree_categories.set_model(model_categories)
	del model_categories

	#Build applications table
	tree_applications = wTree.get_widget("tree_applications")
	column1 = gtk.TreeViewColumn(_("Application"), gtk.CellRendererText(), text=0)
	column1.set_sort_column_id(0)
	column1.set_resizable(True)

	column2 = gtk.TreeViewColumn(_("Average rating"), gtk.CellRendererText(), text=1)
	column2.set_sort_column_id(1)
	column2.set_resizable(True)

	column3 = gtk.TreeViewColumn(_("Reviews"), gtk.CellRendererText(), text=2)
	column3.set_sort_column_id(2)
	column3.set_resizable(True)

	column4 = gtk.TreeViewColumn(_("Views"), gtk.CellRendererText(), text=3)
	column4.set_sort_column_id(3)
	column4.set_resizable(True)

	column5 = gtk.TreeViewColumn(_("Added"), gtk.CellRendererText(), text=4)
	column5.set_sort_column_id(4)
	column5.set_resizable(True)

	column6 = gtk.TreeViewColumn(_("Score"), gtk.CellRendererText(), text=6)
	column6.set_sort_column_id(6)
	column6.set_resizable(True)

	column7 = gtk.TreeViewColumn(_("Status"), gtk.CellRendererPixbuf(), pixbuf=7)
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
	model_applications = gtk.TreeStore(str, int, int, int, str, object, int, gtk.gdk.Pixbuf, int)
	tree_applications.set_model(model_applications)
	del model_applications	

	tree_applications.connect("row_activated", show_more_info_wrapper, model)

	#Build reviews table
	tree_reviews = wTree.get_widget("tree_reviews")
	column1 = gtk.TreeViewColumn(_("Reviewer"), gtk.CellRendererText(), text=0)
	column1.set_sort_column_id(0)
	column1.set_resizable(True)

	column2 = gtk.TreeViewColumn(_("Rating"), gtk.CellRendererText(), text=1)
	column2.set_sort_column_id(1)
	column2.set_resizable(True)

	column3 = gtk.TreeViewColumn(_("Review"), gtk.CellRendererText(), text=2)
	column3.set_sort_column_id(2)
	column3.set_resizable(True)

	tree_reviews.append_column(column1)
	tree_reviews.append_column(column2)
	tree_reviews.append_column(column3)

	tree_reviews.set_headers_clickable(True)
	tree_reviews.set_reorderable(False)
	tree_reviews.show()
	model_reviews = gtk.TreeStore(str, int, str, object)
	tree_reviews.set_model(model_reviews)
	del model_reviews
	
	selection = tree_applications.get_selection()
	selection.connect("changed", show_item, model, wTree, username)

	entry_search = wTree.get_widget("entry_search")
	entry_search.connect("changed", filter_search, wTree, model)		
	
	wTree.get_widget("button_search_online").connect("clicked", open_search, username)
	wTree.get_widget("button_feature").connect("clicked", open_featured)				
	wTree.get_widget("button_screenshot").connect("clicked", show_screenshot, model)
	wTree.get_widget("button_install").connect("clicked", install, model, wTree, username)	
	wTree.get_widget("button_remove").connect("clicked", remove, model, wTree, username)	
	wTree.get_widget("button_show").connect("clicked", show_more_info, model)

	wTree.get_widget("toolbutton_apply").connect("clicked", apply, model, wTree, username)	

	fileMenu = gtk.MenuItem(_("_File"))
	fileSubmenu = gtk.Menu()
	fileMenu.set_submenu(fileSubmenu)
	closeMenuItem = gtk.ImageMenuItem(gtk.STOCK_CLOSE)
	closeMenuItem.get_child().set_text(_("Quit"))
	closeMenuItem.connect("activate", close_application)
	fileSubmenu.append(closeMenuItem)		
	closeMenuItem.show()

	editMenu = gtk.MenuItem(_("_Edit"))
	editSubmenu = gtk.Menu()
	editMenu.set_submenu(editSubmenu)
	cancelMenuItem = gtk.MenuItem(_("Cancel all changes"))
	cancelMenuItem.connect("activate", cancel_changes, wTree, model)
	editSubmenu.append(cancelMenuItem)		
	cancelMenuItem.show()

	helpMenu = gtk.MenuItem(_("_Help"))
	helpSubmenu = gtk.Menu()
	helpMenu.set_submenu(helpSubmenu)
	aboutMenuItem = gtk.ImageMenuItem(gtk.STOCK_ABOUT)
	aboutMenuItem.get_child().set_text(_("About"))
	aboutMenuItem.show()
	aboutMenuItem.connect("activate", open_about)
	helpSubmenu.append(aboutMenuItem)
        fileMenu.show()
	editMenu.show()
	helpMenu.show()
	wTree.get_widget("menubar1").append(fileMenu)
	wTree.get_widget("menubar1").append(editMenu)
	wTree.get_widget("menubar1").append(helpMenu)
	
	return wTree

def cancel_changes(widget, wTree, model):
	for portal in model.portals:
		for item in portal.items:
			if item.status == "add":
				item.status = "available"
			elif item.status == "remove":
				item.status = "installed"
	model.packages_to_install = []
	model.packages_to_remove = []
	wTree.get_widget("toolbutton_apply").set_sensitive(False)
	show_applications(wTree, model, True)

def open_about(widget):
	dlg = gtk.AboutDialog()		
	dlg.set_version(commands.getoutput("/usr/lib/linuxmint/mintInstall/version.py"))
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
	dlg.set_logo(gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/icon.svg"))
        def close(w, res):
            if res == gtk.RESPONSE_CANCEL:
                w.hide()
        dlg.connect("response", close)
        dlg.show()

class DownloadScreenshot(threading.Thread):

	def __init__(self, selected_item, wTree, model):
		threading.Thread.__init__(self)
		self.selected_item = selected_item
		self.wTree = wTree
		self.model = model

	def run(self):
		try:
			import urllib
			urllib.urlretrieve (self.selected_item.screenshot_url, "/usr/share/linuxmint/mintinstall/data/screenshots/" + self.selected_item.key)
			gtk.gdk.threads_enter()
			if (self.model.selected_application == self.selected_item):
				self.wTree.get_widget("image_screenshot").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.selected_item.screenshot, 200, 200))
			gtk.gdk.threads_leave()
		except Exception, detail:
			pass					

class RefreshThread(threading.Thread):

	def __init__(self, wTree, refresh, model, username):
		threading.Thread.__init__(self)
		self.wTree = wTree
		self.refresh = refresh
		self.directory = "/usr/share/linuxmint/mintinstall/data"
		self.model = model
		self.username = username

	def run(self):
		try:
		
			self.initialize()
			del self.model.portals[:]
			self.model = self.register_portals(self.model)
			gtk.gdk.threads_enter()
			self.wTree.get_widget("main_window").set_sensitive(False)
			self.wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
			gtk.gdk.threads_leave()
			if (self.refresh):	
				for portal in self.model.portals:
					self.download_portal(portal)
			try:
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

				gtk.gdk.threads_enter()	
				statusbar = wTree.get_widget("statusbar")
				context_id = statusbar.get_context_id("mintInstall")
				statusbar.push(context_id, _("%d applications listed") % num_apps)
				gtk.gdk.threads_leave()				
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
					gtk.gdk.threads_enter()
					dialog = gtk.MessageDialog(self.wTree.get_widget("main_window"), gtk.DIALOG_MODAL, gtk.MESSAGE_INFO, gtk.BUTTONS_NONE, _("Please refresh mintInstall by clicking on the Refresh button"))
					dialog.set_title("mintInstall")
					dialog.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
					dialog.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
					dialog.connect('response', lambda dialog, response: dialog.destroy())
					dialog.show()
					gtk.gdk.threads_leave()					

				del self.model.portals[:]
				self.model = self.register_portals(self.model)

			gtk.gdk.threads_enter()
			self.load_model_in_GUI(self.wTree, self.model)			
			self.wTree.get_widget("main_window").window.set_cursor(None)
			self.wTree.get_widget("main_window").set_sensitive(True)
			gtk.gdk.threads_leave()
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
		gtk.gdk.threads_enter()	
		statusbar = wTree.get_widget("statusbar")
		context_id = statusbar.get_context_id("mintInstall")
		portal.update_url = portal.update_url.strip()
		statusbar.push(context_id, _("Downloading data for %s") % (portal.name))
		gtk.gdk.threads_leave()		
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
		progressbar = wTree.get_widget("progressbar")
		progressbar.set_fraction(0)
		progressbar.set_text("0%")
		processed_categories = 0
		processed_items = 0
		processed_screenshots = 0
		processed_reviews = 0			
		processed_total = 0
		xml = ET.parse(fileName)
		root = xml.getroot()				
		gtk.gdk.threads_enter()
		statusbar = wTree.get_widget("statusbar")
		context_id = statusbar.get_context_id("mintInstall")
		gtk.gdk.threads_leave()	
		for element in root: 
			if element.tag == "category":
				category = Classes.Category(portal, element.attrib["id"], element.attrib["name"], element.attrib["description"], element.attrib["vieworder"], element.attrib["parent"], element.attrib["logo"])				
				category.name = category.name.replace("ANDAND", "&")
				if self.refresh:
					os.chdir(self.directory + "/icons/categories")	
					os.system("wget -nc -O" + category.key + " " + category.logo)
					os.chdir("/usr/lib/linuxmint/mintInstall")					
				category.logo = gtk.gdk.pixbuf_new_from_file_at_size(self.directory + "/icons/categories/" + category.key, 16, 16)
				category.name = _(category.name)
				portal.categories.append(category)	
				gtk.gdk.threads_enter()	
				processed_categories = int(processed_categories) + 1	
				statusbar.push(context_id, _("%d categories loaded") % processed_categories)
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				gtk.gdk.threads_leave()		
					
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
				gtk.gdk.threads_enter()
				processed_items = int(processed_items) + 1	
				statusbar.push(context_id, _("%d applications loaded") % processed_items)
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				gtk.gdk.threads_leave()						

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
						gtk.gdk.threads_enter()						
						processed_screenshots = int(processed_screenshots) + 1	
						statusbar.push(context_id, _("%d screenshots loaded") % processed_screenshots)
						gtk.gdk.threads_leave()		
					except:
						pass
				gtk.gdk.threads_enter()
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				gtk.gdk.threads_leave()

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
					gtk.gdk.threads_enter()					
					processed_reviews = int(processed_reviews) + 1	
					statusbar.push(context_id, _("%d reviews loaded") % processed_reviews)
					gtk.gdk.threads_leave()								
	
				gtk.gdk.threads_enter()
				processed_total = processed_total + 1
				ratio = float(processed_total) / float(numTotal)
				progressbar.set_fraction(ratio)
				pct = int(ratio * 100)
				progressbar.set_text(str(pct) + "%")
				gtk.gdk.threads_leave()

		fetch_apt_details(model)	

		gtk.gdk.threads_enter()
		progressbar.set_fraction(0)
		progressbar.set_text("")
		gtk.gdk.threads_leave()

	def load_model_in_GUI(self, wTree, model):
		# Build categories tree
		tree_categories = wTree.get_widget("tree_categories")
		model_categories = gtk.TreeStore(str, object, gtk.gdk.Pixbuf)
		#Add the "All" category
		iter = model_categories.insert_before(None, None)						
		model_categories.set_value(iter, 0, _("All applications"))						
		model_categories.set_value(iter, 1, None)
		model_categories.set_value(iter, 2, gtk.gdk.pixbuf_new_from_file_at_size("/usr/lib/linuxmint/mintInstall/icon.svg", 16, 16))
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
		selection.connect("changed", show_category, model, wTree)

		#Build applications table
		tree_applications = wTree.get_widget("tree_applications")
		model_applications = gtk.TreeStore(str, str, int, int, str, object, int, gtk.gdk.Pixbuf, int)		
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
					model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/special.png"))	
					model_applications.set_value(iter, 8, 9)	
				else:					
					if item.status == "available":
						model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/available.png"))		
						model_applications.set_value(iter, 8, 4)				
					elif item.status == "installed":
						model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/installed.png"))
						model_applications.set_value(iter, 8, 3)
					elif item.status == "add":
						model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/add.png"))		
						model_applications.set_value(iter, 8, 1)
					elif item.status == "remove":
						model_applications.set_value(iter, 7, gtk.gdk.pixbuf_new_from_file("/usr/lib/linuxmint/mintInstall/status-icons/remove.png"))		
						model_applications.set_value(iter, 8, 2)
		model_applications.set_sort_column_id( 6, gtk.SORT_DESCENDING )
		tree_applications.set_model(model_applications)		
		first = model_applications.get_iter_first()
		if (first != None):
			tree_applications.get_selection().select_iter(first)
		del model_applications				

if __name__ == "__main__":
	username = sys.argv[1]
	model = Classes.Model()
	wTree = build_GUI(model, username)
	refresh = RefreshThread(wTree, False, model, username)
	refresh.start()
	gtk.main()



		
