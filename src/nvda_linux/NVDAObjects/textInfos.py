# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""``TextInfo`` no estilo do NVDA sobre ``Atspi.Text`` ou sobre texto local.

Um :class:`OffsetsTextInfo` é um intervalo ``[start, end)`` num
:class:`TextBackend`. As operações seguem o ``textInfos`` do NVDA:
``expand``, ``collapse``, ``move``, ``text``, ``update_caret`` e
``update_selection``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from nvda_linux.NVDAObjects import _atspi, textUtils


class TextUnit(Enum):
    CHARACTER = "character"
    WORD = "word"
    LINE = "line"
    PARAGRAPH = "paragraph"
    STORY = "story"


class Position(Enum):
    CARET = "caret"
    SELECTION = "selection"
    FIRST = "first"
    LAST = "last"
    ALL = "all"


class TextBackend(Protocol):
    """Fonte de texto com noção de unidades, cursor e seleção."""

    def length(self) -> int: ...

    def get_text(self, start: int, end: int) -> str: ...

    def unit_bounds(self, offset: int, unit: TextUnit) -> tuple[int, int]: ...

    def caret(self) -> int: ...

    def set_caret(self, offset: int) -> bool: ...

    def selection(self) -> tuple[int, int] | None: ...

    def set_selection(self, start: int, end: int) -> bool: ...

    def attributes_at(self, offset: int) -> dict[str, str]: ...


def _local_bounds(text: str, offset: int, unit: TextUnit) -> tuple[int, int]:
    if unit == TextUnit.CHARACTER:
        return textUtils.char_bounds(text, offset)
    if unit == TextUnit.WORD:
        return textUtils.word_bounds(text, offset)
    if unit == TextUnit.LINE:
        return textUtils.line_bounds(text, offset)
    if unit == TextUnit.PARAGRAPH:
        return textUtils.paragraph_bounds(text, offset)
    return 0, len(text)


class StringTextBackend:
    """Texto local (objetos sem ``Atspi.Text``, testes, buffer virtual)."""

    def __init__(self, text: str, caret: int = 0) -> None:
        self.text = text
        self._caret = textUtils.clamp(caret, len(text))
        self._selection: tuple[int, int] | None = None

    def length(self) -> int:
        return len(self.text)

    def get_text(self, start: int, end: int) -> str:
        return self.text[max(0, start) : max(0, end)]

    def unit_bounds(self, offset: int, unit: TextUnit) -> tuple[int, int]:
        return _local_bounds(self.text, offset, unit)

    def caret(self) -> int:
        return self._caret

    def set_caret(self, offset: int) -> bool:
        self._caret = textUtils.clamp(offset, len(self.text))
        return True

    def selection(self) -> tuple[int, int] | None:
        return self._selection

    def set_selection(self, start: int, end: int) -> bool:
        self._selection = (start, end) if start != end else None
        return True

    def attributes_at(self, offset: int) -> dict[str, str]:
        return {}


_GRANULARITY = {
    TextUnit.WORD: "WORD",
    TextUnit.LINE: "LINE",
    TextUnit.PARAGRAPH: "PARAGRAPH",
}

#: Limite de texto buscado de uma vez para cálculo local (terminais grandes).
_LOCAL_FALLBACK_LIMIT = 200_000


class AtspiTextBackend:
    """Backend sobre a interface ``Atspi.Text`` de um objeto."""

    def __init__(self, text_iface: Any) -> None:
        self._iface = text_iface

    def length(self) -> int:
        try:
            return max(0, int(_atspi.call(self._iface, "get_character_count", default=0)))
        except (TypeError, ValueError):
            return 0

    def get_text(self, start: int, end: int) -> str:
        if end <= start:
            return ""
        return str(_atspi.call(self._iface, "get_text", start, end, default=""))

    def unit_bounds(self, offset: int, unit: TextUnit) -> tuple[int, int]:
        n = self.length()
        offset = textUtils.clamp(offset, n)
        if unit == TextUnit.STORY:
            return 0, n
        if unit == TextUnit.CHARACTER:
            return (n, n) if offset >= n else (offset, offset + 1)
        rng = _atspi.text_range(
            _atspi.call(
                self._iface,
                "get_string_at_offset",
                offset,
                _atspi.granularity(_GRANULARITY[unit]),
                default=None,
            )
        )
        if rng is not None:
            _content, start, end = rng
            if 0 <= start <= offset <= end <= n and (start < end or offset == n):
                return start, end
        text = self.get_text(0, min(n, _LOCAL_FALLBACK_LIMIT))
        return _local_bounds(text, offset, unit)

    def caret(self) -> int:
        try:
            return max(0, int(_atspi.call(self._iface, "get_caret_offset", default=0)))
        except (TypeError, ValueError):
            return 0

    def set_caret(self, offset: int) -> bool:
        return bool(_atspi.call(self._iface, "set_caret_offset", offset, default=False))

    def selection(self) -> tuple[int, int] | None:
        try:
            count = int(_atspi.call(self._iface, "get_n_selections", default=0))
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            return None
        rng = _atspi.offsets_range(_atspi.call(self._iface, "get_selection", 0, default=None))
        if rng is None or rng[0] == rng[1]:
            return None
        return rng

    def set_selection(self, start: int, end: int) -> bool:
        if self.selection() is not None:
            return bool(_atspi.call(self._iface, "set_selection", 0, start, end, default=False))
        return bool(_atspi.call(self._iface, "add_selection", start, end, default=False))

    def attributes_at(self, offset: int) -> dict[str, str]:
        return _atspi.text_attributes_at(self._iface, offset)


