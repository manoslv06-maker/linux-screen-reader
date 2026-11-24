"""appModule do Firefox (Gecko via AT-SPI2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nvda_linux.appModules.appModuleHandler import AppModule as BaseAppModule
from nvda_linux.NVDAObjects.controlTypes import State

if TYPE_CHECKING:
    from collections.abc import Callable

    from nvda_linux.NVDAObjects.base import LinuxNVDAObject


class AppModule(BaseAppModule):
    """Firefox expõe ``DOCUMENT_WEB`` para o conteúdo e usa a interface de UI
    (barra de endereço, abas) como objetos comuns.

    * Durante o carregamento o documento muda de nome várias vezes e fica
      ``BUSY``; essas mudanças de nome não são faladas.
    * Documentos internos do PDF.js (``pdf.js``) usam o Browse Mode normalmente.
    """

    def should_use_browse_mode(self, doc: LinuxNVDAObject) -> bool:
        return doc.is_web_document

    def event_nameChange(
        self, obj: LinuxNVDAObject, next_handler: Callable[[], None]
    ) -> None:
        if obj.is_web_document and State.BUSY in obj.states:
            return
        next_handler()
