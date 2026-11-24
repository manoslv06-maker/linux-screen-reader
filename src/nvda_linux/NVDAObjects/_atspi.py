"""Camada fina e defensiva sobre o AT-SPI2 (``gi.repository.Atspi``).

Todo acesso remoto do leitor de tela passa por aqui. Os objetivos são:

* importar ``gi``/``Atspi`` de forma protegida (o leitor continua de pé, em
  modo degradado, se o PyGObject estiver quebrado ou ausente);
* nunca deixar escapar ``GLib.GError`` ou erros de objeto morto: toda chamada
  remota usa :func:`call`, que devolve um valor padrão quando algo falha;
* normalizar enums do AT-SPI2 (papéis, estados, granularidades) para nomes em
  maiúsculas (``"PUSH_BUTTON"``, ``"FOCUSED"``), o que permite testar toda a
  lógica com uma árvore falsa que devolve strings no lugar dos enums.

Nenhuma outra parte da SEMÂNTICA importa ``gi`` diretamente para o AT-SPI2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: Tipo usado para objetos ``Atspi.Accessible`` (ou equivalentes falsos).
RawAccessible = Any

Atspi: Any = None
GLib: Any = None
Gio: Any = None
IMPORT_ERROR: str | None = None


def _load() -> None:
    """Importa o AT-SPI2 via PyGObject sem nunca levantar exceção."""
    global Atspi, GLib, Gio, IMPORT_ERROR
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi as _atspi
        from gi.repository import Gio as _gio
        from gi.repository import GLib as _glib
    except Exception as exc:  # ImportError, ValueError, gi quebrado...  # noqa: BLE001
        IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        log.info("AT-SPI2 indisponível: %s", IMPORT_ERROR)
        return
    Atspi, GLib, Gio = _atspi, _glib, _gio


_load()

#: Caractere usado pelo AT-SPI2 para marcar objetos embutidos no texto.
EMBEDDED_OBJECT_CHAR = "￼"

_ENUM_PREFIXES = (
    "ATSPI_ROLE_",
    "ATSPI_STATE_",
    "ATSPI_TEXT_GRANULARITY_",
    "ATSPI_TEXT_BOUNDARY_",
    "ATSPI_COORD_TYPE_",
    "ATSPI_COLLECTION_",
)


def available() -> bool:
    """Indica se o módulo ``Atspi`` do PyGObject foi carregado."""
    return Atspi is not None


# --------------------------------------------------------------------------
# Chamadas remotas seguras
# --------------------------------------------------------------------------
def call(obj: Any, method: str, *args: Any, default: Any = None) -> Any:
    """Chama ``obj.method(*args)`` capturando qualquer falha remota.

    Devolve ``default`` se ``obj`` for ``None``, se o método não existir,
    se a chamada levantar (``GLib.GError``, objeto morto, D-Bus caiu...) ou
    se o resultado for ``None``.
    """
    if obj is None:
        return default
    fn = getattr(obj, method, None)
    if fn is None or not callable(fn):
        return default
    try:
        result = fn(*args)
    except Exception as exc:  # noqa: BLE001
        log.debug("Chamada AT-SPI2 %s falhou: %s", method, exc)
        return default
    return default if result is None else result


def enum_name(value: Any) -> str:
    """Normaliza um enum do AT-SPI2 (ou uma string) para ``"NOME_EM_MAIUSCULAS"``."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().upper().replace("-", "_").replace(" ", "_")
    nick = getattr(value, "value_nick", None)
    if isinstance(nick, str) and nick:
        return nick.upper().replace("-", "_")
    vname = getattr(value, "value_name", None)
    if isinstance(vname, str) and vname:
        for prefix in _ENUM_PREFIXES:
            if vname.startswith(prefix):
                return vname[len(prefix):]
        return vname
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name.upper()
    return str(value).upper()


def object_key(raw: RawAccessible) -> Hashable:
    """Identidade estável de um objeto remoto.

    O libatspi mantém um único ``AtspiAccessible`` por (aplicativo, caminho) e o
    PyGObject calcula ``hash`` pelo ponteiro do GObject, então ``hash(raw)``
    identifica o objeto remoto enquanto ele existir.
    """
    try:
        return ("atspi", hash(raw))
    except Exception:  # noqa: BLE001
        return ("id", id(raw))


# --------------------------------------------------------------------------
# Propriedades básicas
# --------------------------------------------------------------------------
def name_of(raw: RawAccessible) -> str:
    return str(call(raw, "get_name", default=""))


def description_of(raw: RawAccessible) -> str:
    return str(call(raw, "get_description", default=""))


