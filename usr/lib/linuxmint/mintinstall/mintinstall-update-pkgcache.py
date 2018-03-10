#!/usr/bin/python3


from installer import cache

pkgcache = cache.PkgCache()

try:
    pkgcache.force_new_cache()
except Exception as e:
    print(e)

exit()
