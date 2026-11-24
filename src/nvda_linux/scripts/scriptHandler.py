# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Scripts e gestos no estilo do ``scriptHandler``/``baseObject`` do NVDA.

* :func:`script` decora métodos ``script_*`` com descrição, categoria e gestos
  (comuns, só Desktop ou só Laptop).
* :class:`ScriptableObject` resolve um :class:`InputGesture` para o método
  ligado, olhando gestos de instância, gestos declarados por decorador e o
  mapa de classe ``gesture_map`` (o ``__gestures`` do NVDA).
* :func:`normalize_gesture_id` aplica a regra do contrato: minúsculas e
  modificadores em ordem alfabética.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, ClassVar, TypeVar, cast

from nvda_linux import services
from nvda_linux.contracts import InputGesture, KeyboardLayout, Script

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

MODIFIER_ORDER: tuple[str, ...] = ("alt", "control", "nvda", "shift", "windows")
_MODIFIER_ALIASES = {
    "ctrl": "control",
    "win": "windows",
    "super": "windows",
    "meta": "windows",
    "nvdakey": "nvda",
}
_KEY_ALIASES = {
    "esc": "escape",
    "return": "enter",
    "del": "delete",
    "ins": "insert",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "spacebar": "space",
    "down": "downarrow",
    "up": "uparrow",
    "left": "leftarrow",
    "right": "rightarrow",
}

_ATTR_DESCRIPTION = "_nvda_script_description"
_ATTR_CATEGORY = "_nvda_script_category"
_ATTR_GESTURES = "_nvda_script_gestures"
_ATTR_DESKTOP = "_nvda_script_desktop_gestures"
_ATTR_LAPTOP = "_nvda_script_laptop_gestures"
_ATTR_BYPASS = "_nvda_script_bypass_input_help"
_ATTR_PASSTHROUGH = "_nvda_script_allow_in_pass_through"


def normalize_gesture_id(identifier: str) -> str:
    """``"kb:NVDA+Shift+DownArrow"`` -> ``"kb:nvda+shift+downarrow"``."""
    ident = identifier.strip().lower()
    source, sep, rest = ident.partition(":")
    if not sep:
        source, rest = "kb", ident
    parts = [p for p in rest.split("+") if p]
    if rest.endswith("++"):
        parts.append("plus")
    if not parts:
        return f"{source}:"
    key = _KEY_ALIASES.get(parts[-1], parts[-1])
    mods = {_MODIFIER_ALIASES.get(p, p) for p in parts[:-1]}
    ordered = sorted(mods, key=lambda m: (MODIFIER_ORDER.index(m) if m in MODIFIER_ORDER else 99, m))
    return f"{source}:{'+'.join([*ordered, key])}"


def gesture_modifiers(identifier: str) -> frozenset[str]:
    """Modificadores de um identificador normalizado."""
    rest = normalize_gesture_id(identifier).partition(":")[2]
    return frozenset(rest.split("+")[:-1])


def gesture_main_key(identifier: str) -> str:
    return normalize_gesture_id(identifier).partition(":")[2].split("+")[-1]


def script(
    description: str = "",
    category: str | None = None,
    gesture: str | None = None,
    gestures: Sequence[str] = (),
    desktop_gestures: Sequence[str] = (),
    laptop_gestures: Sequence[str] = (),
    bypass_input_help: bool = False,
    allow_in_pass_through: bool = False,
) -> Callable[[F], F]:
    """Decora um método ``script_*`` (equivalente ao ``@script`` do NVDA).

    ``gesture``/``gestures`` valem nos dois layouts; ``desktop_gestures`` e
    ``laptop_gestures`` só no layout indicado. ``bypass_input_help`` faz o
    script rodar mesmo com a ajuda de entrada ligada (ex.: o próprio NVDA+1).
    ``allow_in_pass_through`` mantém o script ativo no modo de foco de um
    treeInterceptor (ex.: NVDA+Espaço, Esc).
    """
    common = [*([gesture] if gesture else []), *gestures]

    def decorator(fn: F) -> F:
        setattr(fn, _ATTR_DESCRIPTION, description)
        setattr(fn, _ATTR_CATEGORY, category)
        setattr(fn, _ATTR_GESTURES, tuple(normalize_gesture_id(g) for g in common))
        setattr(fn, _ATTR_DESKTOP, tuple(normalize_gesture_id(g) for g in desktop_gestures))
        setattr(fn, _ATTR_LAPTOP, tuple(normalize_gesture_id(g) for g in laptop_gestures))
        setattr(fn, _ATTR_BYPASS, bypass_input_help)
        setattr(fn, _ATTR_PASSTHROUGH, allow_in_pass_through)
        return fn

    return decorator


