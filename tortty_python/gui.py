"""The single import of Gtk/Gdk/GLib/Pango/cairo.

`gi.require_version` has to come BEFORE `from gi.repository import ...`;
centralising it here keeps a module from forgetting and pinning the wrong
version, and lets the rest of the package import `from .gui import Gtk, Gdk,
GLib, Pango, PangoCairo, cairo`.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

try:
    from gi.repository import GdkX11
except (ImportError, ValueError):  # X11 é opcional (Wayland puro)
    GdkX11 = None

import cairo
