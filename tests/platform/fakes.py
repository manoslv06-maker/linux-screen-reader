"""Fakes da PLATAFORMA: driver de fala, cadeia de scripts, evdev, brlapi, D-Bus."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from nvda_linux.contracts import InputGesture, Script
from nvda_linux.speech.driver import SynthDriver, Utterance

# --------------------------------------------------------------------------
# Fala
# --------------------------------------------------------------------------


class FakeDriver(SynthDriver):
    """Driver que registra chamadas e o instante (perf_counter) de cada cancel()."""

    name = "fake"
    supports_ssml = True
    supports_spelling = True

    def __init__(self, *, auto_done: bool = False) -> None:
        super().__init__()
        self.auto_done = auto_done
        self.spoken: list[Utterance] = []
        self.cancel_times: list[float] = []
        self.paused: list[bool] = []
        self.terminated = False

    @classmethod
    def check(cls) -> bool:
        return True

    async def initialize(self) -> None:
        return None

    def speak(self, utterance: Utterance) -> None:
        self.spoken.append(utterance)
        if self.auto_done:
            self.notify_done(utterance.id)

    def cancel(self) -> None:
        self.cancel_times.append(time.perf_counter())

    def pause(self, paused: bool) -> None:
        self.paused.append(paused)

    async def terminate(self) -> None:
        self.terminated = True

    def finish(self) -> None:
        """Termina o enunciado mais recente."""
        if self.spoken:
            self.notify_done(self.spoken[-1].id)

    @property
    def texts(self) -> list[str]:
        return [u.plain_text for u in self.spoken]


class RecordingSpeech:
    """SpeechOutput mínimo para testes do despachante."""

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.cancels = 0
        self.cancel_times: list[float] = []
        self.paused: list[bool] = []
        self.typed: list[str] = []

    def speak(self, sequence: Sequence[Any], priority: Any = None) -> None:
        self.spoken.append(" ".join(str(s) for s in sequence))

    def speak_text(self, text: str, priority: Any = None) -> None:
        self.spoken.append(text)

    def speak_spelling(self, text: str) -> None:
        self.spoken.append(text)

    def cancel(self) -> None:
        self.cancels += 1
        self.cancel_times.append(time.perf_counter())

    def pause(self, paused: bool) -> None:
        self.paused.append(paused)

    def on_typed_character(self, char: str) -> None:
        self.typed.append(char)


# --------------------------------------------------------------------------
# Cadeia de scripts
# --------------------------------------------------------------------------


class DictProvider:
    """ScriptProvider baseado num dicionário identificador -> script."""

    def __init__(self, scripts: dict[str, Script] | None = None) -> None:
        self.scripts = dict(scripts or {})
        self.asked: list[str] = []

    def get_script(self, gesture: InputGesture) -> Script | None:
        self.asked.append(gesture.identifier)
        return self.scripts.get(gesture.identifier)


class FakeChain:
    def __init__(self, *providers: DictProvider) -> None:
        self.providers = list(providers)

    def chain(self) -> Sequence[DictProvider]:
        return self.providers


def recorder() -> tuple[list[InputGesture], Callable[[InputGesture], None]]:
    calls: list[InputGesture] = []

    def script(gesture: InputGesture) -> None:
        """Script de teste"""
        calls.append(gesture)

    return calls, script


# --------------------------------------------------------------------------
# evdev
# --------------------------------------------------------------------------
EV_KEY = 1
KEY_A, KEY_Z, KEY_SPACE, KEY_ENTER = 30, 44, 57, 28


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


class FakeInputDevice:
    """InputDevice com fd real (pipe) para funcionar com loop.add_reader."""

    def __init__(self, path: str, name: str, keys: Sequence[int], leds: Sequence[int] = ()) -> None:
        self.path = path
        self.name = name
        self._keys = list(keys)
        self._leds = list(leds)
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        self.queue: list[FakeEvent] = []
        self.grabbed = False
        self.grab_calls = 0
        self.ungrab_calls = 0
        self.grab_error: OSError | None = None
        self.active: list[int] = []
        self.closed = False

    @property
    def fd(self) -> int:
        return self._r

    def capabilities(self, verbose: bool = False) -> dict[int, list[int]]:
        return {EV_KEY: self._keys}

    def leds(self) -> list[int]:
        return self._leds

    def grab(self) -> None:
        self.grab_calls += 1
        if self.grab_error is not None:
            raise self.grab_error
        self.grabbed = True

    def ungrab(self) -> None:
        self.ungrab_calls += 1
        self.grabbed = False

    def active_keys(self) -> list[int]:
        return self.active

    def push(self, code: int, value: int) -> None:
        """Simula o kernel entregando um evento."""
        self.queue.append(FakeEvent(EV_KEY, code, value))
        self.queue.append(FakeEvent(0, 0, 0))
        os.write(self._w, b"x")

    def read(self) -> list[FakeEvent]:
        try:
            os.read(self._r, 4096)
        except BlockingIOError:
            pass
        if not self.queue:
            raise BlockingIOError
        events, self.queue = self.queue, []
        return events

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self._r)
            os.close(self._w)


class FakeUInput:
    def __init__(self, events: dict[int, list[int]], name: str = "", bustype: int = 0) -> None:
        self.name = name
        self.events = events
        self.written: list[tuple[int, int, int]] = []
        self.syns = 0
        self.closed = False
        self.devnode = "/dev/uinput"
        self.device = SimpleNamespace(path="/dev/input/event5")

    def write(self, etype: int, code: int, value: int) -> None:
        self.written.append((etype, code, value))

    def syn(self) -> None:
        self.syns += 1

    def close(self) -> None:
        self.closed = True

    @property
    def keys(self) -> list[tuple[int, int]]:
        return [(c, v) for t, c, v in self.written if t == EV_KEY]


class UInputError(Exception):
    pass


def make_fake_evdev(devices: list[FakeInputDevice]) -> Any:
    """Módulo ``evdev`` falso com os dispositivos dados."""
    by_path = {d.path: d for d in devices}
    uinputs: list[FakeUInput] = []

    def uinput_factory(*args: Any, **kwargs: Any) -> FakeUInput:
        ui = FakeUInput(*args, **kwargs)
        uinputs.append(ui)
        return ui

    module = SimpleNamespace(
        ecodes=SimpleNamespace(EV_KEY=EV_KEY, BUS_VIRTUAL=6),
        list_devices=lambda: list(by_path),
        InputDevice=lambda path: by_path[path],
        UInput=uinput_factory,
        UInputError=UInputError,
        uinputs=uinputs,
    )
    return module


KEYBOARD_KEYS = list(range(1, 128))


# --------------------------------------------------------------------------
# D-Bus KeyboardMonitor
# --------------------------------------------------------------------------


@dataclass
class FakeMonitorConnection:
    owner: bool = True
    calls: list[tuple[str, list[Any]]] = field(default_factory=list)
    callbacks: list[Callable[[bool, int, int, int, int], None]] = field(default_factory=list)
    closed: bool = False
    fail_member: str | None = None

    async def has_owner(self) -> bool:
        return self.owner

    async def call(self, member: str, signature: str, body: list[Any]) -> None:
        if member == self.fail_member:
            raise RuntimeError(f"{member} falhou")
        self.calls.append((member, body))

    def on_key_event(self, callback: Callable[[bool, int, int, int, int], None]) -> None:
        self.callbacks.append(callback)

    async def close(self) -> None:
        self.closed = True

    def key(self, keycode_evdev: int, released: bool, keysym: int = 0, unichar: int = 0) -> None:
        for cb in self.callbacks:
            cb(released, 0, keysym, unichar, keycode_evdev + 8)

    def members(self) -> list[str]:
        return [m for m, _ in self.calls]

    def last(self, member: str) -> list[Any]:
        for m, body in reversed(self.calls):
            if m == member:
                return body
        raise AssertionError(f"{member} não foi chamado")


# --------------------------------------------------------------------------
# BrlAPI
# --------------------------------------------------------------------------


class FakeBrlConnection:
    def __init__(self, cells: int = 20) -> None:
        self.displaySize = (cells, 1)
        self.driverName = "fake"
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        self.keys: list[int] = []
        self.texts: list[tuple[str, int]] = []
        self.dots: list[bytes] = []
        self.tty_mode = False
        self.closed = False

    @property
    def fileDescriptor(self) -> int:
        return self._r

    def enterTtyModeWithPath(self) -> None:
        self.tty_mode = True

    def enterTtyMode(self, tty: Any = None) -> None:
        self.tty_mode = True

    def acceptKeys(self, *args: Any) -> None:
        return None

    def leaveTtyMode(self) -> None:
        self.tty_mode = False

    def closeConnection(self) -> None:
        self.closed = True
        os.close(self._r)
        os.close(self._w)

    def writeText(self, text: str, cursor: int) -> None:
        self.texts.append((text, cursor))

    def writeDots(self, cells: bytes) -> None:
        self.dots.append(cells)

    def press(self, code: int) -> None:
        self.keys.append(code)
        os.write(self._w, b"k")

    def readKey(self, wait: bool = True) -> int | None:
        try:
            os.read(self._r, 64)
        except BlockingIOError:
            pass
        return self.keys.pop(0) if self.keys else None

    def expandKeyCode(self, code: int) -> dict[str, int]:
        return {"type": 1, "command": code & 0xFF00, "argument": code & 0xFF, "flags": 0}


def make_fake_brlapi(conn: FakeBrlConnection) -> Any:
    return SimpleNamespace(
        Connection=lambda: conn,
        KEY_TYPE_CMD=1,
        KEY_CMD_ROUTE=0x0100,
        KEY_CMD_FWINLT=0x0200,
        KEY_CMD_FWINRT=0x0300,
        KEY_CMD_LNUP=0x0400,
        CURSOR_OFF=0,
        rangeType_all=0,
    )


async def wait_for(
    predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.005
) -> None:
    """Espera ``predicate()`` ficar verdadeiro girando o loop."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condição não satisfeita a tempo")
        await asyncio.sleep(interval)
