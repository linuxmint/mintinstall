#!/usr/bin/python3

import subprocess
import os

# Remove any obsolete configuration file
obsolete_path = os.path.expanduser("~/.config/autostart/mintinstall-update-flatpak.desktop")
if os.path.exists(obsolete_path):
	try:
		os.unlink(obsolete_path)
	except:
		pass

subprocess.call("/usr/lib/linuxmint/mintinstall/mintinstall.py")
