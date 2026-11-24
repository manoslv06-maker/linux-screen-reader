# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Acesso tolerante a falhas à configuração (``services.config()``).

Os nomes das chaves seguem o ``core/config.py`` da PLATAFORMA (que espelha o
``nvda.ini``). Chaves exclusivas da SEMÂNTICA têm o padrão em
:data:`SEMANTIC_DEFAULTS`, usado quando a PLATAFORMA não conhece a chave.
"""

from __future__ import annotations

import logging
from typing import Any

from nvda_linux import services

log = logging.getLogger(__name__)

#: Padrões das chaves lidas pela SEMÂNTICA (os da PLATAFORMA têm precedência).
SEMANTIC_DEFAULTS: dict[str, Any] = {
    "keyboard.keyboardLayout": "desktop",
    "keyboard.speakTypedCharacters": True,
    "keyboard.speakTypedWords": False,
    "browseMode.autoFocusMode": True,
    "browseMode.maxLineLength": 100,
    "browseMode.linesPerPage": 25,
    "browseMode.autoPassThroughOnFocusChange": True,
    "browseMode.autoPassThroughOnCaretMove": False,
    "browseMode.passThroughAudioIndication": True,
    "browseMode.trapNonCommandGestures": True,
    "browseMode.autoSayAllOnPageLoad": True,
    "browseMode.autoFocusFocusableElements": False,
    "browseMode.enableOnPageLoad": True,
    "browseMode.maxNodes": 20000,
    "browseMode.updateDelayMs": 150,
    "presentation.reportKeyboardShortcuts": True,
    "presentation.reportObjectPositionInformation": True,
    "presentation.reportObjectDescriptions": True,
    "presentation.reportDynamicContentChanges": True,
    "reviewCursor.followFocus": True,
    "reviewCursor.followCaret": True,
    "reviewCursor.simpleReviewMode": True,
    "general.askToExit": True,
    "addons.nvdaCompatAliases": True,
    "braille.tetherTo": "focus",
}


def get(key: str, default: Any = None) -> Any:
    """Lê ``key``; usa :data:`SEMANTIC_DEFAULTS` e depois ``default``."""
    fallback = SEMANTIC_DEFAULTS.get(key, default)
    try:
        value = services.config().get(key, fallback)
    except Exception:  # noqa: BLE001
        return fallback
    return fallback if value is None else value


def get_bool(key: str, default: bool = False) -> bool:
    return bool(get(key, default))


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get(key, default))
    except (TypeError, ValueError):
        return default


def set_value(key: str, value: Any) -> bool:
    """Grava ``key``; devolve ``False`` (com log) se a PLATAFORMA recusar."""
    try:
        services.config().set(key, value)
    except Exception as exc:  # noqa: BLE001
        log.warning("Não foi possível gravar %s=%r: %s", key, value, exc)
        return False
    return True


def save() -> bool:
    try:
        services.config().save()
    except Exception as exc:  # noqa: BLE001
        log.warning("Não foi possível salvar a configuração: %s", exc)
        return False
    return True


def activate_profile(name: str | None) -> None:
    try:
        services.config().activate_profile(name)
    except Exception as exc:  # noqa: BLE001
        log.debug("Falha ao ativar perfil %r: %s", name, exc)
