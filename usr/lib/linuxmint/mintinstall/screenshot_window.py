#!/usr/bin/python3
# encoding=utf-8
# -*- coding: UTF-8 -*-

from gi.repository import GLib, Gtk, GObject, Gdk
import cairo

class ScreenshotWindow(Gtk.Window):
    __gsignals__ = {
        'next-image': (GObject.SignalFlags.RUN_LAST, bool, (Gtk.DirectionType,)),
    }

    def __init__(self, parent):
        Gtk.Window.__init__(self,
                            type=Gtk.WindowType.TOPLEVEL,
                            decorated=False,
                            transient_for=parent,
                            destroy_with_parent=True,
                            skip_taskbar_hint=True,
                            skip_pager_hint=True,
                            type_hint=Gdk.WindowTypeHint.UTILITY,
                            name="ScreenshotWindow")

        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)

        self.screen = Gdk.Screen.get_default()

        self.visual = self.screen.get_rgba_visual()
        if self.visual is not None and self.screen.is_composited():
            self.set_visual(self.visual)
            self.set_app_paintable(True)
            self.connect("draw", self.on_draw)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)

        self.stack = Gtk.Stack(homogeneous=False,
                               hhomogeneous=False,
                               transition_duration=500,
                               no_show_all=True)

        self.spin_box = Gtk.Button(halign=Gtk.Align.CENTER,
                                   valign=Gtk.Align.CENTER,
                                   no_show_all=True)
        self.spin_box.get_style_context().add_class("circular")

        # Don't let the spin_box act like a button. Using a button was the easiest way
        # to have a background for the spinner.
        self.spinner = Gtk.Spinner(active=True,
                                   height_request=36,
                                   width_request=36,
                                   visible=True)
        self.spin_box.connect("enter-notify-event", lambda w, e: Gdk.EVENT_STOP)
        self.spin_box.connect("leave-notify-event", lambda w, e: Gdk.EVENT_STOP)
        self.spin_box.connect("button-press-event", lambda w, e: Gdk.EVENT_STOP)

        self.spin_box.set_image(self.spinner)

        self.overlay.add(self.stack)
        self.overlay.add_overlay(self.spin_box)

        self.swipe_handler = Gtk.GestureSwipe.new(self)
        # Clicking on the spinner will send the event to the window first
        self.swipe_handler.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.swipe_handler.connect("swipe", self.swipe_or_button_release)
        self.connect("key-press-event", self.on_key_press_event)
        self.connect("focus-out-event", self.on_focus_out_event)

        self.scroll_handler = Gtk.EventControllerScroll.new(self, Gtk.EventControllerScrollFlags.VERTICAL)
        # self.scroll_handler = Gtk.EventControllerScroll.new(self, Gtk.EventControllerScrollFlags.BOTH_AXES | Gtk.EventControllerScrollFlags.DISCRETE)
        self.scroll_handler.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.scroll_handler.connect("scroll", self.on_scroll_event)
        self.previous_scroll_event_time = 0

        self.first_image_name = None
        self.last_image_name = None

        if self.visual is not None:
            self.spin_box.show()
            self.show_all()
            self.present()

    def has_image(self, location):
        for image in self.stack.get_children():
            name = self.stack.child_get_property(image, "name")
            if name == location:
                return True
        return False

    def add_image(self, image, location):
        image.show()

        self.stack.add_named(image, location)
        if self.first_image_name is None:
            self.first_image_name = location
        else:
            self.last_image_name = location

        self.show_image(location)

    def show_image(self, image_location):
        self.stack.show()
        self.spin_box.hide()
        self.stack.set_visible_child_name(image_location)

        image = self.stack.get_visible_child()
        self.resize(image.width, image.height)

        if self.visual is None:
            self.show_all()
            self.present()

    def emit_next_image(self, direction):
        if self.emit("next-image", direction):
            self.spin_box.show()
        else:
            self.spin_box.hide()

    def on_key_press_event(self, window, event, data=None):
        keyval = event.get_keyval()[1]

        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
            direction = Gtk.DirectionType.TAB_BACKWARD
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
            direction = Gtk.DirectionType.TAB_FORWARD
        else:
            self.hide()
            return Gdk.EVENT_STOP

        self.emit_next_image(direction)
        return Gdk.EVENT_STOP

    def on_scroll_event(self, controller, xd, yd, data=None):
        # Getting double events for some reason..
        event_time = Gtk.get_current_event().get_time()
        if event_time == self.previous_scroll_event_time:
            return

        if xd < 0 or yd < 0:
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
            direction = Gtk.DirectionType.TAB_BACKWARD
        else:
            self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
            direction = Gtk.DirectionType.TAB_FORWARD

        self.previous_scroll_event_time = event_time
        self.emit_next_image(direction)

    def on_focus_out_event(self, window, event, data=None):
        GLib.timeout_add(200, lambda w: w.hide(), window)
        return Gdk.EVENT_STOP

    def swipe_or_button_release(self, handler, vx, vy):
        if vx == 0 and vy == 0:
            # Need to let the other events for the swipe controller (like button-release) to fire
            # before destroying the window, otherwise there are warnings when their default
            # handlers run.
            GLib.idle_add(self.hide)
            return

        if vx < 0:
            self.emit_next_image(Gtk.DirectionType.TAB_FORWARD)
        elif vx > 0:
            self.emit_next_image(Gtk.DirectionType.TAB_BACKWARD)

    def on_draw(self, window, cr):
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        return Gdk.EVENT_PROPAGATE
