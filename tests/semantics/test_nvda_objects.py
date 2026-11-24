"""LinuxNVDAObject, mapeamento de papéis/estados, cache e objetos mortos."""

from __future__ import annotations

from dataclasses import dataclass

from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects.base import LinuxNVDAObject, format_key_binding, get_object
from nvda_linux.NVDAObjects.behaviors import EditableText, Terminal
from nvda_linux.NVDAObjects.controlTypes import Role, State
from nvda_linux.NVDAObjects.roleMapping import ATSPI_ROLE_MAP, map_role, map_states
from tests.semantics.fake_atspi import FakeAccessible, FakeValue
from tests.semantics.helpers import obj
from tests.semantics.pages import build_dialog, build_terminal, build_web_page

#: Todos os valores de AtspiRole (libatspi 2.52), para garantir mapeamento completo.
ALL_ATSPI_ROLES = ["INVALID", "ACCELERATOR_LABEL", "ALERT", "ANIMATION", "ARROW", "CALENDAR", "CANVAS", "CHECK_BOX", "CHECK_MENU_ITEM", "COLOR_CHOOSER", "COLUMN_HEADER", "COMBO_BOX", "DATE_EDITOR", "DESKTOP_ICON", "DESKTOP_FRAME", "DIAL", "DIALOG", "DIRECTORY_PANE", "DRAWING_AREA", "FILE_CHOOSER", "FILLER", "FOCUS_TRAVERSABLE", "FONT_CHOOSER", "FRAME", "GLASS_PANE", "HTML_CONTAINER", "ICON", "IMAGE", "INTERNAL_FRAME", "LABEL", "LAYERED_PANE", "LIST", "LIST_ITEM", "MENU", "MENU_BAR", "MENU_ITEM", "OPTION_PANE", "PAGE_TAB", "PAGE_TAB_LIST", "PANEL", "PASSWORD_TEXT", "POPUP_MENU", "PROGRESS_BAR", "PUSH_BUTTON", "RADIO_BUTTON", "RADIO_MENU_ITEM", "ROOT_PANE", "ROW_HEADER", "SCROLL_BAR", "SCROLL_PANE", "SEPARATOR", "SLIDER", "SPIN_BUTTON", "SPLIT_PANE", "STATUS_BAR", "TABLE", "TABLE_CELL", "TABLE_COLUMN_HEADER", "TABLE_ROW_HEADER", "TEAROFF_MENU_ITEM", "TERMINAL", "TEXT", "TOGGLE_BUTTON", "TOOL_BAR", "TOOL_TIP", "TREE", "TREE_TABLE", "UNKNOWN", "VIEWPORT", "WINDOW", "EXTENDED", "HEADER", "FOOTER", "PARAGRAPH", "RULER", "APPLICATION", "AUTOCOMPLETE", "EDITBAR", "EMBEDDED", "ENTRY", "CHART", "CAPTION", "DOCUMENT_FRAME", "HEADING", "PAGE", "SECTION", "REDUNDANT_OBJECT", "FORM", "LINK", "INPUT_METHOD_WINDOW", "TABLE_ROW", "TREE_ITEM", "DOCUMENT_SPREADSHEET", "DOCUMENT_PRESENTATION", "DOCUMENT_TEXT", "DOCUMENT_WEB", "DOCUMENT_EMAIL", "COMMENT", "LIST_BOX", "GROUPING", "IMAGE_MAP", "NOTIFICATION", "INFO_BAR", "LEVEL_BAR", "TITLE_BAR", "BLOCK_QUOTE", "AUDIO", "VIDEO", "DEFINITION", "ARTICLE", "LANDMARK", "LOG", "MARQUEE", "MATH", "RATING", "TIMER", "STATIC", "MATH_FRACTION", "MATH_ROOT", "SUBSCRIPT", "SUPERSCRIPT", "DESCRIPTION_LIST", "DESCRIPTION_TERM", "DESCRIPTION_VALUE", "FOOTNOTE", "CONTENT_DELETION", "CONTENT_INSERTION", "MARK", "SUGGESTION", "PUSH_BUTTON_MENU", "SWITCH"]


@dataclass
class FakeEnum:
    value_nick: str


@dataclass
class FakeLegacyEnum:
    value_name: str


