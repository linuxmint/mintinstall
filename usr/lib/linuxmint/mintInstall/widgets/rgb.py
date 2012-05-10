# Copyright (C) 2009 Matthew McGowan
#
# Authors:
#   Matthew McGowan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from gi.repository import Gdk
import colorsys

Color = Gdk.Color

def parse_colour_scheme(colour_scheme_str):
    scheme_dict = {}
    for ln in colour_scheme_str.splitlines():
        k, v = ln.split(':')
        scheme_dict[k.strip()] = gtk.gdk.color_parse(v.strip())
    return scheme_dict


def shade(color, k):
    # as seen in Murrine's cairo-support.c
    r = color.red/65535
    g = color.green/65535
    b = color.blue/65535

    if (k == 1.0):
        return color

    h,l,s = colorsys.rgb_to_hls(r,g,b)

    l *= k
    if (l > 1.0):
        l = 1.0
    elif (l < 0.0):
        l = 0.0

    s *= k
    if (s > 1.0):
        s = 1.0
    elif (s < 0.0):
        s = 0.0

    r, g, b = colorsys.hls_to_rgb(h,l,s)

    return Color(int(r*65535), int(g*65535), int(b*65535))

def mix_color(color1, color2, mix_factor):
    # as seen in Murrine's cairo-support.c
    r = color1.red/65535*(1-mix_factor)+color2.red/65535*mix_factor
    g = color1.green/65535*(1-mix_factor)+color2.green/65535*mix_factor
    b = color1.blue/65535*(1-mix_factor)+color2.blue/65535*mix_factor
    return Color(int(r*65535), int(g*65535), int(b*65535))

def to_float(color):
    return color.red/65535, color.green/65535, color.blue/65535