def role_of(raw: RawAccessible) -> str:
    """Papel AT-SPI2 normalizado (``"PUSH_BUTTON"``) ou ``""`` em caso de falha."""
    return enum_name(call(raw, "get_role", default=None))


def states_of(raw: RawAccessible) -> frozenset[str] | None:
    """Estados AT-SPI2 normalizados, ou ``None`` se o objeto não respondeu."""
    state_set = call(raw, "get_state_set", default=None)
    if state_set is None:
        return None
    states = call(state_set, "get_states", default=None)
    if states is None:
        return None
    try:
        return frozenset(enum_name(s) for s in states)
    except Exception:  # noqa: BLE001
        return None


def attributes_of(raw: RawAccessible) -> dict[str, str]:
    """Atributos de objeto (``level``, ``xml-roles``, ``tag``...)."""
    attrs = call(raw, "get_attributes", default=None)
    if attrs is None:
        return {}
    try:
        return {str(k): str(v) for k, v in dict(attrs).items()}
    except Exception:  # noqa: BLE001
        return {}


def parent_of(raw: RawAccessible) -> RawAccessible | None:
    return call(raw, "get_parent", default=None)


def child_count(raw: RawAccessible) -> int:
    try:
        return max(0, int(call(raw, "get_child_count", default=0)))
    except (TypeError, ValueError):
        return 0


def child_at(raw: RawAccessible, index: int) -> RawAccessible | None:
    if index < 0:
        return None
    return call(raw, "get_child_at_index", index, default=None)


def children_of(raw: RawAccessible, limit: int = 10000) -> list[RawAccessible]:
    """Filhos de ``raw`` (até ``limit``), ignorando os que não respondem."""
    result: list[RawAccessible] = []
    for i in range(min(child_count(raw), limit)):
        child = child_at(raw, i)
        if child is not None:
            result.append(child)
    return result


def index_in_parent(raw: RawAccessible) -> int:
    try:
        return int(call(raw, "get_index_in_parent", default=-1))
    except (TypeError, ValueError):
        return -1


def application_of(raw: RawAccessible) -> RawAccessible | None:
    return call(raw, "get_application", default=None)


def process_id_of(raw: RawAccessible) -> int:
    try:
        return int(call(raw, "get_process_id", default=0))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# Interfaces
# --------------------------------------------------------------------------
_IFACE_GETTERS = {
    "action": "get_action_iface",
    "collection": "get_collection_iface",
    "component": "get_component_iface",
    "document": "get_document_iface",
    "editable_text": "get_editable_text_iface",
    "hypertext": "get_hypertext_iface",
    "image": "get_image_iface",
    "selection": "get_selection_iface",
    "table": "get_table_iface",
    "table_cell": "get_table_cell",
    "text": "get_text_iface",
    "value": "get_value_iface",
}


#: Classe ``Atspi.<Nome>`` de cada interface, para chamar o método certo.
_IFACE_CLASSES = {
    "action": "Action",
    "collection": "Collection",
    "component": "Component",
    "document": "Document",
    "editable_text": "EditableText",
    "hypertext": "Hypertext",
    "image": "Image",
    "selection": "Selection",
    "table": "Table",
    "table_cell": "TableCell",
    "text": "Text",
    "value": "Value",
}


class InterfaceProxy:
    """Interface AT-SPI2 com os métodos resolvidos pela classe da interface.

    No PyGObject, ``get_text_iface()`` devolve o próprio ``Atspi.Accessible``,
    e métodos antigos do Accessible escondem os da interface: ``obj.get_text(0, 5)``
    chama ``Atspi.Accessible.get_text()`` (sem argumentos) em vez de
    ``Atspi.Text.get_text``. O mesmo vale para ``get_name``/``get_description``
    (Action) e ``get_selection`` (Text). Aqui ``proxy.get_text(0, 5)`` vira
    ``Atspi.Text.get_text(obj, 0, 5)``.
    """

    __slots__ = ("_cls", "raw")

    def __init__(self, raw: Any, cls: Any) -> None:
        self.raw = raw
        self._cls = cls

    def __getattr__(self, name: str) -> Any:
        method = getattr(self._cls, name, None)
        if callable(method):
            raw = self.raw

            def bound(*args: Any) -> Any:
                return method(raw, *args)

            return bound
        return getattr(self.raw, name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, InterfaceProxy):
            return bool(self.raw == other.raw)
        return bool(self.raw == other)

    def __hash__(self) -> int:
        return hash(self.raw)


