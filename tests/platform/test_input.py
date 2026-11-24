"""KeyboardInputProcessor + InputManager (despachante)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from nvda_linux import services
from nvda_linux.contracts import GestureDispatcher, InputGesture, KeyboardLayout
from nvda_linux.core.config import TomlConfigStore
from nvda_linux.inputCore import keys as k
from nvda_linux.inputCore.backend import KeyboardBackend, KeyHandler, RawKeyEvent
from nvda_linux.inputCore.dispatcher import InputManager
from nvda_linux.inputCore.gesture_map import GestureMap
from nvda_linux.inputCore.keyboard import KeyboardInputProcessor
from nvda_linux.inputCore.xkb import UsKeymap
from tests.platform.fakes import DictProvider, FakeChain, RecordingSpeech, recorder

KEY_T, KEY_H, KEY_A, KEY_F2, KEY_1 = 20, 35, 30, 60, 2


class InjectBackend(KeyboardBackend):
    name = "inject"
    can_suppress = True

    def __init__(self) -> None:
        super().__init__()
        self.injected: list[tuple[int, int]] = []
        self.released = 0
        self.regrabs = 0

    async def start(self, handler: KeyHandler) -> None:
        self.handler = handler

    async def stop(self) -> None:
        return None

    def inject(self, events: Sequence[tuple[int, int]]) -> bool:
        self.injected.extend(events)
        return True

    def release_grab(self) -> None:
        self.released += 1

    def regrab(self) -> None:
        self.regrabs += 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Rig:
    """Processador + despachante + backend falso + cadeia configurável."""

    def __init__(self, config: TomlConfigStore, providers: list[DictProvider]) -> None:
        self.speech = RecordingSpeech()
        self.chain = FakeChain(*providers)
        self.dispatcher = InputManager(
            config=config, speech=self.speech, chain=self.chain.chain, gesture_map=GestureMap()
        )
        self.clock = Clock()
        self.emergency = 0
        self.processor = KeyboardInputProcessor(
            self.dispatcher,
            config=config,
            keymap=UsKeymap(),
            on_emergency=self._emergency,
            clock=self.clock,
        )
        self.backend = InjectBackend()
        self.processor.backend = self.backend
        self.dispatcher.set_sender(self.processor.send_gesture)

    def _emergency(self) -> None:
        self.emergency += 1

    def key(self, code: int, value: int, suppressed: bool | None = None) -> bool:
        return self.processor.handle(RawKeyEvent(code, value, self.clock.now, suppressed))

    def tap(self, code: int) -> tuple[bool, bool]:
        return self.key(code, 1), self.key(code, 0)

    def advance(self, seconds: float) -> None:
        self.clock.now += seconds


def make_rig(config: TomlConfigStore, scripts: dict[str, object] | None = None) -> Rig:
    return Rig(config, [DictProvider(scripts or {})])  # type: ignore[arg-type]


# ------------------------------------------------------------------ contrato
def test_dispatcher_implements_contract(config: TomlConfigStore) -> None:
    assert isinstance(make_rig(config).dispatcher, GestureDispatcher)


# ------------------------------------------------------------------ tecla NVDA
async def test_nvda_key_combo_runs_script_and_swallows(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:nvda+t": script})
    assert rig.key(k.KEY_INSERT, 1) is True
    assert rig.key(KEY_T, 1) is True
    assert rig.key(KEY_T, 0) is True
    assert rig.key(k.KEY_INSERT, 0) is True
    await rig.dispatcher.drain()
    assert [g.identifier for g in calls] == ["kb:nvda+t"]
    assert rig.speech.cancels == 1  # speechEffectWhenExecuted padrão = cancelar
    assert rig.backend.injected == []


async def test_modifier_order_is_alphabetical(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:control+nvda+shift+t": script})
    rig.key(k.KEY_LEFTSHIFT, 1)
    rig.key(k.KEY_INSERT, 1)
    rig.key(k.KEY_RIGHTCTRL, 1)
    assert rig.key(KEY_T, 1) is True
    await rig.dispatcher.drain()
    assert calls and calls[0].identifier == "kb:control+nvda+shift+t"
    assert calls[0].extra["modifiers"] == ("control", "nvda", "shift")


async def test_nvda_combo_without_script_is_swallowed(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.key(k.KEY_INSERT, 1)
    assert rig.key(KEY_H, 1) is True
    assert rig.key(KEY_H, 0) is True


def test_double_tap_nvda_key_passes_original(config: TomlConfigStore) -> None:
    config.set("keyboard.useCapsLockAsNVDAModifierKey", True)
    rig = make_rig(config)
    assert rig.tap(k.KEY_CAPSLOCK) == (True, True)
    rig.advance(0.2)
    assert rig.tap(k.KEY_CAPSLOCK) == (True, True)
    assert rig.backend.injected == [(k.KEY_CAPSLOCK, 1), (k.KEY_CAPSLOCK, 0)]


def test_slow_double_tap_does_not_pass(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.tap(k.KEY_INSERT)
    rig.advance(0.5)
    rig.tap(k.KEY_INSERT)
    assert rig.backend.injected == []


def test_capslock_is_normal_key_when_not_nvda(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    assert rig.tap(k.KEY_CAPSLOCK) == (False, False)


def test_numpad_insert_depends_on_numlock(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    assert rig.processor.is_nvda_key(k.KEY_KP0)
    rig.processor.numlock = True
    assert not rig.processor.is_nvda_key(k.KEY_KP0)
    config.set("keyboard.useNumpadInsertAsNVDAModifierKey", False)
    rig.processor.numlock = False
    assert not rig.processor.is_nvda_key(k.KEY_KP0)


async def test_numlock_toggle_changes_numpad_names(config: TomlConfigStore) -> None:
    seen: list[str] = []

    class Any_(DictProvider):
        def get_script(self, gesture: InputGesture) -> None:
            seen.append(gesture.identifier)

    rig = Rig(config, [Any_()])
    rig.tap(k.KEY_KP8)
    rig.tap(k.KEY_NUMLOCK)
    rig.tap(k.KEY_KP8)
    assert "kb:numpad8" in seen and "kb:numlocknumpad8" in seen


# ------------------------------------------------------------------ modificadores
def test_plain_typing_passes_through_with_echo(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.key(k.KEY_LEFTSHIFT, 1)
    assert rig.key(KEY_A, 1) is False
    assert rig.key(KEY_A, 0) is False
    rig.key(k.KEY_LEFTSHIFT, 0)
    assert rig.speech.typed == ["A"]
    assert rig.speech.cancels == 1  # speechInterruptForCharacters


def test_control_alone_cancels_speech_shift_tap_pauses(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    assert rig.tap(k.KEY_LEFTCTRL) == (False, False)
    assert rig.speech.cancels == 1
    rig.tap(k.KEY_LEFTSHIFT)
    assert rig.speech.paused == [True]
    rig.tap(k.KEY_LEFTSHIFT)
    assert rig.speech.paused == [True, False]


def test_shift_used_with_letter_does_not_pause(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.key(k.KEY_LEFTSHIFT, 1)
    rig.tap(KEY_A)
    rig.key(k.KEY_LEFTSHIFT, 0)
    assert rig.speech.paused == []


async def test_repeat_count(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:nvda+t": script})
    rig.key(k.KEY_INSERT, 1)
    rig.tap(KEY_T)
    rig.advance(0.2)
    rig.tap(KEY_T)
    rig.advance(1.0)
    rig.tap(KEY_T)
    await rig.dispatcher.drain()
    assert [g.repeat_count for g in calls] == [0, 1, 0]


# ------------------------------------------------------------------ segurança
def test_emergency_combo(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.key(k.KEY_LEFTCTRL, 1)
    rig.key(k.KEY_LEFTALT, 1)
    rig.key(k.KEY_LEFTSHIFT, 1)
    assert rig.key(k.KEY_ESC, 1) is True
    assert rig.emergency == 1 and rig.backend.released == 1


def test_exception_releases_grab(config: TomlConfigStore) -> None:
    rig = make_rig(config)

    def boom(gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        raise RuntimeError("bug")

    rig.dispatcher.process_gesture = boom  # type: ignore[method-assign]
    assert rig.key(KEY_A, 1) is False
    assert rig.backend.released == 1


def _break_dispatcher(rig: Rig) -> list[bool]:
    warnings: list[bool] = []
    rig.processor.on_input_error = warnings.append
    rig.processor.regrab_delay = 0.01

    def boom(gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        raise RuntimeError("bug")

    rig.dispatcher.process_gesture = boom  # type: ignore[method-assign]
    return warnings


async def test_exception_warns_and_regrabs(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    warnings = _break_dispatcher(rig)
    rig.key(k.KEY_INSERT, 1)
    assert rig.key(KEY_A, 1) is False
    assert rig.processor.nvda_held is False  # estado esquecido
    assert warnings == [False]
    await asyncio.sleep(0.05)
    assert rig.backend.regrabs == 1


async def test_repeated_exceptions_give_up(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    warnings = _break_dispatcher(rig)
    for _ in range(5):
        rig.key(KEY_A, 1)
        rig.advance(1.0)
    assert warnings == [False, True]  # avisa no 1º erro e quando desiste
    await asyncio.sleep(0.05)
    assert rig.backend.regrabs == 0
    assert rig.backend.released == 5


async def test_errors_outside_window_do_not_give_up(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    warnings = _break_dispatcher(rig)
    for _ in range(5):
        rig.key(KEY_A, 1)
        rig.advance(31.0)
    assert True not in warnings
    await asyncio.sleep(0.05)
    assert rig.backend.regrabs == 5


# ------------------------------------------------------------------ despachante
async def test_chain_order_first_provider_wins(config: TomlConfigStore) -> None:
    first_calls, first = recorder()
    second_calls, second = recorder()
    rig = Rig(config, [DictProvider({"kb:h": first}), DictProvider({"kb:h": second})])
    assert rig.tap(KEY_H) == (True, True)
    await rig.dispatcher.drain()
    assert len(first_calls) == 1 and second_calls == []


async def test_async_script_and_failing_script(config: TomlConfigStore) -> None:
    done: list[str] = []

    async def slow(gesture: InputGesture) -> None:
        await asyncio.sleep(0.01)
        done.append(gesture.identifier)

    def broken(gesture: InputGesture) -> None:
        raise ValueError("falha de script")

    rig = make_rig(config, {"kb:nvda+a": slow, "kb:nvda+b": broken})
    rig.key(k.KEY_INSERT, 1)
    rig.tap(KEY_A)
    rig.tap(48)  # b
    await rig.dispatcher.drain()
    assert done == ["kb:nvda+a"]


async def test_speech_effect_none_does_not_cancel(config: TomlConfigStore) -> None:
    calls, script = recorder()
    script.speechEffectWhenExecuted = None  # type: ignore[attr-defined]
    rig = make_rig(config, {"kb:h": script})
    rig.tap(KEY_H)
    await rig.dispatcher.drain()
    assert calls and rig.speech.cancels == 0


async def test_input_help_reports_without_running(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:nvda+t": script})
    rig.key(k.KEY_INSERT, 1)
    rig.tap(KEY_1)
    await rig.dispatcher.drain()
    assert rig.dispatcher.input_help
    rig.tap(KEY_T)
    assert rig.tap(KEY_A) == (True, True)  # até teclas comuns são engolidas
    rig.tap(KEY_1)
    await rig.dispatcher.drain()
    assert not rig.dispatcher.input_help
    assert calls == []
    assert "NVDA+t: Script de teste" in rig.speech.spoken
    assert "Ajuda de entrada ativada" in rig.speech.spoken
    assert rig.speech.spoken[-1] == "Ajuda de entrada desativada"


async def test_pass_next_key_through(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:h": script, "kb:nvda+t": script})
    rig.key(k.KEY_INSERT, 1)
    rig.tap(KEY_F2)
    rig.key(k.KEY_INSERT, 0)
    await rig.dispatcher.drain()
    assert rig.dispatcher.pass_next
    assert rig.tap(KEY_H) == (False, False)
    assert not rig.dispatcher.pass_next
    rig.key(k.KEY_INSERT, 1)
    rig.tap(KEY_F2)
    await rig.dispatcher.drain()
    assert rig.key(KEY_T, 1) is True  # NVDA+T repassado: reinjeta Insert+T
    assert rig.backend.injected == [
        (k.KEY_INSERT, 1),
        (KEY_T, 1),
        (KEY_T, 0),
        (k.KEY_INSERT, 0),
    ]
    assert calls == []


def test_send_through_reinjects(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    gesture = InputGesture("kb:control+shift+downarrow")
    rig.dispatcher.send_through(gesture)
    assert rig.backend.injected == [
        (k.KEY_LEFTCTRL, 1),
        (k.KEY_LEFTSHIFT, 1),
        (k.KEY_DOWN, 1),
        (k.KEY_DOWN, 0),
        (k.KEY_LEFTSHIFT, 0),
        (k.KEY_LEFTCTRL, 0),
    ]


async def test_laptop_layout_uses_desktop_equivalent(config: TomlConfigStore) -> None:
    calls, script = recorder()
    config.set("keyboard.keyboardLayout", "laptop")
    rig = make_rig(config, {"kb:nvda+numpad8": script})
    assert rig.dispatcher.layout is KeyboardLayout.LAPTOP
    rig.key(k.KEY_INSERT, 1)
    rig.key(k.KEY_LEFTSHIFT, 1)
    assert rig.tap(k.KEY_UP) == (True, True)
    await rig.dispatcher.drain()
    assert calls[0].identifier == "kb:nvda+numpad8"
    assert calls[0].extra["laptop_identifier"] == "kb:nvda+shift+uparrow"


async def test_layout_override(config: TomlConfigStore) -> None:
    rig = make_rig(config)
    rig.dispatcher.set_layout(KeyboardLayout.LAPTOP)
    assert rig.dispatcher.layout is KeyboardLayout.LAPTOP


async def test_suppressed_false_never_runs_scripts(config: TomlConfigStore) -> None:
    calls, script = recorder()
    rig = make_rig(config, {"kb:h": script})
    assert rig.key(KEY_H, 1, suppressed=False) is False
    await rig.dispatcher.drain()
    assert calls == []


async def test_gesture_map_bindings_in_extra(config: TomlConfigStore) -> None:
    seen: list[InputGesture] = []

    class Spy(DictProvider):
        def get_script(self, gesture: InputGesture) -> None:
            seen.append(gesture)

    rig = Rig(config, [Spy()])
    rig.dispatcher.gesture_map.loads("[browseMode.X]\nnextHeading = kb:h\n")
    rig.tap(KEY_H)
    assert seen[0].extra["bindings"] == [("browseMode.X", "nextHeading")]


async def test_default_chain_uses_services(config: TomlConfigStore) -> None:
    calls, script = recorder()
    services.register("script_chain", FakeChain(DictProvider({"kb:h": script})))
    dispatcher = InputManager(config=config, speech=RecordingSpeech())
    gesture = InputGesture("kb:h", extra={"modifiers": ()})
    assert dispatcher.process_gesture(gesture) is True
    await dispatcher.drain()
    assert calls == [gesture]


def test_missing_chain_service_means_passthrough(config: TomlConfigStore) -> None:
    dispatcher = InputManager(config=config, speech=RecordingSpeech())
    assert dispatcher.process_gesture(InputGesture("kb:h", extra={"modifiers": ()})) is False


@pytest.mark.parametrize("value", [1, 2])
def test_unknown_key_passes(config: TomlConfigStore, value: int) -> None:
    rig = make_rig(config)
    assert rig.key(0x2BF, value) is False
