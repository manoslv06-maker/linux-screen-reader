"""BrailleHandler, BrlapiDisplay (brlapi falso) e tradução liblouis (falsa)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from nvda_linux.braille.display import BrlapiDisplay, NullDisplay
from nvda_linux.braille.handler import (
    BrailleHandler,
    Translator,
    create_braille,
    to_dots,
    window_starts,
)
from nvda_linux.contracts import BrailleOutput, InputGesture
from nvda_linux.core.config import TomlConfigStore
from tests.platform.fakes import FakeBrlConnection, make_fake_brlapi, wait_for


class SpyDispatcher:
    def __init__(self) -> None:
        self.gestures: list[InputGesture] = []
        self.input_help = False

    def process_gesture(self, gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        self.gestures.append(gesture)
        return True


@pytest.fixture
def conn() -> Iterator[FakeBrlConnection]:
    c = FakeBrlConnection(cells=10)
    yield c
    if not c.closed:
        c.closeConnection()


async def make(
    conn: FakeBrlConnection, config: TomlConfigStore | None = None
) -> tuple[BrailleHandler, SpyDispatcher]:
    display = BrlapiDisplay(make_fake_brlapi(conn))
    await display.open()
    spy = SpyDispatcher()
    handler = BrailleHandler(display, config=config, dispatcher=lambda: spy)  # type: ignore[arg-type,return-value]
    return handler, spy


def test_window_starts_word_wrap() -> None:
    text = "um dois tres quatro"
    assert window_starts(len(text), 10, text, word_wrap=True) == [0, 8, 13]
    assert window_starts(len(text), 10, text, word_wrap=False) == [0, 10]
    assert window_starts(0, 10) == [0]


def test_to_dots() -> None:
    assert to_dots("⠁⠃x") == bytes([1, 3, 0])


async def test_show_text_cursor_and_pan(conn: FakeBrlConnection) -> None:
    handler, _ = await make(conn)
    assert isinstance(handler, BrailleOutput) and handler.available
    assert conn.tty_mode
    handler.show_text("um dois tres quatro", cursor=14)
    # janelas: "um dois " | "tres " | "quatro"; cursor 14 -> célula 1 -> BrlAPI 2 (1-based)
    assert conn.texts[-1] == ("quatro    ", 2)
    assert handler.scroll_back() and conn.texts[-1] == ("tres      ", 0)
    assert handler.scroll_back() and conn.texts[-1] == ("um dois   ", 0)
    assert not handler.scroll_back()
    await handler.close()
    assert conn.closed


async def test_message_timeout_restores_text(conn: FakeBrlConnection) -> None:
    handler, _ = await make(conn)
    handler.show_text("conteúdo")
    handler.show_message("aviso", timeout_ms=20)
    assert conn.texts[-1][0] == "aviso     "
    handler.show_text("novo")  # chega durante a mensagem: guardado
    assert conn.texts[-1][0] == "aviso     "
    await wait_for(lambda: conn.texts[-1][0] == "novo      ")
    await handler.close()


async def test_messages_disabled(conn: FakeBrlConnection, config: TomlConfigStore) -> None:
    config.set("braille.messageTimeout", 0)
    handler, _ = await make(conn, config)
    handler.show_message("nada")
    assert conn.texts == []
    await handler.close()


async def test_keys_routing_and_panning(conn: FakeBrlConnection) -> None:
    handler, spy = await make(conn)
    handler.show_text("abcdefghij klmnop")
    conn.press(0x0300)  # FWINRT: tratado aqui
    await wait_for(lambda: conn.texts[-1][0].startswith("klmnop"))
    conn.press(0x0100 | 3)  # ROUTE célula 3 da segunda janela
    await wait_for(lambda: len(spy.gestures) == 1)
    g = spy.gestures[0]
    assert g.identifier == "br(brltty):routing"
    assert g.extra["routing_index"] == 3 and g.extra["text_offset"] == 14
    conn.press(0x0400)  # LNUP -> despachante
    await wait_for(lambda: len(spy.gestures) == 2)
    assert spy.gestures[1].identifier == "br(brltty):lnup"
    await handler.close()


async def test_input_help_sends_panning_to_dispatcher(conn: FakeBrlConnection) -> None:
    handler, spy = await make(conn)
    spy.input_help = True
    conn.press(0x0200)
    await wait_for(lambda: len(spy.gestures) == 1)
    assert spy.gestures[0].identifier == "br(brltty):fwinlt"
    await handler.close()


async def test_louis_translation_writes_dots() -> None:
    calls: list[Any] = []

    def translate(tables: list[str], text: str, cursorPos: int = 0, mode: int = 0) -> Any:
        calls.append((tables, text, mode))
        out = "".join(chr(0x2800 + (ord(c) % 64)) for c in text)
        return out, None, list(range(len(text))), list(range(len(text))), cursorPos

    louis = SimpleNamespace(translate=translate, dotsIO=4, ucBrl=64)
    display = NullDisplay(cells=8)
    handler = BrailleHandler(display, translator=Translator("pt-br-g1.utb", louis))
    handler.show_text("abc", cursor=1)
    assert display.last_dots is not None and len(display.last_dots) == 8
    assert calls[0][0] == ["pt-br-g1.utb"] and calls[0][2] == 68


async def test_null_display_and_factory(config: TomlConfigStore) -> None:
    config.set("braille.display", "none")
    handler = await create_braille(config)
    assert not handler.available
    handler.show_text("x")
    handler.show_message("y")
    from nvda_linux.core import compat

    compat.inject_module("brlapi", None)
    try:
        config.set("braille.display", "auto")
        handler = await create_braille(config)
        assert handler.display.name == "none"
    finally:
        compat.reset_cache()


async def test_brlapi_without_display_is_unavailable() -> None:
    conn = FakeBrlConnection(cells=0)
    display = BrlapiDisplay(make_fake_brlapi(conn))
    with pytest.raises(OSError):
        await display.open()
    await asyncio.sleep(0)
