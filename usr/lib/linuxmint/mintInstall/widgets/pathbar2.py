# Copyright (C) 2009 Matthew McGowan
#
# Authors:
#   Matthew McGowan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from gi.repository import GLib
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango

import rgb
import cairo

from rgb import to_float as f

# pi constants
M_PI = 3.1415926535897931
PI_OVER_180 = 0.017453292519943295


def hack_point_in_rect(x, y, a):
    return (x > a.x and x < a.x + a.width) and (y > a.y and y < a.height)

def hack_rect_in_rect(a, b):
    a = hack_new_GdkRectangle(*a)
    for x,y in ((a.x, a.y), (a.x, a.y + a.height), (a.x + a.width, a.y), (a.x + a.width, a.y + a.height)):
        if (not hack_point_in_rect(x, y, b)):
            return False
    return True

def hack_new_GdkRectangle(x,y,w,h):
    r = Gdk.Rectangle()
    r.x = x
    r.y = y
    r.width = w
    r.height = h

    return r

class PathBar(Gtk.DrawingArea):

    # shapes
    SHAPE_RECTANGLE = 0
    SHAPE_START_ARROW = 1
    SHAPE_MID_ARROW = 2
    SHAPE_END_CAP = 3

    def __init__(self, group=None):
        Gtk.DrawingArea.__init__(self)
        self.__init_drawing()
        self.set_redraw_on_allocate(False)

        self.__parts = []
        self.__active_part = None
        self.__focal_part = None
        self.__button_down = False

        self.__scroller = None
        self.__scroll_xO = 0

        self.theme = self.__pick_theme()

        # setup event handling
        self.set_can_focus(True)
        self.set_events(Gdk.EventMask.POINTER_MOTION_MASK|
                        Gdk.EventMask.BUTTON_PRESS_MASK|
                        Gdk.EventMask.BUTTON_RELEASE_MASK|
                        Gdk.EventMask.KEY_RELEASE_MASK|
                        Gdk.EventMask.KEY_PRESS_MASK|
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)

        self.connect("motion-notify-event", self.__motion_notify_cb)
        self.connect("leave-notify-event", self.__leave_notify_cb)
        self.connect("button-press-event", self.__button_press_cb)
        self.connect("button-release-event", self.__button_release_cb)
#        self.connect("key-release-event", self.__key_release_cb)

        self.connect("realize", self.__realize_cb)
        self.connect("draw", self.__draw_cb)
        self.connect("style-set", self.__style_change_cb)
        self.connect("size-allocate", self.__allocation_change_cb)
	self.last_label = None
        return

    def set_active(self, part):
        part.set_state(Gtk.StateFlags.ACTIVE)
        prev, redraw = self.__set_active(part)
        if redraw:
            self.queue_draw_area(*prev.get_allocation_tuple())
            self.queue_draw_area(*part.get_allocation_tuple())
	self.last_label = None
        return

    def get_active(self):
        return self.__active_part

#    def get_left_part(self):
#        active = self.get_active()
#        if not active:
#            return self.__parts[0]

#        i = self.__parts.index(active)+1
#        if i > len(self.__parts)-1:
#            i = 0
#        return self.__parts[i]

#    def get_right_part(self):
#        active = self.get_active()
#        if not active:
#            return self.__parts[0]

#        i = self.__parts.index(active)-1
#        if i < 0:
#            i = len(self.__parts)-1
#        return self.__parts[i]

    def append(self, part):
        prev, did_shrink = self.__append(part)
        if not self.get_property("visible"):
            return False

        if self.theme.animate and len(self.__parts) > 1:
            aw = self.theme.arrow_width

            # calc draw_area
            x,y,w,h = part.get_allocation_tuple()
            w += aw

            # begin scroll animation
            self.__hscroll_out_init(
                part.get_width(),
                hack_new_GdkRectangle(x,y,w,h),
                self.theme.scroll_duration_ms,
                self.theme.scroll_fps
                )
        else:
            self.queue_draw_area(*part.get_allocation_tuple())
        return False

    def remove(self, part):
        if len(self.__parts)-1 < 1:
            #print 'The first part is sacred ;)'
            return

        old_w = self.__draw_width()

        # remove part from interal part list
	try:
	        del self.__parts[self.__parts.index(part)]
	except:
		pass

        self.__compose_parts(self.__parts[-1], False)

        if old_w >= self.get_allocation().width:
            self.__grow_check(old_w, self.get_allocation())
            self.queue_draw()

        else:
            self.queue_draw_area(*part.get_allocation_tuple())
            self.queue_draw_area(*self.__parts[-1].get_allocation_tuple())
        return

    def __set_active(self, part):

	bigger = False
	for i in self.id_to_part:
            apart = self.id_to_part[i]
	    if bigger:
		self.remove(apart)
	    if apart == part:
		bigger = True

        prev_active = self.__active_part
        redraw = False
        if part.callback:
            part.callback(self, part.obj)
        if prev_active and prev_active != part:
            prev_active.set_state(Gtk.StateFlags.NORMAL)
            redraw = True

        self.__active_part = part
        return prev_active, redraw

    def __append(self, part):
        # clean up any exisitng scroll callbacks
        if self.__scroller:
            GLib.source_remove(self.__scroller)
        self.__scroll_xO = 0

        # the basics
        x = self.__draw_width()
        self.__parts.append(part)
        part.set_pathbar(self)

        prev_active = self.set_active(part)

        # determin part shapes, and calc modified parts widths
        prev = self.__compose_parts(part, True)
        # set the position of new part
        part.set_x(x)

        # check parts fit to widgets allocated width
        if x + part.get_width() > self.get_allocation().width  and \
            self.get_allocation().width != 1:
            self.__shrink_check(self.get_allocation())
            return prev, True

        return prev, False

