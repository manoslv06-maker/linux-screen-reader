"""``LinuxNVDAObject``: o ``NVDAObject`` do NVDA sobre ``Atspi.Accessible``.

* Toda propriedade remota passa por :mod:`._atspi` e nunca levanta exceção:
  objetos mortos devolvem valores vazios e :attr:`is_dead` fica verdadeiro.
* Cache leve por objeto: o papel é guardado até ser invalidado; nome,
  estados, valor etc. expiram em :attr:`cache_ttl` segundos ou quando o
  ``eventHandler`` chama :meth:`invalidate_cache` ao receber um evento.
* :func:`get_object` reaproveita o mesmo wrapper para o mesmo objeto remoto
  (registro fraco) e aplica classes "overlay" (comportamentos, como o
  ``chooseNVDAObjectOverlayClasses`` do NVDA).
"""

from __future__ import annotations

import logging
import time
import weakref
from collections.abc import Callable, Hashable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, TypeVar, cast

from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects.controlTypes import (
    LANDMARK_LABELS,
    LAYOUT_ROLES,
    OutputReason,
    Role,
    State,
)
from nvda_linux.NVDAObjects.roleMapping import WEB_DOCUMENT_ROLES, map_role, map_states
from nvda_linux.NVDAObjects.textInfos import (
    AtspiTextBackend,
    OffsetsTextInfo,
    Position,
    StringTextBackend,
    TextUnit,
)
from nvda_linux.scripts.scriptHandler import ScriptableObject

if TYPE_CHECKING:
    from nvda_linux.appModules.appModuleHandler import AppModule
    from nvda_linux.treeInterceptors.base import TreeInterceptor

log = logging.getLogger(__name__)

T = TypeVar("T")

_FOREVER = float("inf")
_MAX_CHILDREN = 10000
_POSITION_SIBLING_LIMIT = 500
_POSITION_ROLES = frozenset(
    {
        Role.LISTITEM,
        Role.MENUITEM,
        Role.CHECKMENUITEM,
        Role.RADIOMENUITEM,
        Role.TAB,
        Role.TREEVIEWITEM,
    }
)


class Location(NamedTuple):
    """Retângulo em coordenadas de tela."""

    left: int
    top: int
    width: int
    height: int


class PositionInfo(NamedTuple):
    """``N de M`` (``index_in_group`` de ``similar_count``) e nível."""

    index_in_group: int | None
    similar_count: int | None
    level: int | None


_KEY_NAMES = {
    "control": "Ctrl",
    "primary": "Ctrl",
    "ctrl": "Ctrl",
    "alt": "Alt",
    "mod1": "Alt",
    "shift": "Shift",
    "super": "Windows",
    "meta": "Meta",
}


def format_key_binding(binding: str) -> str:
    """``"<Alt>f;<Alt>f:o;<Control>o"`` -> ``"Ctrl+O"`` (atalho, ou mnemônico)."""
    parts = binding.split(";")
    shortcut = parts[2].strip() if len(parts) >= 3 else ""
    chosen = shortcut or parts[0].strip()
    if not chosen:
        return ""
    out: list[str] = []
    rest = chosen.strip()
    while rest.startswith("<"):
        close = rest.find(">")
        if close < 0:
            break
        mod = rest[1:close].lower()
        out.append(_KEY_NAMES.get(mod, mod.capitalize()))
        rest = rest[close + 1 :]
    key = rest.split(":")[0].strip()
    if key:
        out.append(key.upper() if len(key) == 1 else key.capitalize())
    return "+".join(out)


