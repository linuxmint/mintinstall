# Mintinstall

Software Manager for Linux Mint.

![image](https://linuxmint.com/web/img/screenshots/c9.jpg)

## Build
Get source code
```
git clone https://github.com/linuxmint/mintinstall
cd mintinstall
```
Build
```
dpkg-buildpackage --no-sign
```
Install
```
cd ..
sudo dpkg -i mintinstall*.deb
```

## Translations
Please use Launchpad to translate Mintinstall: https://translations.launchpad.net/linuxmint/latest/.

The PO files in this project are imported from there.