#    def __shorten(self, n):
#        n = int(n)
#        old_w = self.__draw_width()
#        end_active = self.get_active() == self.__parts[-1]

#        if len(self.__parts)-n < 1:
#            print WARNING + 'The first part is sacred ;)' + ENDC
#            return old_w, False

#        del self.__parts[-n:]
#        self.__compose_parts(self.__parts[-1], False)

#        if end_active:
#            self.set_active(self.__parts[-1])

#        if old_w >= self.allocation.width:
#            self.__grow_check(old_w, self.allocation)
#            return old_w, True

#        return old_w, False

    def __shrink_check(self, allocation):
        path_w = self.__draw_width()
        shrinkage = path_w - allocation.x
        mpw = self.theme.min_part_width
        xO = 0

        for part in self.__parts[:-1]:
            w = part.get_width()
            dw = 0

            if w - shrinkage <= mpw:
                dw = w - mpw
                shrinkage -= dw
                part.set_size(mpw, -1)
                part.set_x(part.get_x() - xO)

            else:
                part.set_size(w - shrinkage, -1)
                part.set_x(part.get_x() - xO)
                dw = shrinkage
                shrinkage = 0

            xO += dw

        last = self.__parts[-1]
        last.set_x(last.get_x() - xO)
        return

    def __grow_check(self, old_width, allocation):
        parts = self.__parts
        if len(parts) == 0:
            return

        growth = old_width - self.__draw_width()
        parts.reverse()

        for part in parts:
            bw = part.get_size_requisition()[0]
            w = part.get_width()

            if w < bw:
                dw = bw - w

                if dw <= growth:
                    growth -= dw
                    part.set_size(bw, -1)
                    part.set_x(part.get_x() + growth)

                else:
                    part.set_size(w + growth, -1)
                    growth = 0

            else:
                part.set_x(part.get_x() + growth)

        parts.reverse()
        shift =  parts[0].get_x()

        # left align parts
        if shift > 0:
            for part in parts: part.set_x(part.get_x() - shift)
        return

    def __compose_parts(self, last, prev_set_size):
        parts = self.__parts

        if len(parts) == 1:
            last.set_shape(self.SHAPE_RECTANGLE)
            last.set_size(*last.calc_size_requisition())
            prev = None

        elif len(parts) == 2:
            prev = parts[0]
            prev.set_shape(self.SHAPE_START_ARROW)
            prev.calc_size_requisition()

            last.set_shape(self.SHAPE_END_CAP)
            last.set_size(*last.calc_size_requisition())

        else:
            prev = parts[-2]
            prev.set_shape(self.SHAPE_MID_ARROW)
            prev.calc_size_requisition()

            last.set_shape(self.SHAPE_END_CAP)
            last.set_size(*last.calc_size_requisition())

        if prev and prev_set_size:
            prev.set_size(*prev.get_size_requisition())
        return prev

    def __draw_width(self):
        l = len(self.__parts)
        if l == 0:
            return 0
        a = self.__parts[-1].allocation
        return a.x + a.width

    def __hscroll_out_init(self, distance, draw_area, duration, fps):
        self.__scroller = GLib.timeout_add(
            int(1000.0 / fps),  # interval
            self.__hscroll_out_cb,
            distance,
            duration*0.001,   # 1 over duration (converted to seconds)
            GLib.get_current_time(),
            draw_area.x,
            draw_area.y,
            draw_area.width,
            draw_area.height)
        return

    def __hscroll_out_cb(self, distance, duration, start_t, x, y, w, h):
        cur_t = GLib.get_current_time()
        xO = distance - distance*((cur_t - start_t) / duration)

        if xO > 0:
            self.__scroll_xO = xO
            self.queue_draw_area(x, y, w, h)
        else:   # final frame
            self.__scroll_xO = 0
            # redraw the entire widget
            # incase some timeouts are skipped due to high system load
            self.queue_draw()
            self.__scroller = None
            return False
        return True

    def __part_at_xy(self, x, y):
        for part in self.__parts:
            a = part.get_allocation()
            if (hack_point_in_rect(x, y, a)):
                return part
        return None

    def __draw_hscroll(self, cr):
        if len(self.__parts) < 2:
            return

        # draw the last two parts
        prev, last = self.__parts[-2:]

        # style theme stuff
        style, r, aw, shapes = self.get_style_context(), self.theme.curvature, \
            self.theme.arrow_width, self.__shapes

        # draw part that need scrolling
        self.__draw_part(cr,
                         last,
                         style,
                         r,
                         aw,
                         shapes,
                         self.__scroll_xO)

        # draw the last part that does not scroll
        self.__draw_part(cr,
                         prev,
                         style,
                         r,
                         aw,
                         shapes)
        return

    def __draw_all(self, cr):
        event_area = cr.path_extents()
        style = self.get_style_context()
        r = self.theme.curvature
        aw = self.theme.arrow_width
        shapes = self.__shapes

        # if a scroll is pending we want to not draw the final part,
        # as we don't want to prematurely reveal the part befor the
        # scroll animation has had a chance to start
        if self.__scroller:
            parts = self.__parts[:-1]
        else:
            parts = self.__parts

        parts.reverse()
        for part in parts:
            if (hack_rect_in_rect (event_area, part.get_allocation())):
                self.__draw_part(cr, part, style, r, aw, shapes)
        parts.reverse()
        return

    def __draw_part_ltr(self, cr, part, style, r, aw, shapes, sxO=0):
        x, y, w, h = part.get_allocation_tuple()
        shape = part.shape
        state = part.state
        icon_pb = part.icon.pixbuf

        cr.save()
        cr.translate(x-sxO, y)

        # draw bg
        self.__draw_part_bg(cr, part, w, h, state, shape, style,r, aw, shapes)

        # determine left margin.  left margin depends on part shape
        # and whether there exists an icon or not
        if shape == self.SHAPE_MID_ARROW or shape == self.SHAPE_END_CAP:
            margin = int(0.75*self.theme.arrow_width + self.theme.xpadding)
        else:
            margin = self.theme.xpadding

        # draw icon
        if icon_pb:
            cr.set_source_pixbuf(
                icon_pb,
                self.theme.xpadding-sxO,
                (alloc.height - icon_pb.get_height())/2)
            cr.paint()
            margin += icon_pb.get_width() + self.theme.spacing

        # if space is limited and an icon is set, dont draw label
        # otherwise, draw label
        if w == self.theme.min_part_width and icon_pb:
            pass

        else:
            layout = part.get_layout()
            lw, lh = layout.get_pixel_size()
            dst_x = x + margin - int(sxO)
            dst_y = (self.get_allocation().height - lh)/2+1
            Gtk.render_layout(style, cr, dst_x, dst_y, layout)

        cr.restore()
        return

    def __draw_part_rtl(self, cr, part, style, r, aw, shapes, sxO=0):
        x, y, w, h = part.get_allocation_tuple()
        shape = part.shape
        state = part.state
        icon_pb = part.icon.pixbuf

        cr.save()
        cr.translate(x+sxO, y)

        # draw bg
        self.__draw_part_bg(cr, part, w, h, state, shape, style,r, aw, shapes)

        # determine left margin.  left margin depends on part shape
        # and whether there exists an icon or not
        if shape == self.SHAPE_MID_ARROW or shape == self.SHAPE_END_CAP:
            margin = self.theme.arrow_width + self.theme.xpadding
        else:
            margin = self.theme.xpadding

        # draw icon
        if icon_pb:
            margin += icon_pb.get_width()
            cr.set_source_pixbuf(
                icon_pb,
                w - margin + sxO,
                (h - icon_pb.get_height())/2)
            cr.paint()
            margin += self.spacing

        # if space is limited and an icon is set, dont draw label
        # otherwise, draw label
        if w == self.theme.min_part_width and icon_pb:
            pass

        else:
            layout = part.get_layout()
            lw, lh = layout.get_pixel_size()
            dst_x = x + part.get_width() - margin - lw + int(sxO)
            dst_y = (self.get_allocation().height - lh)/2+1
            Gtk.render_layout(style, cr, dst_x, dst_y, layout)

        cr.restore()
        return

    def __draw_part_bg(self, cr, part, w, h, state, shape, style, r, aw, shapes):
        # outer slight bevel or focal highlight
        shapes[shape](cr, 0, 0, w, h, r, aw)
        cr.set_source_rgba(0, 0, 0, 0.055)
        cr.fill()

        # colour scheme dicts
        bg = self.theme.bg_colors
        outer = self.theme.dark_line_colors
        inner = self.theme.light_line_colors

        # bg linear vertical gradient
        if state != Gtk.StateFlags.PRELIGHT:
            color1, color2 = bg[state]
        else:
            if part != self.get_active():
                color1, color2 = bg[self.theme.PRELIT_NORMAL]
            else:
                color1, color2 = bg[self.theme.PRELIT_ACTIVE]

        shapes[shape](cr, 1, 1, w-1, h-1, r, aw)
        lin = cairo.LinearGradient(0, 0, 0, h-1)
        lin.add_color_stop_rgb(0.0, *color1)
        lin.add_color_stop_rgb(1.0, *color2)
        cr.set_source(lin)
        cr.fill()

        cr.set_line_width(1.0)
        # strong outline
        shapes[shape](cr, 1.5, 1.5, w-1.5, h-1.5, r, aw)
        cr.set_source_rgb(*outer[state])
        cr.stroke()

        # inner bevel/highlight
        if self.theme.light_line_colors[state]:
            shapes[shape](cr, 2.5, 2.5, w-2.5, h-2.5, r, aw)
            r, g, b = inner[state]
            cr.set_source_rgba(r, g, b, 0.6)
            cr.stroke()
        return

    def __shape_rect(self, cr, x, y, w, h, r, aw):
        global M_PI, PI_OVER_180
        cr.new_sub_path()
        cr.arc(r+x, r+y, r, M_PI, 270*PI_OVER_180)
        cr.arc(w-r, r+y, r, 270*PI_OVER_180, 0)
        cr.arc(w-r, h-r, r, 0, 90*PI_OVER_180)
        cr.arc(r+x, h-r, r, 90*PI_OVER_180, M_PI)
        cr.close_path()
        return

    def __shape_start_arrow_ltr(self, cr, x, y, w, h, r, aw):
        global M_PI, PI_OVER_180
        cr.new_sub_path()
        cr.arc(r+x, r+y, r, M_PI, 270*PI_OVER_180)
        # arrow head
        cr.line_to(w-aw+1, y)
        cr.line_to(w, (h+y)*0.5)
        cr.line_to(w-aw+1, h)
        cr.arc(r+x, h-r, r, 90*PI_OVER_180, M_PI)
        cr.close_path()
        return

    def __shape_mid_arrow_ltr(self, cr, x, y, w, h, r, aw):
        cr.move_to(-1, y)
        # arrow head
        cr.line_to(w-aw+1, y)
        cr.line_to(w, (h+y)*0.5)
        cr.line_to(w-aw+1, h)
        cr.line_to(-1, h)
        cr.close_path()
        return

    def __shape_end_cap_ltr(self, cr, x, y, w, h, r, aw):
        global M_PI, PI_OVER_180
        cr.move_to(-1, y)
        cr.arc(w-r, r+y, r, 270*PI_OVER_180, 0)
        cr.arc(w-r, h-r, r, 0, 90*PI_OVER_180)
        cr.line_to(-1, h)
        cr.close_path()
        return

    def __shape_start_arrow_rtl(self, cr, x, y, w, h, r, aw):
        global M_PI, PI_OVER_180
        cr.new_sub_path()
        cr.move_to(x, (h+y)*0.5)
        cr.line_to(aw-1, y)
        cr.arc(w-r, r+y, r, 270*PI_OVER_180, 0)
        cr.arc(w-r, h-r, r, 0, 90*PI_OVER_180)
        cr.line_to(aw-1, h)
        cr.close_path()
        return

    def __shape_mid_arrow_rtl(self, cr, x, y, w, h, r, aw):
        cr.move_to(x, (h+y)*0.5)
        cr.line_to(aw-1, y)
        cr.line_to(w+1, y)
        cr.line_to(w+1, h)
        cr.line_to(aw-1, h)
        cr.close_path()
        return

    def __shape_end_cap_rtl(self, cr, x, y, w, h, r, aw):
        global M_PI, PI_OVER_180
        cr.arc(r+x, r+y, r, M_PI, 270*PI_OVER_180)
        cr.line_to(w+1, y)
        cr.line_to(w+1, h)
        cr.arc(r+x, h-r, r, 90*PI_OVER_180, M_PI)
        cr.close_path()
        return

    def __state(self, part):
        # returns the idle state of the part depending on
        # whether part is active or not.
        if part == self.__active_part:
            return Gtk.StateFLags.ACTIVE
        return Gtk.StateFlags.NORMAL

    def __tooltip_check(self, part):
        # only show a tooltip if part is truncated, i.e. not all label text is
        # visible.
        if part.is_truncated():
            self.set_has_tooltip(False)
            GLib.timeout_add(50, self.__set_tooltip_cb, part.label)
        else:
            self.set_has_tooltip(False)
        return

    def __set_tooltip_cb(self, text):
        # callback allows the tooltip position to be updated as pointer moves
        # accross different parts
        self.set_has_tooltip(True)
        self.set_tooltip_markup(text)
        return False

    def __pick_theme(self, name=None):
        name = name or Gtk.Settings.get_default().get_property("gtk-theme-name")
        themes = PathBarThemes.DICT
        if themes.has_key(name):
            return themes[name]()
        #print "No styling hints for %s are available" % name
        return PathBarThemeHuman()

    def __init_drawing(self):
        if self.get_direction() != Gtk.TextDirection.RTL:
            self.__draw_part = self.__draw_part_ltr
            self.__shapes = {
                self.SHAPE_RECTANGLE : self.__shape_rect,
                self.SHAPE_START_ARROW : self.__shape_start_arrow_ltr,
                self.SHAPE_MID_ARROW : self.__shape_mid_arrow_ltr,
                self.SHAPE_END_CAP : self.__shape_end_cap_ltr}
        else:
            self.__draw_part = self.__draw_part_rtl
            self.__shapes = {
                self.SHAPE_RECTANGLE : self.__shape_rect,
                self.SHAPE_START_ARROW : self.__shape_start_arrow_rtl,
                self.SHAPE_MID_ARROW : self.__shape_mid_arrow_rtl,
                self.SHAPE_END_CAP : self.__shape_end_cap_rtl}
        return

    def __motion_notify_cb(self, widget, event):
        if self.__scroll_xO > 0:
            return

        part = self.__part_at_xy(event.x, event.y)
        prev_focal = self.__focal_part

        if self.__button_down:
            if prev_focal and part != prev_focal:
                prev_focal.set_state(self.__state(prev_focal))
                self.queue_draw_area(*prev_focal.get_allocation_tuple())
            return

        self.__button_down = False
        if part and part.state != Gtk.StateFlags.PRELIGHT:
            self.__tooltip_check(part)
            part.set_state(Gtk.StateFlags.PRELIGHT)

            if prev_focal:
                prev_focal.set_state(self.__state(prev_focal))
                self.queue_draw_area(*prev_focal.get_allocation_tuple())

            self.__focal_part = part
            self.queue_draw_area(*part.get_allocation_tuple())

        elif not part and prev_focal != None:
            prev_focal.set_state(self.__state(prev_focal))
            self.queue_draw_area(*prev_focal.get_allocation_tuple())
            self.__focal_part = None
        return

    def __leave_notify_cb(self, widget, event):
        self.__button_down = False
        prev_focal = self.__focal_part
        if prev_focal:
            prev_focal.set_state(self.__state(prev_focal))
            self.queue_draw_area(*prev_focal.get_allocation_tuple())
        self.__focal_part = None
        return

    def __button_press_cb(self, widget, event):
        self.__button_down = True
        part = self.__part_at_xy(event.x, event.y)
        if part:
            part.set_state(Gtk.StateFlags.SELECTED)
            self.queue_draw_area(*part.get_allocation_tuple())
        return

    def __button_release_cb(self, widget, event):
        part = self.__part_at_xy(event.x, event.y)

        if self.__focal_part and self.__focal_part != part:
            pass
        elif part and self.__button_down:
            self.grab_focus()
            prev_active, redraw = self.__set_active(part)
            part.set_state(Gtk.StateFlags.PRELIGHT)
            self.queue_draw_area(*part.get_allocation_tuple())

            if redraw:
                self.queue_draw_area(*prev_active.get_allocation_tuple())
        self.__button_down = False
        return