def test_every_atspi_role_is_mapped() -> None:
    missing = [r for r in ALL_ATSPI_ROLES if r not in ATSPI_ROLE_MAP]
    assert missing == []


def test_enum_name_normalizes_real_enums_and_strings() -> None:
    assert _atspi.enum_name(FakeEnum("push-button")) == "PUSH_BUTTON"
    assert _atspi.enum_name(FakeLegacyEnum("ATSPI_STATE_MULTI_LINE")) == "MULTI_LINE"
    assert _atspi.enum_name("document-web") == "DOCUMENT_WEB"
    assert _atspi.enum_name(None) == ""


def test_call_swallows_remote_errors() -> None:
    acc = FakeAccessible("PUSH_BUTTON", "OK")
    acc.kill()
    assert _atspi.call(acc, "get_name", default="?") == "?"
    assert _atspi.call(None, "get_name", default=1) == 1
    assert _atspi.call(acc, "does_not_exist", default=2) == 2
    assert _atspi.states_of(acc) is None


def test_role_refinement_and_states() -> None:
    assert map_role("TEXT", frozenset({"EDITABLE", "ENABLED"})) == Role.EDITABLETEXT
    assert map_role("TEXT", frozenset({"ENABLED"})) == Role.STATICTEXT
    states = map_states(frozenset({"EXPANDABLE", "ENABLED", "VISIBLE", "SHOWING"}), Role.COMBOBOX)
    assert State.COLLAPSED in states and State.UNAVAILABLE not in states
    disabled = map_states(frozenset({"VISIBLE", "SHOWING"}), Role.BUTTON)
    assert State.UNAVAILABLE in disabled
    half = map_states(frozenset({"INDETERMINATE", "CHECKED", "ENABLED", "VISIBLE", "SHOWING"}),
                      Role.CHECKBOX)
    assert State.HALFCHECKED in half and State.CHECKED not in half
    readonly = map_states(frozenset({"ENABLED", "VISIBLE", "SHOWING"}), Role.EDITABLETEXT)
    assert State.READONLY in readonly
    assert State.PROTECTED in map_states(frozenset({"ENABLED", "EDITABLE"}), Role.PASSWORDEDIT)
    sorted_states = map_states(frozenset({"ENABLED"}), Role.TABLECOLUMNHEADER, {"sort": "ascending"})
    assert State.SORTED_ASCENDING in sorted_states
    switch = map_states(frozenset({"ENABLED", "CHECKED"}), Role.SWITCH)
    assert State.ON in switch and State.CHECKED not in switch


def test_object_properties_and_navigation() -> None:
    d = build_dialog()
    window = obj(d.window)
    assert window.role == Role.DIALOG
    assert State.MODAL in window.states
    ok = obj(d.ok)
    assert ok.name == "OK" and ok.role == Role.BUTTON
    assert ok.next == obj(d.cancel)
    assert obj(d.cancel).previous == ok
    assert ok.previous is None
    assert ok.parent is not None and ok.parent.role == Role.FILLER
    panel = obj(d.panel)
    assert panel.first_child == obj(d.group)
    assert [c.name for c in obj(d.group).children] == ["Nome do arquivo", "Senha", "Sobrescrever"]
    assert obj(d.group).last_child == obj(d.check)
    assert ok.app_name == "gedit" and ok.process_id == 2002
    assert ok.location is not None and ok.location.width == 100
    assert ok.keyboard_shortcut == "Alt+O"
    assert [a.role for a in ok.ancestors()][-1] == Role.APPLICATION


def test_values() -> None:
    d = build_dialog()
    assert obj(d.progress).value == "50%"
    slider = FakeAccessible("SLIDER", "Volume", value=FakeValue(7, 0, 10))
    assert obj(slider).value == "7"
    textual = FakeAccessible("SLIDER", "Zoom", value=FakeValue(1, 0, 2, text="100 por cento"))
    assert obj(textual).value == "100 por cento"
    assert obj(d.entry).value == "relatorio.txt"  # multilinha: linha do cursor
    assert obj(d.password).value == ""
    combo = FakeAccessible("COMBO_BOX", "Idioma", children=[
        FakeAccessible("MENU", children=[FakeAccessible("MENU_ITEM", "Inglês"),
                                         FakeAccessible("MENU_ITEM", "Português",
                                                        extra_states=["SELECTED"])])])
    assert obj(combo).value == "Português"


