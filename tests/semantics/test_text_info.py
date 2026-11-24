"""TextInfo sobre texto local e sobre Atspi.Text falso."""

from __future__ import annotations

import itertools

from nvda_linux.NVDAObjects import textUtils
from nvda_linux.NVDAObjects.textInfos import (
    AtspiTextBackend,
    OffsetsTextInfo,
    Position,
    StringTextBackend,
    TextUnit,
)
from tests.semantics.fake_atspi import FakeAccessible

TEXT = "Olá, mundo cruel.\nSegunda linha\n\nQuarta"


def test_word_and_line_bounds() -> None:
    assert textUtils.word_bounds(TEXT, 1) == (0, 3)  # "Olá"
    assert TEXT[slice(*textUtils.word_bounds(TEXT, 5))] == "mundo "
    assert TEXT[slice(*textUtils.word_bounds(TEXT, 3))] == ", "
    assert TEXT[slice(*textUtils.line_bounds(TEXT, 20))] == "Segunda linha\n"
    assert textUtils.line_bounds(TEXT, 32) == (32, 33)  # linha vazia
    assert textUtils.char_bounds(TEXT, len(TEXT)) == (len(TEXT), len(TEXT))


def test_wrap_line_starts() -> None:
    text = "palavra " * 30 + "\nfim"
    starts = textUtils.wrap_line_starts(text, 40)
    assert starts[0] == 0
    assert all(b - a <= 40 for a, b in itertools.pairwise(starts))
    assert text[starts[-1]:] == "fim"


def test_expand_move_and_edges() -> None:
    info = OffsetsTextInfo(StringTextBackend(TEXT), Position.FIRST)
    info.expand(TextUnit.LINE)
    assert info.text == "Olá, mundo cruel.\n"
    info.collapse()
    assert info.move(TextUnit.LINE, 1) == 1
    info.expand(TextUnit.LINE)
    assert info.text == "Segunda linha\n"
    info.collapse()
    assert info.move(TextUnit.LINE, 5) == 2  # para na última linha
    info.expand(TextUnit.LINE)
    assert info.text == "Quarta"
    info.collapse()
    assert info.move(TextUnit.LINE, 1) == 0
    assert info.move(TextUnit.LINE, -1) == -1
    word = OffsetsTextInfo(StringTextBackend(TEXT), 5)
    word.expand(TextUnit.WORD)
    word.collapse()
    assert word.move(TextUnit.WORD, -1) == -1
    word.expand(TextUnit.WORD)
    assert word.text == ", "
    assert OffsetsTextInfo(StringTextBackend(""), Position.FIRST).move(TextUnit.CHARACTER, 1) == 0


def test_atspi_backend_caret_selection_and_fallback() -> None:
    acc = FakeAccessible("TEXT", text=TEXT, extra_states=["EDITABLE"])
    assert acc.text_iface is not None
    acc.text_iface.caret = 20
    backend = AtspiTextBackend(acc.text_iface)
    info = OffsetsTextInfo(backend, Position.CARET)
    assert info.start == 20
    info.expand(TextUnit.LINE)
    assert info.text == "Segunda linha\n"
    acc.text_iface.fail_string_at_offset = True  # recai no cálculo local
    word = OffsetsTextInfo(backend, 5)
    word.expand(TextUnit.WORD)
    assert word.text == "mundo "
    sel = OffsetsTextInfo(backend, (5, 10))
    assert sel.update_selection()
    assert OffsetsTextInfo(backend, Position.SELECTION).text == "mundo"
    caret = OffsetsTextInfo(backend, 3)
    assert caret.update_caret() and acc.text_iface.caret == 3


def test_set_end_point_and_compare() -> None:
    backend = StringTextBackend(TEXT)
    a = OffsetsTextInfo(backend, (0, 3))
    b = OffsetsTextInfo(backend, (5, 10))
    a.set_end_point(b, "endToEnd")
    assert (a.start, a.end) == (0, 10)
    assert a.compare_start(b) == -1