def script_description(fn: object) -> str:
    """Descrição do script (para a ajuda de entrada)."""
    desc = getattr(fn, _ATTR_DESCRIPTION, None)
    if isinstance(desc, str) and desc:
        return desc
    doc = inspect.getdoc(fn) if callable(fn) else None
    return (doc or "").split("\n", 1)[0]


def script_category(fn: object) -> str | None:
    cat = getattr(fn, _ATTR_CATEGORY, None)
    return cat if isinstance(cat, str) else None


def bypasses_input_help(fn: object) -> bool:
    return bool(getattr(fn, _ATTR_BYPASS, False))


def allowed_in_pass_through(fn: object) -> bool:
    return bool(getattr(fn, _ATTR_PASSTHROUGH, False))


def current_layout() -> KeyboardLayout:
    """Layout de teclado atual (dispatcher da PLATAFORMA, depois configuração)."""
    try:
        return services.dispatcher().layout
    except Exception:  # noqa: BLE001
        log.debug("Dispatcher sem layout; usando a configuração")
    try:
        value = str(services.config().get("keyboard.keyboardLayout", "desktop"))
        return KeyboardLayout(value)
    except Exception:  # noqa: BLE001
        return KeyboardLayout.DESKTOP


def gesture_layout(gesture: InputGesture) -> KeyboardLayout:
    """Layout informado pela PLATAFORMA no gesto (``extra["layout"]``) ou o atual."""
    value = gesture.extra.get("layout")
    if isinstance(value, KeyboardLayout):
        return value
    if isinstance(value, str) and value.strip().lower() in ("desktop", "laptop"):
        return KeyboardLayout(value.strip().lower())
    return current_layout()


def _platform_gesture_map() -> object:
    try:
        return getattr(services.dispatcher(), "gesture_map", None)
    except Exception:  # noqa: BLE001
        return None


async def run_script(fn: Script, gesture: InputGesture) -> None:
    """Executa um script síncrono ou assíncrono."""
    result = fn(gesture)
    if inspect.isawaitable(result):
        await result


class ScriptableObject:
    """Base de tudo que responde a gestos (``baseObject.ScriptableObject``)."""

    #: Mapa de classe ``identificador -> nome do script`` (sem ``script_``).
    gesture_map: ClassVar[Mapping[str, str]] = {}

    _class_map_cache: ClassVar[dict[tuple[type, KeyboardLayout], dict[str, str]]] = {}

    def __init__(self) -> None:
        self._instance_gestures: dict[str, str | None] = {}

    # ----------------------------------------------------------- vínculos
    @classmethod
    def _class_gestures(cls, layout: KeyboardLayout) -> dict[str, str]:
        cache_key = (cls, layout)
        cached = ScriptableObject._class_map_cache.get(cache_key)
        if cached is not None:
            return cached
        mapping: dict[str, str] = {}
        # Da base para a subclasse: a subclasse sobrescreve.
        for klass in reversed(cls.__mro__):
            namespace = getattr(klass, "__dict__", {})
            # ``gesture_map`` (nvda-linux) e ``__gestures`` (NVDA, com name mangling).
            for attr in ("gesture_map", f"_{klass.__name__}__gestures"):
                table = namespace.get(attr, {})
                if isinstance(table, Mapping):
                    for gid, name in table.items():
                        if isinstance(gid, str) and isinstance(name, str):
                            mapping[normalize_gesture_id(gid)] = name
            for attr, value in namespace.items():
                if not attr.startswith("script_") or not callable(value):
                    continue
                name = attr[len("script_"):]
                ids: list[str] = list(getattr(value, _ATTR_GESTURES, ()))
                layout_attr = _ATTR_DESKTOP if layout == KeyboardLayout.DESKTOP else _ATTR_LAPTOP
                ids.extend(getattr(value, layout_attr, ()))
                for gid in ids:
                    mapping[gid] = name
        ScriptableObject._class_map_cache[cache_key] = mapping
        return mapping

    def bind_gesture(self, identifier: str, script_name: str) -> None:
        """Liga um gesto a ``script_<script_name>`` só nesta instância."""
        self._instance_gestures[normalize_gesture_id(identifier)] = script_name

    def bind_gestures(self, mapping: Mapping[str, str]) -> None:
        for gid, name in mapping.items():
            self.bind_gesture(gid, name)

    def remove_gesture(self, identifier: str) -> None:
        """Desliga o gesto nesta instância (mesmo que a classe o declare)."""
        self._instance_gestures[normalize_gesture_id(identifier)] = None

    def clear_gestures(self) -> None:
        self._instance_gestures.clear()

    def gestures_for_layout(self, layout: KeyboardLayout) -> dict[str, str]:
        """Mapa completo ``gesto -> script`` deste objeto no layout."""
        mapping = dict(self._class_gestures(layout))
        for gid, name in self._instance_gestures.items():
            if name is None:
                mapping.pop(gid, None)
            else:
                mapping[gid] = name
        return mapping

    def script_names(self) -> Iterable[str]:
        return (a[len("script_"):] for a in dir(self) if a.startswith("script_"))

    # ----------------------------------------------------------- resolução
    @classmethod
    def gesture_sections(cls) -> list[str]:
        """Nomes de seção do ``gestures.ini`` que valem para esta classe.

        Para cada classe do MRO: ``"<último módulo>.<Classe>"`` (formato do
        NVDA, ex.: ``"globalCommands.GlobalCommands"``) e ``"<módulo>.<Classe>"``.
        """
        sections: list[str] = []
        for klass in cls.__mro__:
            if klass is object:
                continue
            module = getattr(klass, "__module__", "")
            sections.append(f"{module.rsplit('.', 1)[-1]}.{klass.__name__}")
            sections.append(f"{module}.{klass.__name__}")
        return sections

    def _bound_by_user(self, gesture: InputGesture, gid: str) -> tuple[bool, str | None]:
        """Consulta ``gesture.extra["bindings"]`` (gestures.ini lido pela PLATAFORMA).

        Devolve ``(decidido, nome)``: ``(True, None)`` = desassociado pelo usuário.
        """
        sections = self.gesture_sections()
        bindings = gesture.extra.get("bindings")
        if isinstance(bindings, (list, tuple)):
            for binding in bindings:
                try:
                    section, name = binding
                except (TypeError, ValueError):
                    continue
                if (
                    section in sections
                    and name
                    and name != "None"
                    and callable(getattr(self, f"script_{name}", None))
                ):
                    return True, str(name)
        gesture_map = _platform_gesture_map()
        is_unbound = getattr(gesture_map, "is_unbound", None)
        if callable(is_unbound):
            for section in sections[:2]:
                try:
                    if is_unbound(section, gid):
                        return True, None
                except Exception:  # noqa: BLE001
                    break
        return False, None

    def get_script(self, gesture: InputGesture) -> Script | None:
        gid = normalize_gesture_id(gesture.identifier)
        decided, name = self._bound_by_user(gesture, gid)
        if not decided:
            if gid in self._instance_gestures:
                name = self._instance_gestures[gid]
            else:
                name = self._class_gestures(gesture_layout(gesture)).get(gid)
        if not name:
            return None
        fn = getattr(self, f"script_{name}", None)
        if fn is None or not callable(fn):
            log.debug("Gesto %s ligado a script inexistente %s", gid, name)
            return None
        return cast(Script, fn)

    # Alias NVDA para add-ons.
    def getScript(self, gesture: InputGesture) -> Script | None:
        return self.get_script(gesture)

    def bindGesture(self, identifier: str, script_name: str) -> None:
        self.bind_gesture(identifier, script_name)


