#!/usr/bin/env python

# mintInstall
#	No Copyright (What for?) Clem <root@linuxmint.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; Version 2
# of the License.
#
# This program is "inspired" by CNR and the idea of "one click install".

from gi.repository import Gtk
from gi.repository import Gdk

try:
    import sys
    import apt
    import string
    import os
    import commands
    import threading
    import tempfile
    import gettext

except Exception, detail:
    print detail
    sys.exit(1)

from subprocess import Popen, PIPE

Gdk.threads_init()

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

class mintInstallExecuter(threading.Thread):

    def __init__(self, window_id, rightRepositories):
	threading.Thread.__init__(self)
	self.window_id = window_id
	self.rightRepositories = rightRepositories

    def execute(self, command):
	#print "Executing: " + command
	os.system(command)
	ret = commands.getoutput("echo $?")
	return ret

    def run(self):
	global steps
	global progressbar
	global builder
	global packages
	global user
	global home

	builder.get_object("main_button").hide()
	builder.get_object("cancel_button").set_label("gtk-cancel")
	builder.get_object("cancel_button").set_use_stock(True)

	totalSteps = steps
	if (self.rightRepositories != "local"):
		progressbar.set_text(_("Backing up your APT sources"))
		self.execute("mv /etc/apt/sources.list /etc/apt/sources.list.mintbackup")
		self.execute("cp /usr/share/linuxmint/mintinstall/sources.list /etc/apt/sources.list")
		cache = apt.Cache()
		os.system("apt-get update")
		totalSteps = steps + 2

	fraction = 0
	progressbar.set_fraction(fraction)

	for i in range(steps + 1):
		if (i > 0):
			openfile = open("/usr/lib/linuxmint/mintInstall/tmp/steps/"+str(i), 'r' )
                        datalist = openfile.readlines()
			for j in range( len( datalist ) ):
                            if (str.find(datalist[j], "TITLE") > -1):
				title = datalist[j][6:]
				progressbar.set_text(str.strip(title))
			    if (str.find(datalist[j], "INSTALL") > -1):
				install = datalist[j][8:]
				install = str.strip(install)
				installPackages = string.split(install)
				cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window", "--non-interactive", "--parent-window-id", self.window_id]
				cmd.append("--progress-str")
        			cmd.append("\"" + _("Please wait, this can take some time") + "\"")
				cmd.append("--finish-str")
				cmd.append("\"" + _("Installation is complete") + "\"")
				f = tempfile.NamedTemporaryFile()
				for pkg in installPackages:
        			    f.write("%s\tinstall\n" % pkg)
        			cmd.append("--set-selections-file")
        			cmd.append("%s" % f.name)
        			f.flush()
        			comnd = Popen(' '.join(cmd), shell=True)
				returnCode = comnd.wait()
				f.close()

			    if (str.find(datalist[j], "SOURCE") > -1):
				source = datalist[j][7:]
				source = source.rstrip()
				self.execute("echo \"" + source + "\" >> /etc/apt/sources.list")
				os.system("apt-get update")
			    if (str.find(datalist[j], "EXECUTE") > -1):
				execution = datalist[j][8:]
				execution = execution.rstrip()
				execution = execution.replace("<<USER>>", user)
				execution = execution.replace("<<HOME>>", home)
				self.execute(execution)

			fraction = float(i)/float(totalSteps)
			progressbar.set_fraction(fraction)

	if (self.rightRepositories != "local"):
		progressbar.set_text(_("Restoring your APT sources"))
		self.execute("mv /etc/apt/sources.list.mintbackup /etc/apt/sources.list")
		os.system("apt-get update")
	progressbar.set_fraction(1)
	progressbar.set_text(_("Finished"))
	builder.get_object("main_button").hide()
	builder.get_object("cancel_button").set_label(_("Close"))
	#Everything is done, exit quietly
	Gtk.main_quit()
	sys.exit(0)

