"""appModule do GNOME Terminal (VTE).

O VTE expõe o terminal com papel ``TERMINAL`` e emite ``text-changed`` para a
saída. Este módulo usa o comportamento :class:`Terminal` e filtra
redesenhos repetidos (o VTE apaga e reinsere a linha do prompt).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nvda_linux.appModules.appModuleHandler import AppModule as BaseAppModule
from nvda_linux.NVDAObjects.behaviors import Terminal
from nvda_linux.NVDAObjects.controlTypes import Role

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

_REPEAT_WINDOW_S = 0.3


class GnomeTerminal(Terminal):
    """Terminal do VTE: ignora saída idêntica repetida em sequência."""

    _last_output: str = ""
    _last_output_at: float = 0.0

    def event_textChange(self, inserted: str, deleted: str) -> None:
        now = time.monotonic()
        if (
            len(inserted) > 1
            and inserted == self._last_output
            and now - self._last_output_at < _REPEAT_WINDOW_S
        ):
            return
        if len(inserted) > 1:
            self._last_output = inserted
            self._last_output_at = now
        super().event_textChange(inserted, deleted)


class AppModule(BaseAppModule):
    def should_use_browse_mode(self, doc: LinuxNVDAObject) -> bool:
        return False

    def choose_overlay_classes(self, obj: LinuxNVDAObject, cls_list: list[type]) -> None:
        if obj.role == Role.TERMINAL:
            cls_list.insert(0, GnomeTerminal)
