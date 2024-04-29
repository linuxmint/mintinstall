#!/usr/bin/python3
import re
import subprocess
import time
import json
import os
import gi
gi.require_version("Xmlb", "2.0")
from gi.repository import Xmlb, Gio, GLib

class CouldNotInstallError(Exception):
    pass

def test_app(uuid):
    print("Checking", uuid)
    cleaned_uuid = uuid.removesuffix(".desktop")
    if uuid != cleaned_uuid:
        print(f"Sanitized uuid: {uuid} --> {cleaned_uuid}")

    installer = f"flatpak install -y --noninteractive --system {cleaned_uuid}"
    try:
        print("Installing")
        subprocess.check_output(installer, text=True, shell=True)
    except subprocess.CalledProcessError as e:
        raise CouldNotInstallError(f"Could not install {cleaned_uuid}: {e.output}")

    proc = subprocess.Popen(["flatpak", "run", cleaned_uuid], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    time.sleep(3)

    toolkit = None

    print("Starting")
    # Find the process and check maps
    for i in range(1, 30):
        for tk in ("libadwaita", "libgtk-4", "libgtk-3"):
            scanner = f"flatpak enter {cleaned_uuid} cat /proc/{i}/maps| grep -m1 {tk}"

            try:
                out = subprocess.check_output(scanner, text=True, shell=True, stderr=subprocess.DEVNULL)
                if tk in out:
                    print(f"{cleaned_uuid} uses {tk}")
                    toolkit = tk
                    break
            except subprocess.CalledProcessError as e:
                pass
        if toolkit is not None:
            break

    try:
        print(f"Killing {cleaned_uuid}")
        subprocess.check_output(f"flatpak kill {cleaned_uuid}", shell=True)
    except subprocess.CalledProcessError as e:
        print("Could not kill %s: %s" % (cleaned_uuid, e.output))

    time.sleep(1)
    return toolkit


def cleanup(uuids):
    for uuid in uuids:
        cleaned_uuid = uuid.removesuffix(".desktop")

        uninstaller = f"flatpak uninstall -y --noninteractive --system {cleaned_uuid}"
        try:
            print("Uninstalling")
            subprocess.check_output(uninstaller, text=True, shell=True)
        except subprocess.CalledProcessError as e:
            print(f"Could not uninstall {uuid}: {e.output}")
            return

existing = None
try:
    with open("./usr/lib/linuxmint/mintinstall/gnome_platform_apps.json") as f:
        existing = json.load(f)
except Exception as e:
    print(e)
    quit()
    existing = {}
    existing["libadwaita"] = []
    existing["libgtk-4"] = []
    existing["libgtk-3"] = []

scanned_negative = []
try:
    with open("scanned_negative.json") as f:
        scanned_negative = json.load(f)
except:
    pass

could_not_install = []
try:
    with open("could_not_install.json") as f:
        could_not_install = json.load(f)
except:
    pass

s = Xmlb.BuilderSource()
f = Gio.File.new_for_path(
    "/var/lib/flatpak/appstream/flathub/x86_64/active/appstream.xml.gz")
s.load_file(f, Xmlb.BuilderSourceFlags.NONE, None)

b = Xmlb.Builder()
b.import_source(s)
silo = b.compile(0, None)

q = Xmlb.Query.new(silo, "components/component/bundle[@runtime]")
results = silo.query_full(q)

i = 0
found = []
for node in results:
    st = node.get_attr("runtime")
    res = re.search(r"org.gnome.Platform\/[\w\S]+\/(\d+)", st)
    if res is None:
        continue

    #  libadwaita wasn't included until runtime 42
    if int(res.group(1)) < 42:
        continue

    root = node.get_parent()

    nq = root.query("id", 1)
    if nq is not None:
        uuid = nq[0].get_text()
        if uuid.endswith("Sdk") or uuid.endswith("Platform"):
            continue

        found.append(uuid)

print(f"Found {len(found)} apps that use org.gnome.Platform >= 42")

gnome_platform_apps = existing

remove_queue = []

i = len(found)
for uuid in found:
    print(f"{i} more apps to go.")
    i -= 1

    if uuid in existing["libadwaita"] or uuid in existing["libgtk-4"] or uuid in existing["libgtk-3"]:
        print(f"Skipping {uuid} (already positive)")
        continue
    if uuid in scanned_negative:
        print(f"Skipping {uuid} (already negative)")
        continue

    try:
        toolkit = test_app(uuid)
        if toolkit is not None:
            print(f"{uuid} uses {toolkit}")
            gnome_platform_apps[toolkit].append(uuid)
            # Save after each in case we need to restart
            with open("./usr/lib/linuxmint/mintinstall/gnome_platform_apps.json", "w") as f:
                json.dump(gnome_platform_apps, f, indent=4)
        else:
            scanned_negative.append(uuid)
            with open("scanned_negative.json", "w") as ascanned:
                json.dump(scanned_negative, ascanned, indent=4)

    except CouldNotInstallError as e:
        print(e)
        could_not_install.append(uuid)
        with open("could_not_install.json", "w") as cni:
            json.dump(could_not_install, cni, indent=4)

    remove_queue.append(uuid)
    if len(remove_queue) == 10:
        cleanup(remove_queue)
        remove_queue = []
