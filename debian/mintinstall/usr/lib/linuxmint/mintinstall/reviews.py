import os
import threading
import json
import requests
import multiprocessing

from pathlib import Path

from gi.repository import GLib

from misc import print_timing

REVIEWS_CACHE = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "reviews.json")

class Review(object):
    def __init__(self, packagename, date, username, rating, comment):
        self.date = date
        self.packagename = packagename
        self.username = username
        self.rating = int(rating)
        self.comment = comment

    @classmethod
    def from_json(cls, json_data:dict):
        return cls(**json_data)


class ReviewInfo:
    def __init__(self, name, score=0, avg_rating=0, num_reviews=0):
        self.name = name
        self.reviews = []
        self.categories = []
        self.score = score
        self.avg_rating = avg_rating
        self.num_reviews = num_reviews

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

    @classmethod
    def from_json(cls, json_data:dict):
        reviews = list(map(Review.from_json, json_data["reviews"]))
        inst = cls(json_data["name"],
                   json_data["score"],
                   json_data["avg_rating"],
                   json_data["num_reviews"])
        inst.reviews = reviews

        return inst

class JsonObject(object):
    def __init__(self, cache, size):
        super(JsonObject, self).__init__()

        self.cache = cache
        self.size = int(size)

    @classmethod
    def from_json(cls, json_data: dict):
        new_dict = {}
        for key in json_data["cache"].keys():
            info_data = json_data["cache"][key]
            new_dict[key] = ReviewInfo.from_json(info_data)

        return cls(new_dict, json_data["size"])

class ReviewCache(object):
    @print_timing
    def __init__(self):
        super(ReviewCache, self).__init__()

        self._cache_lock = threading.Lock()

        self._reviews, self._size = self._load_cache()

        self.proc = None

        self._update_cache()

    def kill(self):
        try:
            self.proc.terminate()
            self.proc = None
        except AttributeError as e:
            pass

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
                    with path.open(mode='r', encoding="utf8") as f:
                        json_object = JsonObject.from_json(json.load(f))
                        cache = json_object.cache
                        size = json_object.size
                except Exception as e:
                    print("MintInstall: Cannot open reviews cache: %s" % str(e))
                    cache = {}
                    size = 0

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
                with path.open(mode='w', encoding="utf8") as f:
                    pobj = JsonObject(cache, size)
                    json.dump(pobj, f, default=lambda o: o.__dict__, indent=4)
            except Exception as e:
                print("MintInstall: Could not save review cache: %s" % str(e))

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
        self.proc = multiprocessing.Process(target=self._update_cache_process, args=(success, current_size))
        self.proc.start()

        self.proc.join()

        self.proc = None

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

                    if last_package is not None:
                        last_package.update_stats()

                    self._save_cache(new_reviews, r.headers.get("content-length"))
                    print("MintInstall: Downloaded new reviews")
                    success.value = True
                else:
                    print("MintInstall: No new reviews")
            else:
                print("MintInstall: Could not download updated reviews: %s" % r.reason)
                success.value = False
        except Exception as e:
            print("MintInstall: Problem attempting to access reviews url: %s" % str(e))