class mintInstallWindow:
    """This is the main class for the application"""

    def __init__(self, mintFile, user, home):
	global steps
	global progressbar
	global builder
	global installation_terminal
	global installation_progressbar
	global download_progressbar
	global packages

	self.mintFile = mintFile
	self.user = user
	self.home = home

	#Make tmp folder
	os.system("mkdir -p /usr/lib/linuxmint/mintInstall/tmp")

	#Clean tmp files
	os.system("rm -rf /usr/lib/linuxmint/mintInstall/tmp/*")

	#Decompress file
	os.system("cp " + mintFile + " /usr/lib/linuxmint/mintInstall/tmp/file.mint")
	os.system("tar xf /usr/lib/linuxmint/mintInstall/tmp/file.mint -C /usr/lib/linuxmint/mintInstall/tmp/") #Try without gzip
	os.system("tar zxf /usr/lib/linuxmint/mintInstall/tmp/file.mint -C /usr/lib/linuxmint/mintInstall/tmp/") #Try with gzip

	#Extract the name
	self.name = commands.getoutput("cat /usr/lib/linuxmint/mintInstall/tmp/name")
	self.name = str.strip(self.name)

	#Extract the number of steps
	steps = int(commands.getoutput("ls -l /usr/lib/linuxmint/mintInstall/tmp/steps/ | wc -l"))
	steps = steps -1
	self.pulse = 1/steps

	#Initialize APT
	cache = apt.Cache()

	#Extract repositories and packages
	self.repositories = []
	packages = []
	for i in range(steps + 1):
		if (i > 0):
			openfile = open("/usr/lib/linuxmint/mintInstall/tmp/steps/"+str(i), 'r' )
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
			#openfile.close()

        #Set the Glade file
        self.gladefile = "/usr/lib/linuxmint/mintInstall/mintInstall.ui"
        builder = Gtk.Builder()
        builder.add_from_file(self.gladefile)
        w = builder.get_object("main_window")
	w.set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	w.set_title("")

	w.connect("destroy", self.giveUp)

	# Get the window socket (needed for synaptic later on)
	vbox = builder.get_object("vbox1")
	socket = Gtk.Socket()
	vbox.pack_start(socket)
	socket.show()
	window_id = repr(socket.get_id())

	builder.get_object("label_repositories").set_text(_("Using the following repositories:"))

	#Fill in the GUI with information from the mintFile
	builder.get_object("main_button_label").set_text(_("Install"))

        w = builder.get_object("txt_name")
	w.set_text("<big><b>" + _("Install %s?") % (self.name) + "</b></big>")
	w.set_use_markup(True)

	builder.get_object("txt_guidance").set_text(_("The following packages will be installed:"))

	if (len(self.repositories) == 0):
		treeview = builder.get_object("tree_repositories")
		column1 = Gtk.TreeViewColumn()
		renderer = Gtk.CellRendererText()
		column1.pack_start(renderer, False)
		column1.set_attributes(renderer, text = 0)
		treeview.append_column(column1)
		treeview.set_headers_visible(False)
		model = Gtk.ListStore(str)
		model.append([_("Default repositories")])
		treeview.set_model(model)
		builder.get_object("label_repositories").hide()
		builder.get_object("scrolledwindow_repositories").hide()

		treeview = builder.get_object("tree_packages")
		column1 = Gtk.TreeViewColumn()
		renderer = Gtk.CellRendererText()
		column1.pack_start(renderer, False)
		column1.set_attributes(renderer, text = 0)
		treeview.append_column(column1)
		treeview.set_headers_visible(False)
		model = Gtk.ListStore(str)

		for package in packages:
			strPackage = package
			try:
				pkg = cache[package]
				strPackage = str(package) + " [" + pkg.candidateVersion + "]"
				for dep in pkg.candidateDependencies:
					for o in dep.or_dependencies:
						dependency = cache[o.name]
						if not dependency.is_installed:
							strDependency = dependency.name + " [" + dependency.candidateVersion + "]"
							model.append([strDependency])
			except Exception, detail:
				print detail
				pass
			model.append([strPackage])
		treeview.set_model(model)
		treeview.show()
	else:
		treeview = builder.get_object("tree_repositories")
		column1 = Gtk.TreeViewColumn()
		renderer = Gtk.CellRendererText()
		column1.pack_start(renderer, False)
		column1.set_attributes(renderer, text = 0)
		treeview.append_column(column1)
		treeview.set_headers_visible(False)
		model = Gtk.ListStore(str)
		for repository in self.repositories:
			model.append([repository])
		treeview.set_model(model)
		treeview.show()

		treeview = builder.get_object("tree_packages")
		column1 = Gtk.TreeViewColumn()
		renderer = Gtk.CellRendererText()
		column1.pack_start(renderer, False)
		column1.set_attributes(renderer, text = 0)
		treeview.append_column(column1)
		treeview.set_headers_visible(False)
		model = Gtk.ListStore(str)
		for package in packages:
			model.append([package])
		treeview.set_model(model)
		treeview.show()

	self.needToInstallSomething = False
	packageNotFoundLocally = False

	for package in packages:
		try:
			pkg = cache[package]
			if not pkg.is_installed:
				self.needToInstallSomething = True
		except Exception, details:
			print details
			packageNotFoundLocally = True
			self.needToInstallSomething = True

	if ( not self.needToInstallSomething ):
		#builder.get_object("main_window").set_title(_("Upgrade %s?") % (self.name))
		builder.get_object("txt_name").set_text("<big><b>" + _("Upgrade %s?") % (self.name) + "</b></big>")
		builder.get_object("txt_name").set_use_markup(True)
		builder.get_object("txt_guidance").set_text(_("The following packages will be upgraded:"))
		builder.get_object("main_button_label").set_text(_("Upgrade"))

	if (len(self.repositories) > 0):
		#The mint file defines repositories so we use them.
		rightRepositories = "mint"
	else:
		if (packageNotFoundLocally):
		#The mint file doesn't define repositories but the package isn't found with the user's repos.. so we use the ones from mintsystem
			rightRepositories = "default"
		else:
		#The mint file doesn't define repositories but the package is found with the user's repos.. so we use the user's repositories (no update required)
			rightRepositories = "local"

	progressbar = builder.get_object("progressbar1")
	fraction = 0
	progressbar.set_fraction(fraction)

	download_progressbar = builder.get_object("download_progressbar")
	builder.get_object("main_window").show()

	#Create our dictionay and connect it
        dic = {"on_main_button_clicked" : (self.MainButtonClicked, window_id, rightRepositories, wTree),
               "on_cancel_button_clicked" : (self.giveUp) }
        wTree.signal_autoconnect(dic)

    def MainButtonClicked(self, widget, window_id, rightRepositories, wTree):
	builder.get_object("main_window").window.set_cursor(Gdk.Cursor(Gdk.CursorType.WATCH))
	builder.get_object("main_window").set_sensitive(False)
	executer = mintInstallExecuter(window_id, rightRepositories)
	executer.start()
	return True

    def giveUp(self, widget):
	if (os.path.exists("/etc/apt/sources.list.mintbackup")):
		os.system("mv /etc/apt/sources.list.mintbackup /etc/apt/sources.list")
	Gtk.main_quit
	sys.exit(0)

