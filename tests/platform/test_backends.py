"""EvdevBackend e KeyboardMonitorBackend com fakes; escolha automática."""

from __future__ import annotations

import errno
from collections.abc import Iterator
from pathlib import Path

import pytest

from nvda_linux.contracts import InputGesture
from nvda_linux.core.config import TomlConfigStore
from nvda_linux.inputCore import evdev_backend
from nvda_linux.inputCore import keys as k
from nvda_linux.inputCore.backend import (
    BackendUnavailable,
    KeyboardBackend,
    KeyHandler,
    RawKeyEvent,
    UInputInjector,
)
from nvda_linux.inputCore.dispatcher import InputManager
from nvda_linux.inputCore.evdev_backend import EvdevBackend
from nvda_linux.inputCore.factory import select_backend
from nvda_linux.inputCore.keyboard import KeyboardInputProcessor
from nvda_linux.inputCore.keyboard_monitor import KeyboardMonitorBackend
from tests.platform.fakes import (
    KEYBOARD_KEYS,
    DictProvider,
    FakeChain,
    FakeInputDevice,
    FakeMonitorConnection,
    RecordingSpeech,
    make_fake_evdev,
    recorder,
    wait_for,
)

_REAL_READABLE_EVENT_NODES = evdev_backend.readable_event_nodes


class OpenInjector(UInputInjector):
    """Injector que não exige /dev/uinput real."""

    def open(self) -> None:
        assert self._evdev is not None
        self._ui = self._evdev.UInput({1: self.key_capabilities()}, name=self.DEVICE_NAME)


class DeniedInjector(UInputInjector):
    def open(self) -> None:
        raise BackendUnavailable("sem uinput", permission=True)


@pytest.fixture
def devices() -> Iterator[list[FakeInputDevice]]:
    devs = [
        FakeInputDevice("/dev/input/event3", "AT Translated Keyboard", KEYBOARD_KEYS, leds=[0]),
        FakeInputDevice("/dev/input/event4", "Power Button", [116]),
        FakeInputDevice("/dev/input/event5", UInputInjector.DEVICE_NAME, KEYBOARD_KEYS),
    ]
    yield devs
    for d in devs:
        d.close()


@pytest.fixture(autouse=True)
def readable_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evdev_backend, "readable_event_nodes", lambda pattern="": (["/dev/input/event3"], [])
    )


def recording_handler(consume: set[int]) -> tuple[list[RawKeyEvent], KeyHandler]:
    seen: list[RawKeyEvent] = []

    def handler(ev: RawKeyEvent) -> bool:
        seen.append(ev)
        return ev.code in consume

    return seen, handler


# ------------------------------------------------------------------ evdev
async def test_evdev_grabs_keyboards_and_forwards(devices: list[FakeInputDevice]) -> None:
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, OpenInjector(fake), rescan_interval=60)
    seen, handler = recording_handler(consume={k.KEY_INSERT})
    await backend.start(handler)
    kbd, power, own = devices
    assert kbd.grabbed and not power.grabbed and not own.grabbed
    assert backend.grabbing and backend.numlock is True
    kbd.push(30, 1)
    kbd.push(30, 0)
    kbd.push(k.KEY_INSERT, 1)
    await wait_for(lambda: len(seen) == 3)
    ui = fake.uinputs[0]
    assert ui.keys == [(30, 1), (30, 0)]  # Insert foi engolido
    assert seen[0].suppressed is None
    await backend.stop()
    assert not kbd.grabbed and ui.closed


async def test_evdev_release_grab_unsticks_keys_and_regrab(
    devices: list[FakeInputDevice],
) -> None:
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, OpenInjector(fake), rescan_interval=60)
    seen, handler = recording_handler(consume=set())
    await backend.start(handler)
    kbd = devices[0]
    kbd.push(k.KEY_LEFTCTRL, 1)
    await wait_for(lambda: len(seen) == 1)
    backend.release_grab()
    ui = fake.uinputs[0]
    assert not kbd.grabbed
    assert ui.keys[-1] == (k.KEY_LEFTCTRL, 0)  # Ctrl virtual solto
    kbd.push(30, 1)
    await wait_for(lambda: len(seen) == 2)
    assert seen[-1].suppressed is False  # sem grab: só monitorando
    assert ui.keys.count((30, 1)) == 0  # e sem reemitir (o compositor já recebeu)
    kbd.active = [30]
    backend.regrab()
    assert not kbd.grabbed  # tecla física pressionada: espera
    kbd.active = []
    await wait_for(lambda: kbd.grabbed)
    await backend.stop()


