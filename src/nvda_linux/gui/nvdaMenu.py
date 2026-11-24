# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Menu do NVDA (NVDA+N) e confirmação de saída, em GTK 4.

O menu é uma pequena janela com uma lista navegável por setas (Enter ativa,
Esc fecha), mais simples de ler que um ``PopoverMenu`` sem ícone de bandeja.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from nvda_linux.gui import _gtk

log = logging.getLogger(__name__)

MenuAction = Callable[[], object]


def menu_entries() -> list[tuple[str, MenuAction]]:
    """Itens do menu (testável sem GTK)."""
    from nvda_linux import gui

    return [
        ("Configurações...", gui.show_settings),
        ("Visualizador de Fala", gui.show_speech_viewer),
        ("Gerenciador de complementos...", gui.show_addons_manager),
        ("Sair", gui.ask_exit),
    ]


class NvdaMenu:
    def __init__(self) -> None:
        Gtk = _gtk.Gtk
        self.entries = menu_entries()
        self.window: Any = Gtk.Window(title="NVDA")
        self.window.set_default_size(300, 220)
        self.listbox: Any = Gtk.ListBox()
        _gtk.set_accessible_label(self.listbox, "Menu do NVDA")
        for label, _action in self.entries:
            item = Gtk.Label(label=label)
            item.set_xalign(0.0)
            self.listbox.append(item)
        self.listbox.connect("row-activated", self._on_activated)
        self.window.set_child(self.listbox)
        _gtk.close_on_escape(self.window)

    def _on_activated(self, _listbox: Any, row: Any) -> None:
        index = row.get_index()
        self.window.close()
        if 0 <= index < len(self.entries):
            try:
                self.entries[index][1]()
            except Exception:
                log.exception("Item de menu falhou")

    def present(self) -> None:
        self.window.present()
        first = self.listbox.get_row_at_index(0)
        if first is not None:
            first.grab_focus()


def show() -> bool:
    if not _gtk.available():
        return False
    try:
        NvdaMenu().present()
    except Exception:
        log.exception("Falha ao abrir o menu do NVDA")
        return False
    return True


def confirm_exit(on_confirm: Callable[[], None]) -> bool:
    """Pergunta "Sair do NVDA?". Devolve ``False`` se não há GUI."""
    if not _gtk.available():
        return False
    Gtk = _gtk.Gtk
    try:
        window = Gtk.Window(title="Sair do NVDA")
        window.set_modal(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{side}")(12)
        box.append(Gtk.Label(label="Tem certeza de que deseja sair do NVDA?"))
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        yes = Gtk.Button.new_with_mnemonic("_Sim")
        no = Gtk.Button.new_with_mnemonic("_Não")

        def on_yes(*_args: Any) -> None:
            window.close()
            on_confirm()

        yes.connect("clicked", on_yes)
        no.connect("clicked", lambda *_a: window.close())
        buttons.append(yes)
        buttons.append(no)
        box.append(buttons)
        window.set_child(box)
        _gtk.close_on_escape(window)
        window.present()
        yes.grab_focus()
    except Exception:
        log.exception("Falha ao abrir a confirmação de saída")
        return False
    return True