class MessageDialog:
	def __init__(self, title, message):
		self.title = title
		self.message = message

	def show(self):
		warnDlg = Gtk.Dialog(title=_("Software Manager"), parent=None, flags=0, buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK))
		warnDlg.vbox.set_spacing(10)
		labelSpc = Gtk.Label(" ")
		warnDlg.vbox.pack_start(labelSpc)
		labelSpc.show()
		warnText = ("<b>" + self.title + "</b>")
		infoText = (self.message)
		label = Gtk.Label(warnText)
		lblInfo = Gtk.Label(infoText)
		label.set_use_markup(True)
		lblInfo.set_use_markup(True)
		warnDlg.vbox.pack_start(label)
		warnDlg.vbox.pack_start(lblInfo)
		label.show()
		lblInfo.show()
		response = warnDlg.run()
		if response == Gtk.ResonseType.OK :
			warnDlg.destroy()

def search_mint(widget, username, textfield):
	search_txt = textfield.get_text()
	search_txt = search_txt.replace(" ", "_")
	releaseID = commands.getoutput("cat /usr/share/linuxmint/mintinstall/release.id")
	show_website(username, "http://www.linuxmint.com/software/?sec=search&search=" + search_txt + "&release=" + str.strip(releaseID))

def show_portal_mint(widget, username):
	releaseID = commands.getoutput("cat /usr/share/linuxmint/mintinstall/release.id")
	show_website(username, "http://linuxmint.com/software/?sec=categories&release=" + str.strip(releaseID))

def search_getdeb(widget, username, textfield):
	search_txt = textfield.get_text()
	search_txt = search_txt.replace(" ", "_")
	show_website(username, "http://www.getdeb.net/search.php?keywords=" + search_txt)

def show_portal_getdeb(widget, username):
	show_website(username, "http://www.getdeb.net/")

def show_portal_ubuntu_apt(widget, username):
	show_website(username, "http://packages.ubuntu.com/")

def show_portal_mint_apt(widget, username):
	show_website(username, "http://packages.linuxmint.com/")

def show_website(username, link):
	os.system("sudo -u " + username + " /usr/lib/linuxmint/common/launch_browser_as.py \"" + link + "\"")

