"""Layouts de teclado Desktop e Laptop do NVDA.

No NVDA, o layout escolhe *quais gestos* ativam os comandos de revisão e de
navegação por objetos: o Desktop usa o teclado numérico; o Laptop usa
combinações com NVDA nas setas e letras. Os scripts são da SEMÂNTICA; a
PLATAFORMA:

1. informa o layout em ``gesture.extra["layout"]`` e gera os identificadores
   de busca ``kb(laptop):...`` / ``kb(desktop):...`` antes de ``kb:...``;
2. no layout Laptop, preenche ``gesture.extra["desktop_equivalent"]`` com o
   gesto Desktop correspondente (tabela abaixo, do Guia do Usuário do NVDA),
   para que um script ligado só ao gesto Desktop possa ser encontrado.

A tabela cobre os comandos centrais; pode ser estendida pelo ``gestures.ini``.
"""

from __future__ import annotations

from typing import Final

from nvda_linux.contracts import KeyboardLayout

# comando -> (gesto desktop, gesto laptop), já normalizados.
CORE_COMMANDS: Final[dict[str, tuple[str, str]]] = {
    # Navegação por objetos
    "navigatorObject_current": ("kb:nvda+numpad5", "kb:nvda+shift+o"),
    "navigatorObject_parent": ("kb:nvda+numpad8", "kb:nvda+shift+uparrow"),
    "navigatorObject_previous": ("kb:nvda+numpad4", "kb:nvda+shift+leftarrow"),
    "navigatorObject_next": ("kb:nvda+numpad6", "kb:nvda+shift+rightarrow"),
    "navigatorObject_firstChild": ("kb:nvda+numpad2", "kb:nvda+shift+downarrow"),
    "navigatorObject_toFocus": ("kb:nvda+numpadminus", "kb:nvda+backspace"),
    "review_activate": ("kb:nvda+numpadenter", "kb:nvda+enter"),
    # Cursor de revisão
    "review_top": ("kb:shift+numpad7", "kb:control+nvda+home"),
    "review_previousLine": ("kb:numpad7", "kb:nvda+uparrow"),
    "review_currentLine": ("kb:numpad8", "kb:nvda+shift+."),
    "review_nextLine": ("kb:numpad9", "kb:nvda+downarrow"),
    "review_bottom": ("kb:shift+numpad9", "kb:control+nvda+end"),
    "review_previousWord": ("kb:numpad4", "kb:control+nvda+leftarrow"),
    "review_currentWord": ("kb:numpad5", "kb:control+nvda+."),
    "review_nextWord": ("kb:numpad6", "kb:control+nvda+rightarrow"),
    "review_previousCharacter": ("kb:numpad1", "kb:nvda+leftarrow"),
    "review_currentCharacter": ("kb:numpad2", "kb:nvda+."),
    "review_nextCharacter": ("kb:numpad3", "kb:nvda+rightarrow"),
    "review_startOfLine": ("kb:shift+numpad1", "kb:nvda+home"),
    "review_endOfLine": ("kb:shift+numpad3", "kb:nvda+end"),
    # Leitura do sistema
    "sayAll": ("kb:nvda+downarrow", "kb:nvda+a"),
    "reportCurrentLine": ("kb:nvda+uparrow", "kb:nvda+l"),
    "reportCurrentSelection": ("kb:nvda+shift+uparrow", "kb:nvda+shift+s"),
    "reportStatusLine": ("kb:nvda+end", "kb:nvda+shift+end"),
    # Mouse
    "leftMouseClick": ("kb:numpaddivide", "kb:nvda+["),
    "rightMouseClick": ("kb:numpadmultiply", "kb:nvda+]"),
    "toggleLeftMouseButton": ("kb:shift+numpaddivide", "kb:control+nvda+["),
    "toggleRightMouseButton": ("kb:shift+numpadmultiply", "kb:control+nvda+]"),
    "moveMouseToNavigatorObject": ("kb:nvda+numpaddivide", "kb:nvda+shift+m"),
    "moveNavigatorObjectToMouse": ("kb:nvda+numpadmultiply", "kb:nvda+shift+n"),
}

_LAPTOP_TO_DESKTOP: Final[dict[str, str]] = {lap: desk for desk, lap in CORE_COMMANDS.values()}
_DESKTOP_TO_LAPTOP: Final[dict[str, str]] = {desk: lap for desk, lap in CORE_COMMANDS.values()}


def parse_layout(value: object) -> KeyboardLayout:
    """``"laptop"`` -> ``KeyboardLayout.LAPTOP``; qualquer outra coisa -> DESKTOP."""
    if isinstance(value, KeyboardLayout):
        return value
    return (
        KeyboardLayout.LAPTOP if str(value).strip().lower() == "laptop" else KeyboardLayout.DESKTOP
    )


def desktop_equivalent(identifier: str) -> str | None:
    """Gesto Desktop que corresponde a ``identifier`` do layout Laptop."""
    return _LAPTOP_TO_DESKTOP.get(identifier)


def laptop_equivalent(identifier: str) -> str | None:
    """Gesto Laptop que corresponde a ``identifier`` do layout Desktop."""
    return _DESKTOP_TO_LAPTOP.get(identifier)


def gesture_for(command: str, layout: KeyboardLayout) -> str | None:
    """Gesto do comando ``command`` no layout dado (para a ajuda/documentação)."""
    pair = CORE_COMMANDS.get(command)
    if pair is None:
        return None
    return pair[1] if layout is KeyboardLayout.LAPTOP else pair[0]
