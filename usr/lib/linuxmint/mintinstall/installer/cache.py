import time
import os
from pathlib import Path
import pickle
import threading

import gi
gi.require_version('AppStream', '1.0')
gi.require_version('Flatpak', '1.0')
from gi.repository import GLib, GObject

from installer import _apt
from installer import _flatpak
from installer.pkgInfo import PkgInfo
from misc import print_timing

SYS_CACHE_PATH = "/var/cache/mintinstall/pkginfo.cache"
USER_CACHE_PATH = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "pkginfo.cache")

MAX_AGE = 7 * (60 * 60 * 24) # days

class CacheLoadingException(Exception):
    '''Thrown when there was an issue loading the pickled package set'''

class PickleObject(object):
    def __init__(self, pkginfo_cache, section_lists, flatpak_remote_infos):
        super(PickleObject, self).__init__()

        self.pkginfo_cache = pkginfo_cache
        self.section_lists = section_lists
        self.flatpak_remote_infos = flatpak_remote_infos

class PkgCache(object):
    STATUS_EMPTY = 0
    STATUS_OK = 1

    @print_timing
    def __init__(self):
        super(PkgCache, self).__init__()

        self.status = self.STATUS_EMPTY

        self._items = {}
        self._item_lock = threading.Lock()

        try:
            cache, sections, flatpak_remote_infos = self._load_cache()
        except CacheLoadingException:
            cache = {}
            sections = {}
            flatpak_remote_infos = {}

        if len(cache) > 0:
            self.status = self.STATUS_OK
        else:
            self.status = self.STATUS_EMPTY

        self._items = cache
        self.sections = sections
        self.flatpak_remote_infos = flatpak_remote_infos

    def keys(self):
        with self._item_lock:
            return self._items.keys()

    def values(self):
        with self._item_lock:
            return self._items.values()

    def __getitem__(self, key):
        with self._item_lock:
            return self._items[key]

    def __setitem__(self, key, value):
        with self._item_lock:
            self._items[key] = value

    def __contains__(self, pkg_hash):
        with self._item_lock:
            return pkg_hash in self._items

    def __len__(self):
        with self._item_lock:
            return len(self._items)

    def __iter__(self):
        with self._item_lock:
            for pkg_hash in self._items:
                yield self[pkg_hash]
            return

    def _generate_cache(self):
        cache = {}
        sections = {}
        flatpak_remote_infos = {}

        cache, flatpak_remote_infos = _flatpak.process_full_flatpak_installation(cache)
        cache, sections = _apt.process_full_apt_cache(cache)

        return cache, sections, flatpak_remote_infos

    def _get_best_load_path(self):
        try:
            sys_mtime = os.path.getmtime(SYS_CACHE_PATH)

            if (time.time() - MAX_AGE) > sys_mtime:
                print("MintInstall: System pkgcache too old, skipping")
                sys_mtime = 0
        except OSError:
            sys_mtime = 0

        try:
            user_mtime = os.path.getmtime(USER_CACHE_PATH)

            if (time.time() - MAX_AGE) > user_mtime:
                print("MintInstall: User pkgcache too old, skipping")
                user_mtime = 0
        except OSError:
            user_mtime = 0

        # If neither exist, return None, and a new cache will be generated
        if sys_mtime == 0 and user_mtime == 0:
            return None

        most_recent = None

        # Select the most recent
        if sys_mtime > user_mtime:
            most_recent = SYS_CACHE_PATH
            print("MintInstall: System pkgcache is most recent, using it.")
        else:
            most_recent = USER_CACHE_PATH
            print("MintInstall: User pkgcache is most recent, using it.")

        return Path(most_recent)

    @print_timing
    def _load_cache(self):
        """
        The cache pickle file can be in either a system or user location,
        depending on how the cache was generated.  If it exists in both places, take the
        most recent one.  If it's more than MAX_AGE, generate a new one anyhow.
        """

        cache = None
        sections = None
        flatpak_remote_infos = None

        path = self._get_best_load_path()

        if path is None:
            raise CacheLoadingException

        try:
            with path.open(mode='rb') as f:
                pickle_obj = pickle.load(f)
                cache = pickle_obj.pkginfo_cache
                sections = pickle_obj.section_lists
                flatpak_remote_infos = pickle_obj.flatpak_remote_infos
        except Exception as e:
            print("MintInstall: Error loading pkginfo cache:", e)
            cache = None

        if cache == None:
            raise CacheLoadingException

        return cache, sections, flatpak_remote_infos

    def _get_best_save_path(self):
        best_path = None

        # Prefer the system location, as all users can access it
        try:
            path = Path(SYS_CACHE_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except PermissionError:
            try:
                path = Path(USER_CACHE_PATH)
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                path = None
        finally:
            best_path = path

        return best_path

    def _save_cache(self, to_be_pickled):
        path = self._get_best_save_path()

        # Depickling later may fail if we _load_cache from a different context or module.
        # This explicitly stores the module name PkgInfo is defined in, within the pickle
        # file.
        PkgInfo.__module__ = "installer.pkgInfo"

        try:
            with path.open(mode='wb') as f:
                pickle.dump(to_be_pickled, f)
        except Exception as e:
            print("MintInstall: Could not save cache:", str(e))

    def _new_cache_common(self):
        print("MintInstall: Generating new pkgcache")
        cache, sections, flatpak_remote_infos = self._generate_cache()

        if len(cache) > 0:
            self._save_cache(PickleObject(cache, sections, flatpak_remote_infos))

        with self._item_lock:
            self._items = cache
            self.sections = sections
            self.flatpak_remote_infos = flatpak_remote_infos

        if len(cache) == 0:
            self.status = self.STATUS_EMPTY
        else:
            self.status = self.STATUS_OK

    def _generate_cache_thread(self, callback=None):
        self._new_cache_common()

        if callback != None:
            GObject.idle_add(callback)

    def get_subset_of_type(self, pkg_type):
        with self._item_lock:
            return {k: v for k, v in self._items.items() if k.startswith(pkg_type)}

    def force_new_cache_async(self, idle_callback=None):
        thread = threading.Thread(target=self._generate_cache_thread,
                                  kwargs={"callback" : idle_callback})
        thread.start()

    def force_new_cache(self):
        self._new_cache_common()

    def find_pkginfo(self, string, pkg_type=None):
        if pkg_type in (None, "a"):
            pkginfo = _apt.find_pkginfo(self, string)

            if pkginfo != None:
                return pkginfo

        if pkg_type in (None, "f"):
            pkginfo = _flatpak.find_pkginfo(self, string)

            if pkginfo != None:
                return pkginfo

        return None
