"""Árvore AT-SPI2 falsa com a mesma API do ``gi.repository.Atspi``.

Papéis, estados e granularidades são strings (``"PUSH_BUTTON"``, ``"FOCUSED"``,
``"LINE"``); a camada ``_atspi`` normaliza enums reais e strings do mesmo jeito.
:meth:`FakeAccessible.kill` simula um objeto morto: toda chamada levanta
``RuntimeError`` (como o ``GLib.GError`` do AT-SPI2 real).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from nvda_linux.NVDAObjects import _atspi, textUtils

EMBED = _atspi.EMBEDDED_OBJECT_CHAR
BASE_STATES = frozenset({"ENABLED", "SENSITIVE", "SHOWING", "VISIBLE"})


class DeadObjectError(RuntimeError):
    """Equivalente ao GLib.GError de objeto inexistente."""


@dataclass
class FakeTextRange:
    content: str
    start_offset: int
    end_offset: int


@dataclass
class FakeRange:
    start_offset: int
    end_offset: int


@dataclass
class FakeRect:
    x: int
    y: int
    width: int
    height: int


class FakeStateSet:
    def __init__(self, states: Iterable[str]) -> None:
        self._states = set(states)

    def get_states(self) -> list[str]:
        return sorted(self._states)

    def contains(self, state: str) -> bool:
        return state in self._states


class FakeText:
    def __init__(self, owner: FakeAccessible, text: str, caret: int = 0) -> None:
        self.owner = owner
        self.text = text
        self.caret = caret
        self.selections: list[tuple[int, int]] = []
        self.attributes: dict[str, str] = {}
        self.fail_string_at_offset = False

    def _check(self) -> None:
        self.owner._check()

    def get_character_count(self) -> int:
        self._check()
        return len(self.text)

    def get_text(self, start: int, end: int) -> str:
        self._check()
        if end < 0:
            end = len(self.text)
        return self.text[start:end]

    def get_caret_offset(self) -> int:
        self._check()
        return self.caret

    def set_caret_offset(self, offset: int) -> bool:
        self._check()
        self.caret = max(0, min(offset, len(self.text)))
        return True

    def get_string_at_offset(self, offset: int, granularity: Any) -> FakeTextRange:
        self._check()
        if self.fail_string_at_offset:
            raise DeadObjectError("get_string_at_offset falhou")
        unit = _atspi.enum_name(granularity)
        if unit == "WORD":
            start, end = textUtils.word_bounds(self.text, offset)
        elif unit in ("LINE", "PARAGRAPH", "SENTENCE"):
            start, end = textUtils.line_bounds(self.text, offset)
        else:
            start, end = textUtils.char_bounds(self.text, offset)
        return FakeTextRange(self.text[start:end], start, end)

    def get_n_selections(self) -> int:
        return len(self.selections)

    def get_selection(self, index: int) -> FakeRange:
        start, end = self.selections[index]
        return FakeRange(start, end)

    def set_selection(self, index: int, start: int, end: int) -> bool:
        self.selections[index] = (start, end)
        return True

    def add_selection(self, start: int, end: int) -> bool:
        self.selections.append((start, end))
        return True

    def get_attribute_run(self, offset: int, include_defaults: bool) -> tuple[dict[str, str], int, int]:
        return dict(self.attributes), 0, len(self.text)


class FakeAction:
    def __init__(self, owner: FakeAccessible, names: list[str], key_binding: str = "") -> None:
        self.owner = owner
        self.names = names
        self.key_binding = key_binding
        self.performed: list[int] = []

    def get_n_actions(self) -> int:
        return len(self.names)

    def get_action_name(self, index: int) -> str:
        return self.names[index]

    def get_key_binding(self, index: int) -> str:
        return self.key_binding

    def do_action(self, index: int) -> bool:
        self.owner._check()
        self.performed.append(index)
        if self.owner.on_action is not None:
            self.owner.on_action(self.owner)
        return True


class FakeComponent:
    def __init__(self, owner: FakeAccessible, rect: FakeRect) -> None:
        self.owner = owner
        self.rect = rect

    def get_extents(self, coord_type: Any) -> FakeRect:
        self.owner._check()
        return self.rect

    def grab_focus(self) -> bool:
        self.owner._check()
        self.owner.focus_requests += 1
        if self.owner.desktop is not None:
            self.owner.desktop.move_focus(self.owner)
        return True


class FakeValue:
    def __init__(self, current: float, minimum: float, maximum: float, text: str = "") -> None:
        self.current = current
        self.minimum = minimum
        self.maximum = maximum
        self.text = text

    def get_current_value(self) -> float:
        return self.current

    def get_minimum_value(self) -> float:
        return self.minimum

    def get_maximum_value(self) -> float:
        return self.maximum

    def get_text(self) -> str:
        return self.text


class FakeTable:
    def __init__(self, rows: int, cols: int) -> None:
        self.rows = rows
        self.cols = cols

    def get_n_rows(self) -> int:
        return self.rows

    def get_n_columns(self) -> int:
        return self.cols


class FakeCollection:
    def __init__(self, owner: FakeAccessible) -> None:
        self.owner = owner
        self.calls = 0

    def get_matches(self, rule: Any, sort: Any, count: int, traverse: bool) -> list[FakeAccessible]:
        self.owner._check()
        self.calls += 1
        assert isinstance(rule, _atspi.SimpleMatchRule)
        found: list[FakeAccessible] = []
        for node in self.owner.descendants():
            if rule.roles and node.role not in rule.roles:
                continue
            if rule.states and not set(rule.states) <= node.states:
                continue
            found.append(node)
            if count and len(found) >= count:
                break
        return found


class FakeDesktop:
    """Raiz (``Atspi.get_desktop(0)``) e controle do foco falso."""

    def __init__(self) -> None:
        self.root = FakeAccessible("DESKTOP_FRAME", "main")
        self.root.desktop = self
        self.focused: FakeAccessible | None = None

    def add_app(self, app: FakeAccessible) -> FakeAccessible:
        self.root.add(app)
        app.attach_desktop(self)
        return app

    def move_focus(self, acc: FakeAccessible) -> None:
        if self.focused is not None:
            self.focused.states.discard("FOCUSED")
        acc.states.add("FOCUSED")
        self.focused = acc


class FakeAccessible:
    """``Atspi.Accessible`` falso."""

    def __init__(
        self,
        role: str,
        name: str = "",
        children: Iterable[FakeAccessible] = (),
        states: Iterable[str] | None = None,
        extra_states: Iterable[str] = (),
        text: str | None = None,
        attributes: dict[str, str] | None = None,
        description: str = "",
        actions: list[str] | None = None,
        key_binding: str = "",
        value: FakeValue | None = None,
        table: FakeTable | None = None,
        rect: FakeRect | None = None,
        pid: int = 4242,
        collection: bool = True,
    ) -> None:
        self.role = role
        self.name = name
        base = set(BASE_STATES if states is None else states)
        self.states: set[str] = base | set(extra_states)
        self.parent: FakeAccessible | None = None
        self.children: list[FakeAccessible] = []
        self.attributes = dict(attributes or {})
        self.description = description
        self.text_iface: FakeText | None = FakeText(self, text) if text is not None else None
        self.action: FakeAction | None = (
            FakeAction(self, actions or [], key_binding)
            if actions is not None or key_binding
            else None
        )
        self.value = value
        self.table = table
        self.component = FakeComponent(self, rect or FakeRect(0, 0, 100, 20))
        self.collection = FakeCollection(self) if collection else None
        self.pid = pid
        self.app: FakeAccessible | None = None
        self.desktop: FakeDesktop | None = None
        self.dead = False
        self.focus_requests = 0
        self.on_action: Any = None
        for child in children:
            self.add(child)

    # ------------------------------------------------------------ montagem
    def add(self, child: FakeAccessible, index: int | None = None) -> FakeAccessible:
        child.parent = self
        if index is None:
            self.children.append(child)
        else:
            self.children.insert(index, child)
        if self.app is not None:
            child.attach_app(self.app)
        if self.desktop is not None:
            child.attach_desktop(self.desktop)
        return child

    def remove(self, child: FakeAccessible) -> None:
        self.children.remove(child)
        child.parent = None

    def attach_app(self, app: FakeAccessible) -> None:
        self.app = app
        self.pid = app.pid
        for child in self.children:
            child.attach_app(app)

    def attach_desktop(self, desktop: FakeDesktop) -> None:
        self.desktop = desktop
        for child in self.children:
            child.attach_desktop(desktop)

    def descendants(self) -> Iterator[FakeAccessible]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def kill(self) -> None:
        self.dead = True

    def _check(self) -> None:
        if self.dead:
            raise DeadObjectError("The application no longer exists")

    # ------------------------------------------------------------ API Atspi.Accessible
    def get_name(self) -> str:
        self._check()
        return self.name

    def get_role(self) -> str:
        self._check()
        return self.role

    def get_role_name(self) -> str:
        return self.role.lower().replace("_", " ")

    def get_description(self) -> str:
        self._check()
        return self.description

    def get_state_set(self) -> FakeStateSet:
        self._check()
        return FakeStateSet(self.states)

    def get_parent(self) -> FakeAccessible | None:
        self._check()
        return self.parent

    def get_child_count(self) -> int:
        self._check()
        return len(self.children)

    def get_child_at_index(self, index: int) -> FakeAccessible | None:
        self._check()
        return self.children[index] if 0 <= index < len(self.children) else None

    def get_index_in_parent(self) -> int:
        self._check()
        return self.parent.children.index(self) if self.parent is not None else -1

    def get_attributes(self) -> dict[str, str]:
        self._check()
        return dict(self.attributes)

    def get_application(self) -> FakeAccessible | None:
        self._check()
        return self.app

    def get_process_id(self) -> int:
        self._check()
        return self.pid

    def get_text_iface(self) -> FakeText | None:
        self._check()
        return self.text_iface

    def get_action_iface(self) -> FakeAction | None:
        return self.action

    def get_value_iface(self) -> FakeValue | None:
        return self.value

    def get_component_iface(self) -> FakeComponent:
        return self.component

    def get_collection_iface(self) -> FakeCollection | None:
        return self.collection

    def get_table_iface(self) -> FakeTable | None:
        return self.table

    def __repr__(self) -> str:
        return f"<Fake {self.role} {self.name!r}>"


# --------------------------------------------------------------------------
# Atalhos de construção
# --------------------------------------------------------------------------
def hypertext(role: str, *parts: str | FakeAccessible, **kwargs: Any) -> FakeAccessible:
    """Objeto com ``Atspi.Text`` cujo texto tem ``U+FFFC`` para cada filho."""
    text = "".join(p if isinstance(p, str) else EMBED for p in parts)
    children = [p for p in parts if isinstance(p, FakeAccessible)]
    return FakeAccessible(role, children=children, text=text, **kwargs)


def container(role: str, *children: FakeAccessible, **kwargs: Any) -> FakeAccessible:
    """Contêiner com hipertexto só de objetos embutidos (como no Firefox)."""
    return hypertext(role, *children, **kwargs)


def app(name: str, *windows: FakeAccessible, pid: int = 4242) -> FakeAccessible:
    application = FakeAccessible("APPLICATION", name, children=windows, pid=pid)
    application.attach_app(application)
    return application
