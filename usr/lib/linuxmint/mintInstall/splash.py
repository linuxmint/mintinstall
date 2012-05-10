#!/usr/bin/python
# -*- coding: utf-8 -*-

from gi.repository import Gtk
from gi.repository import WebKit

import os
import gettext
import string
import apt
print os.getpid()

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

# Build the GUI
gladefile = "/usr/lib/linuxmint/mintInstall/splash.ui"
builder = Gtk.Builder()
builder.add_from_file(gladefile)
splash_window = builder.get_object("splash_window")
splash_window.set_title(_("Software Manager"))
splash_window.set_icon_from_file("/usr/lib/linuxmint/mintInstall/data/templates/featured.svg")

browser = WebKit.WebView()
builder.get_object("vbox1").add(browser)
browser.connect("button-press-event", lambda w, e: e.button == 3)
subs = {}
subs['title'] = _("Software Manager")
subs['subtitle'] = _("Gathering information for %d packages...") % len(apt.Cache())
font_description = Gtk.Label("pango").get_pango_context().get_font_description()
subs['font_family'] = font_description.get_family()
try:
    subs['font_weight'] = font_description.get_weight().real
except:
    subs['font_weight'] = font_description.get_weight()
subs['font_style'] = font_description.get_style().value_nick
subs['font_size'] = font_description.get_size() / 1024
template = open("/usr/lib/linuxmint/mintInstall/data/templates/splash.html").read()
html = string.Template(template).safe_substitute(subs)
browser.load_html_string(html, "file:/")

splash_window.show_all()
Gtk.main()
