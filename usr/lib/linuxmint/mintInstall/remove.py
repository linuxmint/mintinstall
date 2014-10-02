#!/usr/bin/env python

try:
     import pygtk
     pygtk.require("2.0")
except:
      pass
try:
    import sys
    import string
    import gtk
    import gtk.glade
    import os
    import commands
    import threading
    import tempfile
    import gettext
    from user import home
	
except Exception, detail:
    print detail
    sys.exit(1)

from subprocess import Popen, PIPE

gtk.gdk.threads_init()

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

class RemoveExecuter(threading.Thread):

    def __init__(self, window_id, packages):
	threading.Thread.__init__(self)
	self.window_id = window_id
	self.packages = packages
    
    def execute(self, command):
	#print "Executing: " + command
	os.system(command)
	ret = commands.getoutput("echo $?")
	return ret

    def run(self):		
	cmd = ["sudo", "/usr/sbin/synaptic", "--hide-main-window",  \
	        "--non-interactive", "--parent-window-id", self.window_id]
	cmd.append("--progress-str")
	cmd.append("\"" + _("Please wait, this can take some time") + "\"")
	cmd.append("--finish-str")
	cmd.append("\"" + _("Application removed successfully") + "\"")
	f = tempfile.NamedTemporaryFile()
	for pkg in self.packages:
            f.write("%s\tdeinstall\n" % pkg)
        cmd.append("--set-selections-file")
        cmd.append("%s" % f.name)
        f.flush()
        comnd = Popen(' '.join(cmd), shell=True)
	returnCode = comnd.wait()
	f.close()
	gtk.main_quit()
	sys.exit(0)
		
class mintRemoveWindow:

    def __init__(self, mintFile):
	self.mintFile = mintFile

	if os.path.exists(self.mintFile):			
		directory = home + "/.linuxmint/mintInstall/tmp/mintFile"
		os.system("mkdir -p " + directory)
		os.system("rm -rf " + directory + "/*") 
		os.system("cp " + self.mintFile + " " + directory + "/file.mint")
		os.system("tar zxf " + directory + "/file.mint -C " + directory)
		appName = commands.getoutput("cat " + directory + "/name")
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
				openfile.close()		
					
        #Set the Glade file
        self.gladefile = "/usr/lib/linuxmint/mintInstall/remove.glade"
        wTree = gtk.glade.XML(self.gladefile,"main_window")
	wTree.get_widget("main_window").set_icon_from_file("/usr/lib/linuxmint/mintInstall/icon.svg")
	wTree.get_widget("main_window").set_title("")
	wTree.get_widget("main_window").connect("destroy", self.giveUp)

	# Get the window socket (needed for synaptic later on)
	vbox = wTree.get_widget("vbox1")
	socket = gtk.Socket()
	vbox.pack_start(socket)
	socket.show()
	window_id = repr(socket.get_id())
        
	wTree.get_widget("txt_name").set_text("<big><b>" + _("Remove %s?") % (appName) + "</b></big>")
	wTree.get_widget("txt_name").set_use_markup(True)

	wTree.get_widget("txt_guidance").set_text(_("The following packages will be removed:"))
	
	treeview = wTree.get_widget("tree")
	column1 = gtk.TreeViewColumn()
	renderer = gtk.CellRendererText()
	column1.pack_start(renderer, False)
	column1.set_attributes(renderer, text = 0)
	treeview.append_column(column1)
	treeview.set_headers_visible(False)

	model = gtk.ListStore(str)

	for package in packages:		
		dependenciesString = commands.getoutput("apt-get -s -q remove " + package + " | grep Remv")
		dependencies = string.split(dependenciesString, "\n")
		for dependency in dependencies:
			dependency = dependency.replace("Remv ", "")
			model.append([dependency])

	treeview.set_model(model)
	treeview.show()		

        dic = {"on_remove_button_clicked" : (self.MainButtonClicked, window_id, packages, wTree),
               "on_cancel_button_clicked" : (self.giveUp) }
        wTree.signal_autoconnect(dic)

	wTree.get_widget("main_window").show()


    def MainButtonClicked(self, widget, window_id, packages, wTree):
	wTree.get_widget("main_window").window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
	wTree.get_widget("main_window").set_sensitive(False)
	executer = RemoveExecuter(window_id, packages)
	executer.start()
	return True

    def giveUp(self, widget):
	gtk.main_quit()
	sys.exit(0)

if __name__ == "__main__":
    mainwin = mintRemoveWindow(sys.argv[1])
    gtk.gdk.threads_enter()
    gtk.main()
    gtk.gdk.threads_leave()