# --------------------------------------------------------------------------
# Nomes falados de gestos (ajuda de entrada)
# --------------------------------------------------------------------------
_KEY_LABELS = {
    "alt": "Alt",
    "control": "Ctrl",
    "nvda": "NVDA",
    "shift": "Shift",
    "windows": "Windows",
    "downarrow": "seta para baixo",
    "uparrow": "seta para cima",
    "leftarrow": "seta para a esquerda",
    "rightarrow": "seta para a direita",
    "space": "espaço",
    "enter": "Enter",
    "escape": "Esc",
    "tab": "Tab",
    "backspace": "Backspace",
    "home": "Home",
    "end": "End",
    "pageup": "Page Up",
    "pagedown": "Page Down",
    "delete": "Delete",
    "insert": "Insert",
    "capslock": "Caps Lock",
    "applications": "Aplicativos",
    "numpadplus": "mais do teclado numérico",
    "numpadminus": "menos do teclado numérico",
    "numpadmultiply": "asterisco do teclado numérico",
    "numpaddivide": "barra do teclado numérico",
    "numpadenter": "Enter do teclado numérico",
    "numpaddelete": "Delete do teclado numérico",
    "numpadinsert": "Insert do teclado numérico",
    "period": "ponto",
    "comma": "vírgula",
}


def describe_gesture(identifier: str) -> str:
    """Nome legível do gesto: ``"NVDA+Shift+seta para baixo"``."""
    source, _sep, rest = normalize_gesture_id(identifier).partition(":")
    parts = rest.split("+") if rest else []
    labels: list[str] = []
    for part in parts:
        if part in _KEY_LABELS:
            labels.append(_KEY_LABELS[part])
        elif part.startswith("numpad") and part[6:].isdigit():
            labels.append(f"{part[6:]} do teclado numérico")
        elif len(part) == 1 or (len(part) <= 3 and part.startswith("f") and part[1:].isdigit()):
            labels.append(part.upper())
        else:
            labels.append(part)
    text = "+".join(labels)
    if source not in ("kb", ""):
        text = f"{source} {text}".strip()
    return text
