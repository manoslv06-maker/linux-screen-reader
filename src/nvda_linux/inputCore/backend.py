"""Interface comum dos backends de teclado e o injetor uinput.

Um backend entrega :class:`RawKeyEvent` ao ``handler`` (o
:class:`~nvda_linux.inputCore.keyboard.KeyboardInputProcessor`), que
responde *na hora* se a tecla deve ser engolida (True) ou repassada (False).

- Backends com grab exclusivo (evdev) repassam o que não for engolido
  reemitindo por uinput.
- Backends em que o compositor já decidiu (KeyboardMonitor) marcam
  ``RawKeyEvent.suppressed`` e ignoram a resposta.
"""

from __future__ import annotations

import abc
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RawKeyEvent:
    """Evento de tecla bruto, já em código evdev."""

    code: int
    value: int  # 0 = soltou, 1 = pressionou, 2 = autorepetição
    timestamp: float
    suppressed: bool | None = None  # None = o processador decide
    char: str | None = None  # caractere, se o backend souber (KeyboardMonitor)
    device: str = ""

    @property
    def pressed(self) -> bool:
        return self.value in (1, 2)


KeyHandler = Callable[[RawKeyEvent], bool]


class BackendUnavailable(RuntimeError):
    """O backend não pode ser usado nesta sessão (motivo na mensagem)."""

    def __init__(self, message: str, *, permission: bool = False) -> None:
        super().__init__(message)
        self.permission = permission


class KeyboardBackend(abc.ABC):
    """Fonte de eventos de teclado."""

    name = "abstract"
    #: True se o backend pode engolir teclas e reinjetar as demais.
    can_suppress = False
    #: True se o compositor já repassa o duplo toque na tecla NVDA sozinho.
    compositor_double_tap = False

    def __init__(self) -> None:
        self.handler: KeyHandler | None = None
        self.on_fatal: Callable[[str], None] | None = None

    @abc.abstractmethod
    async def start(self, handler: KeyHandler) -> None:
        """Começa a entregar eventos. Levanta :class:`BackendUnavailable`."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Para e libera tudo (inclusive grabs)."""

    def inject(self, events: Sequence[tuple[int, int]]) -> bool:
        """Emite ``(código, valor)`` como se viessem do teclado. False se não suportado."""
        return False

    def release_grab(self) -> None:
        """Solta grabs exclusivos imediatamente (thread-safe). Padrão: nada."""

    def regrab(self) -> None:
        """Volta a pegar o teclado depois de :meth:`release_grab`."""

    @property
    def numlock(self) -> bool | None:
        """Estado inicial do NumLock, se o backend souber."""
        return None


class NullBackend(KeyboardBackend):
    """Sem teclado (falta de permissão, ou ``keyboard.backend = "none"``)."""

    name = "none"

    async def start(self, handler: KeyHandler) -> None:
        self.handler = handler

    async def stop(self) -> None:
        self.handler = None


class UInputInjector:
    """Teclado virtual via ``/dev/uinput`` para reemitir e injetar teclas.

    Expõe só códigos de teclado (sem a faixa BTN_*), para que o libinput o
    classifique como teclado e não como mouse/joystick.
    """

    DEVICE_NAME = "nvda-linux virtual keyboard"

    def __init__(self, evdev: Any | None = None) -> None:
        self._evdev = evdev if evdev is not None else optional_import("evdev")
        self._ui: Any = None
        self._lock = threading.Lock()

    @staticmethod
    def key_capabilities() -> list[int]:
        return [*range(1, 0x100), *range(0x160, 0x2C0)]

    def open(self) -> None:
        if self._evdev is None:
            raise BackendUnavailable("python-evdev não instalado")
        if not os.access("/dev/uinput", os.W_OK):
            raise BackendUnavailable(
                "sem permissão de escrita em /dev/uinput (veja packaging/udev)", permission=True
            )
        ecodes = self._evdev.ecodes
        try:
            self._ui = self._evdev.UInput(
                {ecodes.EV_KEY: self.key_capabilities()},
                name=self.DEVICE_NAME,
                bustype=ecodes.BUS_VIRTUAL if hasattr(ecodes, "BUS_VIRTUAL") else 0x06,
            )
        except (OSError, self._evdev.UInputError) as exc:
            raise BackendUnavailable(f"uinput indisponível: {exc}", permission=True) from exc

    @property
    def is_open(self) -> bool:
        return self._ui is not None

    @property
    def device_path(self) -> str | None:
        """Nó ``/dev/input/eventN`` do teclado virtual (para não lê-lo de volta)."""
        # python-evdev: ``UInput.devnode`` é /dev/uinput; o nó criado fica em
        # ``UInput.device.path``.
        device = getattr(self._ui, "device", None)
        path = getattr(device, "path", None)
        return path if isinstance(path, str) else None

    def emit(self, code: int, value: int) -> None:
        """Emite uma tecla + SYN_REPORT."""
        ui = self._ui
        if ui is None or self._evdev is None:
            return
        ecodes = self._evdev.ecodes
        with self._lock:
            try:
                ui.write(ecodes.EV_KEY, code, value)
                ui.syn()
            except OSError as exc:
                log.warning("Falha ao escrever no uinput: %s", exc)

    def emit_many(self, events: Sequence[tuple[int, int]]) -> None:
        for code, value in events:
            self.emit(code, value)

    def close(self) -> None:
        ui, self._ui = self._ui, None
        if ui is not None:
            try:
                ui.close()
            except OSError:
                pass


def tap_sequence(modifier_codes: Sequence[int], key_code: int) -> list[tuple[int, int]]:
    """Pressiona modificadores, toca a tecla e solta tudo em ordem inversa."""
    events = [(c, 1) for c in modifier_codes]
    events += [(key_code, 1), (key_code, 0)]
    events += [(c, 0) for c in reversed(modifier_codes)]
    return events
