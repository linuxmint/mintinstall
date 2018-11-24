#!/usr/bin/python3


from installer import installer, cache

installer = installer.Installer()
pkgcache = cache.PkgCache(installer.have_flatpak)

try:
    pkgcache.force_new_cache()
except Exception as e:
    print(e)

exit()