#    def __key_release_cb(self, widget, event):
#        part = None

#        # left key pressed
#        if event.keyval == 65363:
#            part = self.get_left_part()

#        # right key pressed
#        elif event.keyval == 65361:
#            part = self.get_right_part()

#        if not part: return

#        prev_active = self.set_active(part)
#        self.queue_draw_area(*part.allocation)
#        if prev_active:
#            self.queue_draw_area(*prev_active.allocation)

#        part.emit("clicked", event.copy())
#        return

    def __realize_cb(self, widget):
        self.theme.load(widget.get_style())
        return

    def __draw_cb(self, widget, cr):
        if self.theme.base_hack:
            cr.set_source_rgb(*self.theme.base_hack)
            cr.paint()

        if self.__scroll_xO:
            self.__draw_hscroll(cr)
        else:
            self.__draw_all(cr)

        return

    def __style_change_cb(self, widget, old_style):
        # when alloc.width == 1, this is typical of an unallocated widget,
        # lets not break a sweat for nothing...
        if self.get_allocation().width == 1:
            return

        self.theme = self.__pick_theme()
        self.theme.load(widget.get_style())
        # set height to 0 so that if part height has been reduced the widget will
        # shrink to an appropriate new height based on new font size
        self.set_size_request(-1, 28)

        parts = self.__parts
        self.__parts = []

        # recalc best fits, re-append then draw all
        for part in parts:

            if part.icon.pixbuf:
                part.icon.load_pixbuf()

            part.calc_size_requisition()
            self.__append(part)

        self.queue_draw()
        return

    def __allocation_change_cb(self, widget, allocation):
        if allocation.x == 1:
            return

        path_w = self.__draw_width()
        if path_w == allocation.x:
            return
        elif path_w > allocation.x:
            self.__shrink_check(allocation)
        else:
            self.__grow_check(allocation.x, allocation)

        self.queue_draw()
        return


