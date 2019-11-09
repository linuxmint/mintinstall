import sys
if sys.version_info.major < 3:
    raise "python3 required"

from gi.repository import GLib

import time
import os
import threading
import multiprocessing
from pathlib import Path

SCREENSHOT_DIR = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "screenshots")

MAX_AGE = 14 * (60 * 60 * 24) # days

proc = None

def run():
    print("MintInstall: Deleting old screenshots")

    thread = threading.Thread(target=_clean_screenshots_thread)
    thread.start()

def _clean_screenshots_thread():
    global proc

    proc = multiprocessing.Process(target=_clean_screenshots_process)
    proc.start()

    proc.join()

    proc = None

def _clean_screenshots_process():
    ss_location = Path(SCREENSHOT_DIR)

    screenshots = ss_location.glob("*.*")

    for p in screenshots:
        try:
            mtime = os.path.getmtime(str(p))

            if (time.time() - MAX_AGE) > mtime:
                p.unlink()
        except OSError:
            pass

def kill():
    global proc

    try:
        proc.terminate()
        proc = None
    except AttributeError as e:
        pass
