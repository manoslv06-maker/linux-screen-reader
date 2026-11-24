"""Backend ``org.freedesktop.a11y.KeyboardMonitor`` (GNOME/mutter 48+, niri).

No Wayland do GNOME, o caminho oficial para leitores de tela é a interface
D-Bus ``org.freedesktop.a11y.KeyboardMonitor`` no nome
``org.freedesktop.a11y.Manager`` (objeto ``/org/freedesktop/a11y/Manager``):

- ``WatchKeyboard()``: recebe o sinal ``KeyEvent(b released, u state,
  u keysym, u unichar, q keycode)`` de todas as teclas;
- ``SetKeyGrabs(au modifiers, a(uu) keystrokes)``: o compositor engole os
  modificadores do leitor (tecla NVDA), tudo que for pressionado com eles, e
  os pares ``(keysym, máscara)`` listados. Dois toques rápidos num
  modificador registrado são repassados pelo próprio compositor;
- ``GrabKeyboard()``/``UngrabKeyboard()``: engole tudo (ajuda de entrada).

Como quem engole é o compositor, a decisão precisa ser tomada *antes* da
tecla: este backend sonda o despachante periodicamente (e depois de cada
script) para descobrir quais teclas sem NVDA têm script agora (por exemplo,
H/K/B no modo de navegação) e atualiza os grabs. Cada evento chega ao
processador marcado ``suppressed=True/False`` conforme o grab vigente.

Repasse de teclas (``send_through``) usa o uinput se houver permissão; sem
ele, não é possível injetar teclas no Wayland do GNOME.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from nvda_linux.contracts import InputGesture, KeyboardLayout
from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.backend import (
    BackendUnavailable,
    KeyboardBackend,
    KeyHandler,
    RawKeyEvent,
    UInputInjector,
)
from nvda_linux.inputCore.gesture import keyboard_gesture
from nvda_linux.inputCore.keys import (
    KEY_CAPSLOCK,
    KEY_INSERT,
    KEY_KP0,
    MODIFIER_KEYS,
    MODIFIER_MASKS,
    XK_CAPS_LOCK,
    XK_INSERT,
    XK_KP_INSERT,
    key_name,
    keysym_for_name,
)

log = get_logger(__name__)

BUS_NAME = "org.freedesktop.a11y.Manager"
OBJECT_PATH = "/org/freedesktop/a11y/Manager"
INTERFACE = "org.freedesktop.a11y.KeyboardMonitor"
EVDEV_OFFSET = 8
RELEVANT_MASK = sum(MODIFIER_MASKS.values())

KeyEventCallback = Callable[[bool, int, int, int, int], None]
Keystroke = tuple[int, int]  # (keysym, máscara de modificadores)


class MonitorConnection(Protocol):
    """Ligação D-Bus mínima de que o backend precisa (fácil de simular)."""

    async def has_owner(self) -> bool: ...

    async def call(self, member: str, signature: str, body: list[Any]) -> None: ...

    def on_key_event(self, callback: KeyEventCallback) -> None: ...

    async def close(self) -> None: ...


class DbusNextConnection:
    """Implementação real com ``dbus-next`` (mensagens de baixo nível)."""

    def __init__(self, dbus_next: Any) -> None:
        self._dbus = dbus_next
        self._bus: Any = None
        self._callbacks: list[KeyEventCallback] = []

    @classmethod
    async def connect(cls) -> DbusNextConnection:
        dbus_next = optional_import("dbus_next")
        aio = optional_import("dbus_next.aio")
        if dbus_next is None or aio is None:
            raise BackendUnavailable("dbus-next não está instalado")
        conn = cls(dbus_next)
        try:
            conn._bus = await aio.MessageBus(bus_type=dbus_next.BusType.SESSION).connect()
        except Exception as exc:  # sem DBUS_SESSION_BUS_ADDRESS etc.
            raise BackendUnavailable(f"sem barramento de sessão D-Bus: {exc}") from exc
        conn._bus.add_message_handler(conn._handle_message)
        rule = f"type='signal',interface='{INTERFACE}',member='KeyEvent'"
        await conn._raw_call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "AddMatch",
            "s",
            [rule],
        )
        return conn

    async def _raw_call(
        self, dest: str, path: str, iface: str, member: str, sig: str, body: list[Any]
    ) -> Any:
        msg = self._dbus.Message(
            destination=dest, path=path, interface=iface, member=member, signature=sig, body=body
        )
        reply = await self._bus.call(msg)
        if reply.message_type == self._dbus.MessageType.ERROR:
            detail = reply.body[0] if reply.body else ""
            raise BackendUnavailable(f"{member}: {reply.error_name} {detail}".strip())
        return reply

    async def has_owner(self) -> bool:
        reply = await self._raw_call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            "s",
            [BUS_NAME],
        )
        return bool(reply.body and reply.body[0])

    async def call(self, member: str, signature: str, body: list[Any]) -> None:
        await self._raw_call(BUS_NAME, OBJECT_PATH, INTERFACE, member, signature, body)

    def on_key_event(self, callback: KeyEventCallback) -> None:
        self._callbacks.append(callback)

    def _handle_message(self, msg: Any) -> bool:
        if (
            msg.message_type == self._dbus.MessageType.SIGNAL
            and msg.interface == INTERFACE
            and msg.member == "KeyEvent"
        ):
            released, state, keysym, unichar, keycode = msg.body
            for cb in list(self._callbacks):
                cb(bool(released), int(state), int(keysym), int(unichar), int(keycode))
        return False

    async def close(self) -> None:
        if self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.disconnect()
            self._bus = None


class GrabSource(Protocol):
    """O que o backend consulta para montar os grabs (o InputManager)."""

    @property
    def layout(self) -> KeyboardLayout: ...

    @property
    def input_help(self) -> bool: ...

    @property
    def pass_next(self) -> bool: ...

    def probe(self, gestures: Sequence[InputGesture]) -> list[InputGesture]: ...


_CANDIDATE_KEYS: tuple[str, ...] = (
    *"abcdefghijklmnopqrstuvwxyz0123456789",
    *",.;/'[]\\-=`",
    "uparrow",
    "downarrow",
    "leftarrow",
    "rightarrow",
    "home",
    "end",
    "pageup",
    "pagedown",
    "tab",
    "enter",
    "escape",
    "space",
    "delete",
    "backspace",
    "applications",
    *(f"f{i}" for i in range(1, 13)),
    "numpad1",
    "numpad2",
    "numpad3",
    "numpad4",
    "numpad5",
    "numpad6",
    "numpad7",
    "numpad8",
    "numpad9",
    "numpaddelete",
    "numpadplus",
    "numpadminus",
    "numpadmultiply",
    "numpaddivide",
    "numpadenter",
)
_CANDIDATE_MODS: tuple[tuple[str, ...], ...] = (
    (),
    ("shift",),
    ("control",),
    ("alt",),
    ("control", "shift"),
    ("alt", "shift"),
)


def mask_for(modifiers: Sequence[str]) -> int:
    return sum(MODIFIER_MASKS.get(m, 0) for m in set(modifiers))


class KeyboardMonitorBackend(KeyboardBackend):
    """Captura pelo compositor via ``org.freedesktop.a11y.KeyboardMonitor``."""

    name = "keyboardMonitor"
    can_suppress = False
    compositor_double_tap = True

    def __init__(
        self,
        connect: Callable[[], Any] | None = None,
        *,
        source: GrabSource | None = None,
        nvda_keysyms: Callable[[], list[int]] | None = None,
        injector: UInputInjector | None = None,
        refresh_interval: float = 0.3,
    ) -> None:
        super().__init__()
        self._connect = connect or DbusNextConnection.connect
        self.source = source
        self._nvda_keysyms = nvda_keysyms or (lambda: [XK_INSERT, XK_KP_INSERT])
        self._injector = injector
        self._conn: MonitorConnection | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._down: dict[int, bool] = {}  # keycode evdev -> suppressed na pressão
        self._mods: set[int] = set()
        self._modifier_grabs: list[int] = []
        self._keystrokes: frozenset[Keystroke] = frozenset()
        self._full_grab = False
        self._refresh_interval = refresh_interval
        self._refresh_task: asyncio.Task[None] | None = None
        self._refresh_soon: asyncio.TimerHandle | None = None
        self.grab_updates = 0

    # ------------------------------------------------------------ ciclo de vida
    async def start(self, handler: KeyHandler) -> None:
        self.handler = handler
        self._loop = asyncio.get_running_loop()
        conn: MonitorConnection = await self._connect()
        try:
            if not await conn.has_owner():
                raise BackendUnavailable(
                    f"compositor não oferece {INTERFACE} (precisa de GNOME 48+ ou niri)"
                )
            conn.on_key_event(self._on_key_event)
            await conn.call("WatchKeyboard", "", [])
        except BackendUnavailable:
            await conn.close()
            raise
        except Exception as exc:
            await conn.close()
            raise BackendUnavailable(f"KeyboardMonitor recusou a conexão: {exc}") from exc
        self._conn = conn
        if self._injector is None:
            injector = UInputInjector()
            try:
                injector.open()
                self._injector = injector
            except BackendUnavailable as exc:
                log.info("KeyboardMonitor sem uinput (%s): send_through indisponível", exc)
        await self.refresh_grabs()
        self._refresh_task = self._loop.create_task(self._refresh_loop(), name="kbmon-refresh")
        log.info("KeyboardMonitor ativo (%d grabs de teclas)", len(self._keystrokes))

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None
        conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.call("SetKeyGrabs", "aua(uu)", [[], []])
                if self._full_grab:
                    await conn.call("UngrabKeyboard", "", [])
                await conn.call("UnwatchKeyboard", "", [])
            await conn.close()
        if self._injector is not None:
            self._injector.close()
        self.handler = None

    # ------------------------------------------------------------ grabs
    def compute_keystrokes(self) -> frozenset[Keystroke]:
        """Pares (keysym, máscara) que têm script agora, sem a tecla NVDA."""
        source = self.source
        if source is None:
            return frozenset()
        layout = source.layout
        candidates: list[InputGesture] = []
        for mods in _CANDIDATE_MODS:
            for key in _CANDIDATE_KEYS:
                candidates.append(keyboard_gesture(mods, key, layout=layout))
        result: set[Keystroke] = set()
        for gesture in source.probe(candidates):
            mods = gesture.extra.get("modifiers", ())
            key = gesture.identifier.rsplit("+", 1)[-1].split(":", 1)[-1]
            keysym = keysym_for_name(key)
            if keysym is None:
                continue
            mask = mask_for(mods)
            result.add((keysym, mask))
            if len(key) == 1 and key.isalpha():  # Shift+H pode chegar como 'H'
                result.add((ord(key.upper()), mask))
        return frozenset(result)

    async def refresh_grabs(self) -> None:
        """Recalcula e, se mudou, envia SetKeyGrabs/GrabKeyboard ao compositor."""
        conn = self._conn
        if conn is None:
            return
        source = self.source
        want_full = bool(source is not None and source.input_help)
        passing = bool(source is not None and source.pass_next)
        modifiers = [] if passing else list(self._nvda_keysyms())
        keystrokes = frozenset() if passing else self.compute_keystrokes()
        try:
            if want_full != self._full_grab:
                await conn.call("GrabKeyboard" if want_full else "UngrabKeyboard", "", [])
                self._full_grab = want_full
            if modifiers != self._modifier_grabs or keystrokes != self._keystrokes:
                body = [modifiers, [list(k) for k in sorted(keystrokes)]]
                await conn.call("SetKeyGrabs", "aua(uu)", body)
                self._modifier_grabs = modifiers
                self._keystrokes = keystrokes
                self.grab_updates += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao atualizar grabs do KeyboardMonitor: %s", exc)

    def schedule_refresh(self, delay: float = 0.0) -> None:
        """Pede um refresh logo (depois de um script que pode ter trocado o modo)."""
        loop = self._loop
        if loop is None or self._conn is None:
            return
        if self._refresh_soon is not None:
            self._refresh_soon.cancel()

        def fire() -> None:
            self._refresh_soon = None
            loop.create_task(self.refresh_grabs())

        self._refresh_soon = loop.call_later(delay, fire)

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval)
            await self.refresh_grabs()

    # ------------------------------------------------------------ eventos
    def _is_nvda_keysym_code(self, code: int) -> bool:
        syms = set(self._modifier_grabs)
        return (
            (code == KEY_INSERT and XK_INSERT in syms)
            or (code == KEY_KP0 and XK_KP_INSERT in syms)
            or (code == KEY_CAPSLOCK and XK_CAPS_LOCK in syms)
        )

    def _would_suppress(self, code: int) -> bool:
        if self._full_grab:
            return True
        if self._is_nvda_keysym_code(code):
            return True
        if any(self._is_nvda_keysym_code(c) for c in self._down):
            return True  # algo pressionado junto com a tecla NVDA
        name = key_name(code, numlock=False)
        keysym = keysym_for_name(name) if name else None
        if keysym is None:
            return False
        mods = [MODIFIER_KEYS[c] for c in self._mods]
        return (keysym, mask_for(mods)) in self._keystrokes

    def _on_key_event(
        self, released: bool, state: int, keysym: int, unichar: int, keycode: int
    ) -> None:
        code = keycode - EVDEV_OFFSET
        if released:
            suppressed = self._down.pop(code, self._would_suppress(code))
            value = 0
        else:
            value = 2 if code in self._down else 1
            suppressed = self._down.get(code, self._would_suppress(code))
            self._down[code] = suppressed
        if code in MODIFIER_KEYS:
            if released:
                self._mods.discard(code)
            else:
                self._mods.add(code)
        char = chr(unichar) if unichar >= 0x20 and chr(unichar).isprintable() else None
        event = RawKeyEvent(code, value, time.monotonic(), suppressed=suppressed, char=char)
        handler = self.handler
        if handler is not None:
            try:
                handler(event)
            except Exception:
                log.exception("Manipulador de teclado falhou (KeyboardMonitor)")

    # ------------------------------------------------------------ injeção
    def inject(self, events: Sequence[tuple[int, int]]) -> bool:
        if self._injector is None or not self._injector.is_open:
            return False
        self._injector.emit_many(events)
        return True

    def release_grab(self) -> None:
        """Solta grabs no compositor (agendado no loop; seguro de outro thread)."""
        loop, conn = self._loop, self._conn
        if loop is None or conn is None or loop.is_closed():
            return

        async def drop() -> None:
            with contextlib.suppress(Exception):
                await conn.call("SetKeyGrabs", "aua(uu)", [[], []])
                if self._full_grab:
                    await conn.call("UngrabKeyboard", "", [])
            self._full_grab = False
            self._modifier_grabs = []
            self._keystrokes = frozenset()

        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(drop(), loop)
