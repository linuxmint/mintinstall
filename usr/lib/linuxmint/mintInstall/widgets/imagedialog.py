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

import gconf
import glib
import gio
import gtk
import logging
import tempfile
import time
import threading
import urllib
import gobject

from softwarecenter.enums import *
from softwarecenter.utils import get_http_proxy_string_from_gconf

ICON_EXCEPTIONS = ["gnome"]

class Url404Error(IOError):
    pass

class Url403Error(IOError):
    pass

class GnomeProxyURLopener(urllib.FancyURLopener):
    """A urllib.URLOpener that honors the gnome proxy settings"""
    def __init__(self, user_agent=USER_AGENT):
        proxies = {}
        http_proxy = get_http_proxy_string_from_gconf()
        if http_proxy:
            proxies = { "http" : http_proxy }
        urllib.FancyURLopener.__init__(self, proxies)
        self.version = user_agent
    def http_error_404(self, url, fp, errcode, errmsg, headers):
        logging.debug("http_error_404: %s %s %s" % (url, errcode, errmsg))
        raise Url404Error, "404 %s" % url
    def http_error_403(self, url, fp, errcode, errmsg, headers):
        logging.debug("http_error_403: %s %s %s" % (url, errcode, errmsg))
        raise Url403Error, "403 %s" % url

class ShowImageDialog(gtk.Dialog):
    """A dialog that shows a image """

    def __init__(self, title, url, loading_img, loading_img_size, missing_img, parent=None):
        gtk.Dialog.__init__(self)
        # find parent window for the dialog
        if not parent:
            parent = self.get_parent()
            while parent:
                parent = w.get_parent()
        # missing
        self._missing_img = missing_img
        self.image_filename = self._missing_img
        # image
            # loading
        pixbuf_orig = gtk.gdk.pixbuf_new_from_file(loading_img)
        self.x = self._get_loading_x_start(loading_img_size)
        self.y = 0
        self.pixbuf_count = 0
        pixbuf_buffer = pixbuf_orig.copy()
        
        self.pixbuf_list = []
                
        for f in range((pixbuf_orig.get_width() / loading_img_size) * (pixbuf_orig.get_height() / loading_img_size)):
            pixbuf_buffer = pixbuf_orig.subpixbuf(self.x, self.y, loading_img_size, loading_img_size)
            self.pixbuf_list.append(pixbuf_buffer)
            if self.x == pixbuf_orig.get_width() - loading_img_size:
                self.x = self.x = self._get_loading_x_start(loading_img_size)
                self.y += loading_img_size
                if self.y == pixbuf_orig.get_height():
                    self.x = self.x = self._get_loading_x_start(loading_img_size)
                    self.y = 0
            else:
                self.x += loading_img_size
        
        
        
        self.img = gtk.Image()
        self.img.set_from_file(loading_img)
        self.img.show()
        gobject.timeout_add(50, self._update_loading, pixbuf_orig, loading_img_size)

        # view port
        scroll = gtk.ScrolledWindow()
        scroll.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scroll.add_with_viewport(self.img)
        scroll.show() 

        # box
        vbox = gtk.VBox()
        vbox.pack_start(scroll)
        vbox.show()
        # dialog
        self.set_transient_for(parent)
        self.set_position(gtk.WIN_POS_CENTER_ON_PARENT)
        self.get_content_area().add(vbox)
        self.add_button(gtk.STOCK_CLOSE, gtk.RESPONSE_CLOSE)
        self.set_default_size(850,650)
        self.set_title(title)
        self.connect("response", self._response)
        # install urlopener
        urllib._urlopener = GnomeProxyURLopener()
        # data
        self.url = url

    def _update_loading(self, pixbuf_orig, loading_img_size):
        if not self._finished:
            self.img.set_from_pixbuf(self.pixbuf_list[self.pixbuf_count])
            if self.pixbuf_count == (pixbuf_orig.get_width() / loading_img_size) * (pixbuf_orig.get_height() / loading_img_size) - 1:
                self.pixbuf_count = 0
            else:
                self.pixbuf_count += 1
            return True
            
    def _get_loading_x_start(self, loading_img_size):
        if (gtk.settings_get_default().props.gtk_icon_theme_name in ICON_EXCEPTIONS) or (gtk.settings_get_default().props.gtk_fallback_icon_theme in ICON_EXCEPTIONS):
            return loading_img_size
        else:
            return 0
            

    def _response(self, dialog, reponse_id):
        self._finished = True
        self._abort = True
        
    def run(self):
        self.show()
        # thread
        self._finished = False
        self._abort = False
        self._fetched = 0.0
        self._percent = 0.0
        t = threading.Thread(target=self._fetch)
        t.start()
        # wait for download to finish or for abort
        while not self._finished:
            time.sleep(0.1)
            while gtk.events_pending():
                gtk.main_iteration()
        # aborted
        if self._abort:
            return gtk.RESPONSE_CLOSE
        # load into icon
        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file(self.image_filename)
        except:
            logging.debug("The image format couldn't be determined")
            pixbuf = gtk.gdk.pixbuf_new_from_file(self._missing_img)
        self.img.set_from_pixbuf(pixbuf)
        # and run the real thing
        gtk.Dialog.run(self)

    def _fetch(self):
        "fetcher thread"
        logging.debug("_fetch: %s" % self.url)
        self.location = tempfile.NamedTemporaryFile()
        try:
            (screenshot, info) = urllib.urlretrieve(self.url, 
                                                    self.location.name, 
                                                    self._progress)
            self.image_filename = self.location.name
        except (Url403Error, Url404Error), e:
            self.image_filename = self._missing_img
        except Exception, e:
            logging.exception("urlopen error")
        self._finished = True

    def _progress(self, count, block, total):
        "fetcher progress reporting"
        logging.debug("_progress %s %s %s" % (count, block, total))
        #time.sleep(1)
        self._fetched += block
        # ensure we do not go over 100%
        self._percent = min(self._fetched/total, 1.0)

if __name__ == "__main__":
    pkgname = "synaptic"
    url = "http://screenshots.ubuntu.com/screenshot/synaptic"
    loading = "/usr/share/icons/hicolor/32x32/animations/softwarecenter-loading-installed.gif"
    d = ShowImageDialog("Synaptic Screenshot", url, loading, pkgname)
    d.run()
