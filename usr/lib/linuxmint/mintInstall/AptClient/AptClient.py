# AptControl.py
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

import apt, apt.progress.base, logging, threading, gobject, time, sys
from EventsObject import EventsObject
from ThreadedVar import ThreadedVar

class AptInstallProgressMonitor(apt.progress.base.InstallProgress):
    def __init__(self, thread):
        apt.progress.base.InstallProgress.__init__(self)
        self._thread = thread
        
    def status_change(self, pkg, percent, status):
        self._thread.status.set_value((percent, status))
        self._thread.status_changed.set()
        
class AptAcquireProgressMonitor(apt.progress.base.AcquireProgress):
    def __init__(self, thread):
        apt.progress.base.AcquireProgress.__init__(self)
        self._thread = thread
        
    def pulse(self, owner):
        percent = 100. * self.current_bytes / self.total_bytes
        self._thread.status.set_value((percent, ""))
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
                cache[params["package_name"]].mark_install(False)
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
            logging.error("Error during %s task with params %s : %s" % (task_type, params, str(error)))
            self.error.set_value(error)
        
        logging.debug("End of %s thread with params %s" % (task_type, params))
        
        self.ended.set()

class AptClient(EventsObject):
    def __init__(self):
        EventsObject.__init__(self)
        
        logging.debug("Initializing cache")
        self._cache = apt.Cache()
        
        self._tasks = {}
        self._queue = []
        self._task_id = 0
        self._queue_lock = threading.Lock()
        
        self._running = False
        self._running_lock = threading.Lock()
        
        self._apt_thread = None
    
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
            
            self._trigger("task_ended", self._apt_thread.task_id, self._apt_thread.task_type, self._apt_thread.params, self._apt_thread.success.is_set(), self._apt_thread.error.get_value())
            self._process_queue()
            
            return False
        else:
            if self._apt_thread.status_changed.is_set():
                progress, status = self._apt_thread.status.get_value()
                self._trigger("progress", progress, status)
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
            
        self._running_lock.release()
    
    def install_package(self, package_name):
        return self._queue_task("install", package_name = package_name)
    
    def wait(self, delay):
        # Debugging task
        return self._queue_task("wait", delay = delay)
