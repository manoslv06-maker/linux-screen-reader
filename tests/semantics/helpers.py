"""Atalhos para injetar eventos e gestos nos testes."""

from __future__ import annotations

from typing import Any

from nvda_linux.contracts import InputGesture
from nvda_linux.NVDAObjects._atspi import RawEvent
from nvda_linux.NVDAObjects.base import LinuxNVDAObject, get_object
from nvda_linux.scripts.runtime import Runtime
from nvda_linux.scripts.scriptHandler import run_script
from tests.semantics.fake_atspi import FakeAccessible


def gesture(
    identifier: str,
    repeat: int = 0,
    character: str | None = None,
    modifier_only: bool = False,
    **extra: Any,
) -> InputGesture:
    return InputGesture(identifier, modifier_only, repeat, character, dict(extra))


async def press(rt: Runtime, identifier: str, repeat: int = 0, character: str | None = None,
                **extra: Any) -> bool:
    """Faz o que o dispatcher da PLATAFORMA faz: primeiro script da cadeia, ou nada."""
    g = gesture(identifier, repeat, character, **extra)
    script = rt.chain.find_script(g)
    if script is None:
        return False
    await run_script(script, g)
    return True


def event(rt: Runtime, etype: str, source: FakeAccessible, detail1: int = 0, detail2: int = 0,
          any_data: Any = None) -> None:
    assert rt.events is not None
    rt.events.handle_raw_event(RawEvent(etype, source, detail1, detail2, any_data))


def focus(rt: Runtime, acc: FakeAccessible) -> LinuxNVDAObject:
    """Move o foco falso e emite ``object:state-changed:focused``."""
    if acc.desktop is not None:
        acc.desktop.move_focus(acc)
    else:
        acc.states.add("FOCUSED")
    event(rt, "object:state-changed:focused", acc, 1)
    obj = get_object(acc)
    assert obj is not None
    return obj


def obj(acc: FakeAccessible) -> LinuxNVDAObject:
    wrapped = get_object(acc)
    assert wrapped is not None
    return wrapped