async def test_evdev_handler_exception_releases_grab(devices: list[FakeInputDevice]) -> None:
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, OpenInjector(fake), rescan_interval=60)

    def handler(ev: RawKeyEvent) -> bool:
        raise RuntimeError("bug")

    await backend.start(handler)
    devices[0].push(30, 1)
    await wait_for(lambda: not devices[0].grabbed)
    await backend.stop()


async def test_evdev_without_uinput_is_monitor_only(devices: list[FakeInputDevice]) -> None:
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, DeniedInjector(fake), rescan_interval=60)
    seen, handler = recording_handler(consume={30})
    await backend.start(handler)
    assert not backend.grabbing
    devices[0].push(30, 1)
    await wait_for(lambda: len(seen) == 1)
    assert seen[0].suppressed is False
    assert not backend.inject([(30, 1)])
    await backend.stop()


async def test_evdev_grab_busy_is_tolerated(devices: list[FakeInputDevice]) -> None:
    devices[0].grab_error = OSError(errno.EBUSY, "busy")
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, OpenInjector(fake), rescan_interval=60)
    _, handler = recording_handler(set())
    await backend.start(handler)
    assert not backend.grabbing
    await backend.stop()


async def test_evdev_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evdev_backend, "readable_event_nodes", lambda pattern="": ([], ["/dev/input/event0"])
    )
    backend = EvdevBackend(make_fake_evdev([]))
    with pytest.raises(BackendUnavailable) as info:
        await backend.start(lambda ev: False)
    assert info.value.permission


async def test_evdev_device_removal(devices: list[FakeInputDevice]) -> None:
    fake = make_fake_evdev(devices)
    backend = EvdevBackend(fake, OpenInjector(fake), rescan_interval=60)
    _, handler = recording_handler(set())
    await backend.start(handler)
    kbd = devices[0]

    def gone() -> list[object]:
        raise OSError(errno.ENODEV, "No such device")

    kbd.read = gone  # type: ignore[method-assign,assignment]
    import os

    os.write(kbd._w, b"x")
    await wait_for(lambda: backend.devices == [])
    await backend.stop()


def test_readable_event_nodes(tmp_path: Path) -> None:
    (tmp_path / "event0").write_text("")
    ok, denied = _REAL_READABLE_EVENT_NODES(str(tmp_path / "event*"))
    assert ok == [str(tmp_path / "event0")] and denied == []


# ------------------------------------------------------------------ KeyboardMonitor
class Source:
    """GrabSource falso usando um InputManager real."""

    def __init__(self, config: TomlConfigStore, scripts: dict[str, object]) -> None:
        self.manager = InputManager(
            config=config,
            speech=RecordingSpeech(),
            chain=FakeChain(DictProvider(scripts)).chain,  # type: ignore[arg-type]
        )


async def test_monitor_grabs_and_events(config: TomlConfigStore) -> None:
    _calls, script = recorder()
    src = Source(config, {"kb:h": script, "kb:shift+h": script})
    conn = FakeMonitorConnection()

    async def connect() -> FakeMonitorConnection:
        return conn

    backend = KeyboardMonitorBackend(
        connect, source=src.manager, injector=UInputInjector(evdev=None), refresh_interval=60
    )
    seen, handler = recording_handler(set())
    await backend.start(handler)
    assert conn.members()[:2] == ["WatchKeyboard", "SetKeyGrabs"]
    modifiers, keystrokes = conn.last("SetKeyGrabs")
    assert modifiers == [k.XK_INSERT, k.XK_KP_INSERT]
    assert [ord("h"), 0] in keystrokes and [ord("h"), k.MASK_SHIFT] in keystrokes
    assert [ord("H"), k.MASK_SHIFT] in keystrokes
    conn.key(35, released=False, keysym=ord("h"), unichar=ord("h"))  # h: grab
    conn.key(35, released=True, keysym=ord("h"))
    conn.key(30, released=False, keysym=ord("a"), unichar=ord("a"))  # a: livre
    conn.key(k.KEY_INSERT, released=False)
    conn.key(30, released=False)  # repetição com NVDA segura? não: 'a' já está pressionada
    assert [e.suppressed for e in seen] == [True, True, False, True, False]
    assert seen[0].char == "h" and seen[1].value == 0 and seen[4].value == 2
    await backend.stop()
    assert conn.closed and "UnwatchKeyboard" in conn.members()


