import time
import threading
import math

import gi
gi.require_version('AppStream', '1.0')
from gi.repository import AppStream, Flatpak, GLib, GObject, Gtk, Gio

from installer.pkgInfo import FlatpakPkgInfo
from installer import dialogs
from installer.dialogs import ChangesConfirmDialog, FlatpakProgressWindow

_fp_sys = None

_as_pool_lock = threading.Lock()
_as_pools = {} # keyed to remote name

def print_timing(func):
    def wrapper(*arg):
        t1 = time.time()
        res = func(*arg)
        t2 = time.time()
        print('%s took %0.3f ms' % (func.__name__, (t2 - t1) * 1000.0))
        return res
    return wrapper

def get_fp_sys():
    global _fp_sys

    if _fp_sys == None:
        _fp_sys = Flatpak.Installation.new_system(None)

    return _fp_sys

ALIASES = {
    "org.gnome.Weather" : "org.gnome.Weather.Application"
}

def make_pkg_hash(ref):
    if not isinstance(ref, Flatpak.Ref):
        raise TypeError("flatpak.make_pkg_hash() must receive FlatpakRef, not %s" % type(ref))

    try:
        return "fp:%s:%s" % (ref.get_origin(), ref.format_ref())
    except Exception:
        return "fp:%s:%s" % (ref.get_remote_name(), ref.format_ref())

def _get_file_timestamp(gfile):
    try:
        info = gfile.query_info("time::modified", Gio.FileQueryInfoFlags.NONE, None)

        return info.get_attribute_uint64("time::modified")
    except GLib.Error as e:
        if e.code != Gio.IOErrorEnum.NOT_FOUND:
            print("MintInstall: flatpak - could not get time::modified from file %s" % gfile.get_path())
        return 0

def _should_update_appstream_data(fp_sys, remote, arch):
    ret = False

    current_timestamp = _get_file_timestamp(remote.get_appstream_timestamp(arch))

    try:
        if fp_sys.update_remote_sync(remote.get_name(), None):
            print("MintInstall: flatpak - metadata for remote '%s' has been updated. Comparing appstream timestamps..." % remote.get_name())

            new_timestamp = _get_file_timestamp(remote.get_appstream_timestamp(arch))

            if (new_timestamp > current_timestamp) or (current_timestamp == 0):
                ret = True
    except GLib.Error as e:
        print("MintInstall: flatpak - could not update metadata for remote '%s': %s" % (remote.get_name(), e.message))

    return ret

def _process_remote(cache, fp_sys, remote, arch, force_noenumerate=False):
    remote_name = remote.get_name()

    if remote.get_disabled():
        print("MintInstall: flatpak - remote '%s' is disabled, skipping" % remote_name)
        return

    remote_url = remote.get_url()

    if _should_update_appstream_data(fp_sys, remote, arch):
        print("MintInstall: flatpak - new appstream data available for remote '%s', fetching..." % remote_name)

        try:
            fp_sys.update_appstream_sync(remote_name, arch, None)
        except GLib.Error:
            # Not fatal..
            pass
    else:
        print("MintInstall: flatpak - no new appstream data for remote '%s', skipping download" % remote_name)

    # get_no_enumerate indicates whether a remote should be used to list applications.
    # Instead, they're intended for single downloads (via .flatpakref files)
    if remote.get_noenumerate() or force_noenumerate:
        print("MintInstall: flatpak - remote '%s' is marked as no-enumerate (or we're working on a .flatpakref file,) skipping package listing" % remote_name)
        return

    try:
        for ref in fp_sys.list_remote_refs_sync(remote_name, None):
            if ref.get_kind() != Flatpak.RefKind.APP:
                continue

            if ref.get_arch() != arch:
                continue

            _add_package_to_cache(cache, ref, remote_url, False)
    except GLib.Error as e:
        print(e.message)

def _add_package_to_cache(cache, ref, remote_url, installed):
    pkg_hash = make_pkg_hash(ref)

    try:
        remote_name = ref.get_remote_name()
    except Exception:
        remote_name = ref.get_origin()

    try:
        pkginfo = cache[pkg_hash]

        if installed:
            pkginfo.installed = installed
    except KeyError:
        pkginfo = FlatpakPkgInfo(pkg_hash, remote_name, ref, remote_url, installed)
        cache[pkg_hash] = pkginfo

    return pkginfo