class PathPart:

    def __init__(self, id, label=None, callback=None, obj=None):
        self.__requisition = (0,0)
        self.__layout = None
        self.__pbar = None

	self.id = id

        self.allocation = hack_new_GdkRectangle(0,0,0,0)
        self.state = Gtk.StateFlags.NORMAL
        self.shape = PathBar.SHAPE_RECTANGLE

        self.callback = callback
	self.obj = obj
        self.set_label(label or "")
        self.icon = PathBarIcon()
        return

    def set_callback(self, cb):
        self.callback = cb
        return

    def set_label(self, label):
        # escape special characters
        label = GLib.markup_escape_text(label.strip())
        # some hackery to preserve italics markup
        label = label.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
        self.label = label
        return

    def set_icon(self, stock_icon, size=Gtk.IconSize.BUTTON):
        self.icon.specify(stock_icon, size)
        self.icon.load_pixbuf()
        return

    def set_state(self, gtk_state):
        self.state = gtk_state
        return

    def set_shape(self, shape):
        self.shape = shape
        return

    def set_x(self, x):
        self.allocation.x = int(x)
        return

    def set_size(self, w, h):
        if w != -1: self.allocation.width = int(w)
        if h != -1: self.allocation.height = int(h)
        self.__calc_layout_width(self.__layout, self.shape, self.__pbar)
        return

    def set_pathbar(self, path_bar):
        self.__pbar = path_bar
        return

    def get_x(self):
        return self.allocation.x

    def get_width(self):
        return self.allocation.width

    def get_height(self):
        return self.allocation.height

    def get_label(self):
        return self.label

    def get_allocation(self):
        return hack_new_GdkRectangle(*self.get_allocation_tuple())

    def get_allocation_tuple(self):
        x, y, w, h = (self.allocation.x, self.allocation.y, self.allocation.width, self.allocation.height)
        if self.__pbar.get_direction() != Gtk.TextDirection.RTL:
            return x, y, w, h
        x = self.__pbar.allocation.width-x-w
        return x, y, w, h

    def get_size_requisition(self):
        return self.__requisition

    def get_layout(self):
        return self.__layout

    def activate(self):
        self.__pbar.set_active(self)
        return

    def calc_size_requisition(self):
        pbar = self.__pbar

        # determine widget size base on label width
        self.__layout = self.__layout_text(self.label, pbar.get_pango_context())
        extents = self.__layout.get_pixel_extents()

        # calc text width + 2 * padding, text height + 2 * ypadding
        w = extents[1].width + 2*pbar.theme.xpadding
        h = max(extents[1].height + 2*pbar.theme.ypadding, pbar.get_allocation().y)

        # if has icon add some more pixels on
        if self.icon.pixbuf:
            w += self.icon.pixbuf.get_width() + pbar.theme.spacing
            h = max(self.icon.pixbuf.get_height() + 2*pbar.theme.ypadding, h)

        # extend width depending on part shape  ...
        if self.shape == PathBar.SHAPE_START_ARROW or \
            self.shape == PathBar.SHAPE_END_CAP:
            w += pbar.theme.arrow_width

        elif self.shape == PathBar.SHAPE_MID_ARROW:
            w += 2*pbar.theme.arrow_width

        # if height greater than current height request,
        # reset height request to higher value
        # i get the feeling this should be in set_size_request(), but meh
        if h > pbar.get_allocation().y:
            pbar.set_size_request(-1, h)

        self.__requisition = (w,h)
        return w, h

    def is_truncated(self):
        return self.__requisition[0] != self.allocation.width

    def __layout_text(self, text, pango_context):
        layout = Pango.Layout(pango_context)
        layout.set_markup('%s' % text)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        return layout

    def __calc_layout_width(self, layout, shape, pbar):
        # set layout width
        if self.icon.pixbuf:
            icon_w = self.icon.pixbuf.get_width() + pbar.theme.spacing
        else:
            icon_w = 0

        w = self.allocation.width
        if shape == PathBar.SHAPE_MID_ARROW:
            layout.set_width((w - 2*pbar.theme.arrow_width -
                2*pbar.theme.xpadding - icon_w)*Pango.SCALE)

        elif shape == PathBar.SHAPE_START_ARROW or \
            shape == PathBar.SHAPE_END_CAP:
            layout.set_width((w - pbar.theme.arrow_width - 2*pbar.theme.xpadding -
                icon_w)*Pango.SCALE)
        else:
            layout.set_width((w - 2*pbar.theme.xpadding - icon_w)*Pango.SCALE)
        return


