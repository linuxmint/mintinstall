#!/usr/bin/python3

import subprocess

import gi
from gi.repository import GLib
# Make sure flatpak binary and libflatpak are installed, otherwise exit.

print("Checking if flatpak and libflatpak are installed")
try:
    gi.require_version('Flatpak', '1.0')
    from gi.repository import Flatpak

    if not GLib.find_program_in_path("flatpak"):
        raise Exception
except Exception as e:
    print("Flatpak not installed, exiting: %s" % e)
    exit(1)

from mintcommon.installer import _flatpak

print("Updating flatpaks")
out = subprocess.run(["flatpak", "update", "-y"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

print(out.stdout.decode())

print("Checking for theme changes")
theme_refs = _flatpak.get_updated_theme_refs()

if not theme_refs:
    print("No theme packages to install, exiting")
    exit(0)

print("Installing new theme package(s) to match system themes")
for ref in theme_refs:
    name = ref.get_name()
    remote = ref.get_remote_name()

    out = subprocess.run(["flatpak", "install", "-y", remote, name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    print(out.stdout.decode())

print("Done")
exit(0)