class LinuxNVDAObject(ScriptableObject):
    """Envolve um ``Atspi.Accessible`` com a API dos NVDAObjects."""

    #: Validade (s) das propriedades mutáveis no cache.
    cache_ttl: ClassVar[float] = 0.5
    #: Liga/desliga o cache globalmente (depuração).
    cache_enabled: ClassVar[bool] = True

    def __init__(self, raw: _atspi.RawAccessible, key: Hashable | None = None) -> None:
        super().__init__()
        self._raw = raw
        self._key: Hashable = key if key is not None else _atspi.object_key(raw)
        self._cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------ identidade
    @property
    def raw(self) -> _atspi.RawAccessible:
        """O ``Atspi.Accessible`` subjacente."""
        return self._raw

    @property
    def key(self) -> Hashable:
        return self._key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LinuxNVDAObject) and other._key == self._key

    def __hash__(self) -> int:
        return hash(self._key)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.role.name} {self.name!r}>"

    # ------------------------------------------------------------ cache
    def _cached(self, name: str, compute: Callable[[], T], ttl: float | None = None) -> T:
        if not self.cache_enabled:
            return compute()
        now = time.monotonic()
        hit = self._cache.get(name)
        if hit is not None and hit[0] > now:
            return cast(T, hit[1])
        value = compute()
        lifetime = self.cache_ttl if ttl is None else ttl
        self._cache[name] = (now + lifetime, value)
        return value

    def invalidate_cache(self, *names: str) -> None:
        """Esquece propriedades do cache (todas, se ``names`` vazio)."""
        if not names:
            self._cache.clear()
            return
        for name in names:
            self._cache.pop(name, None)
            if name == "states":
                self._cache.pop("atspi_states", None)
                self._cache.pop("role", None)
            if name == "children":
                self._cache.pop("child_count", None)
            if name in ("text", "value"):
                self._cache.pop("value", None)

    # ------------------------------------------------------------ AT-SPI2 cru
    @property
    def atspi_role(self) -> str:
        return self._cached("atspi_role", lambda: _atspi.role_of(self._raw), _FOREVER)

    @property
    def atspi_states(self) -> frozenset[str] | None:
        return self._cached("atspi_states", lambda: _atspi.states_of(self._raw))

    @property
    def attributes(self) -> dict[str, str]:
        return dict(self._cached("attributes", lambda: _atspi.attributes_of(self._raw)))

    # ------------------------------------------------------------ propriedades NVDA
    @property
    def name(self) -> str:
        return self._cached("name", lambda: _atspi.name_of(self._raw))

    @property
    def role(self) -> Role:
        return self._cached(
            "role",
            lambda: map_role(self.atspi_role, self.atspi_states or frozenset()),
            _FOREVER,
        )

    @property
    def states(self) -> frozenset[State]:
        def compute() -> frozenset[State]:
            raw_states = self.atspi_states
            if raw_states is None:
                return frozenset({State.DEFUNCT})
            return map_states(raw_states, self.role, self.attributes)

        return self._cached("states", compute)

    @property
    def description(self) -> str:
        return self._cached("description", lambda: _atspi.description_of(self._raw))

    @property
    def value(self) -> str:
        return self._cached("value", self._compute_value)

    def _compute_value(self) -> str:
        role = self.role
        text_iface = self.text_iface
        if role in (Role.EDITABLETEXT, Role.COMBOBOX, Role.SPINBUTTON) and text_iface is not None:
            if State.PROTECTED in self.states:
                return ""
            backend = AtspiTextBackend(text_iface)
            if State.MULTILINE in self.states:
                info = OffsetsTextInfo(backend, Position.CARET)
                info.expand(TextUnit.LINE)
                return info.text.rstrip("\n")
            return backend.get_text(0, min(backend.length(), 10000))
        value_iface = _atspi.iface(self._raw, "value")
        if value_iface is not None:
            text = str(_atspi.call(value_iface, "get_text", default="") or "")
            if text:
                return text
            try:
                current = float(_atspi.call(value_iface, "get_current_value", default=0.0))
                low = float(_atspi.call(value_iface, "get_minimum_value", default=0.0))
                high = float(_atspi.call(value_iface, "get_maximum_value", default=0.0))
            except (TypeError, ValueError):
                return ""
            if role == Role.PROGRESSBAR and high > low:
                return f"{round((current - low) * 100 / (high - low))}%"
            return f"{current:g}"
        if role == Role.COMBOBOX:
            selected = self._find_selected_descendant(depth=2)
            if selected is not None:
                return selected.name
        return ""

    def _find_selected_descendant(self, depth: int) -> LinuxNVDAObject | None:
        if depth <= 0:
            return None
        for child in self.children[:200]:
            if State.SELECTED in child.states:
                return child
            found = child._find_selected_descendant(depth - 1)
            if found is not None:
                return found
        return None

    @property
    def keyboard_shortcut(self) -> str:
        def compute() -> str:
            action = _atspi.iface(self._raw, "action")
            binding = str(_atspi.call(action, "get_key_binding", 0, default="") or "")
            return format_key_binding(binding) if binding else ""

        return self._cached("keyboard_shortcut", compute, 5.0)

    @property
    def heading_level(self) -> int | None:
        if self.role != Role.HEADING:
            return None
        try:
            level = int(self.attributes.get("level", "0"))
        except ValueError:
            return None
        return level or None

    @property
    def landmark(self) -> str | None:
        """Ponto de referência ARIA/HTML5 (``"main"``, ``"navigation"``...)."""
        xml_roles = self.attributes.get("xml-roles", "").split()
        candidate = xml_roles[0] if xml_roles else ""
        if candidate in LANDMARK_LABELS:
            if candidate in ("region", "form") and not self.name:
                return None
            return candidate
        if self.role == Role.LANDMARK:
            return candidate or "region"
        return None

    @property
    def position_info(self) -> PositionInfo:
        """Posição ``N de M`` e nível, como ``positionInfo`` do NVDA."""

        def compute() -> PositionInfo:
            attrs = self.attributes
            index = _int_or_none(attrs.get("posinset"))
            count = _int_or_none(attrs.get("setsize"))
            level = _int_or_none(attrs.get("level")) if self.role != Role.HEADING else None
            if (index is None or count is None) and self.role in _POSITION_ROLES:
                parent = self.parent
                if parent is not None and parent.child_count <= _POSITION_SIBLING_LIMIT:
                    siblings = [c for c in parent.children if c.role == self.role]
                    if self in siblings:
                        index = siblings.index(self) + 1
                        count = len(siblings)
            return PositionInfo(index, count, level)

        return self._cached("position_info", compute)

    # ------------------------------------------------------------ hierarquia
    @property
    def parent(self) -> LinuxNVDAObject | None:
        return self._cached("parent", lambda: get_object(_atspi.parent_of(self._raw)))

    @property
    def child_count(self) -> int:
        return self._cached("child_count", lambda: _atspi.child_count(self._raw))

    def child_at(self, index: int) -> LinuxNVDAObject | None:
        if index < 0 or index >= self.child_count:
            return None
        return get_object(_atspi.child_at(self._raw, index))

    @property
    def children(self) -> list[LinuxNVDAObject]:
        def compute() -> list[LinuxNVDAObject]:
            result: list[LinuxNVDAObject] = []
            for raw_child in _atspi.children_of(self._raw, _MAX_CHILDREN):
                child = get_object(raw_child)
                if child is not None:
                    result.append(child)
            return result

        return list(self._cached("children", compute))

    @property
    def index_in_parent(self) -> int:
        return self._cached("index_in_parent", lambda: _atspi.index_in_parent(self._raw))

    @property
    def first_child(self) -> LinuxNVDAObject | None:
        return self.child_at(0)

    @property
    def last_child(self) -> LinuxNVDAObject | None:
        return self.child_at(self.child_count - 1)

    @property
    def next(self) -> LinuxNVDAObject | None:
        """Próximo irmão (``next`` do NVDA)."""
        parent = self.parent
        idx = self.index_in_parent
        if parent is None or idx < 0:
            return None
        return parent.child_at(idx + 1)

    @property
    def previous(self) -> LinuxNVDAObject | None:
        parent = self.parent
        idx = self.index_in_parent
        if parent is None or idx <= 0:
            return None
        return parent.child_at(idx - 1)

    next_sibling = next
    previous_sibling = previous

    def ancestors(self, limit: int = 100) -> list[LinuxNVDAObject]:
        """Ancestrais do mais próximo ao mais distante (até o aplicativo)."""
        result: list[LinuxNVDAObject] = []
        node = self.parent
        seen: set[Hashable] = {self._key}
        while node is not None and len(result) < limit and node.key not in seen:
            seen.add(node.key)
            result.append(node)
            if node.role == Role.APPLICATION:
                break
            node = node.parent
        return result

    def iter_descendants(self, max_nodes: int = 50000) -> Iterator[LinuxNVDAObject]:
        for raw in _atspi.iter_descendants(self._raw, max_nodes):
            obj = get_object(raw)
            if obj is not None:
                yield obj

    def find_descendants(
        self, roles: Sequence[str] = (), states: Sequence[str] = (), count: int = 0
    ) -> list[LinuxNVDAObject]:
        """Busca por papéis/estados AT-SPI2 (``Atspi.Collection``, com recuo)."""
        result: list[LinuxNVDAObject] = []
        for raw in _atspi.find_descendants(self._raw, roles, states, count):
            obj = get_object(raw)
            if obj is not None:
                result.append(obj)
        return result

    def is_descendant_of(self, other: LinuxNVDAObject, limit: int = 200) -> bool:
        node = self.parent
        steps = 0
        while node is not None and steps < limit:
            if node == other:
                return True
            node = node.parent
            steps += 1
        return False

    # ------------------------------------------------------------ aplicativo
    @property
    def application(self) -> LinuxNVDAObject | None:
        return self._cached(
            "application", lambda: get_object(_atspi.application_of(self._raw)), _FOREVER
        )

    @property
    def app_name(self) -> str:
        def compute() -> str:
            app = _atspi.application_of(self._raw)
            return _atspi.name_of(app) if app is not None else ""

        return self._cached("app_name", compute, _FOREVER)

    @property
    def process_id(self) -> int:
        return self._cached("process_id", lambda: _atspi.process_id_of(self._raw), _FOREVER)

    @property
    def app_module(self) -> AppModule | None:
        from nvda_linux.scripts import runtime

        rt = runtime.current()
        if rt is None:
            return None
        return rt.app_modules.get_for(self)

    @property
    def tree_interceptor(self) -> TreeInterceptor | None:
        from nvda_linux.scripts import runtime

        rt = runtime.current()
        if rt is None:
            return None
        return rt.tree_interceptors.get_for(self)

    # ------------------------------------------------------------ estado derivado
    @property
    def is_dead(self) -> bool:
        """Objeto removido, aplicativo fechado ou D-Bus sem resposta."""
        raw_states = _atspi.states_of(self._raw)
        return raw_states is None or "DEFUNCT" in raw_states

    @property
    def is_focusable(self) -> bool:
        return State.FOCUSABLE in self.states

    @property
    def is_editable(self) -> bool:
        return State.EDITABLE in self.states and State.READONLY not in self.states

    @property
    def is_web_document(self) -> bool:
        return self.atspi_role in WEB_DOCUMENT_ROLES

    @property
    def is_presentable(self) -> bool:
        """Falso para contêineres de leiaute sem nome (navegação simples)."""
        role = self.role
        if role in LAYOUT_ROLES and not self.name and not self.description:
            return False
        if role in (Role.STATICTEXT, Role.LABEL) and not self.name.strip() and not self.has_text:
            return False
        return State.INVISIBLE not in self.states or role == Role.DIALOG

    # ------------------------------------------------------------ interfaces
    @property
    def text_iface(self) -> Any:
        return self._cached("text_iface", lambda: _atspi.iface(self._raw, "text"), _FOREVER)

    @property
    def has_text(self) -> bool:
        return self.text_iface is not None

    @property
    def location(self) -> Location | None:
        def compute() -> Location | None:
            component = _atspi.iface(self._raw, "component")
            rect = _atspi.call(component, "get_extents", _atspi.coord_screen(), default=None)
            if rect is None:
                return None
            try:
                return Location(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
            except (AttributeError, TypeError, ValueError):
                return None

        return self._cached("location", compute)

    def make_text_info(
        self, position: Position | int | tuple[int, int] = Position.CARET
    ) -> OffsetsTextInfo:
        """TextInfo sobre ``Atspi.Text``; sem a interface, sobre nome/valor."""
        text_iface = self.text_iface
        if text_iface is not None:
            return OffsetsTextInfo(AtspiTextBackend(text_iface), position)
        parts = [p for p in (self.name, self.value, self.description) if p]
        return OffsetsTextInfo(StringTextBackend(" ".join(parts)), position)

    # ------------------------------------------------------------ ações
    def set_focus(self) -> bool:
        component = _atspi.iface(self._raw, "component")
        return bool(_atspi.call(component, "grab_focus", default=False))

    @property
    def action_names(self) -> list[str]:
        action = _atspi.iface(self._raw, "action")
        try:
            count = int(_atspi.call(action, "get_n_actions", default=0))
        except (TypeError, ValueError):
            count = 0
        return [str(_atspi.call(action, "get_action_name", i, default="")) for i in range(count)]

    def do_action(self, index: int = 0) -> bool:
        """Executa a ação padrão (clicar, ativar, alternar...)."""
        action = _atspi.iface(self._raw, "action")
        if action is None:
            return False
        return bool(_atspi.call(action, "do_action", index, default=False))

    # ------------------------------------------------------------ eventos padrão
    def report_focus(self) -> None:
        """Fala o objeto ao receber o foco (``reportFocus`` do NVDA)."""
        from nvda_linux.scripts import objectSpeech

        objectSpeech.speak_object(self, OutputReason.FOCUS)

    def event_gainFocus(self) -> None:
        self.report_focus()

    def event_nameChange(self) -> None:
        from nvda_linux.scripts import objectSpeech

        if objectSpeech.is_focus(self):
            objectSpeech.speak_name_change(self)

    def event_stateChange(self, state_name: str, enabled: bool) -> None:
        from nvda_linux.scripts import objectSpeech

        if objectSpeech.is_focus(self):
            objectSpeech.speak_state_change(self, state_name, enabled)

    def event_valueChange(self) -> None:
        from nvda_linux.scripts import objectSpeech

        if objectSpeech.is_focus(self):
            objectSpeech.speak_value_change(self)

    def event_descriptionChange(self) -> None:
        from nvda_linux.scripts import objectSpeech

        if objectSpeech.is_focus(self) and self.description:
            from nvda_linux.scripts import ui

            ui.speak([self.description])

    def event_caret(self) -> None:
        """Cursor moveu (sobrescrito por ``EditableText``)."""

    def event_textChange(self, inserted: str, deleted: str) -> None:
        """Texto mudou (sobrescrito por ``EditableText``/``Terminal``)."""

    # ------------------------------------------------------------ aliases NVDA
    @property
    def firstChild(self) -> LinuxNVDAObject | None:
        return self.first_child

    @property
    def lastChild(self) -> LinuxNVDAObject | None:
        return self.last_child

    @property
    def appModule(self) -> AppModule | None:
        return self.app_module

    @property
    def treeInterceptor(self) -> TreeInterceptor | None:
        return self.tree_interceptor

    @property
    def processID(self) -> int:
        return self.process_id

    @property
    def childCount(self) -> int:
        return self.child_count

    @property
    def positionInfo(self) -> PositionInfo:
        return self.position_info

    @property
    def keyboardShortcut(self) -> str:
        return self.keyboard_shortcut

    def makeTextInfo(
        self, position: Position | int | tuple[int, int] = Position.CARET
    ) -> OffsetsTextInfo:
        return self.make_text_info(position)

    def setFocus(self) -> bool:
        return self.set_focus()

    def doAction(self, index: int = 0) -> bool:
        return self.do_action(index)


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Fábrica, registro e classes overlay
# --------------------------------------------------------------------------
OverlayChooser = Callable[[LinuxNVDAObject, list[type]], None]

_registry: weakref.WeakValueDictionary[Hashable, LinuxNVDAObject] = weakref.WeakValueDictionary()
_overlay_choosers: list[OverlayChooser] = []
_dynamic_classes: dict[tuple[type, ...], type] = {}
_behaviors_loaded = False


def register_overlay_chooser(chooser: OverlayChooser) -> None:
    """Registra uma função que insere classes overlay em ``cls_list``."""
    if chooser not in _overlay_choosers:
        _overlay_choosers.append(chooser)


def unregister_overlay_chooser(chooser: OverlayChooser) -> None:
    if chooser in _overlay_choosers:
        _overlay_choosers.remove(chooser)


def _ensure_behaviors() -> None:
    global _behaviors_loaded
    if not _behaviors_loaded:
        _behaviors_loaded = True
        import nvda_linux.NVDAObjects.behaviors  # noqa: F401  (registra o chooser)


def _dynamic_class(bases: tuple[type, ...]) -> type:
    cls = _dynamic_classes.get(bases)
    if cls is None:
        name = "Dynamic_" + "".join(b.__name__ for b in bases)
        cls = type(name, bases, {})
        _dynamic_classes[bases] = cls
    return cls


def _apply_overlays(obj: LinuxNVDAObject) -> None:
    cls_list: list[type] = [LinuxNVDAObject]
    for chooser in _overlay_choosers:
        try:
            chooser(obj, cls_list)
        except Exception:
            log.exception("Escolha de classe overlay falhou")
    from nvda_linux.scripts import runtime

    rt = runtime.current()
    if rt is not None:
        rt.app_modules.choose_overlay_classes(obj, cls_list)
        rt.global_plugins.choose_overlay_classes(obj, cls_list)
    unique: list[type] = []
    for cls in cls_list:
        if cls not in unique:
            unique.append(cls)
    if LinuxNVDAObject in unique:
        unique.remove(LinuxNVDAObject)
    unique.append(LinuxNVDAObject)
    if len(unique) == 1:
        return
    try:
        obj.__class__ = _dynamic_class(tuple(unique))
    except TypeError:
        log.exception("Classes overlay incompatíveis: %s", unique)


def get_object(raw: _atspi.RawAccessible | None) -> LinuxNVDAObject | None:
    """Wrapper (reaproveitado) para ``raw``; ``None`` se ``raw`` for ``None``."""
    if raw is None:
        return None
    if isinstance(raw, LinuxNVDAObject):
        return raw
    _ensure_behaviors()
    key = _atspi.object_key(raw)
    existing = _registry.get(key)
    if existing is not None and (existing.raw is raw or _same_raw(existing.raw, raw)):
        return existing
    obj = LinuxNVDAObject(raw, key)
    _apply_overlays(obj)
    _registry[key] = obj
    return obj


def _same_raw(a: _atspi.RawAccessible, b: _atspi.RawAccessible) -> bool:
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return False


def find_cached(raw: _atspi.RawAccessible) -> LinuxNVDAObject | None:
    """Wrapper já existente para ``raw`` (sem criar), para invalidar cache."""
    if raw is None:
        return None
    return _registry.get(_atspi.object_key(raw))


def clear_registry() -> None:
    """Esquece todos os wrappers (testes e ``bootstrap.stop``)."""
    _registry.clear()