def process_full_flatpak_installation(cache):
    fp_time = time.time()

    arch = Flatpak.get_default_arch()
    fp_sys = Flatpak.Installation.new_system(None)

    try:
        for remote in fp_sys.list_remotes():
            _process_remote(cache, fp_sys, remote, arch)

            try:
                remote_name = remote.get_name()

                for ref in fp_sys.list_installed_refs_by_kind(Flatpak.RefKind.APP, None):
                    # All remotes will see installed refs, but the installed refs will always
                    # report their correct origin, so only add installed refs when they match the remote.
                    if ref.get_origin() == remote_name:
                        _add_package_to_cache(cache, ref, remote.get_url(), True)
            except GLib.Error as e:
                print(e.message)

    except GLib.Error as e:
        print("MintInstall: flatpak - could not get remote list", e.message)
        cache = {}

    print('MintInstall: Processing Flatpaks for cache took %0.3f ms' % ((time.time() - fp_time) * 1000.0))

    return cache

def _load_appstream_pool(pools, remote):
    pool = AppStream.Pool()
    pool.add_metadata_location(remote.get_appstream_dir().get_path())
    pool.set_cache_flags(AppStream.CacheFlags.NONE)
    pool.load()
    pools[remote.get_name()] = pool

def initialize_appstream():
    thread = threading.Thread(target=_initialize_appstream_thread)
    thread.start()

def _initialize_appstream_thread():
    fp_sys = get_fp_sys()

    global _as_pools
    global _as_pool_lock

    with _as_pool_lock:
        _as_pools = {}

        try:
            for remote in fp_sys.list_remotes():
                _load_appstream_pool(_as_pools, remote)
        except GLib.Error:
            print("MintInstall: Could not initialize appstream components for flatpaks")

def search_for_pkginfo_as_component(pkginfo):
    name = pkginfo.name

    comps = []

    global _as_pools
    global _as_pool_lock

    with _as_pool_lock:
        try:
            pool = _as_pools[pkginfo.remote]
        except Exception:
            return None

        comps = pool.get_components_by_id(name + ".desktop")

        if comps == []:
            if name in ALIASES.keys():
                comps = pool.get_components_by_id(ALIASES[name] + ".desktop")
            else:
                comps = pool.get_components_by_id(name)

    if len(comps) > 0:
        return comps[0]
    else:
        return None

def _is_ref_installed(fp_sys, remote, ref):
    try:
        iref = fp_sys.get_installed_ref(ref.get_kind(),
                                        ref.get_name(),
                                        ref.get_arch(),
                                        ref.get_branch(),
                                        None)

        if iref:
            return True
    except GLib.Error:
        pass
    except AttributeError: # bad/null ref
        pass

    return False

def _get_remote_sizes(fp_sys, remote, ref):
    try:
        success, dl_s, inst_s = fp_sys.fetch_remote_size_sync(remote,
                                                              ref,
                                                              None)
    except GLib.Error:
        # Not fatal?
        dl_s = 0
        inst_s = 0

    return dl_s, inst_s

def _get_installed_size(fp_sys, ref):
    if isinstance(ref, Flatpak.InstalledRef):
        return ref.get_installed_size()
    else:
        try:
            iref = fp_sys.get_installed_ref(ref.get_kind(),
                                            ref.get_name(),
                                            ref.get_arch(),
                                            ref.get_branch(),
                                            None)
            return iref.get_installed_size()
        except GLib.Error as e:
            # This isn't fatal I guess?
            return 0

def _add_ref_to_task(fp_sys, task, ref, needs_update=False):
    if task.type == "install":
        if needs_update:
            task.to_update.append(ref.format_ref())
        else:
            task.to_install.append(ref.format_ref())

        dl_s, inst_s = _get_remote_sizes(fp_sys, task.remote, ref)

        task.download_size += dl_s
        task.install_size = inst_s
    elif task.type == "remove":
        task.to_remove.append(ref.format_ref())
        task.freed_size += _get_installed_size(fp_sys, ref)
    else:
        task.to_update.append(ref.format_ref())

        current_inst_s = _get_installed_size(fp_sys, ref)
        remote_dl_s, remote_inst_s = _get_remote_sizes(fp_sys, task.remote, ref)

        task.download_size += remote_dl_s

        if current_inst_s < remote_inst_s:
            task.install_size += remote_inst_s - current_inst_s
        else:
            task.freed_size += current_inst_s - remote_inst_s

