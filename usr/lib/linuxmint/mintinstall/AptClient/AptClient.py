# AptControl.py
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

import apt
import apt.progress.base
import logging
import threading
import gobject
import time
import sys
import os
import traceback
from EventsObject import EventsObject
from ThreadedVar import ThreadedVar


class AptInstallProgressMonitor(apt.progress.base.InstallProgress):

    def __init__(self, thread):
        apt.progress.base.InstallProgress.__init__(self)
        self._thread = thread

    def status_change(self, pkg, percent, status):
        if self._thread.task_type == "install":
            self._thread.status.set_value((50 + percent / 2., status))
        else:
            self._thread.status.set_value((percent, status))
        self._thread.status_changed.set()


class AptAcquireProgressMonitor(apt.progress.base.AcquireProgress):

    def __init__(self, thread):
        apt.progress.base.AcquireProgress.__init__(self)
        self._thread = thread

    def pulse(self, owner):
        percent = 100. * self.current_bytes / self.total_bytes
        self._thread.status.set_value((percent / 2., "downloading"))
        self._thread.status_changed.set()
        return True

    def start(self):
        self._thread.status.set_value((0, ""))
        self._thread.status_changed.set()


class AptThread(threading.Thread, EventsObject):

    def __init__(self, task_id, task_type, **params):
        EventsObject.__init__(self)
        threading.Thread.__init__(self, None, self._run, None, (task_type,), params)

        self.task_id = task_id

        self.ended = threading.Event()
        self.success = threading.Event()
        self.status_changed = threading.Event()

        self.error = ThreadedVar(None)
        self.status = ThreadedVar(None)
        self.task_type = task_type
        self.params = params

    def _run(self, task_type, **params):
        logging.debug("Starting %s thread with params %s" % (task_type, params))

        try:
            if task_type == "install":
                acquire_progress_monitor = AptAcquireProgressMonitor(self)
                install_progress_monitor = AptInstallProgressMonitor(self)
                cache = apt.Cache()
                cache[params["package_name"]].mark_install()
                cache.commit(acquire_progress_monitor, install_progress_monitor)
            elif task_type == "remove":
                acquire_progress_monitor = AptAcquireProgressMonitor(self)
                install_progress_monitor = AptInstallProgressMonitor(self)
                cache = apt.Cache()
                cache[params["package_name"]].mark_delete()
                cache.commit(acquire_progress_monitor, install_progress_monitor)
            elif task_type == "update_cache":
                cache = apt.Cache()
                cache.update()
            elif task_type == "wait":
                # Debugging task
                time.sleep(params["delay"])
            else:
                print "Don't know what to do for task type : " + task_type
            self.success.set()
        except:
            error = sys.exc_info()[1]
            stack = traceback.format_exc()
            logging.error("Error during %s task with params %s : %s" % (task_type, params, str(error)))
            self.error.set_value(stack)
            print stack

        logging.debug("End of %s thread with params %s" % (task_type, params))

        self.ended.set()


