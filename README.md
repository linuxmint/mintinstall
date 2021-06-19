# Mintinstall

Software Manager for Linux Mint.

![image](https://user-images.githubusercontent.com/19881231/122644976-86767180-d120-11eb-9cf4-eed2813f749b.png)

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
