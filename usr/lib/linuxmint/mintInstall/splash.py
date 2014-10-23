#!/usr/bin/python
# -*- coding: UTF-8 -*-
import gtk
import gtk.glade
import pygtk
import os
import gettext
import webkit
import string
import apt
print os.getpid()

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

# Build the GUI
gladefile = "/usr/lib/linuxmint/mintInstall/splash.glade"
wTree = gtk.glade.XML(gladefile, "splash_window")
splash_window = wTree.get_widget("splash_window")
splash_window.set_title(_("Software Manager"))
splash_window.set_icon_from_file("/usr/share/linuxmint/mintInstall/data/templates/featured.svg")

browser = webkit.WebView()
wTree.get_widget("vbox1").add(browser)
browser.connect("button-press-event", lambda w, e: e.button == 3)
subs = {}
subs['title'] = _("Software Manager")
subs['subtitle'] = _("Gathering information for %d packages...") % len(apt.Cache())
font_description = gtk.Label("pango").get_pango_context().get_font_description()
subs['font_family'] = font_description.get_family()
try:
    subs['font_weight'] = font_description.get_weight().real
except:
    subs['font_weight'] = font_description.get_weight()   
subs['font_style'] = font_description.get_style().value_nick        
subs['font_size'] = font_description.get_size() / 1024      
template = open("/usr/share/linuxmint/mintInstall/data/templates/splash.html").read()
html = string.Template(template).safe_substitute(subs)
browser.load_html_string(html, "file:/")

splash_window.show_all()
gtk.main()