async def test_monitor_input_help_grabs_everything(config: TomlConfigStore) -> None:
    src = Source(config, {})
    conn = FakeMonitorConnection()

    async def connect() -> FakeMonitorConnection:
        return conn

    backend = KeyboardMonitorBackend(
        connect, source=src.manager, injector=UInputInjector(evdev=None), refresh_interval=60
    )
    await backend.start(lambda ev: False)
    src.manager.set_input_help(True)
    await backend.refresh_grabs()
    assert "GrabKeyboard" in conn.members()
    seen, handler = recording_handler(set())
    backend.handler = handler
    conn.key(30, released=False)
    assert seen[0].suppressed is True
    src.manager.set_input_help(False)
    await backend.refresh_grabs()
    assert "UngrabKeyboard" in conn.members()
    await backend.stop()


async def test_monitor_without_owner_is_unavailable() -> None:
    conn = FakeMonitorConnection(owner=False)

    async def connect() -> FakeMonitorConnection:
        return conn

    backend = KeyboardMonitorBackend(connect, injector=UInputInjector(evdev=None))
    with pytest.raises(BackendUnavailable):
        await backend.start(lambda ev: False)
    assert conn.closed


async def test_monitor_double_tap_left_to_compositor(config: TomlConfigStore) -> None:
    src = Source(config, {})
    conn = FakeMonitorConnection()

    async def connect() -> FakeMonitorConnection:
        return conn

    backend = KeyboardMonitorBackend(
        connect, source=src.manager, injector=UInputInjector(evdev=None), refresh_interval=60
    )
    processor = KeyboardInputProcessor(src.manager, config=config)
    processor.backend = backend
    await backend.start(processor.handle)
    for _ in range(2):
        conn.key(k.KEY_INSERT, released=False)
        conn.key(k.KEY_INSERT, released=True)
    assert backend.inject([(1, 1)]) is False  # nada injetado; o compositor repassa
    await backend.stop()


# ------------------------------------------------------------------ seleção
class Unavailable(KeyboardBackend):
    name = "unavailable"

    def __init__(self, permission: bool = False) -> None:
        super().__init__()
        self.permission = permission

    async def start(self, handler: KeyHandler) -> None:
        raise BackendUnavailable("não", permission=self.permission)

    async def stop(self) -> None:
        return None


class Working(Unavailable):
    name = "working"

    async def start(self, handler: KeyHandler) -> None:
        self.handler = handler


async def test_select_backend_auto_order(config: TomlConfigStore) -> None:
    manager = InputManager(config=config, speech=RecordingSpeech())
    processor = KeyboardInputProcessor(manager, config=config)
    choice = await select_backend(
        "auto",
        processor,
        manager,
        config,
        factories={"keyboardMonitor": Unavailable, "evdev": Working},
    )
    assert choice.backend.name == "working" and len(choice.errors) == 1
    assert processor.backend is choice.backend


async def test_select_backend_reports_permission_problem(config: TomlConfigStore) -> None:
    manager = InputManager(config=config, speech=RecordingSpeech())
    processor = KeyboardInputProcessor(manager, config=config)
    choice = await select_backend(
        "auto",
        processor,
        manager,
        config,
        factories={"keyboardMonitor": Unavailable, "evdev": lambda: Unavailable(True)},
    )
    assert choice.backend.name == "none" and choice.permission_problem
    manager.send_through(InputGesture("kb:a"))  # sem sender: só avisa no log


async def test_refresh_grabs_hook_reaches_monitor(config: TomlConfigStore) -> None:
    scripts: dict[str, object] = {}
    src = Source(config, scripts)
    conn = FakeMonitorConnection()

    async def connect() -> FakeMonitorConnection:
        return conn

    backend = KeyboardMonitorBackend(
        connect, source=src.manager, injector=UInputInjector(evdev=None), refresh_interval=60
    )
    src.manager.add_state_listener(backend.schedule_refresh)
    await backend.start(lambda ev: False)
    assert conn.last("SetKeyGrabs")[1] == []
    _calls, script = recorder()
    scripts["kb:k"] = script
    src.manager._chain = FakeChain(DictProvider(scripts)).chain  # type: ignore[arg-type]
    src.manager.refresh_grabs()
    await wait_for(lambda: [ord("k"), 0] in conn.last("SetKeyGrabs")[1])
    await backend.stop()
