# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Diálogo de configurações GTK 4 (Voz, Teclado, Modo de navegação, Braille)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nvda_linux.gui import _gtk
from nvda_linux.gui.settingsModel import CATEGORIES, SettingSpec, apply_values, load_values
from nvda_linux.scripts import ui

log = logging.getLogger(__name__)


class SettingsDialog:
    """Uma aba por categoria; OK grava e salva, Aplicar só grava, Cancelar descarta."""

    def __init__(self) -> None:
        Gtk = _gtk.Gtk
        self.values = load_values()
        self._readers: dict[str, Callable[[], Any]] = {}
        self.window: Any = Gtk.Window(title="Configurações - NVDA")
        self.window.set_default_size(560, 480)
        self.window.set_modal(True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(12)
        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        for category in CATEGORIES:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for side in ("top", "bottom", "start", "end"):
                getattr(page, f"set_margin_{side}")(8)
            for spec in category.settings:
                page.append(self._make_row(spec))
            notebook.append_page(page, Gtk.Label(label=category.name))
        outer.append(notebook)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        for label, handler in (("_OK", self._on_ok), ("_Cancelar", self._on_cancel),
                               ("_Aplicar", self._on_apply)):
            button = Gtk.Button.new_with_mnemonic(label)
            button.connect("clicked", handler)
            buttons.append(button)
        outer.append(buttons)
        self.window.set_child(outer)
        _gtk.close_on_escape(self.window)

    def _make_row(self, spec: SettingSpec) -> Any:
        Gtk = _gtk.Gtk
        value = self.values.get(spec.key, spec.default)
        if spec.kind == "bool":
            check = Gtk.CheckButton.new_with_mnemonic(spec.label)
            check.set_active(bool(value))
            self._readers[spec.key] = check.get_active
            return check
        if spec.kind == "int":
            spin = Gtk.SpinButton.new_with_range(spec.minimum, spec.maximum, 1)
            spin.set_value(float(value))
            self._readers[spec.key] = _int_reader(spin)
            return _gtk.labeled(spec.label, spin)
        if spec.kind == "choice":
            labels = [label for _v, label in spec.choices]
            values = [v for v, _label in spec.choices]
            drop = Gtk.DropDown.new_from_strings(labels)
            drop.set_selected(values.index(value) if value in values else 0)
            self._readers[spec.key] = _choice_reader(drop, values)
            return _gtk.labeled(spec.label, drop)
        entry = Gtk.Entry()
        entry.set_text(str(value))
        self._readers[spec.key] = entry.get_text
        return _gtk.labeled(spec.label, entry)

    def collect(self) -> dict[str, Any]:
        return {key: read() for key, read in self._readers.items()}

    def _apply(self, save: bool) -> None:
        failed = apply_values(self.collect(), save=save)
        if failed:
            ui.message("Algumas configurações não foram gravadas")

    def _on_ok(self, *_args: Any) -> None:
        self._apply(save=True)
        self.window.close()

    def _on_apply(self, *_args: Any) -> None:
        self._apply(save=False)

    def _on_cancel(self, *_args: Any) -> None:
        self.window.close()

    def present(self) -> None:
        self.window.present()


def _int_reader(spin: Any) -> Callable[[], Any]:
    def read() -> Any:
        return int(spin.get_value())

    return read


def _choice_reader(drop: Any, values: list[str]) -> Callable[[], Any]:
    def read() -> Any:
        index = int(drop.get_selected())
        return values[index] if 0 <= index < len(values) else values[0]

    return read


def show() -> bool:
    if not _gtk.available():
        return False
    try:
        SettingsDialog().present()
    except Exception:
        log.exception("Falha ao abrir as configurações")
        return False
    return True
