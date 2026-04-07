#!/usr/bin/python3

import os
import requests
import logging
from concurrent.futures import ThreadPoolExecutor

from gi.repository import GObject, Gtk, GLib, Gio, Gdk, GdkPixbuf

SCREENSHOT_DIR = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "screenshots")
FLATHUB_MEDIA_BASE_URL = "https://dl.flathub.org/media/"
FALLBACK_PACKAGE_ICON_PATH = "/usr/share/linuxmint/mintinstall/data/fallback-package-icon.svg"

ADDON_ICON_SIZE = 24
LIST_ICON_SIZE = 48
FEATURED_ICON_SIZE = 48
DETAILS_ICON_SIZE = 64
SCREENSHOT_HEIGHT = 351
SCREENSHOT_WIDTH = 624

MAX_THREADS = 2

threadpool = ThreadPoolExecutor(max_workers=MAX_THREADS, thread_name_prefix="mintinstall-images")
icon_surface_cache = {}

def clear_cache():
    icon_surface_cache = {}

def key(string, size):
    return f"{string}_{size}"

def get_icon(string, size):
    icon = None

    try:
        surface = icon_surface_cache[key(string, size)]
        icon = Gtk.Image.new_from_surface(surface)
    except Exception as e:
        icon = AsyncImage(string, size, size, cache=True)

    return icon

def get_image_for_screenshot(string, width, height):
    return AsyncImage(string, width, height)

class AsyncImage(Gtk.Image):
    __gsignals__ = {
        'image-loaded': (GObject.SignalFlags.RUN_LAST, None, ()),
        'image-failed': (GObject.SignalFlags.RUN_LAST, None, ())
    }

    def __init__(self, icon_string=None, width=DETAILS_ICON_SIZE, height=DETAILS_ICON_SIZE, cache=False):
        super(AsyncImage, self).__init__()
        self.icon_string = icon_string
        self.req_width = width
        self.req_height = height

        self.path = None
        self.cancellable = None
        self.loader = None
        self.width = 1
        self.height = 1
        self.cached = cache

        self.connect("destroy", self.on_destroyed)

        if icon_string:
            self.set_icon_string(icon_string, width, height)

    def on_destroyed(self, widget, data=None):
        if self.cancellable:
            self.cancellable.cancel()

    def set_icon_string(self, icon_string, width=DETAILS_ICON_SIZE, height=DETAILS_ICON_SIZE):
        theme = Gtk.IconTheme.get_default()

        self.original_width = width
        self.original_height = height

        # This keeps the icon's space occupied until loaded.
        self.set_size_request(width, height)

        if width != -1:
            self.width = width * self.get_scale_factor()
        else:
            self.width = width

        if height != -1:
            self.height = height * self.get_scale_factor()
        else:
            self.height = height

        self.cancellable = None
        file = None

        if os.path.isabs(icon_string):
            self.path = icon_string
            file = Gio.File.new_for_path(self.path)
        elif icon_string.startswith("http"):
            self.path = icon_string
            file = Gio.File.new_for_uri(self.path)
        elif theme.has_icon(icon_string):
            self.width = width
            self.height = height
            self.set_size_request(width, height)
            self.set_from_icon_name(icon_string, Gtk.IconSize.DIALOG)
            self.set_pixel_size(self.height)
            self.emit("image-loaded")
            return

        if file:
            self.cancellable = Gio.Cancellable()
            threadpool.submit(self._fetch_url_thread, file)
        else:
            self.set_icon_string(FALLBACK_PACKAGE_ICON_PATH, self.original_width, self.original_height)

    def _fetch_url_thread(self, file):
        data = None
        if file.get_uri().startswith("http"):
            try:
                r = requests.get(file.get_uri(), stream=True, timeout=10)

                if self.cancellable.is_cancelled():
                    return

                bdata = b''
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        bdata += chunk

                data = bdata
            except Exception as e:
                print("load image failed")
                GLib.idle_add(self.emit_image_failed, str(e))
                return
        else:
            try:
                success, contents, etag = file.load_contents(self.cancellable)
                data = bytes(contents)
            except GLib.Error as e:
                if e.code != Gio.IOErrorEnum.CANCELLED:
                    GLib.idle_add(self.emit_image_failed, e.message)
                return

        stream = Gio.MemoryInputStream.new_from_data(data, None)

        if self.cancellable.is_cancelled():
            return

        if stream:
            GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(stream,
                                                            self.width,
                                                            self.height,
                                                            True,
                                                            self.cancellable,
                                                            self.on_pixbuf_created)
        else:
            GLib.idle_add(self.emit_image_failed)

    def emit_image_failed(self, message=None):
        print("AsyncIcon could not read icon file contents for loading (%s): %s" % (self.path, message))

        self.cancellable.cancel()
        self.set_icon_string(FALLBACK_PACKAGE_ICON_PATH, self.original_width, self.original_height)
        self.emit("image-failed")

    def on_pixbuf_created(self, stream, result, data=None):
        if self.cancellable.is_cancelled():
            stream.close()
            return

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_finish(result)

            if pixbuf:
                scale = self.get_scale_factor()
                self.width = pixbuf.get_width() / scale
                self.height = pixbuf.get_height() / scale
                surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf,
                                                               scale,
                                                               self.get_window())
                if self.cached:
                    icon_surface_cache[key(self.icon_string, self.req_height)] = surface

                self.set_from_surface(surface)
        except GLib.Error as e:
            self.emit_image_failed(e.message)
            return

        stream.close()

        # size request is whatever sizes we inputted, but those sizes are 'max' in either direction - the
        # final image may be different because of aspect ratios. We re-assigned self.width/height when we
        # made the pixbuf, so update our own size request to match.
        self.set_size_request(self.width, self.height)
        self.emit("image-loaded")

