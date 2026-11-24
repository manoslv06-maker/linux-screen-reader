"""Application: partida/parada com fakes, SEMÂNTICA opcional, emergência."""

from __future__ import annotations

import asyncio
import sys
import types
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from nvda_linux import services
from nvda_linux.braille.handler import BrailleHandler
from nvda_linux.contracts import (
    BrailleOutput,
    ConfigStore,
    GestureDispatcher,
    SpeechOutput,
    ToneOutput,
)
from nvda_linux.core.app import Application, AppOptions
from nvda_linux.core.config import TomlConfigStore
from nvda_linux.inputCore import keys as k
from nvda_linux.inputCore.backend import (
    BackendUnavailable,
    KeyboardBackend,
    KeyHandler,
    RawKeyEvent,
)
from nvda_linux.speech.audio import NullPlayer
from nvda_linux.speech.driver import SynthDriver
from tests.platform.fakes import FakeDriver

BOOTSTRAP = "nvda_linux._fake_bootstrap_for_tests"


class ManualBackend(KeyboardBackend):
    name = "manual"
    can_suppress = True

    def __init__(self) -> None:
        super().__init__()
        self.released = 0
        self.stopped = False

    async def start(self, handler: KeyHandler) -> None:
        self.handler = handler

    async def stop(self) -> None:
        self.stopped = True

    def release_grab(self) -> None:
        self.released += 1

    def press(self, code: int, value: int = 1) -> bool:
        assert self.handler is not None
        return self.handler(RawKeyEvent(code, value, 0.0))


class DeniedBackend(KeyboardBackend):
    name = "denied"

    async def start(self, handler: KeyHandler) -> None:
        raise BackendUnavailable("sem /dev/input", permission=True)

    async def stop(self) -> None:
        return None


@pytest.fixture
def fake_bootstrap(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    calls = {"start": 0, "stop": 0}
    module = types.ModuleType(BOOTSTRAP)

    async def start() -> None:
        calls["start"] += 1
        assert isinstance(services.speech(), SpeechOutput)

    async def stop() -> None:
        calls["stop"] += 1

    module.start = start  # type: ignore[attr-defined]
    module.stop = stop  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, BOOTSTRAP, module)
    monkeypatch.setattr(services, "SEMANTICS_BOOTSTRAP_MODULE", BOOTSTRAP)
    yield calls


def make_app(
    config: TomlConfigStore,
    backend: Callable[[], KeyboardBackend],
    *,
    driver: FakeDriver | None = None,
    load_semantics: bool = True,
) -> tuple[Application, FakeDriver]:
    drv = driver or FakeDriver(auto_done=True)

    async def synth(name: str, get: Callable[[str, Any], Any]) -> SynthDriver:
        return drv

    async def braille(cfg: ConfigStore, disp: Any) -> BrailleHandler:
        return BrailleHandler(config=cfg, dispatcher=disp)

    app = Application(
        AppOptions(load_semantics=load_semantics, play_sounds=False, keyboard_backend="manual"),
        config=config,
        synth_factory=synth,
        audio_player=NullPlayer(),
        braille_factory=braille,
        backend_factories={"manual": backend},
    )
    return app, drv


async def test_start_registers_services_and_runs_semantics(
    config: TomlConfigStore, fake_bootstrap: dict[str, int]
) -> None:
    backend = ManualBackend()
    app, _ = make_app(config, lambda: backend)
    await app.start()
    assert isinstance(services.speech(), SpeechOutput)
    assert isinstance(services.tones(), ToneOutput)
    assert isinstance(services.braille(), BrailleOutput)
    assert isinstance(services.config(), ConfigStore)
    assert isinstance(services.dispatcher(), GestureDispatcher)
    assert fake_bootstrap["start"] == 1 and app.semantics_error is None
    await app.stop()
    assert fake_bootstrap["stop"] == 1
    assert backend.stopped and backend.released >= 1
    assert (config.directory / "nvda.toml").exists()


async def test_missing_semantics_is_tolerated(
    config: TomlConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "SEMANTICS_BOOTSTRAP_MODULE", "nvda_linux._nao_existe_xyz")
    app, _ = make_app(config, ManualBackend)
    await app.start()
    assert app.semantics_error is not None and "não existe" in app.semantics_error
    await app.stop()


async def test_broken_semantics_start_is_logged(
    config: TomlConfigStore, fake_bootstrap: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise RuntimeError("AT-SPI2 fora do ar")

    monkeypatch.setattr(sys.modules[BOOTSTRAP], "start", boom)
    app, _ = make_app(config, ManualBackend)
    await app.start()
    assert app.semantics_error is not None and "AT-SPI2" in app.semantics_error
    await app.stop()


async def test_keyboard_permission_problem_is_spoken(config: TomlConfigStore) -> None:
    app, driver = make_app(config, DeniedBackend, load_semantics=False)
    await app.start()
    assert app.backend is not None and app.backend.name == "none"
    assert any("permissão para ler o teclado" in t for t in driver.texts)
    await app.stop()


async def test_emergency_combo_requests_exit(config: TomlConfigStore) -> None:
    backend = ManualBackend()
    app, _ = make_app(config, lambda: backend, load_semantics=False)
    app.emergency_exit = lambda: app.request_exit(3)  # type: ignore[method-assign]
    assert app.processor is None
    run = asyncio.ensure_future(app.run())
    await asyncio.sleep(0.05)
    assert app.processor is not None
    app.processor.on_emergency = app.emergency_exit
    for code in (k.KEY_LEFTCTRL, k.KEY_LEFTALT, k.KEY_LEFTSHIFT):
        backend.press(code)
    backend.press(k.KEY_ESC)
    assert await asyncio.wait_for(run, 3) == 3
    assert backend.released >= 1 and backend.stopped


async def test_run_exits_on_request(config: TomlConfigStore) -> None:
    app, _ = make_app(config, ManualBackend, load_semantics=False)
    run = asyncio.ensure_future(app.run())
    await asyncio.sleep(0.05)
    services.register("dummy", object())
    app_service = services._registry["app"]
    assert app_service is app
    app.request_exit(0)
    assert await asyncio.wait_for(run, 3) == 0