class OffsetsTextInfo:
    """Intervalo de texto ``[start, end)`` com a API do ``TextInfo`` do NVDA."""

    def __init__(
        self,
        backend: TextBackend,
        position: Position | int | tuple[int, int] = Position.CARET,
    ) -> None:
        self.backend = backend
        length = backend.length()
        if isinstance(position, tuple):
            start, end = position
        elif isinstance(position, int):
            start = end = position
        elif position == Position.CARET:
            start = end = backend.caret()
        elif position == Position.SELECTION:
            sel = backend.selection()
            start, end = sel if sel is not None else (backend.caret(), backend.caret())
        elif position == Position.FIRST:
            start = end = 0
        elif position == Position.LAST:
            start = end = length
        else:
            start, end = 0, length
        self.start = textUtils.clamp(min(start, end), length)
        self.end = textUtils.clamp(max(start, end), length)

    # ------------------------------------------------------------ básicos
    def copy(self) -> OffsetsTextInfo:
        return OffsetsTextInfo(self.backend, (self.start, self.end))

    @property
    def is_collapsed(self) -> bool:
        return self.start == self.end

    @property
    def text(self) -> str:
        return self.backend.get_text(self.start, self.end)

    def collapse(self, end: bool = False) -> None:
        if end:
            self.start = self.end
        else:
            self.end = self.start

    def expand(self, unit: TextUnit) -> None:
        self.start, self.end = self.backend.unit_bounds(self.start, unit)

    def move(self, unit: TextUnit, direction: int) -> int:
        """Move ``direction`` unidades a partir do início; devolve o total movido.

        O intervalo fica recolhido na nova posição. Não passa do fim do texto:
        tentar avançar além da última unidade devolve 0.
        """
        length = self.backend.length()
        pos = self.start
        moved = 0
        step = 1 if direction > 0 else -1
        for _ in range(abs(direction)):
            unit_start, unit_end = self.backend.unit_bounds(pos, unit)
            if step > 0:
                if unit_end >= length or unit_end <= pos:
                    break
                pos = unit_end
            else:
                if unit_start <= 0:
                    break
                pos = self.backend.unit_bounds(unit_start - 1, unit)[0]
            moved += step
        self.start = self.end = pos
        return moved

    def compare_start(self, other: OffsetsTextInfo) -> int:
        return (self.start > other.start) - (self.start < other.start)

    def set_end_point(self, other: OffsetsTextInfo, which: str) -> None:
        """``which`` em ``startToStart``, ``startToEnd``, ``endToStart``, ``endToEnd``."""
        src = other.start if which.endswith("ToStart") else other.end
        if which.startswith("start"):
            self.start = src
            self.end = max(self.end, src)
        else:
            self.end = src
            self.start = min(self.start, src)

    # ------------------------------------------------------------ efeitos
    def update_caret(self) -> bool:
        return self.backend.set_caret(self.start)

    def update_selection(self) -> bool:
        return self.backend.set_selection(self.start, self.end)

    @property
    def attributes(self) -> dict[str, str]:
        return self.backend.attributes_at(self.start)

    # Aliases no estilo do NVDA para add-ons.
    def updateCaret(self) -> bool:
        return self.update_caret()

    def updateSelection(self) -> bool:
        return self.update_selection()

    def __repr__(self) -> str:
        return f"OffsetsTextInfo({self.start}, {self.end})"
