#!/usr/bin/python3

from urllib.parse import urlparse
import json
import os

from gi.repository import GLib

from mintcommon.installer import installer

# The purpose of this script is to try and match up deb packages to their flatpak versions, if they exist. It
# uses a single thread and takes around 5 minutes to complete on a 5ghz processor (if there are no new matches
# to process).
# It:
#   - Creates a master list of debs, filter by a few criteria as well as ignoring matches we've already made
#     (these are contained in 'apt_flatpak_match_data.info').
#   - Creates a master list of flatpaks, again doing a bit of filtering, including previous stored matches
#     (in the .info file).
#   - It then begins working through every apt package in the resulting list, and thru the flatpak list for each
#     iteration, looking for likely matches.
#   - When it finds a potential match, it presents the package names, summaries and homepages so you can confirm
#     or skip them. Just pressing enter allows the match, pressing n then enter discards it.
#   - When a match is confirmed, it's added to a file named 'good'. Discarded apt names are put in a 'bad' file.
#   - You need to add this list of entries to apt_flatpak_match_data.info, the bad ones in apt_ignore_list, and
#     the matches in apt_flatpak_matches. The ignore list is used only for subsequent runs of this script to prevent
#     you having to process those false-positives again. The match list is used both in this script as well as
#     in mintinstall to allow linking.
#
#     I doubt the current list is complete, either by our selection criteria not being that great or due to missing
#     fields in the apps themselves. Improvements to the heuristic welcome.

ml = GLib.MainLoop.new(None, True)

def quit_ml(sig=None, frame=None):
    ml.quit()

os.chdir("./usr/lib/linuxmint/mintinstall")
with open("apt_flatpak_match_data.info") as f:
    lists = json.load(f)

apt_ignore_list = lists["apt_ignore_list"]
existing_matches = lists["apt_flatpak_matches"]

class Scraper():
    def __init__(self):
        self.installer = installer.Installer()
        self.installer.init(self.init_done)
        self.installer.initialize_appstream()

        self.fp = []
        self.apt = []
        self.matches = []

    def init_done(self):
        for pkg_hash in self.installer.cache.keys():
            pkginfo = self.installer.cache[pkg_hash]

            if pkginfo.pkg_hash.startswith("a"):
                if pkginfo.name.startswith("linux-"):
                    continue
                if pkginfo.name in apt_ignore_list:
                    continue
                if pkginfo.name.rsplit(":")[0] in existing_matches.keys():
                    continue
                if len(pkginfo.name) > 2:
                    self.apt.append(pkginfo)
                continue
            elif pkginfo.pkg_hash.startswith("f"):
                if pkginfo.name in existing_matches.values():
                    continue
                # if len(pkginfo.name.split(".")) > 3:
                    # continue
                if pkginfo.name.endswith(".Locale"):
                    continue
                if pkginfo.name.endswith(".Debug"):
                    continue
                if pkginfo.name.endswith(".Sources"):
                    continue
                if pkginfo.name.endswith(".Codecs"):
                    continue
                if "Gtk3theme" in pkginfo.name:
                    continue
                if ".Addon." in pkginfo.name:
                    continue

                self.fp.append(pkginfo)

        matches = []

        with open("good", "w") as goodfile:
            with open("bad", "w") as badfile:
                for apt_pkginfo in self.apt:
                    for f in self.fp:
                        match = None
                        # print(apt_pkginfo.name.rsplit(":"))
                        aname = apt_pkginfo.name.rsplit(":")[0] # foobar:i386
                        # print(apt_pkginfo.name, aname)
                        if aname in matches or f.name in matches:
                            continue

                        hp_url_a = self.installer.get_homepage_url(apt_pkginfo)
                        hp_url_f = self.installer.get_homepage_url(f)

                        hn_a = urlparse(hp_url_a).hostname or '<none>-apt'
                        hn_f = urlparse(hp_url_f).hostname or '<none-fp'

                        if hp_url_a == "github.com" and hp_url_f == "github.com":
                            continue

                        fname = f.name.partition(".")[2]
                        # if len(aname) == 0:
                            # continue
                        if aname == "seahorse":
                            print(aname, fname)
                        # print("1", aname.lower() == fname.lower().rpartition(".")[2], aname.lower(), fname.lower().rpartition(".")[2])
                        # print("2",(aname.lower() in fname.split(".")[0] and len(aname) / len(fname.split(".")[0]) > 0.5), aname.lower(), fname.split(".")[0])
                        # print("3",(aname.startswith("gnome-") and f.name == "org.gnome.%s" % aname[6:].capitalize()))
                        # print("4",(fname.lower() == "%s.%s" % (aname.lower(), aname.lower())), fname.lower(),aname.lower(), aname.lower())
                        # if (aname.lower() in fname.lower()) or \
                        if (aname.lower() in fname.lower() and len(aname) / len(fname) > 0.5) or \
                           (aname.lower() in f.name.split(".")) or \
                           (aname.startswith("gnome-") and f.name == "org.gnome.%s" % aname[6:].capitalize()) or \
                           (fname.lower() == "%s.%s" % (aname.lower(), aname.lower())) or \
                           (hp_url_a == hp_url_f):

                            print("\n\\\n%s\n%s\n\n%s\n%s\n\n%s\n%s\n/\n" % 
                                        (aname, f.name,
                                         self.installer.get_summary(apt_pkginfo), self.installer.get_summary(f),
                                         hp_url_a, hp_url_f))
                            i = input("enter to accept, or n to skip: ")
                            if i == "n":
                                badfile.write("%s\n" % (aname,))
                                continue
                            elif i == "q":
                                exit(0)
                            matches.append(aname)
                            matches.append(f.name)
                            goodfile.write("%s, %s\n" % (aname, f.name))

        quit_ml()


if __name__ == "__main__":

    import signal
    signal.signal(signal.SIGINT, quit_ml)

    scraper = Scraper()
    ml.run()

    exit(0)
