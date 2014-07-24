# urlview.py
#  
#  Copyright (c) 2006 Sebastian Heinlein
#  
#  Author: Sebastian Heinlein <sebastian.heinlein@web.de>
#
#  This modul provides an inheritance of the gtk.TextView that is 
#  aware of http URLs and allows to open them in a browser.
#  It is based on the pygtk-demo "hypertext".
# 
#  This program is free software; you can redistribute it and/or 
#  modify it under the terms of the GNU General Public License as 
#  published by the Free Software Foundation; version 3.
# 
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# 
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
#  USA


import pygtk
import gtk
import pango
import subprocess
import os

class UrlTextView(gtk.TextView):
    def __init__(self, text=None):
        """TextView subclass that supports tagging/adding of links"""
        # init the parent
        gtk.TextView.__init__(self)
        # global hovering over link state
        self.hovering = False
        self.first = True
        # setup the buffer and signals
        self.set_property("editable", False)
        self.set_cursor_visible(False)
        self.buffer = gtk.TextBuffer()
        self.set_buffer(self.buffer)
        self.connect("event-after", self.event_after)
        self.connect("motion-notify-event", self.motion_notify_event)
        self.connect("visibility-notify-event", self.visibility_notify_event)
        #self.buffer.connect("changed", self.search_links)
        self.buffer.connect_after("insert-text", self.on_insert_text)
        # search text
        if text != None:
            self.buffer.set_text(text)

    def tag_link(self, start, end, url):
        """Apply the tag that marks links to the specified buffer selection"""
        tag = self.buffer.create_tag(None, 
                                     foreground="blue",
                                     underline=pango.UNDERLINE_SINGLE)
        tag.set_data("url", url)
        self.buffer.apply_tag(tag , start, end)

    def on_insert_text(self, buffer, iter_end, text, *args):
        """Search for http URLs in newly inserted text  
           and tag them accordingly"""
        iter = buffer.get_iter_at_offset(iter_end.get_offset() - len(text))
        iter_real_end = buffer.get_end_iter()
        for protocol in ["http://", "https://"]:
            while True:
                # search for the next URL in the buffer
                ret = iter.forward_search(protocol, 
                                      gtk.TEXT_SEARCH_VISIBLE_ONLY,
                                      iter_end)
                # if we reach the end break the loop
                if not ret:
                    break
                # get the position of the protocol prefix
                (match_start, match_end) = ret
                match_tmp = match_end.copy()
                while True:
                    # extend the selection to the complete URL
                    if match_tmp.forward_char():
                        text =  match_end.get_text(match_tmp)
                        if text in (" ", ")", "]", "\n", "\t",">","!"):
                            break
                    else:
                        break
                    match_end = match_tmp.copy()
                # call the tagging method for the complete URL
                url = match_start.get_text(match_end)
                tags = match_start.get_tags()
                tagged = False
                for tag in tags:
                    url = tag.get_data("url")
                    if url != "":
                        tagged = True
                        break
                if tagged == False:
                    self.tag_link(match_start, match_end, url)
                # set the starting point for the next search
                iter = match_end

    def event_after(self, text_view, event):
        """callback for mouse click events"""
        # we only react on left mouse clicks
        if event.type != gtk.gdk.BUTTON_RELEASE:
            return False
        if event.button != 1:
            return False

        # try to get a selection
        try:
            (start, end) = self.buffer.get_selection_bounds()
        except ValueError:
            pass
        else:
            if start.get_offset() != end.get_offset():
                return False

        # get the iter at the mouse position
        (x, y) = self.window_to_buffer_coords(gtk.TEXT_WINDOW_WIDGET,
                                              int(event.x), int(event.y))
        iter = self.get_iter_at_location(x, y)
        
        # call open_url if an URL is assigned to the iter
        tags = iter.get_tags()
        for tag in tags:
            url = tag.get_data("url")
            if url != None:
                self.open_url(url)
                break

    def open_url(self, url):
        """Open the specified URL in a browser"""
        # Find an appropiate browser
        if os.path.exists('/usr/bin/gnome-open'):
            command = ['gnome-open', url]
        else:
            command = ['x-www-browser', url]

        # Avoid to run the browser as user root
        if os.getuid() == 0 and os.environ.has_key('SUDO_USER'):
            command = ['sudo', '-u', os.environ['SUDO_USER']] + command

        subprocess.Popen(command)

    def motion_notify_event(self, text_view, event):
        """callback for the mouse movement event, that calls the
           check_hovering method with the mouse postition coordiantes"""
        x, y = text_view.window_to_buffer_coords(gtk.TEXT_WINDOW_WIDGET,
                                                 int(event.x), int(event.y))
        self.check_hovering(x, y)
        self.window.get_pointer()
        return False
    
    def visibility_notify_event(self, text_view, event):
        """callback if the widgets gets visible (e.g. moves to the foreground)
           that calls the check_hovering method with the mouse position
           coordinates"""
        (wx, wy, mod) = text_view.window.get_pointer()
        (bx, by) = text_view.window_to_buffer_coords(gtk.TEXT_WINDOW_WIDGET, wx,
                                                     wy)
        self.check_hovering(bx, by)
        return False

    def check_hovering(self, x, y):
        """Check if the mouse is above a tagged link and if yes show
           a hand cursor"""
        _hovering = False
        # get the iter at the mouse position
        iter = self.get_iter_at_location(x, y)
        
        # set _hovering if the iter has the tag "url"
        tags = iter.get_tags()
        for tag in tags:
            url = tag.get_data("url")
            if url != None:
                _hovering = True
                break

        # change the global hovering state
        if _hovering != self.hovering or self.first == True:
            self.first = False
            self.hovering = _hovering
            # Set the appropriate cursur icon
            if self.hovering:
                self.get_window(gtk.TEXT_WINDOW_TEXT).\
                        set_cursor(gtk.gdk.Cursor(gtk.gdk.HAND2))
            else:
                self.get_window(gtk.TEXT_WINDOW_TEXT).\
                        set_cursor(gtk.gdk.Cursor(gtk.gdk.LEFT_PTR))
