#! /usr/bin/python2
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

from AptClient import AptClient
from gi.repository import Gtk
import logging
from gi.repository import GObject


class TestApp(object):

    def __init__(self):
        self._apt_client = AptClient()
        self._apt_client.connect("idle", lambda c: Gtk.main_quit())
        self._apt_client.connect("task_ended", self._on_task_ended)
        self._apt_client.connect("progress", self._on_progress)

    def _on_progress(self, apt_client, progress, status):
        print "_on_progress:", progress, status

    def _on_task_ended(self, apt_client, task_id, task_type, task_params, success, error):
        print "\t\t_on_task_ended : ", apt_client, task_id, task_type, task_params, success, error

    def _start_tasks(self):
        #self._apt_client.update_cache()
        self._apt_client.install_package("phpmyadmin")
        #self._apt_client.install_package("gedit")
        #self._apt_client.install_package("gnome-xcf-thumbnailer")
        return False

    def run(self):
        GObject.threads_init()
        GObject.timeout_add(100, self._start_tasks)
        Gtk.main()

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.FATAL)
    TestApp().run()