def iface(raw: RawAccessible, name: str) -> Any:
    """Interface AT-SPI2 ``name`` de ``raw`` ou ``None`` se não implementada."""
    getter = _IFACE_GETTERS.get(name)
    if getter is None:
        return None
    found = call(raw, getter, default=None)
    if found is None or Atspi is None:
        return found  # sem AT-SPI2 real (testes): o objeto já resolve os métodos
    cls = getattr(Atspi, _IFACE_CLASSES[name], None)
    return InterfaceProxy(found, cls) if cls is not None else found


def granularity(unit: str) -> Any:
    """``Atspi.TextGranularity.<unit>`` ou a própria string, sem AT-SPI2."""
    if Atspi is not None:
        try:
            return getattr(Atspi.TextGranularity, unit)
        except AttributeError:
            pass
    return unit


def coord_screen() -> Any:
    if Atspi is not None:
        try:
            return Atspi.CoordType.SCREEN
        except AttributeError:
            pass
    return "SCREEN"


# --------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------
def text_range(rng: Any) -> tuple[str, int, int] | None:
    """Converte ``Atspi.TextRange`` em ``(conteúdo, início, fim)``."""
    if rng is None:
        return None
    try:
        return (
            str(getattr(rng, "content", "") or ""),
            int(rng.start_offset),
            int(rng.end_offset),
        )
    except (AttributeError, TypeError, ValueError):
        return None


def offsets_range(rng: Any) -> tuple[int, int] | None:
    """Converte ``Atspi.Range`` em ``(início, fim)``."""
    if rng is None:
        return None
    try:
        return int(rng.start_offset), int(rng.end_offset)
    except (AttributeError, TypeError, ValueError):
        return None


def text_attributes_at(text: Any, offset: int) -> dict[str, str]:
    """Atributos de formatação no deslocamento (fonte, tamanho, peso...)."""
    result = call(text, "get_attribute_run", offset, True, default=None)
    if result is None:
        result = call(text, "get_text_attributes", offset, default=None)
    if result is None:
        return {}
    if isinstance(result, tuple):
        result = result[0] if result else {}
    try:
        return {str(k): str(v) for k, v in dict(result).items()}
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------
# Collection (consultas em lote)
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SimpleMatchRule:
    """Regra usada quando o AT-SPI2 real não está carregado (testes)."""

    roles: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    attributes: tuple[tuple[str, str], ...] = ()


