
import threading


class ThreadedVar(object):

    def __init__(self, value=None):
        self._value = value
        self._lock = threading.Lock()

    def get_value(self):
        self._lock.acquire()
        res = self._value
        self._lock.release()
        return res

    def set_value(self, value):
        self._lock.acquire()
        self._value = value
        self._lock.release()
