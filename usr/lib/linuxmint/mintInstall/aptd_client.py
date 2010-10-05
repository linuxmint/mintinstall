#!/usr/bin/python
import aptdaemon, sys, gettext
from aptdaemon.client import AptClient

# i18n
gettext.install("mintinstall", "/usr/share/linuxmint/locale")

if len(sys.argv) == 3:
    operation = sys.argv[1]
    package = sys.argv[2]
    aptd_client = AptClient()
    if operation == "install":
        transaction = aptd_client.install_packages([package])    
        transaction.set_meta_data(mintinstall_label=_("Installing %s") % package)        
    elif operation == "remove":
        transaction = aptd_client.remove_packages([package])    
        transaction.set_meta_data(mintinstall_label=_("Removing %s") % package)
    else:
        print "Invalid operation: %s" % operation
        sys.exit(1)        
    transaction.set_meta_data(mintinstall_pkgname=package)
    transaction.run()
