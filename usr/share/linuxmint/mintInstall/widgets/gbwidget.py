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
import sys
import string

class GtkbuilderWidget(gtk.HBox):
    """A widget that gets loaded from a Gtkbuilder UI file 
    
    If no "toplevel_name" paramter is given, the name of
    the class is used to find a UI file of that name and
    load the object with that name
    """
    def __init__(self, datadir, toplevel_name=None):
        gtk.HBox.__init__(self)
        if toplevel_name is None:
            toplevel_name = self.__class__.__name__
        ui_file = "%s/ui/%s.ui" % (datadir, toplevel_name)
        builder = gtk.Builder()
        builder.add_objects_from_file(ui_file, [toplevel_name])
        builder.connect_signals(self)
        for o in builder.get_objects():
            if issubclass(type(o), gtk.Buildable):
                name = gtk.Buildable.get_name(o)
                setattr(self, name, o)
            else:
                logging.warn("WARNING: can not get name for '%s'" % o)
        # parent
        w = getattr(self, self.__class__.__name__)
        self.add(w)
    def show(self):
        w = getattr(self, self.__class__.__name__)
        w.show_all()

# test widget that just loads the 
class GBTestWidget(GtkbuilderWidget):

    def on_button_clicked(self, button):
        print "on_button_clicked"


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) > 1:
        datadir = sys.argv[1]
    elif os.path.exists("./data"):
        datadir = "./data"
    else:
        datadir = "/usr/share/software-center"

    w = GBTestWidget(datadir)
    w.show()

    win = gtk.Window()
    win.add(w)
    #win.set_size_request(600,400)
    win.show_all()

    gtk.main()
