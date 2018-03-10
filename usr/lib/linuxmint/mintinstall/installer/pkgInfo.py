import sys
if sys.version_info.major < 3:
    raise "python3 required"

from gi.repository import AppStream

def capitalize(string):
    if string and len(string) > 1:
        return (string[0].upper() + string[1:])
    else:
        return (string)

class PkgInfo:
    __slots__ = "pkg_hash", "name", "display_name", "summary", "description",    \
                "icon", "screenshots", "url", "version", "categories", "refid",  \
                "remote", "remote_url", "kind", "arch", "branch", "commit"

    def __init__(self, pkg_hash):
        # Saved stuff
        self.pkg_hash = pkg_hash
        self.name = None
        # some flatpak-specific things
        self.refid=""
        self.remote = ""
        self.kind = 0
        self.arch = ""
        self.branch = ""
        self.commit = ""
        self.remote_url = ""

        # Display info fetched by methods always
        self.display_name = None
        self.summary = None
        self.description = None
        self.version = None
        self.icon = None
        self.screenshots = []
        self.url = None

        # Runtime categories
        self.categories = []

    def __getstate__(self):
        return (                                 \
        self.pkg_hash,       self.name,          \
        self.remote,         self.remote_url,    \
        self.kind,           self.arch,          \
        self.branch,         self.commit,        \
        self.refid                               \
        )

    def __setstate__(self, state):
        self.pkg_hash,       self.name,          \
        self.remote,         self.remote_url,    \
        self.kind,           self.arch,          \
        self.branch,         self.commit,        \
        self.refid                               = state

        self.categories = []
        self.clear_cached_info()

    def clear_cached_info(self):
        self.display_name = None
        self.summary = None
        self.description = None
        self.icon = None
        self.screenshots = []
        self.version = None
        self.url = None

class AptPkgInfo(PkgInfo):
    def __init__(self, pkg_hash, apt_pkg):
        super(AptPkgInfo, self).__init__(pkg_hash)
        self.name = apt_pkg.name

    def get_display_name(self, apt_pkg=None):
        # fastest
        if self.display_name:
            return self.display_name

        if apt_pkg:
            self.display_name = apt_pkg.name.capitalize()

        if not self.display_name:
            self.display_name = self.name.capitalize()

        self.display_name = self.display_name.replace(":i386", "")

        return self.display_name

    def get_summary(self, apt_pkg=None):
        # fastest
        if self.summary:
            return self.summary

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            summary = ""
            if candidate.summary is not None:
                summary = candidate.summary
                summary = summary.replace("<", "&lt;")
                summary = summary.replace("&", "&amp;")

                self.summary = capitalize(summary)

        if self.summary == None:
            self.summary = ""

        return self.summary

    def get_description(self, apt_pkg=None):
        # fastest
        if self.description:
            return self.description

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            description = ""
            if candidate.description != None:
                description = candidate.description
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")

                self.description = capitalize(description)

        if self.description == None:
            self.description = ""

        return self.description

    def get_icon(self, apt_pkg=None):
        return None # this is handled in mintinstall directly for now

    def get_screenshots(self, apt_pkg=None):
        return [] # handled in mintinstall for now

    def get_version(self, apt_pkg=None):
        if self.version:
            return self.version

        if apt_pkg:
            if apt_pkg.is_installed:
                self.version = apt_pkg.installed.version
            else:
                self.version = apt_pkg.candidate.version

            if self.version == None:
                self.version = ""

        return self.version

    def get_url(self, apt_pkg=None):
        if self.url:
            return self.url

        if apt_pkg:
            if apt_pkg.is_installed:
                self.url = apt_pkg.installed.homepage
            else:
                self.url = apt_pkg.candidate.homepage

        if self.url == None:
            self.url = ""

        return self.url


class FlatpakPkgInfo(PkgInfo):
    def __init__(self, pkg_hash, remote, ref, remote_url, installed):
        super(FlatpakPkgInfo, self).__init__(pkg_hash)

        self.name = ref.get_name() # org.foo.Bar
        self.remote = remote # "flathub"
        self.remote_url = remote_url

        self.refid = ref.format_ref() # app/org.foo.Bar/x86_64/stable
        self.kind = ref.get_kind() # Will be app for now
        self.arch = ref.get_arch()
        self.branch = ref.get_branch()
        self.commit = ref.get_commit()

    def get_display_name(self, as_component=None):
        # fastest
        if self.display_name:
            return self.display_name

        if as_component:
            display_name = as_component.get_name()

            if display_name != None:
                self.display_name = capitalize(display_name)

        if self.display_name == None:
            self.display_name = self.name

        return self.display_name

    def get_summary(self, as_component=None):
        # fastest
        if self.summary:
            return self.summary

        if as_component:
            summary = as_component.get_summary()

            if summary != None:
                self.summary = summary

        if self.summary == None:
            self.summary = ""

        return self.summary

    def get_description(self, as_component=None):
        # fastest
        if self.description:
            return self.description

        if as_component:
            description = as_component.get_description()

            if description != None:
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")
                self.description = capitalize(description)

        if self.description == None:
            self.description = ""

        return self.description

    def get_icon(self, as_component=None):
        if self.icon:
            return self.icon

        if as_component:
            icons = as_component.get_icons()

            if icons:
                if icons[0].get_kind() == AppStream.IconKind.LOCAL:
                    self.icon = icons[0].get_filename()
                elif icons[0].get_kind() == AppStream.IconKind.STOCK:
                    self.icon = icons[0].get_name()

        if self.icon == None:
            self.icon = self.name

        return self.icon

    def get_screenshots(self, as_component=None):
        if len(self.screenshots) > 0:
            return self.screenshots

        if as_component:
            screenshots = as_component.get_screenshots()

            for ss in screenshots:
                images = ss.get_images()

                if len(images) == 0:
                    continue

                # FIXME: there must be a better way.  Finding an optimal size to use without just
                # resorting to an original source.

                best = None
                largest = None

                for image in images:
                    if image.get_kind() == AppStream.ImageKind.SOURCE:
                        continue

                    w = image.get_width()

                    if w > 500 and w < 625:
                        best = image
                        break

                    if w > 625:
                        continue

                    if largest == None or (largest != None and largest.get_width() < w):
                        largest = image

                if best == None and largest == None:
                    continue

                if best == None:
                    best = largest

                if ss.get_kind() == AppStream.ScreenshotKind.DEFAULT:
                    self.screenshots.insert(0, best.get_url())
                else:
                    self.screenshots.append(best.get_url())

        return self.screenshots

    def get_version(self, as_component=None):
        if self.version:
            return self.version

        if as_component:
            releases = as_component.get_releases()

            if len(releases) > 0:
                version = releases[0].get_version()

                if version:
                    self.version = version

        if self.version == None:
            self.version = ""

        return self.version

    def get_url(self, as_component=None):
        if self.url:
            return self.url

        if as_component:
            url = as_component.get_url(AppStream.UrlKind.HOMEPAGE)

            if url != None:
                self.url = url

        if self.url == None:
            self.url = self.remote_url

        return self.url