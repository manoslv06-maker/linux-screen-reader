# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Gerenciador de complementos (add-ons) em GTK 4."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nvda_linux.gui import _gtk
from nvda_linux.scripts import ui

if TYPE_CHECKING:
    from nvda_linux.addons.addonHandler import Addon, AddonManager

log = logging.getLogger(__name__)


def describe(addon: Addon) -> str:
    state = "ativado" if addon.enabled else "desativado"
    if addon.errors:
        state += ", com erros"
    manifest = addon.manifest
    return f"{manifest.summary or addon.name}, {manifest.version}, {manifest.author}, {state}"


class AddonsManagerDialog:
    """Lista de add-ons com Instalar, Ativar/Desativar, Remover e Fechar."""

    def __init__(self, manager: AddonManager) -> None:
        Gtk = _gtk.Gtk
        self.manager = manager
        self.addons: list[Addon] = []
        self.window: Any = Gtk.Window(title="Gerenciador de complementos - NVDA")
        self.window.set_default_size(560, 400)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("top", "bottom", "start", "end"):
            getattr(outer, f"set_margin_{side}")(12)
        self.listbox: Any = Gtk.ListBox()
        _gtk.set_accessible_label(self.listbox, "Complementos instalados")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(self.listbox)
        outer.append(scrolled)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        for label, handler in (
            ("_Instalar...", self._on_install),
            ("Ativar/_Desativar", self._on_toggle),
            ("_Remover", self._on_remove),
            ("_Fechar", lambda *_a: self.window.close()),
        ):
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
        self.addons = self.manager.addons
        for addon in self.addons:
            label = Gtk.Label(label=describe(addon))
            label.set_xalign(0.0)
            self.listbox.append(label)

    def _selected(self) -> Addon | None:
        row = self.listbox.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return self.addons[index] if 0 <= index < len(self.addons) else None

    def _on_toggle(self, *_args: Any) -> None:
        addon = self._selected()
        if addon is None:
            return
        if addon.enabled:
            self.manager.disable(addon.name)
            ui.message(f"{addon.name} desativado")
        else:
            self.manager.enable(addon.name)
            ui.message(f"{addon.name} ativado")
        self.refresh()

    def _on_remove(self, *_args: Any) -> None:
        addon = self._selected()
        if addon is None:
            return
        if self.manager.remove(addon.name):
            ui.message(f"{addon.name} removido")
        self.refresh()

    def _on_install(self, *_args: Any) -> None:
        Gtk = _gtk.Gtk
        dialog_cls = getattr(Gtk, "FileDialog", None)
        if dialog_cls is None:
            ui.message("Seletor de arquivos indisponível nesta versão do GTK")
            return
        dialog = dialog_cls(title="Instalar complemento")

        def done(source: Any, result: Any) -> None:
            try:
                gfile = source.open_finish(result)
            except Exception:  # noqa: BLE001
                return
            path = gfile.get_path() if gfile is not None else None
            if not path:
                return
            try:
                addon = self.manager.install(Path(path))
            except Exception as exc:  # noqa: BLE001
                ui.message(f"Falha ao instalar: {exc}")
                return
            ui.message(f"{addon.name} instalado")
            self.refresh()

        dialog.open(self.window, None, done)

    def present(self) -> None:
        self.window.present()


def show(manager: AddonManager | None) -> bool:
    if manager is None or not _gtk.available():
        return False
    try:
        AddonsManagerDialog(manager).present()
    except Exception:
        log.exception("Falha ao abrir o gerenciador de complementos")
        return False
    return True