def _get_runtime_ref(fp_sys, remote_name, ref):
    runtime_ref = None

    try:
        meta = fp_sys.fetch_remote_metadata_sync(remote_name, ref, None)

        keyfile = GLib.KeyFile.new()

        data = meta.get_data().decode()
        keyfile.load_from_data(data, len(data), GLib.KeyFileFlags.NONE)

        runtime = keyfile.get_string("Application", "runtime")
        basic_ref = Flatpak.Ref.parse("runtime/%s" % runtime)

        try:
            # prefer the same-remote's runtimes
            runtime_ref = fp_sys.fetch_remote_ref_sync(remote_name,
                                                       basic_ref.get_kind(),
                                                       basic_ref.get_name(),
                                                       basic_ref.get_arch(),
                                                       basic_ref.get_branch(),
                                                       None)
        except GLib.Error as e:
            # check other remotes if this fails
            for other_remote in fp_sys.list_remotes():
                other_remote_name = other_remote.get_name()

                if other_remote_name == remote_name:
                    continue

                try:
                    runtime_ref = fp_sys.fetch_remote_ref_sync(other_remote_name,
                                                               basic_ref.get_kind(),
                                                               basic_ref.get_name(),
                                                               basic_ref.get_arch(),
                                                               basic_ref.get_branch(),
                                                               None)
                    break
                except GLib.Error as e:
                    continue
    except GLib.Error as e:
        raise Exception("Could not determine runtime info for app: %s" % e.message)

    return runtime_ref

def _get_remote_related_refs(fp_sys, remote, ref):
    related_refs = []

    try:
        related_refs = fp_sys.list_remote_related_refs_sync(remote,
                                                            ref.format_ref(),
                                                            None)
    except GLib.Error as e:
        raise Exception("Could not determine remote related refs for app: %s" % e.message)

    return related_refs

def _get_installed_related_refs(fp_sys, remote, ref):
    related_refs = []

    try:
        related_refs = fp_sys.list_installed_related_refs_sync(remote,
                                                               ref.format_ref(),
                                                               None)
    except GLib.Error as e:
        raise Exception("Could not determine installed refs for app: %s" % e.message)

    return related_refs

def select_updates(task):
    thread = threading.Thread(target=_select_updates_thread, args=(task,))
    thread.start()

def _select_updates_thread(task):
    fp_sys = get_fp_sys()

    try:
        updates = fp_sys.list_installed_refs_for_update(None)
    except GLib.Error as e:
        task.info_ready_status = task.STATUS_BROKEN
        task.error_message = str(e)
        dialogs.show_flatpak_error(task.error_message)
        if task.info_ready_callback:
            GObject.idle_add(task.info_ready_callback, task)
        return

    for ref in updates:
        _add_ref_to_task(fp_sys, task, ref, needs_update=True)

    if len(task.to_update) > 0:
        print("flatpaks that can be updated:")
        for ref in task.to_update:
            print(ref)

        task.info_ready_status = task.STATUS_OK
        task.execute = execute_transaction
    else:
        print("no updated flatpaks")

    if task.info_ready_callback:
        GObject.idle_add(task.info_ready_callback, task)

def select_packages(task):
    method = None

    if task.type == "install":
        method = _pick_refs_for_installation
    else:
        method = _pick_refs_for_removal

    print("MintInstall: Calculating changes required for Flatpak package: %s" % task.pkginfo.name)

    thread = threading.Thread(target=method, args=(task,))
    thread.start()

def _pick_refs_for_installation(task):
    fp_sys = get_fp_sys()

    pkginfo = task.pkginfo
    refid = pkginfo.refid

    # We don't need a real RemoteRef to pass to add_ref_to_task, the disk space calls go thru
    # fp_sys
    ref = Flatpak.Ref.parse(refid)
    remote_name = pkginfo.remote

    _add_ref_to_task(fp_sys, task, ref)

    try:
        update_list = fp_sys.list_installed_refs_for_update(None)

        runtime_ref = _get_runtime_ref(fp_sys, remote_name, ref)

        if not _is_ref_installed(fp_sys, remote_name, runtime_ref):
            _add_ref_to_task(fp_sys, task, runtime_ref)
        else:
            if runtime_ref in update_list:
                _add_ref_to_task(fp_sys, task, runtime_ref, needs_update=True)

        all_related_refs = _get_remote_related_refs(fp_sys, remote_name, ref)
        all_related_refs += _get_remote_related_refs(fp_sys, remote_name, runtime_ref)

        for related_ref in all_related_refs:
            if (not _is_ref_installed(fp_sys, remote_name, related_ref)) and related_ref.should_download():
                _add_ref_to_task(fp_sys, task, related_ref)
            else:
                if related_ref in update_list:
                    _add_ref_to_task(fp_sys, task, related_ref, needs_update=True)

    except Exception as e:
        # Something went wrong, bail out
        task.info_ready_status = task.STATUS_BROKEN
        task.error_message = str(e)
        dialogs.show_flatpak_error(task.error_message)
        if task.info_ready_callback:
            GObject.idle_add(task.info_ready_callback, task)
        return

    print("For installation:")
    for ref in task.to_install:
        print(ref)

    task.info_ready_status = task.STATUS_OK
    task.execute = execute_transaction

    if task.info_ready_callback:
        GObject.idle_add(task.info_ready_callback, task)

