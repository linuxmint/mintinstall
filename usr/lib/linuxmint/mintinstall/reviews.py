#!/usr/bin/python3
# encoding=utf8
# -*- coding: UTF-8 -*-

import os
import threading
import time
import pickle
import requests
import multiprocessing
import signal

from pathlib import Path

from gi.repository import GLib

REVIEWS_CACHE = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "reviews.cache")

def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print('%s took %0.3f ms' % (func.__name__, (t2 - t1) * 1000.0))
        return res
    return wrapper

class ReviewInfo:
    def __init__(self, name):
        self.name = name
        self.reviews = []
        self.categories = []
        self.score = 0
        self.avg_rating = 0
        self.num_reviews = 0

    def update_stats(self):
        points = 0
        sum_rating = 0
        self.num_reviews = len(self.reviews)
        self.avg_rating = 0
        for review in self.reviews:
            points = points + (review.rating - 3)
            sum_rating = sum_rating + review.rating
        if self.num_reviews > 0:
            self.avg_rating = round(float(sum_rating) / float(self.num_reviews), 1)
        self.score = points

class Review(object):
    __slots__ = 'date', 'packagename', 'username', 'rating', 'comment', 'package' #To remove __dict__ memory overhead

    def __init__(self, packagename, date, username, rating, comment):
        self.date = date
        self.packagename = packagename
        self.username = username
        self.rating = int(rating)
        self.comment = comment
        self.package = None

class PickleObject(object):
    def __init__(self, cache, size):
        super(PickleObject, self).__init__()

        self.cache = cache
        self.size = int(size)

class ReviewCache(object):
    @print_timing
    def __init__(self):
        super(ReviewCache, self).__init__()

        self._cache_lock = threading.Lock()

        self._reviews, self._size = self._load_cache()

        self._update_cache()

    def keys(self):
        with self._cache_lock:
            return self._reviews.keys()

    def values(self):
        with self._cache_lock:
            return self._reviews.values()

    def __getitem__(self, key):
        with self._cache_lock:
            try:
                return self._reviews[key]
            except KeyError:
                return ReviewInfo(key)

    def __contains__(self, name):
        with self._cache_lock:
            return (name in self._reviews)

    def __len__(self):
        with self._cache_lock:
            return len(self._reviews)

    def _load_cache(self):
        cache = None
        size = 0

        path = None

        try:
            path = Path(REVIEWS_CACHE)
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            path = None
        finally:
            if path != None:
                try:
                    with path.open(mode='rb') as f:
                        pobj = pickle.load(f)

                        cache = pobj.cache
                        size = pobj.size
                except Exception as e:
                    print(e)
                    cache = None

        return cache, size

    def _save_cache(self, cache, size):
        path = None

        try:
            path = Path(REVIEWS_CACHE)
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            path = None
        finally:
            try:
                with path.open(mode='wb') as f:
                    pobj = PickleObject(cache, size)
                    pickle.dump(pobj, f)
            except Exception as e:
                print("Could not save review cache:", str(e))

    def _update_cache(self):
        thread = threading.Thread(target=self._update_reviews_thread)
        thread.start()

    @print_timing
    def _update_reviews_thread(self):
        # Update the review cache in a separate process.  Just doing it in a thread
        # would end up blocking ui, due to the GIL problem.  But we can use this thread
        # to monitor the Process and then reload the cache here once it terminates.

        success = multiprocessing.Value('b', False)

        current_size = multiprocessing.Value('d', self._size)
        proc = multiprocessing.Process(target=self._update_cache_process, args=(success, current_size))

        proc.start()
        proc.join()

        if success.value == True:
            with self._cache_lock:
                self._reviews, self._size = self._load_cache()

    def _update_cache_process(self, success, current_size):
        new_reviews = {}

        try:
            r = requests.head("https://community.linuxmint.com/data/new-reviews.list")

            if r.status_code == 200:
                if int(r.headers.get("content-length")) != current_size.value:

                    r = requests.get("https://community.linuxmint.com/data/new-reviews.list")

                    last_package = None

                    for line in r.iter_lines():
                        decoded = line.decode()

                        elements = decoded.split("~~~")
                        if len(elements) == 5:
                            review = Review(elements[0], float(elements[1]), elements[2], elements[3], elements[4])
                            if last_package != None and last_package.name == elements[0]:
                                #Comment is on the same package as previous comment.. no need to search for the package
                                last_package.reviews.append(review)
                                review.package = last_package
                            else:
                                if last_package is not None:
                                    last_package.update_stats()

                                try:
                                    package = new_reviews[elements[0]]
                                except Exception:
                                    package = ReviewInfo(elements[0])
                                    new_reviews[elements[0]] = package

                                last_package = package
                                package.reviews.append(review)
                                review.package = package

                    if last_package is not None:
                        last_package.update_stats()

                    self._save_cache(new_reviews, r.headers.get("content-length"))
                    print("Downloaded new reviews")
                    success.value = True
                else:
                    print("No new reviews")
            else:
                print("Could not download updated reviews: %s" % r.reason)
                success.value = False
        except Exception as e:
            print("Problem attempting to access reviews url: %s" % str(e))

# Debugging - you can run reviews.py on its own, and inspect the ReviewCache (i)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    i = ReviewCache()

    import readline
    import code
    variables = globals().copy()
    variables.update(locals())
    shell = code.InteractiveConsole(variables)
    shell.interact()

    ml = GLib.MainLoop.new(None, True)
    ml.run()