def make_match_rule(
    roles: Sequence[str] = (),
    states: Sequence[str] = (),
    attributes: Mapping[str, str] | None = None,
) -> Any:
    """Cria um ``Atspi.MatchRule`` (papéis em OU, estados e atributos em E)."""
    if Atspi is None:
        return SimpleMatchRule(
            tuple(roles), tuple(states), tuple(sorted((attributes or {}).items()))
        )
    try:
        state_set = Atspi.StateSet.new([getattr(Atspi.StateType, s) for s in states])
        # Nomes de papel mudam entre versões (PUSH_BUTTON -> BUTTON): ignora os ausentes.
        role_values = [getattr(Atspi.Role, r) for r in roles if hasattr(Atspi.Role, r)]
        if roles and not role_values:
            return None
        match = Atspi.CollectionMatchType
        return Atspi.MatchRule.new(
            state_set,
            match.ALL,
            dict(attributes or {}),
            match.ALL,
            role_values,
            match.ANY if role_values else match.ALL,
            [],
            match.ALL,
            False,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Não foi possível criar MatchRule: %s", exc)
        return None


def _sort_canonical() -> Any:
    if Atspi is not None:
        try:
            return Atspi.CollectionSortOrder.CANONICAL
        except AttributeError:
            pass
    return "CANONICAL"


def get_matches(
    raw: RawAccessible,
    roles: Sequence[str] = (),
    states: Sequence[str] = (),
    count: int = 0,
    attributes: Mapping[str, str] | None = None,
) -> list[RawAccessible] | None:
    """Busca descendentes via ``Atspi.Collection`` numa única chamada D-Bus.

    Devolve ``None`` quando a interface não existe ou a chamada falha, para o
    chamador cair no percurso manual (:func:`find_descendants`).
    """
    collection = iface(raw, "collection")
    if collection is None:
        return None
    rule = make_match_rule(roles, states, attributes)
    if rule is None:
        return None
    found = call(collection, "get_matches", rule, _sort_canonical(), count, True, default=None)
    if found is None:
        return None
    try:
        return list(found)
    except TypeError:
        return None


def iter_descendants(raw: RawAccessible, max_nodes: int = 50000) -> Iterator[RawAccessible]:
    """Percorre os descendentes em pré-ordem (ordem do documento)."""
    stack: list[RawAccessible] = list(reversed(children_of(raw)))
    seen = 0
    while stack and seen < max_nodes:
        node = stack.pop()
        seen += 1
        yield node
        stack.extend(reversed(children_of(node)))


def find_descendants(
    raw: RawAccessible,
    roles: Sequence[str] = (),
    states: Sequence[str] = (),
    count: int = 0,
    max_nodes: int = 50000,
) -> list[RawAccessible]:
    """Como :func:`get_matches`, com recuo para percurso manual da árvore."""
    matches = get_matches(raw, roles, states, count)
    if matches is not None:
        return matches
    wanted_roles = set(roles)
    wanted_states = set(states)
    result: list[RawAccessible] = []
    for node in iter_descendants(raw, max_nodes):
        if wanted_roles and role_of(node) not in wanted_roles:
            continue
        if wanted_states:
            node_states = states_of(node) or frozenset()
            if not wanted_states <= node_states:
                continue
        result.append(node)
        if count and len(result) >= count:
            break
    return result


# --------------------------------------------------------------------------
# Inicialização e desktop
# --------------------------------------------------------------------------
def init() -> bool:
    """Inicializa o libatspi. ``False`` se o barramento de acessibilidade não responde."""
    if Atspi is None:
        return False
    try:
        Atspi.init()
        desktop = Atspi.get_desktop(0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Falha ao inicializar AT-SPI2: %s", exc)
        return False
    return desktop is not None


def shutdown() -> None:
    if Atspi is None:
        return
    try:
        Atspi.exit()
    except Exception as exc:  # noqa: BLE001
        log.debug("Atspi.exit falhou: %s", exc)


def desktop() -> RawAccessible | None:
    if Atspi is None:
        return None
    try:
        return Atspi.get_desktop(0)
    except Exception:  # noqa: BLE001
        return None


def set_screen_reader_enabled(enabled: bool = True) -> None:
    """Liga ``org.a11y.Status.ScreenReaderEnabled`` no barramento de sessão.

    Chromium, Electron e GTK 4 só expõem a árvore completa quando essa
    propriedade está ligada. A chamada é assíncrona e as falhas só vão ao log.
    """
    if Gio is None or GLib is None:
        return
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        params = GLib.Variant(
            "(ssv)", ("org.a11y.Status", "ScreenReaderEnabled", GLib.Variant("b", enabled))
        )
        bus.call(
            "org.a11y.Bus",
            "/org/a11y/bus",
            "org.freedesktop.DBus.Properties",
            "Set",
            params,
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
            None,
            None,
        )
    except Exception as exc:  # noqa: BLE001
        log.info("Não foi possível ligar ScreenReaderEnabled: %s", exc)


# --------------------------------------------------------------------------
# Eventos
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RawEvent:
    """Evento AT-SPI2 já convertido para tipos Python."""

    type: str
    source: RawAccessible
    detail1: int = 0
    detail2: int = 0
    any_data: Any = None


@dataclass(slots=True)
class EventBridge:
    """Liga ``Atspi.EventListener`` a um callback que recebe :class:`RawEvent`."""

    callback: Callable[[RawEvent], None]
    _listener: Any = None
    _registered: list[str] = field(default_factory=list)

    def register(self, event_types: Sequence[str]) -> list[str]:
        """Registra os tipos de evento. Devolve os que foram aceitos."""
        if Atspi is None:
            return []
        if self._listener is None:
            try:
                self._listener = Atspi.EventListener.new(self._on_event)
            except Exception as exc:  # noqa: BLE001
                log.warning("Não foi possível criar EventListener: %s", exc)
                return []
        for event_type in event_types:
            try:
                if self._listener.register(event_type):
                    self._registered.append(event_type)
            except Exception as exc:  # noqa: BLE001
                log.warning("Falha ao registrar %s: %s", event_type, exc)
        return list(self._registered)

    def deregister(self) -> None:
        if self._listener is None:
            return
        for event_type in self._registered:
            try:
                self._listener.deregister(event_type)
            except Exception as exc:  # noqa: BLE001
                log.debug("Falha ao remover %s: %s", event_type, exc)
        self._registered.clear()
        self._listener = None

    def _on_event(self, event: Any, *_user_data: Any) -> None:
        try:
            raw = RawEvent(
                type=str(getattr(event, "type", "") or ""),
                source=getattr(event, "source", None),
                detail1=int(getattr(event, "detail1", 0) or 0),
                detail2=int(getattr(event, "detail2", 0) or 0),
                any_data=getattr(event, "any_data", None),
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Evento AT-SPI2 ilegível: %s", exc)
            return
        try:
            self.callback(raw)
        except Exception:
            log.exception("Erro ao tratar evento %s", raw.type)
