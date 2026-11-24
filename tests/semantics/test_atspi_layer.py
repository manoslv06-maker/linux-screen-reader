"""Camada _atspi contra comportamentos do PyGObject real (vistos no Fedora 45)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects.controlTypes import Role
from nvda_linux.NVDAObjects.roleMapping import map_role


class ClashingAccessible:
    """Como o Atspi.Accessible do PyGObject: ``get_text_iface()`` devolve o próprio
    objeto, e os métodos antigos ``get_text()``/``get_name()`` não têm argumentos."""

    def __init__(self, text: str, actions: list[str]) -> None:
        self.text = text
        self.actions = actions

    def get_text_iface(self) -> ClashingAccessible:
        return self

    def get_action_iface(self) -> ClashingAccessible:
        return self

    def get_text(self) -> ClashingAccessible:  # Atspi.Accessible.get_text (antigo)
        return self

    def get_name(self) -> str:  # Atspi.Accessible.get_name
        return "nome do objeto"


class FakeText:
    @staticmethod
    def get_text(obj: ClashingAccessible, start: int, end: int) -> str:
        return obj.text[start:end]

    @staticmethod
    def get_character_count(obj: ClashingAccessible) -> int:
        return len(obj.text)


class FakeAction:
    @staticmethod
    def get_name(obj: ClashingAccessible, index: int) -> str:
        return obj.actions[index]


@pytest.fixture
def real_like_atspi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_atspi, "Atspi", SimpleNamespace(Text=FakeText, Action=FakeAction))


def test_text_interface_calls_the_interface_method(real_like_atspi: None) -> None:
    raw = ClashingAccessible("Primeira linha do texto de teste.", ["click"])
    text = _atspi.iface(raw, "text")
    assert _atspi.call(text, "get_character_count", default=0) == 33
    assert _atspi.call(text, "get_text", 0, 8, default="") == "Primeira"


def test_action_name_is_not_the_object_name(real_like_atspi: None) -> None:
    raw = ClashingAccessible("", ["press", "jump"])
    action = _atspi.iface(raw, "action")
    assert _atspi.call(action, "get_name", 1, default="") == "jump"
    assert _atspi.name_of(raw) == "nome do objeto"


def test_proxy_falls_back_to_object_attributes(real_like_atspi: None) -> None:
    raw = ClashingAccessible("abc", [])
    text = _atspi.iface(raw, "text")
    assert text.actions == []  # atributo do próprio objeto
    assert text == _atspi.iface(raw, "text") and hash(text) == hash(raw)


def test_without_real_atspi_the_object_is_returned_as_is() -> None:
    raw = ClashingAccessible("abc", [])
    assert _atspi.iface(raw, "text") is raw


def test_new_button_role_name_maps_to_button() -> None:
    assert map_role("BUTTON", frozenset()) == Role.BUTTON
    assert map_role("PUSH_BUTTON", frozenset()) == Role.BUTTON


def test_match_rule_skips_role_names_missing_in_this_atspi(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}

    class MatchRule:
        @staticmethod
        def new(*args: Any) -> str:
            created["roles"] = args[4]
            return "regra"

    fake = SimpleNamespace(
        Role=SimpleNamespace(BUTTON="r-button", HEADING="r-heading"),  # sem PUSH_BUTTON
        StateType=SimpleNamespace(),
        StateSet=SimpleNamespace(new=lambda states: states),
        CollectionMatchType=SimpleNamespace(ALL="all", ANY="any"),
        MatchRule=MatchRule,
    )
    monkeypatch.setattr(_atspi, "Atspi", fake)
    assert _atspi.make_match_rule(["PUSH_BUTTON", "BUTTON", "HEADING"]) == "regra"
    assert created["roles"] == ["r-button", "r-heading"]
    assert _atspi.make_match_rule(["SO_EXISTE_NO_FUTURO"]) is None
