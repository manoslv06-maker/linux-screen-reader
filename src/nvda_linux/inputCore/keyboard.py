"""Processamento de teclado: estado de modificadores, tecla NVDA e gestos.

Equivale ao ``keyboardHandler`` do NVDA. Recebe :class:`RawKeyEvent` do
backend e decide, de forma síncrona (o backend está esperando), se a tecla
é engolida ou repassada ao sistema:

- **tecla NVDA** (Insert, Insert numérico com NumLock desligado, Caps Lock;
  conforme ``keyboard.use*AsNVDAModifierKey``): sempre engolida. Dois
  toques em menos de ``keyboard.doubleTapTimeoutMs`` (350 ms) repassam a
  tecla original (por exemplo, para ligar o Caps Lock);
- **modificadores comuns** (Ctrl, Shift, Alt, Windows): sempre repassados
  na hora. Ctrl sozinho interrompe a fala e Shift sozinho (toque) pausa,
  como no NVDA;
- **demais teclas**: viram :class:`~nvda_linux.contracts.InputGesture` e vão
  ao despachante; se ele usar o gesto, a tecla (e sua soltura) é engolida;
- **emergência**: Ctrl+Alt+Shift+Esc solta o teclado e encerra o leitor,
  antes de qualquer outra lógica.

Qualquer exceção aqui dentro solta o grab do teclado (o usuário nunca pode
ficar sem teclado por um bug do leitor).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol

from nvda_linux.contracts import ConfigStore, InputGesture, KeyboardLayout
from nvda_linux.core.log import IO, get_logger
from nvda_linux.inputCore.backend import KeyboardBackend, RawKeyEvent, tap_sequence
from nvda_linux.inputCore.gesture import keyboard_gesture, parse_identifier
from nvda_linux.inputCore.keys import (
    KEY_CAPSLOCK,
    KEY_ESC,
    KEY_INSERT,
    KEY_KP0,
    KEY_LEFTCTRL,
    KEY_NUMLOCK,
    KEY_RIGHTALT,
    KEY_RIGHTCTRL,
    MODIFIER_INJECT,
    MODIFIER_KEYS,
    code_for_name,
    key_name,
)
from nvda_linux.inputCore.xkb import Keymap, UsKeymap

log = get_logger(__name__)


class GestureSink(Protocol):
    """O que o processador precisa do despachante."""

    @property
    def layout(self) -> KeyboardLayout: ...

    def process_gesture(self, gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        """True = gesto usado (engolir a tecla)."""

    def modifier_event(self, modifier: str, pressed: bool, lone: bool) -> None:
        """Ctrl/Shift sozinhos (interromper/pausar fala)."""


EMERGENCY_DESCRIPTION = "Ctrl+Alt+Shift+Esc"
#: Segundos entre soltar o teclado por um erro e pegá-lo de novo.
REGRAB_DELAY = 1.0
#: Mais erros que isso dentro da janela (s) e o leitor desiste de pegar o teclado.
MAX_INPUT_ERRORS = 3
INPUT_ERROR_WINDOW = 30.0


class KeyboardInputProcessor:
    """Máquina de estados do teclado (um por sessão, compartilhada entre teclados)."""

    def __init__(
        self,
        sink: GestureSink,
        *,
        config: ConfigStore | None = None,
        keymap: Keymap | None = None,
        on_emergency: Callable[[], None] | None = None,
        on_input_error: Callable[[bool], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sink = sink
        self.config = config
        self.keymap: Keymap = keymap or UsKeymap()
        self.on_emergency = on_emergency
        self.clock = clock
        self.backend: KeyboardBackend | None = None
        self.numlock = False
        self._pressed: set[int] = set()
        self._swallowed: set[int] = set()
        self._nvda_down: int | None = None
        self._nvda_used = False
        self._last_tap: tuple[int, float] | None = None
        self._lone_modifier: int | None = None
        self._last_gesture: tuple[str, float, int] | None = None
        self.last_handle_ns = 0
        #: Chamado com ``gave_up`` quando um erro soltou o teclado (para avisar o usuário).
        self.on_input_error = on_input_error
        self.regrab_delay = REGRAB_DELAY
        self._error_times: list[float] = []
        self._gave_up = False

    # ------------------------------------------------------------ configuração
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def is_nvda_key(self, code: int) -> bool:
        if code == KEY_INSERT:
            return bool(self._cfg("keyboard.useExtendedInsertAsNVDAModifierKey", True))
        if code == KEY_KP0:
            return not self.numlock and bool(
                self._cfg("keyboard.useNumpadInsertAsNVDAModifierKey", True)
            )
        if code == KEY_CAPSLOCK:
            return bool(self._cfg("keyboard.useCapsLockAsNVDAModifierKey", False))
        return False

    def nvda_key_code(self) -> int:
        """Tecla usada para reinjetar "NVDA" em ``send_through``."""
        if self._cfg("keyboard.useExtendedInsertAsNVDAModifierKey", True):
            return KEY_INSERT
        if self._cfg("keyboard.useCapsLockAsNVDAModifierKey", False):
            return KEY_CAPSLOCK
        return KEY_KP0

    @property
    def nvda_held(self) -> bool:
        return self._nvda_down is not None

    def held_modifiers(self) -> set[str]:
        mods = {MODIFIER_KEYS[c] for c in self._pressed if c in MODIFIER_KEYS}
        if self._nvda_down is not None:
            mods.add("nvda")
        return mods

    # ------------------------------------------------------------ entrada
    def handle(self, event: RawKeyEvent) -> bool:
        """Processa um evento. True = engolir. Nunca propaga exceções."""
        start = time.perf_counter_ns()
        try:
            return self._handle(event)
        except Exception:
            log.exception("Erro processando tecla %s; soltando o teclado", event.code)
            if self.backend is not None:
                try:
                    self.backend.release_grab()
                except Exception:
                    log.exception("Falha ao soltar o grab")
            self.reset()
            self._recover_after_error()
            return False
        finally:
            self.last_handle_ns = time.perf_counter_ns() - start

    def _recover_after_error(self) -> None:
        """Depois de soltar o teclado por um erro: avisa e pega de novo.

        Sem isso, no evdev, as teclas seguintes chegariam sem grab
        (``suppressed=False``) e nenhum comando do NVDA funcionaria mais, sem
        aviso. Com mais de ``MAX_INPUT_ERRORS`` erros em ``INPUT_ERROR_WINDOW``
        segundos o leitor desiste (o teclado fica só com o sistema).
        """
        if self._gave_up:
            return
        now = self.clock()
        self._error_times = [t for t in self._error_times if now - t < INPUT_ERROR_WINDOW]
        self._error_times.append(now)
        gave_up = len(self._error_times) > MAX_INPUT_ERRORS
        if gave_up:
            self._gave_up = True
            log.error("Erros repetidos no teclado: comandos do NVDA desligados até reiniciar")
        else:
            self._schedule_regrab()
        if (gave_up or len(self._error_times) == 1) and self.on_input_error is not None:
            try:
                self.on_input_error(gave_up)
            except Exception:
                log.exception("Aviso de erro de teclado falhou")

    def _schedule_regrab(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # fora do loop (testes síncronos): o watchdog ainda pode recuperar
        loop.call_later(self.regrab_delay, self._regrab)

    def _regrab(self) -> None:
        if self._gave_up or self.backend is None:
            return
        try:
            self.backend.regrab()
        except Exception:
            log.exception("Falha ao pegar o teclado de novo")

    def _handle(self, ev: RawKeyEvent) -> bool:
        code, value = ev.code, ev.value
        now = ev.timestamp or self.clock()

        # 1. Emergência: antes de tudo.
        if value == 1 and code == KEY_ESC and self._is_emergency_combo():
            log.warning("Combinação de emergência %s: encerrando", EMERGENCY_DESCRIPTION)
            if self.backend is not None:
                self.backend.release_grab()
            if self.on_emergency is not None:
                self.on_emergency()
            return True

        # 2. Tecla NVDA.
        if self.is_nvda_key(code) or (value != 1 and code == self._nvda_down):
            return self._handle_nvda_key(code, value, now, ev)

        # 3. Modificadores comuns: sempre repassados.
        if code in MODIFIER_KEYS:
            return self._handle_modifier(code, value, ev)

        # 4. Demais teclas.
        if value == 0:
            self._pressed.discard(code)
            self.keymap.update(code, False)
            if code in self._swallowed:
                self._swallowed.discard(code)
                return True
            return False

        self._lone_modifier = None
        if self._nvda_down is not None:
            self._nvda_used = True
        if value == 1:
            self._pressed.add(code)
        gesture = self._build_gesture(code, value, now, ev)
        if gesture is None:
            consumed = self._nvda_down is not None  # NVDA+tecla desconhecida: engole
        else:
            log.log(IO, "Tecla: %s", gesture.identifier)
            consumed = self.sink.process_gesture(gesture, suppressed=ev.suppressed)
            if not consumed and self._nvda_down is not None and ev.suppressed is None:
                # Repasse de NVDA+tecla (NVDA+F2): a tecla NVDA não foi enviada.
                self._inject_with_nvda(code)
                consumed = True
        if consumed:
            self._swallowed.add(code)
        else:
            self.keymap.update(code, True)
            if value == 1 and code == KEY_NUMLOCK:
                self.numlock = not self.numlock
        return consumed

    def _is_emergency_combo(self) -> bool:
        mods = {MODIFIER_KEYS[c] for c in self._pressed if c in MODIFIER_KEYS}
        return {"control", "alt", "shift"} <= mods

    def _handle_modifier(self, code: int, value: int, ev: RawKeyEvent) -> bool:
        name = MODIFIER_KEYS[code]
        if value == 1:
            lone = not self._pressed and self._nvda_down is None
            self._pressed.add(code)
            self.keymap.update(code, True)
            self._lone_modifier = code if lone else None
            if self._nvda_down is not None:
                self._nvda_used = True
            if lone and code in (KEY_LEFTCTRL, KEY_RIGHTCTRL):
                self.sink.modifier_event(name, True, True)
        elif value == 0:
            self._pressed.discard(code)
            self.keymap.update(code, False)
            if self._lone_modifier == code:
                self._lone_modifier = None
                self.sink.modifier_event(name, False, True)
        return False

    def _handle_nvda_key(self, code: int, value: int, now: float, ev: RawKeyEvent) -> bool:
        if value == 1:
            if self._nvda_down is None:
                self._nvda_down = code
                self._nvda_used = False
            self._lone_modifier = None
            return True
        if value == 2:
            return True
        # Soltou.
        if self._nvda_down != code:
            return True
        self._nvda_down = None
        if self._nvda_used:
            return True
        timeout = int(self._cfg("keyboard.doubleTapTimeoutMs", 350)) / 1000.0
        last = self._last_tap
        if last is not None and last[0] == code and now - last[1] < timeout:
            self._last_tap = None
            self._pass_original_key(code)
            return True
        self._last_tap = (code, now)
        gesture = keyboard_gesture(
            (),
            "nvda",
            layout=self.sink.layout,
            is_modifier_only=True,
            extra={"nvda_key": key_name(code, self.numlock)},
        )
        self.sink.process_gesture(gesture, suppressed=ev.suppressed)
        return True

    def _pass_original_key(self, code: int) -> None:
        """Duplo toque na tecla NVDA: envia a tecla original ao sistema."""
        log.debug("Duplo toque na tecla NVDA: repassando %s", key_name(code))
        if self.backend is not None and self.backend.compositor_double_tap:
            return  # o compositor (KeyboardMonitor) já repassou a tecla
        if self.backend is not None and self.backend.inject([(code, 1), (code, 0)]):
            self.keymap.update(code, True)
            self.keymap.update(code, False)

    def _inject_with_nvda(self, code: int) -> None:
        nvda = self._nvda_down if self._nvda_down is not None else self.nvda_key_code()
        if self.backend is not None:
            self.backend.inject([(nvda, 1), (code, 1), (code, 0), (nvda, 0)])

    # ------------------------------------------------------------ gestos
    def _character(self, code: int, mods: set[str]) -> str | None:
        blocking = mods - {"shift"}
        if blocking == {"alt"} and KEY_RIGHTALT in self._pressed:
            blocking = set()  # AltGr digita caracteres (ABNT2, layouts europeus)
        if blocking:
            return None
        return self.keymap.character(code)

    def _build_gesture(
        self, code: int, value: int, now: float, ev: RawKeyEvent
    ) -> InputGesture | None:
        name = key_name(code, self.numlock)
        if name is None:
            return None
        mods = self.held_modifiers()
        character = ev.char if ev.char is not None else self._character(code, mods)
        identifier_mods = sorted(mods)
        probe = f"kb:{'+'.join([*identifier_mods, name])}"
        repeat = 0
        if self._last_gesture is not None and self._last_gesture[0] == probe:
            _, t, count = self._last_gesture
            timeout = int(self._cfg("keyboard.repeatTimeoutMs", 500)) / 1000.0
            if value == 2:
                repeat = count
            elif now - t < timeout:
                repeat = count + 1
        self._last_gesture = (probe, now, repeat)
        return keyboard_gesture(
            mods,
            name,
            layout=self.sink.layout,
            character=character,
            repeat_count=repeat,
            extra={"keycode": code, "autorepeat": value == 2},
        )

    # ------------------------------------------------------------ reenvio
    def send_gesture(self, gesture: InputGesture) -> bool:
        """Reinjeta ``gesture`` (contrato ``send_through``). False se impossível."""
        if self.backend is None:
            return False
        try:
            parsed = parse_identifier(gesture.identifier)
        except ValueError:
            return False
        if parsed.source != "kb":
            return False
        code = gesture.extra.get("keycode")
        if not isinstance(code, int):
            code = code_for_name(parsed.key)
        if code is None:
            log.warning("Não sei reinjetar %s", gesture.identifier)
            return False
        mod_codes = [
            self.nvda_key_code() if m == "nvda" else MODIFIER_INJECT[m] for m in parsed.modifiers
        ]
        held = {c for c in self._pressed if c in MODIFIER_KEYS}
        # Modificadores já seguros fisicamente não são pressionados de novo.
        mod_codes = [c for c in mod_codes if c not in held]
        return self.backend.inject(tap_sequence(mod_codes, code))

    def reset(self) -> None:
        """Esquece todo o estado (ao trocar de backend ou soltar o grab)."""
        self._pressed.clear()
        self._swallowed.clear()
        self._nvda_down = None
        self._nvda_used = False
        self._last_tap = None
        self._lone_modifier = None
