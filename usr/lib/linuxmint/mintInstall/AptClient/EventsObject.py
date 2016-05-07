# EventsObject.py
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-


class EventsObject(object):

    def __init__(self):
        self._events = {}
        self._event_id = 0
        self._events_map = {}

    def connect(self, event, callback, *params):
        if not event in self._events:
            self._events[event] = {}
        self._event_id += 1
        self._events[event][self._event_id] = (callback, params, self._event_id)
        self._events_map[self._event_id] = event
        return self._event_id

    def disconnect(self, event_id):
        if event_id in self._events_map.keys():
            event = self._events_map[event_id]
            if event in self._events.keys() and event_id in self._events[event].keys():
                del self._events[event][event_id]

    def _trigger(self, event, *params):
        if event in self._events.keys():
            for callback, def_params, event_id in self._events[event].values():
                callback(*((self,) + params + def_params))
