"""Latência tecla -> cancel() da fala. Falha se passar de 30 ms.

Três medições, da mais isolada à mais completa:

1. ``processor.handle()`` síncrono -> ``FakeDriver.cancel()``;
2. tecla escrita no fd de um teclado evdev falso -> loop (``add_reader``) ->
   EvdevBackend -> processador -> despachante -> SpeechManager -> driver;
3. igual a (2), mas com o SpeechDispatcherDriver real (transporte nativo)
   e medindo até o servidor SSIP falso *receber* ``CANCEL self`` no socket.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest

from nvda_linux.core.config import TomlConfigStore
from nvda_linux.inputCore import evdev_backend
from nvda_linux.inputCore import keys as k
from nvda_linux.inputCore.backend import RawKeyEvent, UInputInjector
from nvda_linux.inputCore.dispatcher import InputManager
from nvda_linux.inputCore.evdev_backend import EvdevBackend
from nvda_linux.inputCore.keyboard import KeyboardInputProcessor
from nvda_linux.inputCore.xkb import UsKeymap
from nvda_linux.speech.drivers.speechdispatcher import SpeechDispatcherDriver
from nvda_linux.speech.manager import SpeechManager
from tests.platform.fakes import (
    KEYBOARD_KEYS,
    DictProvider,
    FakeChain,
    FakeDriver,
    FakeInputDevice,
    make_fake_evdev,
    recorder,
    wait_for,
)
from tests.platform.test_ssip import FakeSSIPServer

LIMIT_MS = 30.0
ROUNDS = 40
KEY_T, KEY_A = 20, 30


class _Injector(UInputInjector):
    def open(self) -> None:
        assert self._evdev is not None
        self._ui = self._evdev.UInput({1: self.key_capabilities()}, name=self.DEVICE_NAME)


def _stack(
    config: TomlConfigStore, driver: FakeDriver | SpeechDispatcherDriver
) -> tuple[SpeechManager, InputManager, KeyboardInputProcessor]:
    _, script = recorder()
    speech = SpeechManager(driver, config=config)
    speech.start(asyncio.get_running_loop())
    chain = FakeChain(DictProvider({"kb:nvda+t": script}))
    dispatcher = InputManager(config=config, speech=speech, chain=chain.chain)
    processor = KeyboardInputProcessor(dispatcher, config=config, keymap=UsKeymap())
    return speech, dispatcher, processor


def _grows(size: Callable[[], int], than: int) -> Callable[[], bool]:
    """Predicado: ``size()`` passou de ``than``."""
    return lambda: size() > than


def _report(name: str, samples: list[float]) -> None:
    print(
        f"\n{name}: mediana {statistics.median(samples):.3f} ms, "
        f"máx {max(samples):.3f} ms ({len(samples)} amostras)"
    )


@pytest.fixture
def keyboard() -> Iterator[FakeInputDevice]:
    dev = FakeInputDevice("/dev/input/event3", "Teclado", KEYBOARD_KEYS)
    yield dev
    dev.close()


@pytest.fixture(autouse=True)
def _nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evdev_backend, "readable_event_nodes", lambda pattern="": (["/dev/input/event3"], [])
    )


async def test_sync_path_key_to_cancel(config: TomlConfigStore) -> None:
    driver = FakeDriver()
    speech, dispatcher, processor = _stack(config, driver)
    samples: list[float] = []
    for i in range(ROUNDS):
        speech.speak_text(f"texto longo {i}")
        code = KEY_A if i % 2 else KEY_T
        if code == KEY_T:
            processor.handle(RawKeyEvent(k.KEY_INSERT, 1, time.monotonic()))
        t0 = time.perf_counter()
        processor.handle(RawKeyEvent(code, 1, time.monotonic()))
        samples.append((driver.cancel_times[-1] - t0) * 1000)
        processor.handle(RawKeyEvent(code, 0, time.monotonic()))
        if code == KEY_T:
            processor.handle(RawKeyEvent(k.KEY_INSERT, 0, time.monotonic()))
        await dispatcher.drain()
    _report("síncrono", samples)
    assert len(driver.cancel_times) >= ROUNDS
    assert max(samples) < LIMIT_MS


async def test_evdev_path_key_to_cancel(config: TomlConfigStore, keyboard: FakeInputDevice) -> None:
    driver = FakeDriver()
    speech, _dispatcher, processor = _stack(config, driver)
    fake = make_fake_evdev([keyboard])
    backend = EvdevBackend(fake, _Injector(fake), rescan_interval=60)
    processor.backend = backend
    await backend.start(processor.handle)
    samples: list[float] = []
    try:
        for i in range(ROUNDS):
            speech.speak_text(f"frase {i}")
            before = len(driver.cancel_times)
            keyboard.push(k.KEY_INSERT, 1)
            await asyncio.sleep(0)
            t0 = time.perf_counter()
            keyboard.push(KEY_T, 1)  # NVDA+T: script com cancelamento
            await wait_for(_grows(lambda: len(driver.cancel_times), before))
            samples.append((driver.cancel_times[before] - t0) * 1000)
            keyboard.push(KEY_T, 0)
            keyboard.push(k.KEY_INSERT, 0)
            await asyncio.sleep(0.001)
    finally:
        await backend.stop()
    _report("evdev -> driver", samples)
    assert max(samples) < LIMIT_MS


@pytest.fixture
async def ssip_server(tmp_path: Path) -> AsyncIterator[FakeSSIPServer]:
    srv = FakeSSIPServer(tmp_path / "speechd.sock", auto_end=False)
    await srv.start()
    yield srv
    await srv.close()


async def test_evdev_to_speechd_socket_cancel(
    config: TomlConfigStore,
    keyboard: FakeInputDevice,
    ssip_server: FakeSSIPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECHD_ADDRESS", f"unix_socket:{ssip_server.path}")
    driver = SpeechDispatcherDriver(transport="native", autospawn=False)
    driver.bind(asyncio.get_running_loop(), lambda _id: None)
    await driver.initialize()
    speech, _dispatcher, processor = _stack(config, driver)
    fake = make_fake_evdev([keyboard])
    backend = EvdevBackend(fake, _Injector(fake), rescan_interval=60)
    processor.backend = backend
    await backend.start(processor.handle)
    samples: list[float] = []
    try:
        for i in range(ROUNDS // 2):
            speech.speak_text(f"mensagem {i}")
            await wait_for(_grows(lambda: len(ssip_server.messages), i))
            before = ssip_server.commands.count("CANCEL self")
            t0 = time.perf_counter()
            keyboard.push(KEY_A, 1)  # digitação: speechInterruptForCharacters
            await wait_for(
                _grows(lambda: ssip_server.commands.count("CANCEL self"), before), interval=0
            )
            samples.append((time.perf_counter() - t0) * 1000)
            keyboard.push(KEY_A, 0)
            # O eco do caractere digitado gera um enunciado; encerra-o.
            await wait_for(_grows(lambda: len(ssip_server.messages), i + 1))
            ssip_server.messages[:] = ssip_server.messages[: i + 1]
            speech.cancel()
            await asyncio.sleep(0.002)
    finally:
        await backend.stop()
        await driver.terminate()
    _report("evdev -> socket SSIP (CANCEL recebido)", samples)
    assert max(samples) < LIMIT_MS
