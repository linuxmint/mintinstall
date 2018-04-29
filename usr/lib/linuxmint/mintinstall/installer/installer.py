#!/usr/bin/python3
import threading
import signal
import time

import gi
gi.require_version('AppStream', '1.0')
gi.require_version('Flatpak', '1.0')
from gi.repository import GLib, GObject, Gio

from installer import cache, _flatpak, _apt
from misc import print_timing

PKG_TYPE_NONE = None
PKG_TYPE_APT = "a"
PKG_TYPE_FLATPAK = "f"

# the action that initiated the task
INSTALL_TASK = "install"
UNINSTALL_TASK = "remove"
UPDATE_TASK = "update"

class InstallerTask:
    # Set after a package selection, reflects whether task can proceed or not
    STATUS_NONE = "none"
    STATUS_OK = "ok"
    STATUS_BROKEN = "broken"
    STATUS_FORBIDDEN = "forbidden"

    # Used by standalone progress window to update labels appropriately
    PROGRESS_STATE_INIT = "init"
    PROGRESS_STATE_INSTALLING = "installing"
    PROGRESS_STATE_UPDATING = "updating"
    PROGRESS_STATE_REMOVING = "removing"
    PROGRESS_STATE_FINISHED = "finished"
    PROGRESS_STATE_FAILED = "failed"

    def __init__(self, pkginfo, installer, info_ready_callback):
        self.type = INSTALL_TASK

        self.parent_window = None

        # pkginfo will be None for an update task
        self.pkginfo = pkginfo

        self.name = None

        # Set by .select_pkginfo(), the re-entry point after a task is fully
        # calculated, and the UI should be updated with detailed info about
        # the pending operation (disk use, etc..)
        self.info_ready_callback = info_ready_callback
        # To be checked by the info_ready_callback, to allow the UI to reflect
        # the ability to proceed with a task, or report that something is not right.
        self.info_ready_status = self.STATUS_NONE

        # Set by the backend, the function to call to actually perform the task (will
        # be none on STATUS_BROKEN or _FORBIDDEN)
        self.execute = None

        # Passed to _flatpak operations to respond to the Cancel button in the
        # standalone progress window. eventually it may be used elsewhere.
        self.cancellable = Gio.Cancellable()

        # Callbacks that will be used at various points during a task being operated on.
        # The .client_* callbacks are arguments of Installer.execute_task().  The
        # client_finished_cb is required.  If the progress callback is missing, a standalone
        # progress window will be provided.
        self.client_progress_cb = None
        self.client_finished_cb = None

        # These are internally used - called as the 'real' error and finished callback,
        # to do some cleanup like removing the task and reloading the apt cache before
        # finally calling task.client_finished_cb
        self.error_cleanup_cb = None
        self.finished_cleanup_cb = None

        self.has_window = False
        # Updated throughout a flatpak operation - for now it's used for updating the
        # standalone flatpak progress window
        self.progress_state = self.PROGRESS_STATE_INIT
        # Same - allows the flatpak window to update the current package being installed/removed
        self.current_package_name = None
        # The error message displayed in a popup if a flatpak operation fails.
        self.error_message = None

        # apt only, stores the AptTransaction
        self.transaction = None

        # The command that can be used to launch the current target package, if it's installed
        self.exec_string = None

        # List of additional packages to install, remove or update, based on the selected
        # pkginfo. Always lists of strings, but depending on the backend, they will consist
        # of package names (apt) or stringified flatpak refs (the result of ref.format_ref())
        self.to_install = []
        self.to_remove = []
        self.to_update = []

        # Size info for display, calculated by the backend during .select_pkginfo()
        self.download_size = 0
        self.install_size = 0
        self.freed_size = 0

        # Static info filled in for display
        if pkginfo:
            self.name = pkginfo.name

            if pkginfo.pkg_hash.startswith("a"):
                self.arch = ""
                self.branch = ""
                self.remote = ""
            else:
                self.arch = pkginfo.arch
                self.remote = pkginfo.remote
                self.branch = pkginfo.branch

            self.version = installer.get_version(pkginfo)