class PathBarIcon:

    def __init__(self, name=None, size=None):
        self.name = name
        self.size = size
        self.pixbuf = None
        return

    def specify(self, name, size):
        self.name = name
        self.size = size
        return

    def load_pixbuf(self):
        if not self.name:
            print 'Error: No icon specified.'
            return
        if not self.size:
            print 'Note: No icon size specified.'

        def render_icon(icon_set, name, size):
            self.pixbuf = icon_set.render_icon(
                style,
                Gtk.TextDirection.NONE,
                Gtk.StateFlags.NORMAL,
                self.size or Gtk.IconSize.BUTTON,
                Gtk.Image(),
                None)
            return

        style = Gtk.StyleContext()
        icon_set = style.lookup_icon_set(self.name)

        if not icon_set:
            t = Gtk.IconTheme.get_default()
            self.pixbuf = t.lookup_icon(self.name, self.size, 0).load_icon()
        else:
            icon_set = style.lookup_icon_set(self.name)
            render_icon(icon_set, self.name, self.size)

        if not self.pixbuf:
            print 'Error: No name failed to match any installed icon set.'
            self.name = Gtk.STOCK_MISSING_IMAGE
            icon_set = style.lookup_icon_set(self.name)
            render_icon(icon_set, self.name, self.size)
        return


