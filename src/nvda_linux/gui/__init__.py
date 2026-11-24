"""Interface gráfica GTK 4 do nvda-linux (import protegido).

Todas as funções devolvem ``True`` se a janela abriu e ``False`` se o GTK
não está disponível (o chamador então fala um aviso). Nada aqui levanta
exceção para quem chama.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from nvda_linux.gui import _gtk

if TYPE_CHECKING:
    from nvda_linux.treeInterceptors.elementsList import ElementsListModel

log = logging.getLogger(__name__)


def available() -> bool:
    return _gtk.available()


def show_nvda_menu() -> bool:
    from nvda_linux.gui import nvdaMenu

    return nvdaMenu.show()


def show_settings() -> bool:
    from nvda_linux.gui import settingsDialog

    return settingsDialog.show()


def show_speech_viewer() -> bool:
    from nvda_linux.gui import speechViewer

    return speechViewer.show()


def show_elements_list(model: ElementsListModel) -> bool:
    try:
        from nvda_linux.gui import elementsListDialog
    except Exception:
        log.exception("Lista de elementos indisponível")
        return False
    return elementsListDialog.show(model)


def show_addons_manager() -> bool:
    from nvda_linux.gui import addonsManager
    from nvda_linux.scripts import runtime

    rt = runtime.current()
    return addonsManager.show(rt.addons if rt is not None else None)


def confirm_exit(on_confirm: Callable[[], None]) -> bool:
    from nvda_linux.gui import nvdaMenu

    return nvdaMenu.confirm_exit(on_confirm)


def ask_exit() -> bool:
    from nvda_linux.scripts.globalCommands import request_quit

    if confirm_exit(request_quit):
        return True
    request_quit()
    return True


def close_all() -> None:
    """Fecha janelas abertas (``bootstrap.stop``)."""
    try:
        from nvda_linux.gui import speechViewer

        speechViewer.close()
    except Exception:  # noqa: BLE001
        log.debug("Falha ao fechar janelas da GUI")
