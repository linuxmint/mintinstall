#! /usr/bin/python2
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

from AptClient import AptClient
import gtk
import logging
import gobject


class TestApp(object):

    def __init__(self):
        self._apt_client = AptClient()
        self._apt_client.connect("idle", lambda c: gtk.main_quit())
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
        gobject.threads_init()
        gobject.timeout_add(100, self._start_tasks)
        gtk.main()

if __name__ == "__main__":
    logging.getLogger().setLevel(logging.FATAL)
    TestApp().run()
