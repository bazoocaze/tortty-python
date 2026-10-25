"""Importação única de Gtk/Gdk/GLib/cairo.

`gi.require_version` tem que vir ANTES do `from gi.repository import ...`;
centralizar aqui evita que um módulo esqueça e trave a versão errada, e deixa
o resto do pacote importar `from .gui import Gtk, Gdk, GLib, cairo`.
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkX11", "3.0")

from gi.repository import Gtk, Gdk, GLib

try:
    from gi.repository import GdkX11
except (ImportError, ValueError):   # X11 é opcional (Wayland puro)
    GdkX11 = None

import cairo
