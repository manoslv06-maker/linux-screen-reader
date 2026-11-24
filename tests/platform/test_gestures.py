"""Identificadores, layouts, gestures.ini e xkb."""

from __future__ import annotations

from pathlib import Path

import pytest

from nvda_linux.contracts import KeyboardLayout
from nvda_linux.inputCore import keys, layouts
from nvda_linux.inputCore.gesture import (
    build_identifier,
    display_name,
    keyboard_gesture,
    layout_identifiers,
    normalize_identifier,
    parse_identifier,
)
from nvda_linux.inputCore.gesture_map import GestureMap, split_gesture_list
from nvda_linux.inputCore.xkb import UsKeymap, create_keymap, detect_layout


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("kb:NVDA+Shift+DownArrow", "kb:nvda+shift+downarrow"),
        ("kb:shift+nvda+downArrow", "kb:nvda+shift+downarrow"),
        ("kb:ctrl+alt+win+t", "kb:alt+control+windows+t"),
        ("kb(laptop):NVDA+Ctrl+Home", "kb(laptop):control+nvda+home"),
        ("kb:nvda++", "kb:nvda++"),
        ("kb:nvda+comma", "kb:nvda+,"),
        ("kb:Esc", "kb:escape"),
        ("br(brltty):routing", "br(brltty):routing"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize_identifier(raw) == expected


def test_parse_errors() -> None:
    with pytest.raises(ValueError):
        parse_identifier("semfonte")
    with pytest.raises(ValueError):
        parse_identifier("kb:")


def test_build_and_layout_identifiers() -> None:
    assert build_identifier({"shift", "nvda"}, "downarrow") == "kb:nvda+shift+downarrow"
    assert build_identifier([], "h") == "kb:h"
    assert layout_identifiers("kb:nvda+t", KeyboardLayout.LAPTOP) == [
        "kb(laptop):nvda+t",
        "kb:nvda+t",
    ]


def test_keyboard_gesture_extras() -> None:
    g = keyboard_gesture({"nvda", "shift"}, "uparrow", layout=KeyboardLayout.LAPTOP)
    assert g.identifier == "kb:nvda+shift+uparrow"
    assert g.extra["layout"] == "laptop"
    assert g.extra["modifiers"] == ("nvda", "shift")
    assert g.extra["desktop_equivalent"] == "kb:nvda+numpad8"
    d = keyboard_gesture({"nvda", "shift"}, "uparrow", layout=KeyboardLayout.DESKTOP)
    assert "desktop_equivalent" not in d.extra


def test_display_name() -> None:
    assert display_name("kb:nvda+shift+downarrow") == "NVDA+shift+seta abaixo"
    assert display_name("kb:numpad8") == "8 numérico"
    assert display_name("br(brltty):routing") == "braille routing"


def test_layout_table_consistency() -> None:
    for desktop, laptop in layouts.CORE_COMMANDS.values():
        assert normalize_identifier(desktop) == desktop
        assert normalize_identifier(laptop) == laptop
        assert layouts.desktop_equivalent(laptop) == desktop
        assert layouts.laptop_equivalent(desktop) == laptop
    assert layouts.gesture_for("sayAll", KeyboardLayout.LAPTOP) == "kb:nvda+a"
    assert layouts.parse_layout("LAPTOP") is KeyboardLayout.LAPTOP
    assert layouts.parse_layout("x") is KeyboardLayout.DESKTOP


def test_key_tables() -> None:
    assert keys.key_name(keys.KEY_KP8) == "numpad8"
    assert keys.key_name(keys.KEY_KP8, numlock=True) == "numlocknumpad8"
    assert keys.key_name(keys.KEY_KP0) == "numpadinsert"
    assert keys.key_name(30) == "a" and keys.key_name(57) == "space"
    assert keys.code_for_name("downarrow") == keys.KEY_DOWN
    assert keys.code_for_name("numpad8") == keys.KEY_KP8
    assert keys.us_character(30, shift=True) == "A"
    assert keys.us_character(3, shift=True) == "@"
    assert keys.keysym_for_name("h") == ord("h")
    assert keys.keysym_for_name("f5") == 0xFFC2


# ------------------------------------------------------------------ gestures.ini
INI = """
; comentário
[globalCommands.GlobalCommands]
reportCurrentFocus = kb:NVDA+Tab, kb(laptop):nvda+shift+tab
None = kb:nvda+t
quoted = "kb:nvda+,", kb:nvda+f12

[browseMode.BrowseModeTreeInterceptor]
nextHeading = kb:h
"""


def test_gesture_map_parse_and_lookup() -> None:
    gm = GestureMap()
    gm.loads(INI)
    assert gm.bindings_for(["kb:nvda+tab"]) == [
        ("globalCommands.GlobalCommands", "reportCurrentFocus")
    ]
    assert gm.bindings_for(["kb(laptop):nvda+shift+tab", "kb:nvda+shift+tab"]) == [
        ("globalCommands.GlobalCommands", "reportCurrentFocus")
    ]
    assert gm.bindings_for(["kb:nvda+,"]) == [("globalCommands.GlobalCommands", "quoted")]
    assert gm.is_unbound("globalCommands.GlobalCommands", "kb:NVDA+T")
    assert gm.gestures_for("browseMode.BrowseModeTreeInterceptor", "nextHeading") == ["kb:h"]
    assert len(gm) == 5


def test_gesture_map_roundtrip(tmp_path: Path) -> None:
    gm = GestureMap()
    gm.loads(INI)
    path = tmp_path / "gestures.ini"
    gm.save(path)
    again = GestureMap()
    assert again.load(path)
    assert again.to_ini() == gm.to_ini()
    assert not GestureMap().load(tmp_path / "nao-existe.ini")


def test_gesture_map_invalid_text_is_tolerated() -> None:
    gm = GestureMap()
    gm.loads("isto não é ini")
    gm.loads("[s]\nscript = kb:\n")
    assert len(gm) == 0


def test_split_gesture_list() -> None:
    assert split_gesture_list('kb:a, "kb:nvda+,", kb:b') == ["kb:a", "kb:nvda+,", "kb:b"]


# ------------------------------------------------------------------ xkb
def test_xkb_abnt2_characters() -> None:
    km = create_keymap("br", "abnt2")
    if isinstance(km, UsKeymap):
        pytest.skip("libxkbcommon indisponível")
    assert km.character(39) == "ç"
    km.update(keys.KEY_LEFTSHIFT, True)
    assert km.character(39) == "Ç"
    km.update(keys.KEY_LEFTSHIFT, False)
    assert km.character(30) == "a"


def test_invalid_layout_falls_back_to_us() -> None:
    km = create_keymap("layout-que-nao-existe-xyz")
    assert km.character(30) == "a"


def test_us_keymap_shift_and_caps() -> None:
    km = UsKeymap()
    assert km.character(30) == "a"
    km.update(keys.KEY_CAPSLOCK, True)
    assert km.character(30) == "A"
    km.update(keys.KEY_LEFTSHIFT, True)
    assert km.character(30) == "a"


def test_detect_layout_from_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XKB_DEFAULT_LAYOUT", raising=False)
    (tmp_path / "etc/default").mkdir(parents=True)
    (tmp_path / "etc/default/keyboard").write_text(
        'XKBMODEL="pc105"\nXKBLAYOUT="br,us"\nXKBVARIANT="abnt2"\n', encoding="utf-8"
    )
    assert detect_layout(tmp_path) == ("br", "abnt2")
    assert detect_layout(tmp_path / "vazio") == ("us", "")
    monkeypatch.setenv("XKB_DEFAULT_LAYOUT", "pt")
    assert detect_layout(tmp_path)[0] == "pt"
