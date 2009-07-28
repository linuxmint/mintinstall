#!/usr/bin/python

import apt
import sys

try:
	cache = apt.Cache()	
	pkg = cache["mintinstall"]
	print pkg.installedVersion
except:
	pass