def search_apt(widget, textfield):
	os.system("/usr/bin/mint-search-apt " + textfield.get_text() + " &")

def show_apt(widget, textfield):
	os.system("/usr/bin/mint-show-apt " + textfield.get_text() + " &")

def install_apt(widget, textfield, window_id):
	os.system("/usr/bin/mint-make-cmd " + textfield.get_text())

def updateEntries(widget, wTree):
	builder.get_object("txt_search_mint").set_text(widget.get_text())
	builder.get_object("txt_search_getdeb").set_text(widget.get_text())
	builder.get_object("txt_apt").set_text(widget.get_text())

global user
global home
if __name__ == "__main__":
    if (len(sys.argv) != 4):
	username = sys.argv[1]
        gladefile = "/usr/lib/linuxmint/mintInstall/mintInstall.ui"
        builder = Gtk.Builder
        builder.add_from_file(gladefile)

	# Get the window socket (needed for synaptic later on)
	vbox = builder.get_object("vbox3")
	socket = Gtk.Socket()
	vbox.pack_start(socket)
	socket.show()
	window_id = repr(socket.get_id())

	builder.get_object("window_menu").connect("destroy", Gtk.main_quit)
	builder.get_object("button_portal_mint").connect("clicked", show_portal_mint, username)
	builder.get_object("button_search_mint").connect("clicked", search_mint, username, builder.get_object("txt_search_mint"))
	builder.get_object("txt_search_mint").connect("activate", search_mint, username, builder.get_object("txt_search_mint"))
	builder.get_object("button_portal_getdeb").connect("clicked", show_portal_getdeb, username)
	builder.get_object("button_search_getdeb").connect("clicked", search_getdeb, username, builder.get_object("txt_search_getdeb"))
	builder.get_object("txt_search_getdeb").connect("activate", search_getdeb, username, builder.get_object("txt_search_getdeb"))
	builder.get_object("button_portal_ubuntu_apt").connect("clicked", show_portal_ubuntu_apt, username)
	builder.get_object("button_portal_mint_apt").connect("clicked", show_portal_mint_apt, username)
	builder.get_object("button_search_apt").connect("clicked", search_apt, builder.get_object("txt_apt"))
	builder.get_object("button_install_apt").connect("clicked", install_apt, builder.get_object("txt_apt"), window_id)
	builder.get_object("button_show_apt").connect("clicked", show_apt, builder.get_object("txt_apt"))
	builder.get_object("txt_search_mint").connect("changed", updateEntries, wTree)
	builder.get_object("txt_search_getdeb").connect("changed", updateEntries, wTree)
	builder.get_object("txt_apt").connect("changed", updateEntries, wTree)
	builder.get_object("window_menu").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	builder.get_object("window_menu").set_title(_("Find Software"))

	#i18n
	builder.get_object("button_portal_mint_label").set_label(_("Go to the Linux Mint Software Portal"))
	builder.get_object("button_search_mint_label").set_label(_("Search for a .mint application"))
	builder.get_object("button_portal_getdeb_label").set_label(_("Go to the GetDeb Portal"))
	builder.get_object("button_search_getdeb_label").set_label(_("Search for a .deb package"))
	builder.get_object("button_search_apt_label").set_label(_("Search"))
	builder.get_object("button_install_apt_label").set_label(_("Install"))
	builder.get_object("button_show_apt_label").set_label(_("Show"))
	builder.get_object("button_portal_ubuntu_apt_label").set_label(_("Go to the Ubuntu repository"))
	builder.get_object("button_portal_mint_apt_label").set_label(_("Go to the Linux Mint repository"))
	builder.get_object("txt_search_mint").grab_focus()
	builder.get_object("window_menu").show()
        Gtk.main()
    else:
        os.system("rm -rf /var/lib/dpkg/lock")
        os.system("rm -rf /var/lib/apt/lists/lock")
        os.system("rm -rf /var/cache/apt/archives/lock")

        if (os.path.exists("/etc/apt/sources.list.mintbackup")):
	    os.system("mv /etc/apt/sources.list.mintbackup /etc/apt/sources.list")
    	    os.system("sudo apt-get update")
	    message = MessageDialog(_("Your APT sources were corrupted."), _("Your APT sources were not correctly restored after you last ran mintInstall. They now have been restored."))
	    message.show()
	    sys.exit(0)
        else:
	    username = sys.argv[2]
	    home = sys.argv[3]
    	    mainwin = mintInstallWindow(sys.argv[1], username, home)
    	    Gtk.main()
