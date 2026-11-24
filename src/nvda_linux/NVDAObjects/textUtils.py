# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Cálculo local de limites de caractere, palavra, linha e parágrafo.

Usado pelo buffer virtual, pelo texto sintético de objetos sem ``Atspi.Text``
e como recuo quando ``get_string_at_offset`` falha.
"""

from __future__ import annotations

import re
from bisect import bisect_right

# Palavra = sequência de caracteres de palavra, ou de pontuação, seguida dos
# espaços que a acompanham; espaços no início da linha e "\n" isolados.
_WORD_RE = re.compile(r"\w+[^\S\n]*|[^\w\s]+[^\S\n]*|[^\S\n]+|\n")


def clamp(offset: int, length: int) -> int:
    return max(0, min(offset, length))


def char_bounds(text: str, offset: int) -> tuple[int, int]:
    """Limites do caractere em ``offset``. No fim do texto, intervalo vazio."""
    n = len(text)
    offset = clamp(offset, n)
    if offset >= n:
        return n, n
    return offset, offset + 1


def line_bounds(text: str, offset: int) -> tuple[int, int]:
    """Limites da linha lógica (terminada por ``\\n``, que fica incluído)."""
    n = len(text)
    offset = clamp(offset, n)
    start = text.rfind("\n", 0, offset) + 1
    if offset == n and n > 0 and text[-1] == "\n":
        return n, n
    end = text.find("\n", offset)
    end = n if end < 0 else end + 1
    return start, end


def word_bounds(text: str, offset: int) -> tuple[int, int]:
    """Limites da palavra em ``offset`` (inclui os espaços seguintes)."""
    n = len(text)
    offset = clamp(offset, n)
    if offset >= n:
        return n, n
    line_start, line_end = line_bounds(text, offset)
    for match in _WORD_RE.finditer(text, line_start, line_end):
        if match.start() <= offset < match.end():
            return match.start(), match.end()
    return char_bounds(text, offset)


def paragraph_bounds(text: str, offset: int) -> tuple[int, int]:
    """Parágrafo = linha lógica (como fazem os campos de edição do GTK)."""
    return line_bounds(text, offset)


def wrap_line_starts(text: str, max_length: int) -> list[int]:
    """Inícios das linhas físicas, quebrando linhas longas em espaços.

    Usado pelo buffer virtual (``browseMode.maxLineLength``).
    """
    starts: list[int] = [0]
    n = len(text)
    pos = 0
    max_length = max(10, max_length)
    while pos < n:
        nl = text.find("\n", pos)
        logical_end = n if nl < 0 else nl + 1
        while logical_end - pos > max_length:
            cut = text.rfind(" ", pos, pos + max_length)
            cut = pos + max_length if cut <= pos else cut + 1
            starts.append(cut)
            pos = cut
        pos = logical_end
        if pos < n:
            starts.append(pos)
    return starts


def bounds_from_starts(starts: list[int], length: int, offset: int) -> tuple[int, int]:
    """Limites da linha física que contém ``offset`` dados os inícios ordenados."""
    if not starts:
        return 0, length
    offset = clamp(offset, length)
    idx = bisect_right(starts, offset) - 1
    idx = max(0, idx)
    start = starts[idx]
    end = starts[idx + 1] if idx + 1 < len(starts) else length
    if offset == length and start == length and idx > 0:
        return length, length
    return start, end