class PathBarThemeHuman:

    PRELIT_NORMAL = 10
    PRELIT_ACTIVE = 11

    curvature = 2.5
    min_part_width = 56
    xpadding = 8
    ypadding = 2
    spacing = 4
    arrow_width = 13
    scroll_duration_ms = 150
    scroll_fps = 50
    animate = Gtk.Settings.get_default().get_property("gtk-enable-animations")

    def __init__(self):
        return

    def load(self, style):
        mid = style.mid
        dark = style.dark
        light = style.light
        text = style.text
        active = rgb.mix_color(mid[Gtk.StateFlags.NORMAL],
                               mid[Gtk.StateFlags.SELECTED], 0.25)

        self.bg_colors = {
            Gtk.StateFlags.NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.2)),
                                f(mid[Gtk.StateFlags.NORMAL])),

            Gtk.StateFlags.ACTIVE: (f(rgb.shade(active, 1.2)),
                               f(active)),

            Gtk.StateFlags.SELECTED: (f(mid[Gtk.StateFlags.ACTIVE]),
                                 f(mid[Gtk.StateFlags.ACTIVE])),

            self.PRELIT_NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.25)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.05))),

            self.PRELIT_ACTIVE: (f(rgb.shade(active, 1.25)),
                                 f(rgb.shade(active, 1.05)))
            }

        self.dark_line_colors = {
            Gtk.StateFlags.NORMAL: f(dark[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.ACTIVE: f(dark[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.SELECTED: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.9)),
            Gtk.StateFlags.PRELIGHT: f(dark[Gtk.StateFlags.PRELIGHT])
            }

        self.light_line_colors = {
            Gtk.StateFlags.NORMAL: f(light[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.ACTIVE: f(light[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.SELECTED: None,
            Gtk.StateFlags.PRELIGHT: f(light[Gtk.StateFlags.PRELIGHT])
            }

        self.text_state = {
            Gtk.StateFlags.NORMAL: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.PRELIGHT: Gtk.StateFlags.PRELIGHT
            }

        self.base_hack = None
        return


class PathBarThemeHumanClearlooks(PathBarThemeHuman):

    def __init__(self):
        PathBarThemeHuman.__init__(self)
        return

    def __init__(self):
        return

    def load(self, style):
        mid = style.mid
        dark = style.dark
        light = style.light
        text = style.text
        active = rgb.mix_color(mid[Gtk.StateFlags.NORMAL],
                               mid[Gtk.StateFlags.SELECTED], 0.25)

        self.bg_colors = {
            Gtk.StateFlags.NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.20)),
                                f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.05))),

            Gtk.StateFlags.ACTIVE: (f(rgb.shade(active, 1.20)),
                               f(rgb.shade(active, 1.05))),

            Gtk.StateFlags.SELECTED: (f(rgb.shade(mid[Gtk.StateFlags.ACTIVE], 1.15)),
                                f(mid[Gtk.StateFlags.ACTIVE])),

            self.PRELIT_NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.35)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.15))),

            self.PRELIT_ACTIVE: (f(rgb.shade(active, 1.35)),
                                 f(rgb.shade(active, 1.15)))
            }

        self.dark_line_colors = {
            Gtk.StateFlags.NORMAL: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.975)),
            Gtk.StateFlags.ACTIVE: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.975)),
            Gtk.StateFlags.SELECTED: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.95)),
            Gtk.StateFlags.PRELIGHT: f(dark[Gtk.StateFlags.PRELIGHT])
            }

        self.light_line_colors = {
            Gtk.StateFlags.NORMAL: None,
            Gtk.StateFlags.ACTIVE: None,
            Gtk.StateFlags.SELECTED: f(mid[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.PRELIGHT: f(light[Gtk.StateFlags.PRELIGHT])
            }

        self.text_state = {
            Gtk.StateFlags.NORMAL: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.PRELIGHT: Gtk.StateFlags.PRELIGHT
            }

        self.base_hack = None
        return


class PathBarThemeDust(PathBarThemeHuman):

    def __init__(self):
        PathBarThemeHuman.__init__(self)
        return

    def load(self, style):
        mid = style.mid
        dark = style.dark
        light = style.light
        text = style.text
        active = rgb.mix_color(mid[Gtk.StateFlags.NORMAL],
                               light[Gtk.StateFlags.SELECTED], 0.3)

        self.bg_colors = {
            Gtk.StateFlags.NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.3)),
                                f(mid[Gtk.StateFlags.NORMAL])),

            Gtk.StateFlags.ACTIVE: (f(rgb.shade(active, 1.3)),
                               f(active)),

            Gtk.StateFlags.SELECTED: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 0.95)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 0.95))),

            self.PRELIT_NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.35)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.15))),

            self.PRELIT_ACTIVE: (f(rgb.shade(active, 1.35)),
                                 f(rgb.shade(active, 1.15)))
            }

        self.dark_line_colors = {
            Gtk.StateFlags.NORMAL: f(dark[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.ACTIVE: f(dark[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.SELECTED: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.95)),
            Gtk.StateFlags.PRELIGHT: f(dark[Gtk.StateFlags.PRELIGHT])
            }

        self.light_line_colors = {
            Gtk.StateFlags.NORMAL: f(light[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.ACTIVE: f(light[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.SELECTED: None,
            Gtk.StateFlags.PRELIGHT: f(light[Gtk.StateFlags.PRELIGHT])
            }

        self.text_state = {
            Gtk.StateFlags.NORMAL: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.PRELIGHT: Gtk.StateFlags.PRELIGHT
            }

        self.base_hack = None
        return


class PathBarThemeNewWave(PathBarThemeHuman):

    curvature = 1.5

    def __init__(self):
        PathBarThemeHuman.__init__(self)
        return

    def load(self, style):
        mid = style.mid
        dark = style.dark
        light = style.light
        text = style.text
        active = rgb.mix_color(mid[Gtk.StateFlags.NORMAL],
                               light[Gtk.StateFlags.SELECTED], 0.5)

        self.bg_colors = {
            Gtk.StateFlags.NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.01)),
                                f(mid[Gtk.StateFlags.NORMAL])),

            Gtk.StateFlags.ACTIVE: (f(rgb.shade(active, 1.01)),
                               f(active)),

            Gtk.StateFlags.SELECTED: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 0.95)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 0.95))),

            self.PRELIT_NORMAL: (f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.2)),
                                 f(rgb.shade(mid[Gtk.StateFlags.NORMAL], 1.15))),

            self.PRELIT_ACTIVE: (f(rgb.shade(active, 1.2)),
                                 f(rgb.shade(active, 1.15)))
            }

        self.dark_line_colors = {
            Gtk.StateFlags.NORMAL: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.95)),
            Gtk.StateFlags.ACTIVE: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.95)),
            Gtk.StateFlags.SELECTED: f(rgb.shade(dark[Gtk.StateFlags.ACTIVE], 0.95)),
            Gtk.StateFlags.PRELIGHT: f(dark[Gtk.StateFlags.PRELIGHT])
            }

        self.light_line_colors = {
            Gtk.StateFlags.NORMAL: f(rgb.shade(light[Gtk.StateFlags.NORMAL], 1.2)),
            Gtk.StateFlags.ACTIVE: f(rgb.shade(light[Gtk.StateFlags.NORMAL], 1.2)),
            Gtk.StateFlags.SELECTED: None,
            Gtk.StateFlags.PRELIGHT: f(rgb.shade(light[Gtk.StateFlags.PRELIGHT], 1.2))
            }

        self.text_state = {
            Gtk.StateFlags.NORMAL: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.PRELIGHT: Gtk.StateFlags.PRELIGHT
            }

        self.base_hack = f(gtk.gdk.color_parse("#F2F2F2"))
        return