class Installer:
    def __init__(self):
        self.tasks = {}

        self.inited = False

        self.cache = {}
        self._init_cb = None

        self.startup_timer = time.time()

    def init_sync(self):
        """
        Loads the cache asynchronously.  If there is no cache (or it's too old,) it causes
        one to be generated and saved.  The ready_callback is called on idle once this is finished.
        """
        self.backend_table = {}

        self.cache = cache.PkgCache()

        if self.cache.status == self.cache.STATUS_OK:
            self.inited = True

            GObject.idle_add(self.initialize_appstream)

            return True

        return False

    def init(self, ready_callback=None):
        """
        Loads the cache asynchronously.  If there is no cache (or it's too old,) it causes
        one to be generated and saved.  The ready_callback is called on idle once this is finished.
        """
        self.backend_table = {}

        self.cache = cache.PkgCache()

        self._init_cb = ready_callback

        if self.cache.status == self.cache.STATUS_OK:
            self.inited = True

            GObject.idle_add(self._idle_cache_load_done)
        else:
            self.cache.force_new_cache_async(self._idle_cache_load_done)

        return self

    def _idle_cache_load_done(self):
        self.inited = True

        GObject.idle_add(self.initialize_appstream)

        print('Full installer startup took %0.3f ms' % ((time.time() - self.startup_timer) * 1000.0))

        if self._init_cb:
            self._init_cb()

    def select_pkginfo(self, pkginfo, ready_callback):
        """
        Initiates calculations for installing or removing a particular package
        (depending upon whether or not the selected package is installed.  Creates
        an InstallerTask instance and populates it with info relevant for display
        and for execution later.  When this is completed, ready_callback is called,
        with the newly-created task as its argument.  Note:  At that point, this is
        the *only* reference to the task object.  It can be safely discarded.  If
        the task is to be run, Installer.execute_task() is called, passing this task
        object, along with callback functions.  The task object is then added to a
        queue (and is tracked in self.tasks from there on out.)
        """
        if pkginfo.pkg_hash in self.tasks.keys():
            task = self.tasks[pkginfo.pkg_hash]

            GObject.idle_add(task.info_ready_callback, task)
            return

        task = InstallerTask(pkginfo, self, ready_callback)

        if self.pkginfo_is_installed(pkginfo):
            # It's not installed, so assume we're installing
            task.type = UNINSTALL_TASK
        else:
            task.type = INSTALL_TASK

        if pkginfo.pkg_hash.startswith("a"):
            _apt.select_packages(task)
        else:
            _flatpak.select_packages(task)

    def prepare_flatpak_update(self, ready_callback):
        """
        Creates an InstallerTask populated with all flatpak packages that can be
        updated.  Note, unlike select_pkginfo, there is no 'primary' package here.
        Only disk utilization and download info, along with the list of ref strings
        (in task.to_update) will be populated.
        """
        task = InstallerTask(None, self, ready_callback)

        task.type = UPDATE_TASK

        _flatpak.select_updates(task)

    def list_updated_flatpak_pkginfos(self):
        """
        Returns a list of flatpak pkginfos that can be updated.  Unlike
        prepare_flatpak_update, this is for the convenience of displaying information
        to the user.
        """
        return _flatpak.list_updated_pkginfos(self.cache)

    def find_pkginfo(self, name, pkg_type=PKG_TYPE_NONE):
        """
        Attempts to find and return a PkgInfo object, given a package name.  If
        pkg_type is None, looks in first apt, then flatpaks.
        """
        return self.cache.find_pkginfo(name, pkg_type)

    def get_pkginfo_from_ref_file(self, file, ready_callback):
        """
        Accepts a GFile to a .flatpakref on a local path.  If the flatpak's remote
        has not been previously added to the system installation, this also adds
        it and downloads Appstream info as well, before calling ready_callback with
        the created (or existing) PkgInfo as an argument.
        """
        _flatpak.get_pkginfo_from_file(self.cache, file, ready_callback)

    def add_remote_from_repo_file(self, file, ready_callback):
        """
        Accepts a GFile to a .flatpakrepo on a local path.  Adds the remote if it
        doesn't exist already, fetches any appstream data, and then calls
        ready_callback
        """
        _flatpak.add_remote_from_repo_file(self.cache, file, ready_callback)

    def list_flatpak_remotes(self):
        """
        Returns a list of tuples of (remote name, remote title).  The remote_name
        can be used to match with PkgInfo.remote and the title is for display.
        """
        return _flatpak.list_remotes()

    def pkginfo_is_installed(self, pkginfo):
        """
        Returns whether or not a given package is currently installed.  This uses
        the AptCache or the FlatpakInstallation to check.
        """
        if self.inited:
            if pkginfo.pkg_hash.startswith("a"):
                return _apt.pkginfo_is_installed(pkginfo)
            elif pkginfo.pkg_hash.startswith("f"):
                return _flatpak.pkginfo_is_installed(pkginfo)

        return False

    @print_timing
    def initialize_appstream(self):
        """
        Loads and caches the AppStream pools so they can be used to provide
        display info for packages.
        """
        _flatpak.initialize_appstream()
        # Is there any reason to use apt's appstream?

    def _get_backend_component(self, pkginfo):
        try:
            backend_component = self.backend_table[pkginfo]

            return backend_component
        except KeyError:
            if pkginfo.pkg_hash.startswith("a"):
                backend_component = _apt.search_for_pkginfo_apt_pkg(pkginfo)
            else:
                backend_component = _flatpak.search_for_pkginfo_as_component(pkginfo)

            self.backend_table[pkginfo] = backend_component

            # It's possible at some point we'll refresh appstream at runtime, if so we'll
            # want to clear cached data so it can be re-fetched anew.  For now there's
            # no need. The only possible case is on-demand adding of a remote (from
            # launching a .flatpakref file), and in this case, we won't have had anything
            # cached for it to clear anyhow.

            # pkginfo.clear_cached_info()

            return backend_component

    def get_display_name(self, pkginfo):
        """
        Returns the name of the package formatted for displaying
        """
        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_display_name(comp)

    def get_summary(self, pkginfo, for_search=False):
        """
        Returns the summary of the package.  If for_search is True,
        this is the raw, unformatted string in the case of apt.
        """
        if for_search and pkginfo.pkg_hash.startswith("a"):
            try:
                return _apt._apt_cache[pkginfo.name].candidate.summary
            except Exception:
                pass

        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_summary(comp)

    def get_description(self, pkginfo, for_search=False):
        """
        Returns the description of the package.  If for_search is True,
        this is the raw, unformatted string in the case of apt.
        """
        if for_search and pkginfo.pkg_hash.startswith("a"):
            try:
                return _apt._apt_cache[pkginfo.name].candidate.description
            except Exception:
                pass

        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_description(comp)

    def get_icon(self, pkginfo):
        """
        Returns the icon name (or path) to display for the package
        """
        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_icon(comp)

    def get_screenshots(self, pkginfo):
        """
        Returns a list of screenshot urls
        """
        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_screenshots(comp)

    def get_version(self, pkginfo):
        """
        Returns the current version string, if available
        """
        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_version(comp)

    def get_url(self, pkginfo):
        """
        Returns the home page url for a package.  If there is
        no url for the package, in the case of flatpak, the remote's url
        is displayed instead
        """
        comp = self._get_backend_component(pkginfo)

        return pkginfo.get_url(comp)

    def is_busy(self):
        return len(self.tasks.keys()) > 0

    def get_task_count(self):
        return len(self.tasks.keys())

    def get_active_pkginfos(self):
        pkginfos = []

        for pkg_hash in self.tasks.keys():
            pkginfos.append(self.tasks[pkg_hash].pkginfo)

        return pkginfos

    def task_running(self, task):
        """
        Returns whether a given task is currently executing.
        """
        return task.pkginfo.pkg_hash in self.tasks.keys()

    def execute_task(self, task, client_finished_cb, client_progress_cb=None):
        """
        Executes a given task.  The client_finished_cb is required always, to notify
        when the task completes. The progress and error callbacks are optional.  If
        they're left out, a standalone progress window is created to allow the user to
        see the task's progress (and cancel it if desired.)
        """
        self.tasks[task.pkginfo.pkg_hash] = task
        print("Starting task for package %s, type '%s'" % (task.pkginfo.pkg_hash, task.type))

        task.client_finished_cb = client_finished_cb
        task.client_progress_cb = client_progress_cb

        task.finished_cleanup_cb = self._task_finished
        task.error_cleanup_cb = self._task_error

        task.execute(task)

    def _task_finished(self, task):
        print("Done with task (success)", task.pkginfo.pkg_hash)
        del self.tasks[task.pkginfo.pkg_hash]

        self._post_task_update(task)

    def _task_error(self, task):
        print("Done with task (error)", task.pkginfo.pkg_hash)
        del self.tasks[task.pkginfo.pkg_hash]

        self._post_task_update(task)

    def _post_task_update(self, task):
        if task.pkginfo.pkg_hash.startswith("a"):
            thread = threading.Thread(target=self._apt_post_task_update_thread, args=(task,))
            thread.start()
        else:
            self._run_client_callback(task)

    def _apt_post_task_update_thread(self, task):
        _apt.sync_cache_installed_states()

        # This needs to be called after reloading the apt cache, otherwise our installed
        # apps don't update correctly
        self._run_client_callback(task)

    def _run_client_callback(self, task):
        GObject.idle_add(task.client_finished_cb, task.pkginfo, task.error_message)

def interact():
    import readline
    import code
    variables = globals().copy()
    variables.update(locals())
    shell = code.InteractiveConsole(variables)
    shell.interact()

# Debugging - you can run installer.py on its own, and test things with the Installer (i)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    i = Installer()
    i.init(ready_callback=interact)

    ml = GLib.MainLoop.new(None, True)
    ml.run()
