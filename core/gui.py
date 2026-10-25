"""Importação única de Gtk/Gdk/GLib/Pango/cairo.

`gi.require_version` tem que vir ANTES do `from gi.repository import ...`;
centralizar aqui evita que um módulo esqueça e trave a versão errada, e deixa
o resto do pacote importar `from .gui import Gtk, Gdk, GLib, Pango, PangoCairo,
cairo`.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

try:
    from gi.repository import GdkX11
except (ImportError, ValueError):   # X11 é opcional (Wayland puro)
    GdkX11 = None

import cairo
