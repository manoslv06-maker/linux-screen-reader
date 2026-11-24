# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Diálogo da Lista de Elementos (NVDA+F7) em GTK 4."""

from __future__ import annotations

import logging
from typing import Any

from nvda_linux.gui import _gtk
from nvda_linux.treeInterceptors.elementsList import (
    ELEMENT_TYPES,
    ElementItem,
    ElementsListModel,
)

log = logging.getLogger(__name__)


class ElementsListDialog:
    """Tipo (botões de opção), filtro, lista e botões Ativar / Mover para."""

    def __init__(self, model: ElementsListModel) -> None:
        Gtk = _gtk.Gtk
        self.model = model
        self.kind = ELEMENT_TYPES[0][0]
        self.items: list[ElementItem] = []
        self.window: Any = Gtk.Window(title=f"Lista de elementos - {model.title}")
        self.window.set_default_size(520, 460)
        self.window.set_modal(True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(12)

        types_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        group: Any = None
        for kind, label in ELEMENT_TYPES:
            radio = Gtk.CheckButton.new_with_mnemonic(f"_{label}")
            if group is None:
                group = radio
                radio.set_active(True)
            else:
                radio.set_group(group)
            radio.connect("toggled", self._on_type, kind)
            types_box.append(radio)
        outer.append(types_box)

        self.listbox: Any = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_row_activated)
        _gtk.set_accessible_label(self.listbox, "Elementos")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(self.listbox)
        outer.append(scrolled)

        self.filter_entry: Any = Gtk.Entry()
        self.filter_entry.connect("changed", lambda *_a: self.refresh())
        outer.append(_gtk.labeled("_Filtrar por:", self.filter_entry))

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        for label, handler in (("_Ativar", self._on_activate), ("_Mover para", self._on_move),
                               ("_Fechar", lambda *_a: self.window.close())):
            button = Gtk.Button.new_with_mnemonic(label)
            button.connect("clicked", handler)
            buttons.append(button)
        outer.append(buttons)
        self.window.set_child(outer)
        _gtk.close_on_escape(self.window)
        self.refresh()

    def refresh(self) -> None:
        Gtk = _gtk.Gtk
        child = self.listbox.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.listbox.remove(child)
            child = following
        self.items = self.model.items(self.kind, self.filter_entry.get_text())
        for item in self.items:
            label = Gtk.Label(label=("  " * item.depth) + item.label)
            label.set_xalign(0.0)
            self.listbox.append(label)
        first = self.listbox.get_row_at_index(0)
        if first is not None:
            self.listbox.select_row(first)

    def _selected(self) -> ElementItem | None:
        row = self.listbox.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return self.items[index] if 0 <= index < len(self.items) else None

    def _on_type(self, button: Any, kind: str) -> None:
        if button.get_active():
            self.kind = kind
            self.refresh()

    def _on_row_activated(self, *_args: Any) -> None:
        self._on_activate()

    def _on_activate(self, *_args: Any) -> None:
        item = self._selected()
        if item is not None:
            self.window.close()
            self.model.activate(item)

    def _on_move(self, *_args: Any) -> None:
        item = self._selected()
        if item is not None:
            self.window.close()
            self.model.move_to(item)

    def present(self) -> None:
        self.window.present()


def show(model: ElementsListModel) -> bool:
    if not _gtk.available():
        return False
    try:
        ElementsListDialog(model).present()
    except Exception:
        log.exception("Falha ao abrir a lista de elementos")
        return False
    return True