class ScreenshotDownloader():
    def __init__(self, application, pkginfo, scale):
        self.application = application
        self.pkginfo = pkginfo
        self.settings = Gio.Settings(schema_id="com.linuxmint.install")
        self.scale_factor = scale
        threadpool.submit(self._download_screenshots_thread)

    def prefix_media_base_url(self, url):
        if (not url.startswith("http")) and self.pkginfo.remote == "flathub":
            return FLATHUB_MEDIA_BASE_URL + url
        return url

    def _download_screenshots_thread(self):
        num_screenshots = 0
        self.application.screenshots = []
        # Add main screenshot

        if self.pkginfo.pkg_hash.startswith("f"):
            try:
                # Add additional screenshots from appstream info.
                if len(self.application.installer.get_screenshots(self.pkginfo)) > 0:
                    for screenshot in self.pkginfo.screenshots:
                        image = screenshot.get_image(624, 351, self.scale_factor)
                        source = screenshot.get_source_image()

                        url = self.prefix_media_base_url(image.url)

                        if requests.head(url, timeout=5).status_code >= 400 and source is not None:
                            url = self.prefix_media_base_url(source.url)
                            if requests.head(url, timeout=5).status_code >= 400:
                                continue

                        num_screenshots += 1

                        local_name = os.path.join(SCREENSHOT_DIR, "%s_%s.png" % (self.pkginfo.name, num_screenshots))
                        if source is not None:
                            source_url = self.prefix_media_base_url(source.url)
                            self.save_to_file(url, source_url, local_name)
                            self.add_screenshot(self.pkginfo, local_name, num_screenshots)
            except Exception as e:
                print(e)

            if num_screenshots == 0:
                self.add_screenshot(self.pkginfo, None, 0)

            return

        """
        Community screenshots are ~95% from 2014 and severly outdated!
        https://community.linuxmint.com/img/screenshots/

        So add screenshots from Debshots.
        Documentation: https://screenshots.debian.net/about
        """

        DEBSHOTS_HOST = "https://screenshots.debian.net"
        debshots_api = f"{DEBSHOTS_HOST}/json/package/{self.pkginfo.name}"

        response = requests.get(debshots_api)
        if response.status_code == 200:
            data = response.json()
            for image in data.get("screenshots", []):
                if num_screenshots >= 8:
                    break

                num_screenshots += 1

                # image in "thumb_image_url" is too small
                thumb = image.get("screenshot_image_url")
                local_name = os.path.join(SCREENSHOT_DIR, f"{self.pkginfo.name}_{num_screenshots}.png")
                self.save_to_file(thumb, None, local_name)

                self.add_screenshot(self.pkginfo, local_name, num_screenshots)

        if num_screenshots == 0:
            self.add_screenshot(self.pkginfo, None, 0)

    def save_to_file(self, url, source_url, path):
        r = requests.get(url, stream=True, timeout=10)

        with open(path, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=128):
                fd.write(chunk)

        if source_url is None:
            source_url = path

        file = Gio.File.new_for_path(path)
        info = Gio.FileInfo.new()
        info.set_attribute_string("metadata::mintinstall-screenshot-source-url", source_url)
        try:
            file.set_attributes_from_info(info, Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error as e:
            logging.warning("Unable to store screenshot source url to metadata '%s': %s" % (source_url, e.message))

    def add_screenshot(self, pkginfo, name, num):
        GLib.idle_add(self.add_ss_idle, pkginfo, name, num)

    def add_ss_idle(self, pkginfo, name, num):
        self.application.add_screenshot(pkginfo, name, num)
