"""Escolha automática do backend de teclado e montagem do inputCore.

Regra de ``keyboard.backend = "auto"``:

1. ``KeyboardMonitor`` se o compositor oferecer
   ``org.freedesktop.a11y.KeyboardMonitor`` (GNOME 48+ no Wayland, niri);
2. ``evdev`` (grab + uinput) nos demais casos: KDE, Sway, Hyprland, X11;
3. nenhum (``NullBackend``), com aviso falado, se faltar permissão.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from nvda_linux.contracts import ConfigStore
from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.backend import BackendUnavailable, KeyboardBackend, NullBackend
from nvda_linux.inputCore.dispatcher import InputManager
from nvda_linux.inputCore.evdev_backend import EvdevBackend
from nvda_linux.inputCore.keyboard import KeyboardInputProcessor
from nvda_linux.inputCore.keyboard_monitor import KeyboardMonitorBackend
from nvda_linux.inputCore.keys import XK_CAPS_LOCK, XK_INSERT, XK_KP_INSERT

log = get_logger(__name__)

BackendFactory = Callable[[], KeyboardBackend]


@dataclass
class BackendChoice:
    backend: KeyboardBackend
    errors: list[str] = field(default_factory=list)
    permission_problem: bool = False


def nvda_keysyms(config: ConfigStore | None) -> Callable[[], list[int]]:
    """Keysyms das teclas NVDA ativas (para SetKeyGrabs)."""

    def get() -> list[int]:
        def cfg(key: str, default: bool) -> bool:
            return bool(config.get(key, default)) if config is not None else default

        syms: list[int] = []
        if cfg("keyboard.useExtendedInsertAsNVDAModifierKey", True):
            syms.append(XK_INSERT)
        if cfg("keyboard.useNumpadInsertAsNVDAModifierKey", True):
            syms.append(XK_KP_INSERT)
        if cfg("keyboard.useCapsLockAsNVDAModifierKey", False):
            syms.append(XK_CAPS_LOCK)
        return syms

    return get


async def select_backend(
    name: str,
    processor: KeyboardInputProcessor,
    dispatcher: InputManager,
    config: ConfigStore | None = None,
    *,
    factories: dict[str, BackendFactory] | None = None,
) -> BackendChoice:
    """Inicia o primeiro backend que funcionar e liga-o ao processador."""

    def make_monitor() -> KeyboardBackend:
        backend = KeyboardMonitorBackend(source=dispatcher, nvda_keysyms=nvda_keysyms(config))
        dispatcher.add_state_listener(backend.schedule_refresh)
        dispatcher.add_script_listener(lambda _g: backend.schedule_refresh(0.02))
        return backend

    available: dict[str, BackendFactory] = {
        "keyboardMonitor": make_monitor,
        "evdev": EvdevBackend,
        "none": NullBackend,
    }
    if factories:
        available.update(factories)
    if name in ("", "auto"):
        order = ["keyboardMonitor", "evdev"]
    elif name in available:
        order = [name]
    else:
        log.warning("keyboard.backend desconhecido: %s; usando auto", name)
        order = ["keyboardMonitor", "evdev"]

    errors: list[str] = []
    permission = False
    for candidate in order:
        backend = available[candidate]()
        processor.backend = backend
        try:
            await backend.start(processor.handle)
        except BackendUnavailable as exc:
            errors.append(f"{candidate}: {exc}")
            permission = permission or exc.permission
            log.info("Backend de teclado %s indisponível: %s", candidate, exc)
            continue
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            log.exception("Backend de teclado %s falhou", candidate)
            continue
        if backend.numlock is not None:
            processor.numlock = backend.numlock
        dispatcher.set_sender(processor.send_gesture)
        log.info("Backend de teclado: %s", backend.name)
        return BackendChoice(backend, errors, permission)

    null = NullBackend()
    processor.backend = null
    await null.start(processor.handle)
    dispatcher.set_sender(None)
    log.error("Nenhum backend de teclado disponível: %s", "; ".join(errors))
    return BackendChoice(null, errors, permission)