def _pick_refs_for_removal(task):
    fp_sys = get_fp_sys()

    pkginfo = task.pkginfo

    try:
        ref = fp_sys.get_installed_ref(pkginfo.kind,
                                       pkginfo.name,
                                       pkginfo.arch,
                                       pkginfo.branch,
                                       None)

        remote = pkginfo.remote

        _add_ref_to_task(fp_sys, task, ref)

        related_refs = _get_installed_related_refs(fp_sys, remote, ref)

        for related_ref in related_refs:
            if _is_ref_installed(fp_sys, remote, related_ref) and related_ref.should_delete():
                _add_ref_to_task(fp_sys, task, related_ref)

    except Exception as e:
        task.info_ready_status = task.STATUS_BROKEN
        task.error_message = str(e)
        dialogs.show_flatpak_error(task.error_message)
        GObject.idle_add(task.info_ready_callback, task)
        return

    print("For removal:")
    for ref in task.to_remove:
        print(ref)

    task.info_ready_status = task.STATUS_OK
    task.execute = execute_transaction

    if task.info_ready_callback:
        GObject.idle_add(task.info_ready_callback, task)

def list_updated_pkginfos(cache):
    fp_sys = get_fp_sys()

    updated = []

    try:
        updates = fp_sys.list_installed_refs_for_update(None)
    except GLib.Error as e:
        print("MintInstall: flatpak - could not get updated flatpak refs")
        return []

    for ref in updates:
        pkg_hash = make_pkg_hash(ref)

        try:
            updated.append(cache[pkg_hash])
        except KeyError:
            pass

    return updated

def find_pkginfo(cache, string):
    for key in cache.get_subset_of_type("f").keys():
        candidate = cache[key]

        if string == candidate.name:
            return candidate

    return None

def pkginfo_is_installed(pkginfo):
    fp_sys = get_fp_sys()

    try:
        iref = fp_sys.get_installed_ref(pkginfo.kind,
                                        pkginfo.name,
                                        pkginfo.arch,
                                        pkginfo.branch,
                                        None)

        if iref:
            return True
    except GLib.Error:
        pass

    return False

def list_remotes():
    fp_sys = get_fp_sys()

    remotes = []

    try:
        for remote in fp_sys.list_remotes():
            name = remote.get_name()
            title = remote.get_title()

            if title == None:
                title = name.capitalize()

            remotes.append((name, title))
    except GLib.Error as e:
        print("MintInstall: flatpak - could not fetch remote list", e.message)
        remotes = []

    return remotes

def get_pkginfo_from_file(cache, uri, callback):
    thread = threading.Thread(target=_pkginfo_from_file_thread, args=(cache, uri, callback))
    thread.start()

def _pkginfo_from_file_thread(cache, uri, callback):
    fp_sys = get_fp_sys()

    from urllib.parse import urlparse

    if uri == None:
        print("MintInstall: flatpak - no valid uri provided")
        return None

    path = urlparse(uri).path

    ref = None
    pkginfo = None

    with open(path) as f:
        contents = f.read()

        b = contents.encode("utf-8")
        gb = GLib.Bytes(b)

        try:
            ref = fp_sys.install_ref_file(gb, None)

            if ref:
                remote_name = ref.get_remote_name()
                remote = fp_sys.get_remote_by_name(remote_name, None)
                _process_remote(None, fp_sys, remote, Flatpak.get_default_arch(), force_noenumerate=True)

                pkginfo = _add_package_to_cache(cache, ref, remote.get_url(), False)

                global _as_pools

                if remote_name not in _as_pools.keys():
                    _load_appstream_pool(_as_pools, remote)

        except GLib.Error as e:
            if e.code == Flatpak.Error.ALREADY_INSTALLED:
                try:
                    kf = GLib.KeyFile()
                    if kf.load_from_file(path, GLib.KeyFileFlags.NONE):
                        name = kf.get_string("Flatpak Ref", "Name")
                        if name:
                            pkginfo = find_pkginfo(cache, name)
                except GLib.Error:
                    print("MintInstall: flatpak package already installed, but an error occurred finding it")
            else:
                print("MintInstall: could not read .flatpakref file: %s" % e.message)

    GLib.idle_add(callback, pkginfo, priority=GLib.PRIORITY_DEFAULT)