def test_position_info_from_attributes_and_siblings() -> None:
    page = build_web_page()
    item = obj(page.nav_list.children[1])
    assert item.position_info.index_in_group == 2
    assert item.position_info.similar_count == 3
    tagged = FakeAccessible("LIST_ITEM", "x", attributes={"posinset": "4", "setsize": "9"})
    assert obj(tagged).position_info[:2] == (4, 9)
    d = build_dialog()
    assert obj(d.menu_item).position_info[:2] == (1, 2)


def test_heading_level_and_landmark() -> None:
    page = build_web_page()
    assert obj(page.h1).heading_level == 1
    assert obj(page.nav).landmark == "navigation"
    region = FakeAccessible("SECTION", attributes={"xml-roles": "region"})
    assert obj(region).landmark is None  # região sem nome não é landmark
    named = FakeAccessible("SECTION", "Destaques", attributes={"xml-roles": "region"})
    assert obj(named).landmark == "region"


def test_dead_object_never_raises() -> None:
    acc = FakeAccessible("PUSH_BUTTON", "OK", actions=["click"])
    wrapped = obj(acc)
    acc.kill()
    wrapped.invalidate_cache()
    assert wrapped.is_dead
    assert wrapped.name == ""
    assert State.DEFUNCT in wrapped.states
    assert wrapped.children == []
    assert wrapped.parent is None
    assert wrapped.do_action() is False
    assert wrapped.location is None
    assert wrapped.make_text_info().text == ""


def test_cache_and_invalidation() -> None:
    acc = FakeAccessible("PUSH_BUTTON", "Antes")
    wrapped = obj(acc)
    assert wrapped.name == "Antes"
    acc.name = "Depois"
    assert wrapped.name == "Antes"  # ainda em cache
    wrapped.invalidate_cache("name")
    assert wrapped.name == "Depois"
    acc.states.add("PRESSED")
    wrapped.invalidate_cache("states")
    assert State.PRESSED in wrapped.states


def test_registry_reuses_wrappers_and_applies_overlays() -> None:
    d = build_dialog()
    assert get_object(d.ok) is get_object(d.ok)
    assert isinstance(obj(d.entry), EditableText)
    assert not isinstance(obj(d.ok), EditableText)
    t = build_terminal()
    assert isinstance(obj(t.terminal), Terminal)
    assert isinstance(obj(d.ok), LinuxNVDAObject)


def test_find_descendants_uses_collection_and_falls_back() -> None:
    d = build_dialog()
    window = obj(d.window)
    found = window.find_descendants(roles=("PUSH_BUTTON",))
    assert [f.name for f in found] == ["OK", "Cancelar"]
    assert d.window.collection is not None and d.window.collection.calls == 1
    d.window.collection = None  # sem Collection: percurso manual
    found = window.find_descendants(roles=("STATUS_BAR",), count=1)
    assert len(found) == 1 and found[0].role == Role.STATUSBAR


def test_format_key_binding() -> None:
    assert format_key_binding("<Alt>f;<Alt>f:o;<Control>o") == "Ctrl+O"
    assert format_key_binding("o;;") == "O"
    assert format_key_binding("<Primary><Shift>s") == "Ctrl+Shift+S"
    assert format_key_binding("") == ""


def test_event_bridge_converts_and_isolates_callbacks() -> None:
    received: list[_atspi.RawEvent] = []
    bridge = _atspi.EventBridge(received.append)
    if not _atspi.available():
        assert bridge.register(["focus:"]) == []

    @dataclass
    class RealLikeEvent:
        type: str
        source: object
        detail1: int
        detail2: int
        any_data: object

    source = FakeAccessible("PUSH_BUTTON", "OK")
    bridge._on_event(RealLikeEvent("focus:", source, 0, 0, None))
    assert received == [_atspi.RawEvent("focus:", source, 0, 0, None)]

    def broken(_event: _atspi.RawEvent) -> None:
        raise RuntimeError("callback com erro")

    _atspi.EventBridge(broken)._on_event(RealLikeEvent("focus:", source, 0, 0, None))
    bridge.deregister()
