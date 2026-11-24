"""Tradução de teclas em caracteres conforme o layout XKB do usuário.

O evdev entrega só códigos físicos; para o eco de caracteres e para
``InputGesture.character`` precisamos saber o que a tecla *digita* no layout
real (ABNT2: a tecla depois do L é "ç"). Usamos o ``libxkbcommon`` via
``ctypes`` (biblioteca presente em qualquer desktop Linux, X11 ou Wayland).
Sem ele, cai para o layout US.

O layout vem de ``keyboard.xkbLayout`` ou é detectado por
``XKB_DEFAULT_LAYOUT``, ``/etc/default/keyboard``,
``/etc/X11/xorg.conf.d/00-keyboard.conf`` e ``/etc/vconsole.conf``.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import re
from pathlib import Path
from typing import Protocol

from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.keys import KEY_CAPSLOCK, KEY_LEFTSHIFT, KEY_RIGHTSHIFT, us_character

log = get_logger(__name__)

EVDEV_OFFSET = 8  # keycode XKB = código evdev + 8


class Keymap(Protocol):
    """Estado de teclado capaz de dizer o caractere de uma tecla."""

    def update(self, code: int, down: bool) -> None: ...

    def character(self, code: int) -> str | None: ...

    @property
    def description(self) -> str: ...


class UsKeymap:
    """Reserva sem xkbcommon: layout US, com Shift e Caps Lock."""

    def __init__(self) -> None:
        self._shift: set[int] = set()
        self._caps = False

    @property
    def description(self) -> str:
        return "us (embutido)"

    def update(self, code: int, down: bool) -> None:
        if code in (KEY_LEFTSHIFT, KEY_RIGHTSHIFT):
            if down:
                self._shift.add(code)
            else:
                self._shift.discard(code)
        elif code == KEY_CAPSLOCK and down:
            self._caps = not self._caps

    def character(self, code: int) -> str | None:
        return us_character(code, bool(self._shift), self._caps)


class _RuleNames(ctypes.Structure):
    _fields_ = [
        ("rules", ctypes.c_char_p),
        ("model", ctypes.c_char_p),
        ("layout", ctypes.c_char_p),
        ("variant", ctypes.c_char_p),
        ("options", ctypes.c_char_p),
    ]


class XkbKeymap:
    """Estado XKB real via libxkbcommon."""

    def __init__(self, lib: ctypes.CDLL, layout: str, variant: str = "", options: str = "") -> None:
        self._lib = lib
        self._layout = layout
        self._variant = variant
        lib.xkb_context_new.restype = ctypes.c_void_p
        lib.xkb_context_new.argtypes = [ctypes.c_int]
        lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        lib.xkb_keymap_new_from_names.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_RuleNames),
            ctypes.c_int,
        ]
        lib.xkb_state_new.restype = ctypes.c_void_p
        lib.xkb_state_new.argtypes = [ctypes.c_void_p]
        lib.xkb_state_update_key.restype = ctypes.c_int
        lib.xkb_state_update_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
        lib.xkb_state_key_get_utf8.restype = ctypes.c_int
        lib.xkb_state_key_get_utf8.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        for name in ("xkb_state_unref", "xkb_keymap_unref", "xkb_context_unref"):
            getattr(lib, name).restype = None
            getattr(lib, name).argtypes = [ctypes.c_void_p]

        self._state: int | None = None
        self._keymap: int | None = None
        self._ctx: int | None = lib.xkb_context_new(0)
        if not self._ctx:
            raise OSError("xkb_context_new falhou")
        names = _RuleNames(
            None, None, layout.encode() or None, variant.encode() or None, options.encode() or None
        )
        self._keymap = lib.xkb_keymap_new_from_names(self._ctx, ctypes.byref(names), 0)
        if not self._keymap:
            lib.xkb_context_unref(self._ctx)
            self._ctx = None  # evita unref duplo em __del__
            raise OSError(f"layout XKB inválido: {layout!r} {variant!r}")
        self._state = lib.xkb_state_new(self._keymap)
        self._buf = ctypes.create_string_buffer(16)

    @property
    def description(self) -> str:
        return f"{self._layout}{'(' + self._variant + ')' if self._variant else ''} (xkbcommon)"

    def update(self, code: int, down: bool) -> None:
        self._lib.xkb_state_update_key(self._state, code + EVDEV_OFFSET, 1 if down else 0)

    def character(self, code: int) -> str | None:
        n = self._lib.xkb_state_key_get_utf8(
            self._state, code + EVDEV_OFFSET, self._buf, ctypes.sizeof(self._buf)
        )
        if n <= 0:
            return None
        text = self._buf.value.decode("utf-8", errors="replace")
        if len(text) != 1 or (not text.isprintable() and text not in "\t\n\r"):
            return None
        return text

    def __del__(self) -> None:
        lib = getattr(self, "_lib", None)
        if lib is None:
            return
        with contextlib.suppress(Exception):
            if getattr(self, "_state", None):
                lib.xkb_state_unref(self._state)
            if getattr(self, "_keymap", None):
                lib.xkb_keymap_unref(self._keymap)
            if getattr(self, "_ctx", None):
                lib.xkb_context_unref(self._ctx)


_ASSIGN = re.compile(r'^\s*(XKBLAYOUT|XKBVARIANT|KEYMAP)\s*=\s*"?([^"\n]*)"?', re.MULTILINE)
_XORG = re.compile(r'Option\s+"Xkb(Layout|Variant)"\s+"([^"]*)"', re.IGNORECASE)


def detect_layout(root: Path = Path("/")) -> tuple[str, str]:
    """(layout, variante) do sistema; ``("us", "")`` se nada for encontrado."""
    env_layout = os.environ.get("XKB_DEFAULT_LAYOUT", "")
    if env_layout:
        return env_layout.split(",")[0], os.environ.get("XKB_DEFAULT_VARIANT", "").split(",")[0]
    for rel in ("etc/default/keyboard", "etc/vconsole.conf"):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        values = {k: v.strip() for k, v in _ASSIGN.findall(text)}
        layout = values.get("XKBLAYOUT", "")
        if layout:
            return layout.split(",")[0], values.get("XKBVARIANT", "").split(",")[0]
    try:
        text = (root / "etc/X11/xorg.conf.d/00-keyboard.conf").read_text(encoding="utf-8")
        values = {k.lower(): v for k, v in _XORG.findall(text)}
        if values.get("layout"):
            return values["layout"].split(",")[0], values.get("variant", "").split(",")[0]
    except OSError:
        pass
    return "us", ""


def create_keymap(layout: str = "", variant: str = "") -> Keymap:
    """Keymap XKB para ``layout`` (detectado se vazio), ou US se impossível."""
    if not layout:
        layout, detected_variant = detect_layout()
        variant = variant or detected_variant
    libname = ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0"
    try:
        lib = ctypes.CDLL(libname)
        keymap = XkbKeymap(lib, layout, variant)
    except OSError as exc:
        log.info("xkbcommon indisponível (%s); usando layout US embutido", exc)
        return UsKeymap()
    log.debug("Layout de teclado: %s", keymap.description)
    return keymap
