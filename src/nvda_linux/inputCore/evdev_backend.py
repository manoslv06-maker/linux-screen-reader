"""Backend evdev: grab exclusivo dos teclados + reemissão por uinput.

Funciona em qualquer sessão (X11, KDE/KWin, Sway, Hyprland, console),
porque lê ``/dev/input/event*`` abaixo do compositor. Exige que o usuário
esteja no grupo ``input`` (leitura) e tenha escrita em ``/dev/uinput``
(regra udev em ``packaging/udev/99-nvda-input.rules``).

Fluxo de cada tecla::

    teclado físico --(grab)--> leitor --engole--> (script)
                                      \\--repassa--> uinput --> compositor

Segurança:

- qualquer exceção no processamento solta o grab (``release_grab``);
- ``release_grab`` é seguro para chamar de outro thread (watchdog) e solta
  no teclado virtual as teclas que estavam pressionadas, para não deixar
  Ctrl/Shift "presos";
- ``regrab`` só pega de novo quando nenhuma tecla física está pressionada;
- se o processo morrer, o kernel solta o grab sozinho ao fechar o fd.

Sem acesso ao ``/dev/uinput`` o backend ainda funciona em modo monitor
(sem grab): os gestos chegam marcados ``suppressed=False``, então nenhum
script é executado por tecla que o aplicativo também recebeu.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import os
import threading
import time
from collections.abc import Sequence
from typing import Any

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.backend import (
    BackendUnavailable,
    KeyboardBackend,
    KeyHandler,
    RawKeyEvent,
    UInputInjector,
)

log = get_logger(__name__)

EV_SYN = 0
EV_KEY = 1
KEY_A = 30
KEY_Z = 44
KEY_SPACE = 57
KEY_ENTER = 28
LED_NUML = 0


def readable_event_nodes(pattern: str = "/dev/input/event*") -> tuple[list[str], list[str]]:
    """(legíveis, sem permissão) entre os nós de evento existentes."""
    ok: list[str] = []
    denied: list[str] = []
    for path in sorted(glob.glob(pattern)):
        (ok if os.access(path, os.R_OK) else denied).append(path)
    return ok, denied


class _Device:
    """Estado de um teclado físico aberto."""

    __slots__ = ("dev", "grabbed", "name", "path")

    def __init__(self, dev: Any) -> None:
        self.dev = dev
        self.path: str = str(getattr(dev, "path", "?"))
        self.name: str = str(getattr(dev, "name", "?"))
        self.grabbed = False


class EvdevBackend(KeyboardBackend):
    """Captura via python-evdev com grab exclusivo e repasse por uinput."""

    name = "evdev"

    def __init__(
        self,
        evdev: Any | None = None,
        injector: UInputInjector | None = None,
        *,
        grab: bool = True,
        rescan_interval: float = 3.0,
    ) -> None:
        super().__init__()
        self._evdev = evdev if evdev is not None else optional_import("evdev")
        self._injector = injector or UInputInjector(self._evdev)
        self._want_grab = grab
        self._grab_suspended = False
        self._devices: dict[str, _Device] = {}
        self._forwarded_down: set[int] = set()
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._rescan_interval = rescan_interval
        self._rescan_task: asyncio.Task[None] | None = None
        self._regrab_handle: asyncio.TimerHandle | None = None
        self._numlock: bool | None = None

    # ------------------------------------------------------------ propriedades
    @property
    def grabbing(self) -> bool:
        """True se ao menos um teclado está sob grab exclusivo."""
        with self._lock:
            return any(d.grabbed for d in self._devices.values())

    @property
    def can_suppress(self) -> bool:  # type: ignore[override]
        return self.grabbing

    @property
    def devices(self) -> list[str]:
        return [f"{d.name} ({d.path})" for d in self._devices.values()]

    @property
    def numlock(self) -> bool | None:
        return self._numlock

    # ------------------------------------------------------------ ciclo de vida
    async def start(self, handler: KeyHandler) -> None:
        if self._evdev is None:
            raise BackendUnavailable("python-evdev não está instalado")
        ok, denied = readable_event_nodes()
        if not ok:
            if denied:
                raise BackendUnavailable(
                    "sem permissão de leitura em /dev/input "
                    "(adicione o usuário ao grupo 'input' ou instale a regra udev)",
                    permission=True,
                )
            raise BackendUnavailable("nenhum dispositivo em /dev/input")
        self.handler = handler
        self._loop = asyncio.get_running_loop()
        if self._want_grab:
            try:
                self._injector.open()
            except BackendUnavailable as exc:
                log.warning("Sem uinput (%s): modo monitor, sem engolir teclas", exc)
                self._want_grab = False
        self._scan()
        if not self._devices:
            await self.stop()
            raise BackendUnavailable("nenhum teclado legível encontrado em /dev/input")
        self._rescan_task = self._loop.create_task(self._rescan_loop(), name="evdev-rescan")
        log.info(
            "evdev: %d teclado(s), grab=%s: %s",
            len(self._devices),
            self.grabbing,
            "; ".join(self.devices),
        )

    async def stop(self) -> None:
        if self._rescan_task is not None:
            self._rescan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._rescan_task
            self._rescan_task = None
        if self._regrab_handle is not None:
            self._regrab_handle.cancel()
        self.release_grab()
        with self._lock:
            devices = list(self._devices.values())
            self._devices.clear()
        for d in devices:
            self._detach(d)
        self._injector.close()
        self.handler = None

    # ------------------------------------------------------------ dispositivos
    def _is_keyboard(self, dev: Any) -> bool:
        try:
            caps = dev.capabilities(verbose=False)
        except OSError:
            return False
        keys = set(caps.get(EV_KEY, ()))
        return {KEY_A, KEY_Z, KEY_SPACE, KEY_ENTER} <= keys

    def _scan(self) -> None:
        evdev = self._evdev
        assert evdev is not None
        own = self._injector.device_path
        try:
            paths = list(evdev.list_devices())
        except OSError as exc:
            log.warning("Falha ao listar /dev/input: %s", exc)
            return
        for path in paths:
            if path in self._devices or path == own:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue  # sem permissão para este nó, ou sumiu
            if getattr(dev, "name", "") == UInputInjector.DEVICE_NAME or not self._is_keyboard(dev):
                with contextlib.suppress(Exception):
                    dev.close()
                continue
            self._attach(_Device(dev))

    def _attach(self, d: _Device) -> None:
        loop = self._loop
        assert loop is not None
        if self._numlock is None:
            with contextlib.suppress(Exception):
                self._numlock = LED_NUML in d.dev.leds()
        if self._want_grab and not self._grab_suspended and self._injector.is_open:
            self._grab_device(d)
        try:
            loop.add_reader(d.dev.fd, self._on_readable, d)
        except (OSError, ValueError) as exc:
            log.warning("Não foi possível monitorar %s: %s", d.path, exc)
            self._ungrab_device(d)
            return
        with self._lock:
            self._devices[d.path] = d
        log.debug("Teclado conectado: %s (%s) grab=%s", d.name, d.path, d.grabbed)

    def _detach(self, d: _Device) -> None:
        if self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(d.dev.fd)
        self._ungrab_device(d)
        with contextlib.suppress(Exception):
            d.dev.close()

    def _grab_device(self, d: _Device) -> None:
        try:
            d.dev.grab()
            d.grabbed = True
        except OSError as exc:
            log.warning("Grab recusado em %s (%s): outro programa usa o teclado?", d.path, exc)
            d.grabbed = False

    def _ungrab_device(self, d: _Device) -> None:
        if d.grabbed:
            d.grabbed = False
            with contextlib.suppress(OSError):
                d.dev.ungrab()

    async def _rescan_loop(self) -> None:
        while True:
            await asyncio.sleep(self._rescan_interval)
            try:
                self._scan()
            except Exception:
                log.exception("Falha ao procurar novos teclados")

    # ------------------------------------------------------------ eventos
    def _on_readable(self, d: _Device) -> None:
        try:
            events = list(d.dev.read())
        except BlockingIOError:
            return
        except OSError as exc:
            log.info("Teclado %s removido (%s)", d.path, exc)
            with self._lock:
                self._devices.pop(d.path, None)
            self._detach(d)
            return
        for ev in events:
            if ev.type == EV_KEY:
                self._on_key(d, ev)

    def _on_key(self, d: _Device, ev: Any) -> None:
        handler = self.handler
        grabbed = d.grabbed
        raw = RawKeyEvent(
            code=int(ev.code),
            value=int(ev.value),
            timestamp=time.monotonic(),
            suppressed=None if grabbed else False,
            device=d.path,
        )
        consumed = False
        if handler is not None:
            try:
                consumed = bool(handler(raw))
            except Exception:
                log.exception("Manipulador de teclado falhou; soltando o grab")
                self.release_grab()
                consumed = False
        if grabbed and d.grabbed and not consumed:
            self._forward(raw.code, raw.value)

    def _forward(self, code: int, value: int) -> None:
        with self._lock:
            if value == 0:
                if code not in self._forwarded_down:
                    return  # nunca enviamos a pressão; não solta "do nada"
                self._forwarded_down.discard(code)
            else:
                self._forwarded_down.add(code)
        self._injector.emit(code, value)

    # ------------------------------------------------------------ injeção / grab
    def inject(self, events: Sequence[tuple[int, int]]) -> bool:
        if not self._injector.is_open:
            return False
        for code, value in events:
            self._injector.emit(code, value)
        return True

    def release_grab(self) -> None:
        """Solta todos os grabs agora (thread-safe) e destrava teclas virtuais."""
        with self._lock:
            self._grab_suspended = True
            devices = list(self._devices.values())
            stuck = sorted(self._forwarded_down)
            self._forwarded_down.clear()
        for d in devices:
            self._ungrab_device(d)
        for code in stuck:
            self._injector.emit(code, 0)
        if devices:
            log.warning("Grab do teclado solto (%d dispositivo(s))", len(devices))

    def regrab(self) -> None:
        """Pega de novo os teclados quando nenhuma tecla física estiver pressionada."""
        if not self._want_grab or not self._injector.is_open:
            return
        with self._lock:
            devices = list(self._devices.values())
        busy = False
        for d in devices:
            with contextlib.suppress(Exception):
                if d.dev.active_keys():
                    busy = True
        if busy and self._loop is not None:
            self._regrab_handle = self._loop.call_later(0.1, self.regrab)
            return
        with self._lock:
            self._grab_suspended = False
        for d in devices:
            if not d.grabbed:
                self._grab_device(d)
        log.info("Grab do teclado restaurado")
