"""appModule do Chromium, Google Chrome, Brave e Edge (Blink via AT-SPI2).

O Chromium só publica a árvore web completa quando
``org.a11y.Status.ScreenReaderEnabled`` está ligado (o bootstrap liga) ou
quando é iniciado com ``--force-renderer-accessibility``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nvda_linux.appModules.appModuleHandler import AppModule as BaseAppModule
from nvda_linux.NVDAObjects.controlTypes import Role

if TYPE_CHECKING:
    from collections.abc import Callable

    from nvda_linux.NVDAObjects.base import LinuxNVDAObject


class AppModule(BaseAppModule):
    """Ajustes para o Chromium.

    O Chromium costuma emitir foco na janela (``FRAME``) imediatamente antes
    do foco no documento; anunciar os dois duplicaria o título. O foco no
    quadro sem nome é ignorado.
    """

    def should_use_browse_mode(self, doc: LinuxNVDAObject) -> bool:
        return doc.is_web_document

    def event_gainFocus(
        self, obj: LinuxNVDAObject, next_handler: Callable[[], None]
    ) -> None:
        if obj.role == Role.FRAME and not obj.name:
            return
        next_handler()
