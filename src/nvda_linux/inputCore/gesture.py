"""Identificadores de gesto no formato do NVDA.

Regras (as mesmas do ``inputCore.normalizeGestureIdentifier`` do NVDA):

- fonte e corpo separados por ``:`` — ``kb:``, ``kb(desktop):``,
  ``kb(laptop):``, ``br(brltty):``;
- tudo em minúsculas, modificadores primeiro e em ordem alfabética, depois
  a tecla principal: ``kb:nvda+shift+downarrow``;
- apelidos aceitos na leitura: ``ctrl`` -> ``control``, ``win``/``super``
  -> ``windows``, ``ins`` -> ``insert``, ``esc`` -> ``escape``...
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from nvda_linux.contracts import InputGesture, KeyboardLayout
from nvda_linux.inputCore.keys import MODIFIER_NAMES

_ALIASES: Final[dict[str, str]] = {
    "ctrl": "control",
    "win": "windows",
    "super": "windows",
    "meta": "windows",
    "ins": "insert",
    "del": "delete",
    "esc": "escape",
    "return": "enter",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "up": "uparrow",
    "down": "downarrow",
    "left": "leftarrow",
    "right": "rightarrow",
    "plus": "+",
    "comma": ",",
    "period": ".",
}


@dataclass(frozen=True, slots=True)
class ParsedIdentifier:
    source: str  # "kb", "br"
    qualifier: str | None  # "desktop", "laptop", "brltty"...
    modifiers: tuple[str, ...]
    key: str

    @property
    def normalized(self) -> str:
        head = f"{self.source}({self.qualifier})" if self.qualifier else self.source
        return f"{head}:{'+'.join((*self.modifiers, self.key))}"

    @property
    def generic(self) -> str:
        """Sem o qualificador de layout (``kb(laptop):x`` -> ``kb:x``)."""
        if self.source == "kb":
            return f"kb:{'+'.join((*self.modifiers, self.key))}"
        return self.normalized


def _split_body(body: str) -> list[str]:
    # "nvda++" significa a tecla "+" com NVDA; trata o '+' final como tecla.
    if body.endswith("++"):
        return [*body[:-2].split("+"), "+"] if body[:-2] else ["+"]
    if body == "+":
        return ["+"]
    return body.split("+")


def parse_identifier(identifier: str) -> ParsedIdentifier:
    """Interpreta e normaliza um identificador. Levanta ``ValueError`` se vazio."""
    raw = identifier.strip()
    if ":" not in raw:
        raise ValueError(f"Identificador de gesto sem fonte: {identifier!r}")
    head, body = raw.split(":", 1)
    head = head.strip().lower()
    qualifier: str | None = None
    if "(" in head and head.endswith(")"):
        head, qualifier = head[:-1].split("(", 1)
        qualifier = qualifier.strip() or None
    parts = [p.strip().lower() for p in _split_body(body.strip())]
    parts = [_ALIASES.get(p, p) for p in parts if p]
    if not parts:
        raise ValueError(f"Identificador de gesto vazio: {identifier!r}")
    if head != "kb":
        return ParsedIdentifier(head, qualifier, (), "+".join(parts))
    mods = sorted({p for p in parts[:-1] if p in MODIFIER_NAMES})
    others = [p for p in parts[:-1] if p not in MODIFIER_NAMES]
    key = parts[-1]
    if others:  # "kb:a+b": não é modificador; mantém a ordem original
        key = "+".join([*others, key])
    return ParsedIdentifier("kb", qualifier, tuple(mods), key)


def normalize_identifier(identifier: str) -> str:
    """Forma canônica de ``identifier`` (``"kb:Shift+NVDA+DownArrow"`` -> ``"kb:nvda+shift+downarrow"``)."""
    return parse_identifier(identifier).normalized


def build_identifier(modifiers: Iterable[str], key: str, source: str = "kb") -> str:
    """Monta ``kb:<mods em ordem alfabética>+<tecla>``."""
    mods = sorted({m.lower() for m in modifiers if m.lower() != key.lower()})
    return f"{source}:{'+'.join((*mods, key.lower()))}"


def layout_identifiers(identifier: str, layout: KeyboardLayout) -> list[str]:
    """Identificadores para busca, do mais específico ao genérico (como o NVDA).

    ``kb:nvda+t`` no layout laptop -> ``["kb(laptop):nvda+t", "kb:nvda+t"]``.
    """
    parsed = parse_identifier(identifier)
    if parsed.source != "kb":
        return [parsed.normalized]
    specific = ParsedIdentifier("kb", layout.value, parsed.modifiers, parsed.key).normalized
    return [specific, parsed.generic]


_DISPLAY_PT: Final[dict[str, str]] = {
    "nvda": "NVDA",
    "control": "control",
    "shift": "shift",
    "alt": "alt",
    "windows": "windows",
    "downarrow": "seta abaixo",
    "uparrow": "seta acima",
    "leftarrow": "seta esquerda",
    "rightarrow": "seta direita",
    "space": "espaço",
    "enter": "enter",
    "escape": "esc",
    "backspace": "backspace",
    "pageup": "page up",
    "pagedown": "page down",
    "capslock": "caps lock",
    "numpadinsert": "insert numérico",
    "numpaddelete": "delete numérico",
    "numpadenter": "enter numérico",
    "numpadplus": "mais numérico",
    "numpadminus": "menos numérico",
    "numpadmultiply": "multiplicar numérico",
    "numpaddivide": "dividir numérico",
    "applications": "aplicações",
}


def display_name(identifier: str) -> str:
    """Nome legível para ajuda de entrada: ``"NVDA+shift+seta abaixo"``."""
    try:
        parsed = parse_identifier(identifier)
    except ValueError:
        return identifier
    if parsed.source == "br":
        return f"braille {parsed.key}"
    names: list[str] = []
    for part in (*parsed.modifiers, parsed.key):
        if part in _DISPLAY_PT:
            names.append(_DISPLAY_PT[part])
        elif part.startswith("numpad") and part[6:].isdigit():
            names.append(f"{part[6:]} numérico")
        elif part.startswith("numlocknumpad"):
            names.append(f"{part[13:]} numérico")
        else:
            names.append(part)
    return "+".join(names)


def keyboard_gesture(
    modifiers: Iterable[str],
    key: str,
    *,
    layout: KeyboardLayout,
    character: str | None = None,
    repeat_count: int = 0,
    is_modifier_only: bool = False,
    extra: dict[str, Any] | None = None,
) -> InputGesture:
    """Cria o :class:`InputGesture` de teclado com os extras padronizados.

    ``extra`` sempre traz ``layout`` (``"desktop"``/``"laptop"``),
    ``normalized_identifiers`` (específico do layout primeiro) e
    ``modifiers`` (tupla); no layout laptop, quando houver, também
    ``desktop_equivalent`` (ver :mod:`nvda_linux.inputCore.layouts`).
    """
    from nvda_linux.inputCore.layouts import desktop_equivalent

    identifier = build_identifier(modifiers, key)
    data: dict[str, Any] = {
        "layout": layout.value,
        "normalized_identifiers": layout_identifiers(identifier, layout),
        "modifiers": tuple(sorted({m.lower() for m in modifiers})),
    }
    if layout is KeyboardLayout.LAPTOP:
        equivalent = desktop_equivalent(identifier)
        if equivalent is not None:
            data["desktop_equivalent"] = equivalent
    if extra:
        data.update(extra)
    return InputGesture(
        identifier=identifier,
        is_modifier_only=is_modifier_only,
        repeat_count=repeat_count,
        character=character,
        extra=data,
    )


def gesture_has_modifier(gesture: InputGesture, modifier: str) -> bool:
    mods = gesture.extra.get("modifiers")
    if isinstance(mods, tuple):
        return modifier in mods
    try:
        return modifier in parse_identifier(gesture.identifier).modifiers
    except ValueError:
        return False