def execute_transaction(task):
    if len(task.to_install + task.to_remove + task.to_update) > 1:
        dia = ChangesConfirmDialog(None, task)
        res = dia.run()
        dia.hide()
        if res != Gtk.ResponseType.OK:
            GObject.idle_add(task.finished_cleanup_cb, task)
            return

    if task.client_progress_cb != None:
        task.has_window = True
    else:
        progress_window = FlatpakProgressWindow(task)
        progress_window.present()

    thread = threading.Thread(target=_execute_transaction_thread, args=(task,))
    thread.start()

def _execute_transaction_thread(task):
    GLib.idle_add(task.client_progress_cb, task.pkginfo, 0, True, priority=GLib.PRIORITY_DEFAULT)

    fp_sys = get_fp_sys()

    task.transaction = MetaTransaction(fp_sys, task)

class MetaTransaction():
    def __init__(self, fp_sys, task):
        self.fp_sys = fp_sys
        self.task = task
        pkginfo = self.pkginfo = task.pkginfo

        task.to_install.reverse()

        self.item_count = len(task.to_install + task.to_remove + task.to_update)
        self.current_count = 0

        try:
            for str_ref in task.to_install:
                ref = Flatpak.Ref.parse(str_ref)

                task.progress_state = task.PROGRESS_STATE_INSTALLING
                task.current_package_name = ref.get_name()

                print("installing: %s" % str_ref)
                self.fp_sys.install(pkginfo.remote,
                                    ref.get_kind(),
                                    ref.get_name(),
                                    ref.get_arch(),
                                    ref.get_branch(),
                                    self.on_flatpak_progress,
                                    None,
                                    task.cancellable)

                self.current_count += 1

            for str_ref in task.to_remove:
                ref = Flatpak.Ref.parse(str_ref)

                task.progress_state = task.PROGRESS_STATE_REMOVING
                task.current_package_name = ref.get_name()

                print("removing: %s" % str_ref)
                self.fp_sys.uninstall(ref.get_kind(),
                                      ref.get_name(),
                                      ref.get_arch(),
                                      ref.get_branch(),
                                      self.on_flatpak_progress,
                                      None,
                                      task.cancellable)

                self.current_count += 1

            for str_ref in task.to_update:
                ref = Flatpak.Ref.parse(str_ref)

                task.progress_state = task.PROGRESS_STATE_UPDATING
                task.current_package_name = ref.get_name()

                print("updating: %s" % str_ref)
                self.fp_sys.update(Flatpak.UpdateFlags.NONE,
                                   pkginfo.remote,
                                   ref.get_kind(),
                                   ref.get_name(),
                                   ref.get_arch(),
                                   ref.get_branch(),
                                   self.on_flatpak_progress,
                                   None,
                                   task.cancellable)

                self.current_count += 1
        except GLib.Error as e:
            if e.code != Gio.IOErrorEnum.CANCELLED:
                task.progress_state = task.PROGRESS_STATE_FAILED
                task.current_package_name = None
                self.on_flatpak_error(e.message)
                return

        task.progress_state = task.PROGRESS_STATE_FINISHED
        task.current_package_name = None
        self.on_flatpak_finished()

    def on_flatpak_progress(self, status, progress, estimating, data=None):
        # Simple for now, each package gets an equal slice, and package progress is a percentage of that slice

        package_chunk_size = 1.0 / self.item_count
        partial_chunk = (progress / 100.0) * package_chunk_size

        actual_progress = math.floor(((self.current_count * package_chunk_size) + partial_chunk) * 100.0)

        GLib.idle_add(self.task.client_progress_cb,
                      self.task.pkginfo,
                      actual_progress,
                      estimating,
                      priority=GLib.PRIORITY_DEFAULT)

    def on_flatpak_error(self, error_details):
        self.task.error_message = error_details

        # Show an error popup only if we're in mintinstall, otherwise a flatpak
        # progress window will show the error details
        if self.task.has_window:
            dialogs.show_flatpak_error(error_details)

        GLib.idle_add(self.task.error_cleanup_cb, self.task)

    def on_flatpak_finished(self):
        GLib.idle_add(self.task.finished_cleanup_cb, self.task)