class PathBarThemeHicolor:

    PRELIT_NORMAL = 10
    PRELIT_ACTIVE = 11

    curvature = 0.5
    min_part_width = 56
    xpadding = 15
    ypadding = 10
    spacing = 10
    arrow_width = 15
    scroll_duration_ms = 150
    scroll_fps = 50
    animate = Gtk.Settings.get_default().get_property("gtk-enable-animations")

    def __init__(self):
        return

    def load(self, style):
        mid = style.mid
        dark = style.dark
        light = style.light
        text = style.text

        self.bg_colors = {
            Gtk.StateFlags.NORMAL: (f(mid[Gtk.StateFlags.NORMAL]),
                               f(mid[Gtk.StateFlags.NORMAL])),

            Gtk.StateFlags.ACTIVE: (f(mid[Gtk.StateFlags.ACTIVE]),
                               f(mid[Gtk.StateFlags.ACTIVE])),

            Gtk.StateFlags.SELECTED: (f(mid[Gtk.StateFlags.SELECTED]),
                                 f(mid[Gtk.StateFlags.SELECTED])),

            self.PRELIT_NORMAL: (f(mid[Gtk.StateFlags.PRELIGHT]),
                                 f(mid[Gtk.StateFlags.PRELIGHT])),

            self.PRELIT_ACTIVE: (f(mid[Gtk.StateFlags.PRELIGHT]),
                                 f(mid[Gtk.StateFlags.PRELIGHT]))
            }

        self.dark_line_colors = {
            Gtk.StateFlags.NORMAL: f(dark[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.ACTIVE: f(dark[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.SELECTED: f(dark[Gtk.StateFlags.SELECTED]),
            Gtk.StateFlags.PRELIGHT: f(dark[Gtk.StateFlags.PRELIGHT])
            }

        self.light_line_colors = {
            Gtk.StateFlags.NORMAL: f(light[Gtk.StateFlags.NORMAL]),
            Gtk.StateFlags.ACTIVE: f(light[Gtk.StateFlags.ACTIVE]),
            Gtk.StateFlags.SELECTED: None,
            Gtk.StateFlags.PRELIGHT: f(light[Gtk.StateFlags.PRELIGHT])
            }

        self.text_state = {
            Gtk.StateFlags.NORMAL: Gtk.StateFlags.NORMAL,
            Gtk.StateFlags.ACTIVE: Gtk.StateFlags.ACTIVE,
            Gtk.StateFlags.SELECTED: Gtk.StateFlags.SELECTED,
            Gtk.StateFlags.PRELIGHT: Gtk.StateFlags.PRELIGHT
            }

        self.base_hack = None
        return


class PathBarThemes:

    DICT = {
        "Human": PathBarThemeHuman,
        "Human-Clearlooks": PathBarThemeHumanClearlooks,
        "HighContrastInverse": PathBarThemeHicolor,
        "HighContrastLargePrintInverse": PathBarThemeHicolor,
        "Dust": PathBarThemeDust,
        "Dust Sand": PathBarThemeDust,
        "New Wave": PathBarThemeNewWave
        }


class NavigationBar(PathBar):
    def __init__(self, group=None):
        PathBar.__init__(self)
        self.set_size_request(-1, 28)
        self.id_to_part = {}
        return

    def add_with_id(self, label, callback, id, obj, icon=None):
        """
        Add a new button with the given label/callback

        If there is the same id already, replace the existing one
        with the new one
        """
	if label == self.last_label:
		#ignoring duplicate
		return

	#print "Adding %s(%d)" % (label, id)


        # check if we have the button of that id or need a new one
	if id == 1 and len(self.id_to_part) > 0:
		# We already have the first item, just don't do anything
		return
	else:
		for i in self.id_to_part:
			part = self.id_to_part[i]
			if part.id >= id:
				self.remove(part)

	part = PathPart(id, label, callback, obj)
        part.set_pathbar(self)
        self.id_to_part[id] = part
        GLib.timeout_add(150, self.append, part)

        if icon: part.set_icon(icon)
	self.last_label = label
        return

    def remove_id(self, id):
        if not id in self.id_to_part:
            return

        part = self.id_to_part[id]
        del self.id_to_part[id]
        self.remove(part)
	self.last_label = None
        return

    def remove_all(self):
        """remove all elements"""
        self.__parts = []
        self.id_to_part = {}
        self.queue_draw()
	self.last_label = None
        return

    def get_button_from_id(self, id):
        """
        return the button for the given id (or None)
        """
        if not id in self.id_to_part:
            return None
        return self.id_to_part[id]

    def get_label(self, id):
        """
        Return the label of the navigation button with the given id
        """
        if not id in self.id_to_part:
            return
