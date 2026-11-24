"""Gerenciador braille (implementa ``contracts.BrailleOutput``).

Equivale ao ``braille.handler`` do NVDA, de forma enxuta:

- **tradução**: com o módulo ``louis`` e ``braille.translationTable``
  definida, o texto é traduzido pelo liblouis (com mapa célula -> caractere);
  sem isso, o texto vai cru e o BRLTTY aplica a tabela de texto dele;
- **janela e rolagem**: o texto é dividido em janelas do tamanho da linha,
  com quebra em palavra (``braille.wordWrap``); a janela segue o cursor;
- **mensagens**: ``show_message`` mostra por ``timeout_ms`` e volta ao texto
  anterior (``braille.messageTimeout = 0`` desliga as mensagens);
- **teclas**: rolagem (fwinlt/fwinrt) é tratada aqui; as demais viram
  ``InputGesture("br(brltty):<comando>")`` e vão ao despachante. Roteamento:
  ``br(brltty):routing`` com ``extra["routing_index"]`` = célula na linha e
  ``extra["text_offset"]`` = posição correspondente no texto mostrado.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nvda_linux.braille.display import BrailleDisplay, BrlapiDisplay, DisplayKey, NullDisplay
from nvda_linux.contracts import ConfigStore, GestureDispatcher, InputGesture
from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger

log = get_logger(__name__)

PAN_BACK = ("fwinlt", "fwinltskip")
PAN_FORWARD = ("fwinrt", "fwinrtskip")


@dataclass(frozen=True, slots=True)
class Translation:
    """Resultado da tradução: células e mapa célula -> índice no texto."""

    cells: str  # texto cru, ou braille Unicode (U+2800..) se ``dots``
    cell_to_text: tuple[int, ...]
    cursor: int | None
    dots: bool


class Translator:
    """liblouis quando configurado; senão, identidade (BRLTTY traduz)."""

    def __init__(self, table: str = "", louis: Any | None = None) -> None:
        self.table = table
        self._louis = louis if louis is not None else (optional_import("louis") if table else None)

    @property
    def uses_louis(self) -> bool:
        return bool(self.table) and self._louis is not None

    def translate(self, text: str, cursor: int | None) -> Translation:
        louis = self._louis
        if not self.uses_louis or louis is None:
            return Translation(text, tuple(range(len(text))), cursor, False)
        mode = getattr(louis, "dotsIO", 4) | getattr(louis, "ucBrl", 64)
        try:
            out, _typeform, in_pos, _out_pos, cur = louis.translate(
                [self.table], text, cursorPos=cursor or 0, mode=mode
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("liblouis falhou com a tabela %s: %s", self.table, exc)
            return Translation(text, tuple(range(len(text))), cursor, False)
        mapping = tuple(int(i) for i in in_pos) if in_pos else tuple(range(len(out)))
        return Translation(out, mapping, cur if cursor is not None else None, True)


def to_dots(cells: str) -> bytes:
    """Braille Unicode (U+2800 + pontos) -> bytes de pontos para ``writeDots``."""
    return bytes((ord(c) - 0x2800) & 0xFF if 0x2800 <= ord(c) <= 0x28FF else 0 for c in cells)


def window_starts(length: int, width: int, text: str = "", word_wrap: bool = True) -> list[int]:
    """Inícios das janelas que cobrem ``length`` células de largura ``width``."""
    if width <= 0 or length <= 0:
        return [0]
    starts = [0]
    pos = 0
    while pos + width < length:
        end = pos + width
        if word_wrap and text:
            space = text.rfind(" ", pos + 1, end + 1)
            if space > pos:
                end = space + 1
        starts.append(end)
        pos = end
    return starts


class BrailleHandler:
    """Implementação de :class:`nvda_linux.contracts.BrailleOutput`."""

    def __init__(
        self,
        display: BrailleDisplay | None = None,
        *,
        config: ConfigStore | None = None,
        dispatcher: Callable[[], GestureDispatcher | None] | None = None,
        translator: Translator | None = None,
    ) -> None:
        self.display = display or NullDisplay()
        self.config = config
        self._dispatcher = dispatcher
        self.translator = translator or Translator(self._cfg("braille.translationTable", ""))
        self._text = ""
        self._cursor: int | None = None
        self._translation = Translation("", (), None, False)
        self._starts: list[int] = [0]
        self._window = 0
        self._message: Translation | None = None
        self._message_handle: asyncio.TimerHandle | None = None
        self.display.on_key = self._on_key

    # ------------------------------------------------------------ contrato
    @property
    def available(self) -> bool:
        return self.display.num_cells > 0

    def show_text(self, text: str, cursor: int | None = None) -> None:
        """Mostra ``text``; a janela acompanha ``cursor`` (índice no texto)."""
        self._text = text
        self._cursor = cursor
        self._translation = self.translator.translate(text, cursor)
        self._starts = window_starts(
            len(self._translation.cells),
            self.display.num_cells,
            "" if self._translation.dots else text,
            bool(self._cfg("braille.wordWrap", True)),
        )
        self._window = self._window_for(self._translation.cursor)
        if self._message is None:
            self._render()

    def show_message(self, text: str, timeout_ms: int = 4000) -> None:
        """Mostra uma mensagem temporária e volta ao texto anterior."""
        seconds = self._cfg("braille.messageTimeout", 4)
        if not self.available or seconds == 0:
            return
        self._message = self.translator.translate(text, None)
        self._render()
        if self._message_handle is not None:
            self._message_handle.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._message_handle = loop.call_later(max(timeout_ms, 0) / 1000.0, self.dismiss_message)

    def dismiss_message(self) -> None:
        self._message = None
        self._message_handle = None
        self._render()

    # ------------------------------------------------------------ rolagem
    def scroll_forward(self) -> bool:
        if self._message is not None:
            self.dismiss_message()
            return True
        if self._window + 1 < len(self._starts):
            self._window += 1
            self._render()
            return True
        return False

    def scroll_back(self) -> bool:
        if self._message is not None:
            self.dismiss_message()
            return True
        if self._window > 0:
            self._window -= 1
            self._render()
            return True
        return False

    @property
    def window_text(self) -> str:
        start, end = self._bounds()
        return self._translation.cells[start:end]

    def _bounds(self) -> tuple[int, int]:
        start = self._starts[min(self._window, len(self._starts) - 1)]
        nxt = self._window + 1
        end = self._starts[nxt] if nxt < len(self._starts) else len(self._translation.cells)
        return start, min(end, start + max(self.display.num_cells, 0))

    def _window_for(self, cursor: int | None) -> int:
        if cursor is None:
            return 0
        for i in range(len(self._starts) - 1, -1, -1):
            if cursor >= self._starts[i]:
                return i
        return 0

    # ------------------------------------------------------------ desenho
    def _render(self) -> None:
        cells = self.display.num_cells
        if cells <= 0:
            return
        if self._message is not None:
            msg = self._message
            window, cursor, dots = msg.cells[:cells], None, msg.dots
        else:
            start, end = self._bounds()
            window = self._translation.cells[start:end]
            cur = self._translation.cursor
            last = self._window + 1 >= len(self._starts)
            visible = cur is not None and (
                start <= cur < end or (last and cur == end and end - start < cells)
            )
            cursor = cur - start if visible and cur is not None else None
            dots = self._translation.dots
        if dots:
            self.display.write_dots(to_dots(window.ljust(cells, "⠀")))
        else:
            self.display.write_text(window.ljust(cells), cursor)

    # ------------------------------------------------------------ teclas
    def _on_key(self, key: DisplayKey) -> None:
        dispatcher = self._dispatcher() if self._dispatcher is not None else None
        in_help = bool(dispatcher is not None and dispatcher.input_help)
        if not in_help:
            if key.name in PAN_BACK:
                self.scroll_back()
                return
            if key.name in PAN_FORWARD:
                self.scroll_forward()
                return
        extra: dict[str, Any] = {"command": key.name, "argument": key.argument}
        if key.name == "routing":
            extra["routing_index"] = key.argument
            start, _ = self._bounds()
            cell = start + key.argument
            mapping = self._translation.cell_to_text
            extra["text_offset"] = (
                mapping[cell] if self._message is None and cell < len(mapping) else None
            )
            if self._message is not None:
                self.dismiss_message()
        gesture = InputGesture(identifier=f"br(brltty):{key.name}", extra=extra)
        process = getattr(dispatcher, "process_gesture", None)
        if callable(process):
            process(gesture)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    async def close(self) -> None:
        if self._message_handle is not None:
            self._message_handle.cancel()
        with contextlib.suppress(Exception):
            await self.display.close()


async def create_braille(
    config: ConfigStore | None,
    dispatcher: Callable[[], GestureDispatcher | None] | None = None,
) -> BrailleHandler:
    """Conecta ao BRLTTY se possível; senão devolve o gerenciador com linha nula."""
    choice = str(config.get("braille.display", "auto")) if config is not None else "auto"
    display: BrailleDisplay = NullDisplay()
    if choice in ("auto", "brltty"):
        candidate = BrlapiDisplay()
        try:
            await candidate.open()
            display = candidate
        except OSError as exc:
            level = log.warning if choice == "brltty" else log.info
            level("Braille indisponível: %s", exc)
    return BrailleHandler(display, config=config, dispatcher=dispatcher)
