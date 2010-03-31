# Copyright (C) 2009 Canonical
#
# Authors:
#  Michael Vogt
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; version 3.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import gobject
import gtk
import logging
import os
import tempfile
import string

gobject.threads_init()
import webkit

class WebkitWidget(webkit.WebView):
    """Widget that uses a webkit html form for its drawing

    All i18n should be done *outside* the html, currently
    no i18n supported. So all user visible strings should
    be set via templates.

    When a function is prefixed with "wksub_" it will be
    called on load of the page and the template in the
    html page will be replaced by the value that is returned
    by the function. E.g. the html has "... <p>$description</p>"
    then that will get replaced by the call to 
    "def wksub_description(self)".

    It support calls to functions via javascript title change
    methods. The title should look like any of those:
    - "call:func_name"
    - "call:func_name:argument"
    - "call:func_name:arg1,args2"
    """
    SUBSTITUTE_FUNCTION_PREFIX = "wksub_"

    def __init__(self, datadir, substitute=None):
        # init webkit
        webkit.WebView.__init__(self)
        # kill right click menu (the hard way) by stopping event
        # propergation on right-click
        self.connect("button-press-event", lambda w, e: e.button == 3)
        # setup vard
        self.datadir = datadir
        self._template = ""
        self._html = ""
        # callbacks
        self.connect('title-changed', self._on_title_changed)
        self.connect("show", self._show)
        # global settings
        settings = self.get_settings()
        settings.set_property("enable-plugins", False)
        if logging.root.level == logging.DEBUG:
            self.debug_html_path = os.path.join(
                tempfile.mkdtemp(), "software-center-render.html")
            logging.info("writing html output to '%s'" % self.debug_html_path)

    def refresh_html(self):
        self._show(None)

    # internal helpers
    def _show(self, widget):
        """Load and render when show is called"""
        logging.debug("%s.show() called" % self.__class__.__name__)
        self._load()
        self._substitute()
        self._render()
        #print self._html

    def _load(self):
        class_name = self.__class__.__name__        
        self._html_path = self.datadir+"/templates/%s.html" % class_name
        logging.debug("looking for '%s'" % self._html_path)
        if os.path.exists(self._html_path):
            self._template = open(self._html_path).read()

    def _render(self):
        # FIXME: use self._html_path here as base_uri ?
        self.load_html_string(self._html, "file:/")
        # If we are debugging, save us a copy of the substitued HTML
        if logging.root.level == logging.DEBUG:
            f = open(self.debug_html_path, "w")
            logging.info("writing html output to '%s'" % self.debug_html_path)
            f.write(self._html)
            f.close()

    def _substitute(self, subs=None):
        """
        substituate template strings in the html text. If a dict is passed
        to the argument "subs" that will be used for the substitution.
        Otherwise it will call all functions that are prefixed with 
        "wksub_" and use those values for the substitution
        """
        if subs is None:
            subs = {}
            for (k, v) in self.__class__.__dict__.iteritems():
                if callable(v) and k.startswith(self.SUBSTITUTE_FUNCTION_PREFIX):
                    subs[k[len(self.SUBSTITUTE_FUNCTION_PREFIX):]] = v(self)
        self._html = string.Template(self._template).safe_substitute(subs)

    # internal callbacks
    def _on_title_changed(self, view, frame, title):
        logging.debug("%s: title_changed %s %s %s" % (self.__class__.__name__,
                                                      view, frame, title))
        # no op - needed to reset the title after a action so that
        #         the action can be triggered again
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
            self.execute_script('document.title = "nop"')


class WKTestWidget(WebkitWidget):

    def func1(self, arg1, arg2):
        print "func1: ", arg1, arg2

    def func2(self):
        print "func2"

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    import sys

    if len(sys.argv) > 1:
        datadir = sys.argv[1]
    elif os.path.exists("./data"):
        datadir = "./data"
    else:
        datadir = "/usr/share/software-center"


    subs = {
        'key' : 'subs value' 
    }
    w = WKTestWidget(datadir, subs)

    win = gtk.Window()
    scroll = gtk.ScrolledWindow()
    scroll.add(w)
    win.add(scroll)
    win.set_size_request(600,400)
    win.show_all()

    gtk.main()
