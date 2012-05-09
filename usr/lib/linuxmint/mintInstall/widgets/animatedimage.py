# Copyright (C) 2009 Canonical
#
# Authors:
#  Michael Vogt
#  Andrew Higginson (rugby471)
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

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import GLib
from gi.repository import GObject

import os
import glob
import time

class AnimatedImage(Gtk.Image):

    FPS = 20.0
    SIZE = 24

    def __init__(self, icon):
        """ Animate a gtk.Image

        Keywords:
        icon: pass either:
              - None - creates empty image with self.SIZE
              - string - for a static icon
              - string - for a image with multiple sub icons
              - list of string pathes
              - a gtk.gdk.Pixbuf if you require a static image
        """
        super(AnimatedImage, self).__init__()
        self._progressN = 0
        if icon is None:
            icon = GdkPixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
            icon.fill(0)
        if isinstance(icon, list):
            self.images = []
            for f in icon:
                self.images.append(GdkPixbuf.Pixbuf.new_from_file(f))
        elif isinstance(icon, GdkPixbuf.Pixbuf):
            self.images = [icon]
            self.set_from_pixbuf(icon)
        elif isinstance(icon, str):
            self._imagefiles = icon
            self.images = []
            if not self._imagefiles:
                raise IOError, "no images for the animation found in '%s'" % icon
            # construct self.images list
            pixbuf_orig = GdkPixbuf.Pixbuf.new_from_file(icon)
            pixbuf_buffer = pixbuf_orig.copy()
            x = 0
            y = 0
            for f in range((pixbuf_orig.get_width() / self.SIZE) *
                           (pixbuf_orig.get_height() / self.SIZE)):
                pixbuf_orig.copy_area(x, y, self.SIZE, self.SIZE, pixbuf_buffer, 0, 0)
                self.images.append(pixbuf_buffer)
                if x == (pixbuf_orig.get_width() - self.SIZE):
                    x = 0
                    y += self.SIZE
                else:
                    x += self.SIZE

            self.set_from_pixbuf(self.images[self._progressN])
            self.connect("show", self.start)
            self.connect("hide", self.stop)
        else:
            raise IOError, "need a str, list or a pixbuf"

    def start(self, w=None):
        source_id = GLib.timeout_add(int(1000/self.FPS),
                                              self._progress_timeout)
        self._run = True

    def stop(self, w=None):
        self._run = False

    def get_current_pixbuf(self):
        return self.images[self._progressN]

    def get_animation_len(self):
        return len(self.images)

    def _progress_timeout(self):
        self._progressN += 1
        if self._progressN == len(self.images):
            self._progressN = 0
        self.set_from_pixbuf(self.get_current_pixbuf())
        return self._run

class CellRendererAnimatedImage(Gtk.CellRendererPixbuf):

    __gproperties__  = {
        "image" : (Gtk.Image,
                   "Image",
                   "Image",
                   GObject.PARAM_READWRITE),
    }
    FPS = 20.0

    def __init__(self):
        Gtk.CellRendererPixbuf.__init__(self)
    def do_set_property(self, pspec, value):
        setattr(self, pspec.name, value)
    def do_get_property(self, pspec):
        return getattr(self, pspec.name)
    def _animation_helper(self, widget, image):
        #print time.time()
        model = widget.get_model()
        if not model:
            return
        for row in model:
            cell_area = widget.get_cell_area(row.path, widget.get_column(0))
            widget.queue_draw_area(cell_area.x, cell_area.y,
                                   cell_area.width, cell_area.height)
    def do_render(self, window, widget, background_area, cell_area, expose_area):
        image = self.get_property("image")
        if image.get_animation_len() > 1:
            GLib.timeout_add(int(1000.0/self.FPS), self._animation_helper, widget, image)
        self.set_property("pixbuf", image.get_current_pixbuf())
        return Gtk.CellRendererPixbuf.do_render(self, window, widget, background_area, cell_area, expose_area)
    def do_get_size(self, widget, cell_area):
        image = self.get_property("image")
        self.set_property("pixbuf", image.get_current_pixbuf())
        return Gtk.CellRendererPixbuf.do_get_size(self, widget, cell_area)

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        datadir = sys.argv[1]
    elif os.path.exists("./data"):
        datadir = "./data"
    else:
        datadir = "/usr/share/icons/gnome"

    image = AnimatedImage(datadir+"/24x24/status/software-update-available.png")
    image1 = AnimatedImage(datadir+"/24x24/status/software-update-available.png")
    image1.start()
    image2 = AnimatedImage(datadir+"/24x24/status/software-update-available.png")
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(datadir+"/24x24/status/software-update-available.png")
    image3 = AnimatedImage(pixbuf)
    image3.show()

    image4 = AnimatedImage(glob.glob(datadir+"/32x32/status/*"))
    image4.start()
    image4.show()

    model = Gtk.ListStore(AnimatedImage)
    model.append([image1])
    model.append([image2])
    treeview = Gtk.TreeView(model)
    tp = CellRendererAnimatedImage()
    column = Gtk.TreeViewColumn("Icon", tp, image=0)
    treeview.append_column(column)
    treeview.show()

    box = Gtk.VBox()
    box.add(image)
    box.add(image3)
    box.add(image4)
    box.add(treeview)
    box.show()
    win = Gtk.Window()
    win.add(box)
    win.set_size_request(400,400)
    win.show()

    print "running the image for 5s"
    GLib.timeout_add_seconds(1, image.show)
    GLib.timeout_add_seconds(5, image.hide)

    Gtk.main()