class AptClient(EventsObject):

    def __init__(self):
        EventsObject.__init__(self)

        self._init_debconf()

        logging.debug("Initializing cache")
        self._cache = apt.Cache()

        self._tasks = {}
        self._queue = []
        self._task_id = 0
        self._queue_lock = threading.Lock()
        self._completed_operations_count = 0

        self._running = False
        self._running_lock = threading.Lock()

        self._apt_thread = None

    def _init_debconf(self):
        # Need to find a way to detect available frontends and use the appropriate fallback
        # Should we implement a custom debconf frontend for better integration ?
        os.putenv("DEBIAN_FRONTEND", "gnome")

    def update_cache(self):
        return self._queue_task("update_cache")

    def _queue_task(self, task_type, **params):
        logging.debug("Queueing %s task with params %s" % (task_type, str(params)))

        self._queue_lock.acquire()

        self._task_id += 1
        self._tasks[self._task_id] = (task_type, params)
        self._queue.append(self._task_id)
        res = self._task_id

        self._queue_lock.release()

        self._process_queue()

        return res

    def cancel_task(self, task_id):
        self._queue_lock.acquire()
        if task_id in self._tasks:
            i = self._queue.index(task_id)
            del self._queue[i]
            del self._tasks[task_id]
        self._queue_lock.release()

    def _process_task(self, task_id, task_type, **params):
        logging.debug("Processing %s task with params %s" % (task_type, str(params)))

        self._apt_thread = AptThread(task_id, task_type, **params)
        gobject.timeout_add(100, self._watch_thread)
        self._apt_thread.start()

    def _watch_thread(self):
        if self._apt_thread.ended.is_set():
            self._running_lock.acquire()
            self._running = False
            self._running_lock.release()

            self._completed_operations_count += 1

            self._trigger("task_ended", self._apt_thread.task_id, self._apt_thread.task_type, self._apt_thread.params, self._apt_thread.success.is_set(), self._apt_thread.error.get_value())
            self._process_queue()

            return False
        else:
            if self._apt_thread.status_changed.is_set():
                progress, status = self._apt_thread.status.get_value()
                self._trigger("progress", self._apt_thread.task_id, self._apt_thread.task_type, self._apt_thread.params, progress, status)
                self._apt_thread.status_changed.clear()
            return True

    def _process_queue(self):
        self._running_lock.acquire()

        if not self._running:
            self._queue_lock.acquire()

            queue_empty = False

            if len(self._queue) > 0:
                task_id = self._queue[0]
                task_type, params = self._tasks[task_id]
                del self._queue[0]
                del self._tasks[task_id]
            else:
                task_id = None
                self._trigger("idle")

            self._queue_lock.release()

            if task_id != None:
                self._running = True
                self._process_task(task_id, task_type, **params)
            else:
                self._completed_operations_count = 0

        self._running_lock.release()

    def install_package(self, package_name):
        return self._queue_task("install", package_name=package_name)

    def remove_package(self, package_name):
        return self._queue_task("remove", package_name=package_name)

    def wait(self, delay):
        # Debugging task
        return self._queue_task("wait", delay=delay)

    def get_progress_info(self):
        res = {"tasks": []}
        self._running_lock.acquire()
        self._queue_lock.acquire()
        nb_tasks = len(self._queue)
        total_nb_tasks = len(self._queue) + self._completed_operations_count
        if self._running:
            nb_tasks += 1
            total_nb_tasks += 1
            task_perc = 100. / total_nb_tasks
            task_progress, status = self._apt_thread.status.get_value()
            task_progress = min(task_progress, 99) # Do not show 100% when the task isn't completed
            progress = (100. * self._completed_operations_count + task_progress) / total_nb_tasks
            res["tasks"].append({"role": self._apt_thread.task_type, "status": status, "progress": task_progress, "task_id": self._apt_thread.task_id, "task_params": self._apt_thread.params, "cancellable": False})
        else:
            if total_nb_tasks > 0:
                task_perc = 100. / total_nb_tasks
                progress = (100. * self._completed_operations_count) / total_nb_tasks
            else:
                progress = 0
        for task_id in self._queue:
            task_type, params = self._tasks[task_id]
            res["tasks"].append({"role": task_type, "progress": 0, "task_id": task_id, "task_params": params, "status": "waiting", "cancellable": True})
        self._queue_lock.release()
        self._running_lock.release()
        res["nb_tasks"] = nb_tasks
        res["progress"] = progress
        return res

    def call_on_completion(self, callback, *args):
        self._running_lock.acquire()
        self._queue_lock.acquire()
        if self._running or len(self._queue) > 0:
            self.connect("idle", lambda client, *a: callback(*a), *args)
        else:
            callback(*args)
        self._queue_lock.release()
        self._running_lock.release()
