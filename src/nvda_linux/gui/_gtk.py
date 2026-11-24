"""Importação protegida do GTK 4 (PyGObject).

Sem GTK (ou sem display), :data:`Gtk` fica ``None`` e as funções do pacote
``gui`` devolvem ``False``, deixando os comandos falarem um aviso.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

Gtk: Any = None
Gdk: Any = None
GLib: Any = None
Gio: Any = None
IMPORT_ERROR: str | None = None
_initialized = False


def _load() -> None:
    global Gtk, Gdk, GLib, Gio, IMPORT_ERROR
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk as _gdk
        from gi.repository import Gio as _gio
        from gi.repository import GLib as _glib
        from gi.repository import Gtk as _gtk
    except Exception as exc:  # noqa: BLE001
        IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        log.info("GTK 4 indisponível: %s", IMPORT_ERROR)
        return
    Gtk, Gdk, GLib, Gio = _gtk, _gdk, _glib, _gio


_load()


def available() -> bool:
    """GTK carregado e inicializado com um display."""
    global _initialized
    if Gtk is None:
        return False
    if _initialized:
        return True
    try:
        ok = Gtk.init_check() if hasattr(Gtk, "init_check") else True
    except Exception as exc:  # noqa: BLE001
        log.info("Gtk.init_check falhou: %s", exc)
        return False
    _initialized = bool(ok if not isinstance(ok, tuple) else ok[0])
    return _initialized


def close_on_escape(window: Any) -> None:
    """Fecha a janela com Esc (como os diálogos do NVDA)."""
    if Gtk is None or Gdk is None:
        return
    controller = Gtk.EventControllerKey()

    def on_key(_ctrl: Any, keyval: int, _keycode: int, _state: Any) -> bool:
        if keyval == Gdk.KEY_Escape:
            window.close()
            return True
        return False

    controller.connect("key-pressed", on_key)
    window.add_controller(controller)


def labeled(label_text: str, widget: Any) -> Any:
    """Linha horizontal ``rótulo + widget`` com rótulo mnemônico (acessível)."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    label = Gtk.Label.new_with_mnemonic(label_text)
    label.set_mnemonic_widget(widget)
    label.set_xalign(0.0)
    label.set_hexpand(True)
    box.append(label)
    box.append(widget)
    return box


def set_accessible_label(widget: Any, text: str) -> None:
    try:
        widget.update_property([Gtk.AccessibleProperty.LABEL], [text])
    except Exception:  # noqa: BLE001
        log.debug("update_property indisponível")
