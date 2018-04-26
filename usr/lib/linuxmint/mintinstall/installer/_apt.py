import time
import threading
import apt

import gi
gi.require_version('AppStream', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import GObject, Gtk

import aptdaemon.client
from aptdaemon.gtk3widgets import AptErrorDialog, AptProgressDialog
import aptdaemon.errors

from installer.pkgInfo import AptPkgInfo
from installer.dialogs import ChangesConfirmDialog

# List of packages which are either broken or do not install properly in mintinstall
BROKEN_PACKAGES = ['pepperflashplugin-nonfree']

# List extra packages that aren't necessarily marked in their control files, but
# we know better...
CRITICAL_PACKAGES = ["mint-common", "mint-meta-core", "mintdesktop"]

def capitalize(string):
    if len(string) > 1:
        return (string[0].upper() + string[1:])

    return (string)

_apt_cache = None
_apt_cache_lock = threading.Lock()
_as_pool = None

def get_apt_cache(full=False):
    global _apt_cache

    if full or (not _apt_cache):
        with _apt_cache_lock:
            _apt_cache = apt.Cache()

    return _apt_cache

def add_prefix(name):
    return "apt:%s" % (name)

def make_pkg_hash(apt_pkg):
    if not isinstance(apt_pkg, apt.Package):
        raise TypeError("apt.make_pkg_hash_make must receive apt.Package, not %s" % type(apt_pkg))

    return add_prefix(apt_pkg.name)

def process_full_apt_cache(cache):
    apt_time = time.time()
    apt_cache = get_apt_cache()

    sections = {}

    keys = apt_cache.keys()

    for key in keys:
        name = apt_cache[key].name

        if name.startswith("lib") and not name.startswith("libreoffice"):
            continue
        if name.endswith(":i386") and name != "steam:i386":
            continue
        if name.endswith("-dev"):
            continue
        if name.endswith("-dbg"):
            continue
        if name.endswith("-doc"):
            continue
        if name.endswith("-common"):
            continue
        if name.endswith("-data"):
            continue
        if "-locale-" in name:
            continue
        if "-l10n-" in name:
            continue
        if name.endswith("-dbgsym"):
            continue
        if name.endswith("l10n"):
            continue
        if name.endswith("-perl"):
            continue
        if ":" in name and name.split(":")[0] in keys:
            continue

        pkg = apt_cache[key]

        pkg_hash = make_pkg_hash(pkg)

        if pkg.section:
            section_string = pkg.section

            if "/" in section_string:
                section = section_string.split("/")[1]
            else:
                section = section_string

        try:
            sections[section].append(pkg_hash)
        except Exception:
            sections[section] = []
            sections[section].append(pkg_hash)

        cache[pkg_hash] = AptPkgInfo(pkg_hash, pkg)

    print('MintInstall: Processing APT packages for cache took %0.3f ms' % ((time.time() - apt_time) * 1000.0))

    return cache, sections

# def initialize_appstream():
#     global _as_pool

#     if _as_pool == None:
#         pool = AppStream.Pool()
#         pool.set_cache_flags(AppStream.CacheFlags.NONE)
#         pool.load()
#         _as_pool = pool

def search_for_pkginfo_apt_pkg(pkginfo):
    name = pkginfo.name

    apt_cache = get_apt_cache()

    try:
        return apt_cache[name]
    except:
        return None

def find_pkginfo(cache, string):
    try:
        pkginfo = cache[add_prefix(string)]
    except:
        pkginfo = None

    return pkginfo

def pkginfo_is_installed(pkginfo):
    global _apt_cache_lock
    apt_cache = get_apt_cache()

    with _apt_cache_lock:
        try:
            return apt_cache[pkginfo.name].installed != None
        except:
            return False

def select_packages(task):
    thread = threading.Thread(target=_calculate_apt_changes, args=(task,))
    thread.start()

def _is_critical_package(pkg):
    try:
        if pkg.essential or pkg.versions[0].priority == "required" or pkg.name in CRITICAL_PACKAGES:
            return True

        return False
    except Exception:
        return False

def _calculate_apt_changes(task):
    global _apt_cache_lock
    apt_cache = get_apt_cache()

    with _apt_cache_lock:
        apt_cache.clear()

        print("MintInstall: Calculating changes required for APT package: %s" % task.pkginfo.name)

        pkginfo = task.pkginfo

        aptpkg = apt_cache[pkginfo.name]

        try:
            if aptpkg.is_installed:
                aptpkg.mark_delete(True, True)
            else:
                aptpkg.mark_install()
        except:
            if aptpkg.name not in BROKEN_PACKAGES:
                BROKEN_PACKAGES.append(aptpkg.name)

        changes = apt_cache.get_changes()

        for pkg in changes:
            if pkg.marked_install:
                task.to_install.append(pkg.name)
            elif pkg.marked_upgrade:
                task.to_update.append(pkg.name)
            elif pkg.marked_delete:
                task.to_remove.append(pkg.name)

        task.download_size = apt_cache.required_download

        space = apt_cache.required_space

        if space < 0:
            task.freed_size = space * -1
            task.install_size = 0
        else:
            task.freed_size = 0
            task.install_size = space

        for pkg_name in task.to_remove:
            if _is_critical_package(apt_cache[pkg_name]):
                print("MintInstall: apt - cannot remove critical package: %s" % pkg_name)
                task.info_ready_status = task.STATUS_FORBIDDEN

        if aptpkg.name in BROKEN_PACKAGES:
            print("MintInstall: apt- cannot execute task, package is broken: %s" % aptpkg.name)
            task.info_ready_status = task.STATUS_BROKEN

        print("For install:", task.to_install)
        print("For removal:", task.to_remove)
        print("For upgrade:", task.to_update)

        if task.info_ready_status not in (task.STATUS_FORBIDDEN, task.STATUS_BROKEN):
            task.info_ready_status = task.STATUS_OK
            task.execute = execute_transaction

    GObject.idle_add(task.info_ready_callback, task)

def sync_cache_installed_states():
    get_apt_cache(full=True)

def execute_transaction(task):
    if task.client_progress_cb != None:
        task.has_window = True

    task.transaction = MetaTransaction(task)

class MetaTransaction():
    def __init__(self, task):
        self.apt_client = aptdaemon.client.AptClient()
        self.task = task
        self.apt_transaction = None

        if task.type == "remove":
            self.apt_client.remove_packages([task.pkginfo.name],
                                            reply_handler=self._calculate_changes,
                                            error_handler=self._on_error) # dbus.DBusException
        else:
            self.apt_client.install_packages([task.pkginfo.name],
                                             reply_handler=self._calculate_changes,
                                             error_handler=self._on_error) # dbus.DBusException

    def _calculate_changes(self, apt_transaction):
        self.apt_transaction = apt_transaction
        self.apt_transaction.set_debconf_frontend("gnome")

        self.apt_transaction.simulate(reply_handler=self._confirm_changes,
                                      error_handler=self._on_error) # aptdaemon.errors.TransactionFailed, dbus.DBusException

    def _confirm_changes(self):
        try:
            if [pkgs for pkgs in self.apt_transaction.dependencies if pkgs]:
                dia = ChangesConfirmDialog(self.apt_transaction, self.task)
                res = dia.run()
                dia.hide()
                if res != Gtk.ResponseType.OK:
                    GObject.idle_add(self.task.finished_cleanup_cb, self.task)
                    return
            self._run_transaction()
        except Exception as e:
            print(e)

    def _on_error(self, error):
        if self.apt_transaction.error_code == "error-not-authorized":
            # Silently ignore auth failures

            self.task.error_message = None # Should already be none, but this is a reminder
            return
        elif not isinstance(error, aptdaemon.errors.TransactionFailed):
            # Catch internal errors of the client
            error = aptdaemon.errors.TransactionFailed(aptdaemon.enums.ERROR_UNKNOWN,
                                                       str(error))

        if self.task.progress_state != self.task.PROGRESS_STATE_FAILED:
            self.task.progress_state = self.task.PROGRESS_STATE_FAILED

            self.task.error_message = self.apt_transaction.error_details

            dia = AptErrorDialog(error)
            dia.run()
            dia.hide()
            GObject.idle_add(self.task.error_cleanup_cb, self.task)

    def _run_transaction(self):
        self.apt_transaction.connect("finished", self.on_transaction_finished)

        if self.task.has_window:
            self.apt_transaction.connect("progress-changed", self.on_transaction_progress)
            self.apt_transaction.connect("error", self.on_transaction_error)
            self.apt_transaction.run(reply_handler=lambda: None, error_handler=self._on_error)
        else:
            progress_window = AptProgressDialog(self.apt_transaction)
            progress_window.run(show_error=False, error_handler=self._on_error)

    def on_transaction_progress(self, apt_transaction, progress):
        if not apt_transaction.error:
            self.task.client_progress_cb(self.task.pkginfo, progress, False)

    def on_transaction_error(self, apt_transaction, error_code, error_details):
        if self.task.progress_state != self.task.PROGRESS_STATE_FAILED:
            self._on_error(apt_transaction.error)

    def on_transaction_finished(self, apt_transaction, exit_state):
        # finished signal is always called whether successful or not
        # Only call here if we succeeded, to prevent multiple calls
        if (exit_state == aptdaemon.enums.EXIT_SUCCESS) or apt_transaction.error_code == "error-not-authorized":
            self.task.progress_state = self.task.PROGRESS_STATE_FINISHED
            GObject.idle_add(self.task.finished_cleanup_cb, self.task)
