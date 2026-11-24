"""Tabelas de teclas: códigos do kernel (evdev) <-> nomes do NVDA.

Os códigos são os de ``linux/input-event-codes.h`` (ABI estável do kernel),
escritos aqui para que o mapeamento funcione mesmo sem o ``python-evdev``
(backend KeyboardMonitor). Os nomes seguem o ``vkCodes`` do NVDA, em
minúsculas, como exige o contrato (``"downarrow"``, ``"numpad8"``...).

Também ficam aqui os keysyms do X11/XKB usados para registrar grabs no
``org.freedesktop.a11y.KeyboardMonitor``.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Códigos evdev
# --------------------------------------------------------------------------
KEY_ESC: Final = 1
KEY_BACKSPACE: Final = 14
KEY_TAB: Final = 15
KEY_ENTER: Final = 28
KEY_LEFTCTRL: Final = 29
KEY_LEFTSHIFT: Final = 42
KEY_RIGHTSHIFT: Final = 54
KEY_KPASTERISK: Final = 55
KEY_LEFTALT: Final = 56
KEY_SPACE: Final = 57
KEY_CAPSLOCK: Final = 58
KEY_NUMLOCK: Final = 69
KEY_SCROLLLOCK: Final = 70
KEY_KP7: Final = 71
KEY_KP8: Final = 72
KEY_KP9: Final = 73
KEY_KPMINUS: Final = 74
KEY_KP4: Final = 75
KEY_KP5: Final = 76
KEY_KP6: Final = 77
KEY_KPPLUS: Final = 78
KEY_KP1: Final = 79
KEY_KP2: Final = 80
KEY_KP3: Final = 81
KEY_KP0: Final = 82
KEY_KPDOT: Final = 83
KEY_KPENTER: Final = 96
KEY_RIGHTCTRL: Final = 97
KEY_KPSLASH: Final = 98
KEY_SYSRQ: Final = 99
KEY_RIGHTALT: Final = 100
KEY_HOME: Final = 102
KEY_UP: Final = 103
KEY_PAGEUP: Final = 104
KEY_LEFT: Final = 105
KEY_RIGHT: Final = 106
KEY_END: Final = 107
KEY_DOWN: Final = 108
KEY_PAGEDOWN: Final = 109
KEY_INSERT: Final = 110
KEY_DELETE: Final = 111
KEY_PAUSE: Final = 119
KEY_LEFTMETA: Final = 125
KEY_RIGHTMETA: Final = 126
KEY_COMPOSE: Final = 127
KEY_F1: Final = 59

MODIFIER_NAMES: Final = ("alt", "control", "nvda", "shift", "windows")

# Tecla -> nome do modificador NVDA
MODIFIER_KEYS: Final[dict[int, str]] = {
    KEY_LEFTCTRL: "control",
    KEY_RIGHTCTRL: "control",
    KEY_LEFTSHIFT: "shift",
    KEY_RIGHTSHIFT: "shift",
    KEY_LEFTALT: "alt",
    KEY_RIGHTALT: "alt",
    KEY_LEFTMETA: "windows",
    KEY_RIGHTMETA: "windows",
}

# Modificador -> tecla usada para reinjetar
MODIFIER_INJECT: Final[dict[str, int]] = {
    "control": KEY_LEFTCTRL,
    "shift": KEY_LEFTSHIFT,
    "alt": KEY_LEFTALT,
    "windows": KEY_LEFTMETA,
}

_LETTERS: Final = "qwertyuiop asdfghjkl zxcvbnm"
_LETTER_CODES: Final = (16, 30, 44)

# Nomes fixos (independentes do NumLock)
KEY_NAMES: Final[dict[int, str]] = {
    KEY_ESC: "escape",
    2: "1",
    3: "2",
    4: "3",
    5: "4",
    6: "5",
    7: "6",
    8: "7",
    9: "8",
    10: "9",
    11: "0",
    12: "-",
    13: "=",
    KEY_BACKSPACE: "backspace",
    KEY_TAB: "tab",
    26: "[",
    27: "]",
    KEY_ENTER: "enter",
    39: ";",
    40: "'",
    41: "`",
    43: "\\",
    51: ",",
    52: ".",
    53: "/",
    KEY_SPACE: "space",
    KEY_CAPSLOCK: "capslock",
    KEY_NUMLOCK: "numlock",
    KEY_SCROLLLOCK: "scrolllock",
    KEY_KPASTERISK: "numpadmultiply",
    KEY_KPMINUS: "numpadminus",
    KEY_KPPLUS: "numpadplus",
    KEY_KPENTER: "numpadenter",
    KEY_KPSLASH: "numpaddivide",
    86: "oem102",
    KEY_SYSRQ: "printscreen",
    KEY_HOME: "home",
    KEY_UP: "uparrow",
    KEY_PAGEUP: "pageup",
    KEY_LEFT: "leftarrow",
    KEY_RIGHT: "rightarrow",
    KEY_END: "end",
    KEY_DOWN: "downarrow",
    KEY_PAGEDOWN: "pagedown",
    KEY_INSERT: "insert",
    KEY_DELETE: "delete",
    KEY_PAUSE: "pause",
    KEY_COMPOSE: "applications",
    113: "volumemute",
    114: "volumedown",
    115: "volumeup",
    121: "numpaddecimal",  # KPCOMMA (teclados ABNT2 e afins)
    KEY_LEFTCTRL: "leftcontrol",
    KEY_RIGHTCTRL: "rightcontrol",
    KEY_LEFTSHIFT: "leftshift",
    KEY_RIGHTSHIFT: "rightshift",
    KEY_LEFTALT: "leftalt",
    KEY_RIGHTALT: "rightalt",
    KEY_LEFTMETA: "leftwindows",
    KEY_RIGHTMETA: "rightwindows",
}
for _row, _start in zip(_LETTERS.split(), _LETTER_CODES, strict=True):
    for _i, _ch in enumerate(_row):
        KEY_NAMES[_start + _i] = _ch
for _i in range(10):  # F1..F10
    KEY_NAMES[KEY_F1 + _i] = f"f{_i + 1}"
KEY_NAMES[87] = "f11"
KEY_NAMES[88] = "f12"
for _i in range(12):  # F13..F24
    KEY_NAMES[183 + _i] = f"f{_i + 13}"

# Teclado numérico: (NumLock desligado, NumLock ligado)
NUMPAD_NAMES: Final[dict[int, tuple[str, str]]] = {
    KEY_KP7: ("numpad7", "numlocknumpad7"),
    KEY_KP8: ("numpad8", "numlocknumpad8"),
    KEY_KP9: ("numpad9", "numlocknumpad9"),
    KEY_KP4: ("numpad4", "numlocknumpad4"),
    KEY_KP5: ("numpad5", "numlocknumpad5"),
    KEY_KP6: ("numpad6", "numlocknumpad6"),
    KEY_KP1: ("numpad1", "numlocknumpad1"),
    KEY_KP2: ("numpad2", "numlocknumpad2"),
    KEY_KP3: ("numpad3", "numlocknumpad3"),
    KEY_KP0: ("numpadinsert", "numlocknumpad0"),
    KEY_KPDOT: ("numpaddelete", "numpaddecimal"),
}


def key_name(code: int, numlock: bool = False) -> str | None:
    """Nome NVDA da tecla ``code`` (considerando o NumLock no teclado numérico)."""
    pair = NUMPAD_NAMES.get(code)
    if pair is not None:
        return pair[1] if numlock else pair[0]
    return KEY_NAMES.get(code)


def code_for_name(name: str) -> int | None:
    """Inverso de :func:`key_name` (para reinjetar gestos via uinput)."""
    name = name.lower()
    for code, pair in NUMPAD_NAMES.items():
        if name in pair:
            return code
    for code, known in KEY_NAMES.items():
        if known == name:
            return code
    return None


# --------------------------------------------------------------------------
# Caracteres no layout US (reserva quando o xkbcommon não estiver disponível)
# --------------------------------------------------------------------------
_US_SHIFTED: Final[dict[str, str]] = {
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",
    "-": "_",
    "=": "+",
    "[": "{",
    "]": "}",
    ";": ":",
    "'": '"',
    "`": "~",
    "\\": "|",
    ",": "<",
    ".": ">",
    "/": "?",
}


def us_character(code: int, shift: bool, capslock: bool = False) -> str | None:
    """Caractere que ``code`` digitaria num teclado US (ou None)."""
    if code == KEY_SPACE:
        return " "
    name = KEY_NAMES.get(code)
    if name is None or len(name) != 1:
        return None
    if name.isalpha():
        return name.upper() if shift != capslock else name
    return _US_SHIFTED.get(name, name) if shift else name


# --------------------------------------------------------------------------
# Keysyms (X11/XKB) para o KeyboardMonitor
# --------------------------------------------------------------------------
XK_INSERT: Final = 0xFF63
XK_KP_INSERT: Final = 0xFF9E
XK_CAPS_LOCK: Final = 0xFFE5

MASK_SHIFT: Final = 1 << 0
MASK_LOCK: Final = 1 << 1
MASK_CONTROL: Final = 1 << 2
MASK_MOD1: Final = 1 << 3  # Alt
MASK_MOD2: Final = 1 << 4  # NumLock
MASK_MOD4: Final = 1 << 6  # Super

MODIFIER_MASKS: Final[dict[str, int]] = {
    "shift": MASK_SHIFT,
    "control": MASK_CONTROL,
    "alt": MASK_MOD1,
    "windows": MASK_MOD4,
}

_NAMED_KEYSYMS: Final[dict[str, int]] = {
    "escape": 0xFF1B,
    "backspace": 0xFF08,
    "tab": 0xFF09,
    "enter": 0xFF0D,
    "space": 0x20,
    "home": 0xFF50,
    "leftarrow": 0xFF51,
    "uparrow": 0xFF52,
    "rightarrow": 0xFF53,
    "downarrow": 0xFF54,
    "pageup": 0xFF55,
    "pagedown": 0xFF56,
    "end": 0xFF57,
    "insert": XK_INSERT,
    "delete": 0xFFFF,
    "applications": 0xFF67,
    "printscreen": 0xFF61,
    "pause": 0xFF13,
    "capslock": XK_CAPS_LOCK,
    "numpad7": 0xFF95,
    "numpad8": 0xFF97,
    "numpad9": 0xFF9A,
    "numpad4": 0xFF96,
    "numpad5": 0xFF9D,
    "numpad6": 0xFF98,
    "numpad1": 0xFF9C,
    "numpad2": 0xFF99,
    "numpad3": 0xFF9B,
    "numpadinsert": XK_KP_INSERT,
    "numpaddelete": 0xFF9F,
    "numpadplus": 0xFFAB,
    "numpadminus": 0xFFAD,
    "numpadmultiply": 0xFFAA,
    "numpaddivide": 0xFFAF,
    "numpadenter": 0xFF8D,
}


def keysym_for_name(name: str) -> int | None:
    """Keysym (nível base) para um nome de tecla NVDA."""
    name = name.lower()
    if name in _NAMED_KEYSYMS:
        return _NAMED_KEYSYMS[name]
    if name.startswith("f") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 35:
            return 0xFFBE + n - 1
    if len(name) == 1 and 0x20 <= ord(name) < 0x7F:
        return ord(name)
    return None
