# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Eventos AT-SPI2 -> eventos do NVDA (``eventHandler``).

Fluxo:

1. :class:`~nvda_linux.NVDAObjects._atspi.EventBridge` entrega
   :class:`RawEvent` a :meth:`EventHandler.handle_raw_event` (no loop GLib).
2. Os eventos são enfileirados e processados em lote após
   :attr:`EventHandler.coalesce_delay` (padrão 20 ms). No lote, o cache dos
   objetos é invalidado, eventos repetidos (mesmo tipo e objeto) são
   deduplicados e só o último foco/ativação de janela é tratado.
3. Cada evento vira ``gainFocus``, ``foreground``, ``nameChange``,
   ``stateChange``, ``valueChange``, ``caret``, ``textChange``,
   ``descriptionChange``, ``childrenChanged`` ou ``documentLoadComplete`` e
   percorre a cadeia do NVDA: globalPlugins -> appModule -> treeInterceptor ->
   ``NVDAObject.event_*``. Cada manipulador recebe ``(obj, next_handler)``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any

from nvda_linux.contracts import SpeechPriority
from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects.base import LinuxNVDAObject, find_cached, get_object
from nvda_linux.NVDAObjects.controlTypes import OutputReason, Role, State
from nvda_linux.scripts import configUtils, objectSpeech, ui
from nvda_linux.scripts.chain import refresh_grabs

if TYPE_CHECKING:
    from nvda_linux.scripts.runtime import Runtime

log = logging.getLogger(__name__)

#: Tipos de evento registrados no AT-SPI2.
ATSPI_EVENT_TYPES: tuple[str, ...] = (
    "object:state-changed",
    "focus:",
    "object:text-caret-moved",
    "object:text-changed",
    "object:property-change:accessible-name",
    "object:property-change:accessible-description",
    "object:property-change:accessible-value",
    "object:value-changed",
    "object:children-changed",
    "object:active-descendant-changed",
    "window:activate",
    "document:load-complete",
)

_FOCUS_TYPES = ("object:state-changed:focused", "focus:")
_DEFUNCT_EVENT = "object:state-changed:defunct"
_LIVE_VALUES = frozenset({"polite", "assertive"})


def _event_kind(event_type: str) -> str:
    """``"object:state-changed:checked"`` -> ``"object:state-changed"``."""
    parts = event_type.split(":")
    return ":".join(parts[:2]) if len(parts) >= 2 else event_type


def _event_detail(event_type: str) -> str:
    parts = event_type.split(":")
    return parts[2] if len(parts) >= 3 else ""


class EventHandler:
    """Recebe eventos AT-SPI2 e executa os eventos do NVDA."""

    #: Janela de coalescência (s).
    coalesce_delay: float = 0.02

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._queue: list[_atspi.RawEvent] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._flush_scheduled = False
        self._bridge = _atspi.EventBridge(self.handle_raw_event)
        self._signature_cache: dict[Hashable, bool] = {}
        self._allow_repeat_focus = False
        self.registered: list[str] = []

    # ------------------------------------------------------------ ciclo de vida
    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> list[str]:
        """Registra os ouvintes AT-SPI2. Devolve os tipos aceitos."""
        self._loop = loop
        self.registered = self._bridge.register(ATSPI_EVENT_TYPES)
        return self.registered

    def stop(self) -> None:
        self._bridge.deregister()
        self._queue.clear()
        self._flush_scheduled = False
        self._loop = None

    # ------------------------------------------------------------ fila
    def handle_raw_event(self, event: _atspi.RawEvent) -> None:
        """Enfileira um evento (chamado no contexto do loop GLib)."""
        if event.source is None:
            return
        if event.type == _DEFUNCT_EVENT:
            # Objeto morreu: só esquece o cache local, sem nenhuma chamada remota.
            # Consultar um objeto morto faz o gnome-shell emitir outro "defunct",
            # e o leitor entrava num ciclo de milhares de eventos por segundo.
            cached = find_cached(event.source)
            if cached is not None:
                cached.invalidate_cache()
            return
        self._queue.append(event)
        if self._flush_scheduled:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            self.flush()
            return
        self._flush_scheduled = True
        try:
            loop.call_soon_threadsafe(self._schedule_flush)
        except RuntimeError:
            self._flush_scheduled = False
            self.flush()

    def _schedule_flush(self) -> None:
        if self._loop is None:
            self.flush()
            return
        self._loop.call_later(self.coalesce_delay, self.flush)

    def coalesce(self, events: list[_atspi.RawEvent]) -> list[_atspi.RawEvent]:
        """Deduplica: mantém a última ocorrência de cada (tipo, objeto, detalhe).

        Foco: só o último ganho de foco do lote. ``window:activate``: só o último,
        processado antes do foco.
        """
        last_focus: int | None = None
        last_window: int | None = None
        keep: dict[tuple[Any, ...], int] = {}
        for i, ev in enumerate(events):
            if ev.type in _FOCUS_TYPES:
                if ev.type == "focus:" or ev.detail1:
                    last_focus = i
                continue
            if ev.type == "object:active-descendant-changed":
                last_focus = i
                continue
            if ev.type == "window:activate":
                last_window = i
                continue
            if ev.type.startswith("object:text-changed") or ev.type == "object:text-caret-moved":
                # Texto inserido e cursor: cada ocorrência importa (eco, ordem).
                keep[(i,)] = i
                continue
            key = (ev.type, _atspi.object_key(ev.source), ev.detail1)
            keep.pop(key, None)
            keep[key] = i
        selected = set(keep.values())
        ordered = [events[i] for i in sorted(selected)]
        head: list[_atspi.RawEvent] = []
        if last_window is not None:
            head.append(events[last_window])
        if last_focus is not None:
            head.append(events[last_focus])
        return head + ordered

    def flush(self) -> None:
        """Processa a fila agora (também usado pelos testes)."""
        self._flush_scheduled = False
        batch, self._queue = self._queue, []
        if not batch:
            return
        for ev in batch:
            self._invalidate(ev)
        for ev in self.coalesce(batch):
            try:
                self.dispatch(ev)
            except Exception:
                log.exception("Erro ao processar %s", ev.type)

    @staticmethod
    def _invalidate(ev: _atspi.RawEvent) -> None:
        obj = find_cached(ev.source)
        if obj is None:
            return
        kind = _event_kind(ev.type)
        if kind == "object:state-changed":
            obj.invalidate_cache("states")
        elif ev.type == "object:property-change:accessible-name":
            obj.invalidate_cache("name")
        elif ev.type == "object:property-change:accessible-description":
            obj.invalidate_cache("description")
        elif kind in ("object:value-changed", "object:property-change"):
            obj.invalidate_cache("value")
        elif kind == "object:children-changed":
            obj.invalidate_cache("children", "child_count")
            child = get_object(ev.any_data) if ev.any_data is not None else None
            if child is not None:
                child.invalidate_cache("parent", "index_in_parent")
        elif kind == "object:text-changed":
            obj.invalidate_cache("text", "value")

    # ------------------------------------------------------------ despacho
    def dispatch(self, ev: _atspi.RawEvent) -> None:
        obj = get_object(ev.source)
        if obj is None:
            return
        app = self.runtime.app_modules.get_for(obj)
        if app is not None and app.sleep_mode:
            return
        etype = ev.type
        kind = _event_kind(etype)
        detail = _event_detail(etype)
        if etype in _FOCUS_TYPES:
            if etype == "focus:" or ev.detail1:
                self.gain_focus(obj, check_state=etype != "focus:")
            return
        if etype == "object:active-descendant-changed":
            child = get_object(ev.any_data)
            if child is not None and (self._is_focus(obj) or State.FOCUSED in obj.states):
                self.gain_focus(child, check_state=False)
            return
        if etype == "window:activate":
            self.foreground(obj)
            return
        if kind == "object:state-changed":
            self._state_changed(obj, detail, bool(ev.detail1))
            return
        if etype == "object:property-change:accessible-name":
            self.execute_event("nameChange", obj)
            return
        if etype == "object:property-change:accessible-description":
            self.execute_event("descriptionChange", obj)
            return
        if etype in ("object:property-change:accessible-value", "object:value-changed"):
            self.execute_event("valueChange", obj)
            return
        if etype == "object:text-caret-moved":
            self.execute_event("caret", obj)
            return
        if kind == "object:text-changed":
            text = ev.any_data if isinstance(ev.any_data, str) else ""
            inserted = text if detail.startswith("insert") else ""
            deleted = text if detail.startswith("delete") else ""
            self._text_changed(obj, inserted, deleted)
            return
        if kind == "object:children-changed":
            self._children_changed(obj)
            return
        if etype.startswith("document:load-complete"):
            self.document_load_complete(obj)

    def _is_focus(self, obj: LinuxNVDAObject) -> bool:
        focus = self.runtime.focus.focus
        return focus is not None and focus == obj

    # ------------------------------------------------------------ eventos de alto nível
    def gain_focus(self, obj: LinuxNVDAObject, check_state: bool = True) -> None:
        """Foco mudou: atualiza estado (pre-gain) e executa ``gainFocus``."""
        raw_states = obj.atspi_states
        if raw_states is None or "DEFUNCT" in raw_states:
            return
        if check_state and raw_states and "FOCUSED" not in raw_states:
            return  # evento atrasado: o objeto já perdeu o foco
        if self._is_focus(obj) and not self._allow_repeat_focus:
            return  # duplicado
        self._allow_repeat_focus = False
        self.runtime.tree_interceptors.update_for_focus(obj)
        self.runtime.focus.set_focus(obj)
        ui.cancel()
        self.execute_event("gainFocus", obj)
        refresh_grabs()

    def foreground(self, obj: LinuxNVDAObject) -> None:
        focus_manager = self.runtime.focus
        if focus_manager.foreground is not None and focus_manager.foreground == obj:
            return
        focus_manager.set_foreground(obj)
        self._allow_repeat_focus = True
        self.execute_event("foreground", obj)

    def _state_changed(self, obj: LinuxNVDAObject, state: str, enabled: bool) -> None:
        if state == "defunct":
            obj.invalidate_cache()
            return
        if state == "busy" and not enabled and obj.is_web_document:
            self.document_load_complete(obj)
            return
        if state in ("focused", "showing", "visible", "active", "armed", "stale"):
            return
        self.execute_event("stateChange", obj, state_name=state, enabled=enabled)

    def _text_changed(self, obj: LinuxNVDAObject, inserted: str, deleted: str) -> None:
        ti = self.runtime.tree_interceptors.get_for(obj)
        if ti is not None and not self._is_focus(obj):
            schedule = getattr(ti, "schedule_update", None)
            if callable(schedule):
                schedule(obj)
            self._report_live_region(obj, inserted)
            return
        self.execute_event("textChange", obj, inserted=inserted, deleted=deleted)

    def _report_live_region(self, obj: LinuxNVDAObject, inserted: str) -> None:
        if not inserted.strip():
            return
        if not configUtils.get_bool("presentation.reportDynamicContentChanges", True):
            return
        attrs = obj.attributes
        live = attrs.get("container-live", attrs.get("live", ""))
        if live in _LIVE_VALUES:
            priority = SpeechPriority.NOW if live == "assertive" else SpeechPriority.NORMAL
            ui.speak([inserted.strip()], priority)

    def _children_changed(self, obj: LinuxNVDAObject) -> None:
        ti = self.runtime.tree_interceptors.get_for(obj)
        if ti is not None:
            schedule = getattr(ti, "schedule_update", None)
            if callable(schedule):
                schedule(obj)
        self.execute_event("childrenChanged", obj)

    def document_load_complete(self, obj: LinuxNVDAObject) -> None:
        tis = self.runtime.tree_interceptors
        ti = tis.get_for_root(obj)
        focus = self.runtime.focus.focus
        active = focus is not None and (focus == obj or focus.is_descendant_of(obj))
        if ti is None and active:
            ti = tis.update_for_focus(focus) if focus is not None else None
        if ti is None:
            return
        handler = getattr(ti, "on_load_complete", None)
        if callable(handler):
            try:
                handler(active)
            except Exception:
                log.exception("on_load_complete falhou")
        self.execute_event("documentLoadComplete", obj)

    # ------------------------------------------------------------ cadeia
    def _accepts_kwargs(self, handler: Callable[..., Any], kwargs: dict[str, Any]) -> bool:
        if not kwargs:
            return False
        key = getattr(handler, "__func__", handler)
        cached = self._signature_cache.get(key)
        if cached is not None:
            return cached
        try:
            params = inspect.signature(handler).parameters.values()
        except (TypeError, ValueError):
            result = False
        else:
            result = any(p.kind == p.VAR_KEYWORD for p in params) or all(
                k in {p.name for p in params} for k in kwargs
            )
        self._signature_cache[key] = result
        return result

    def execute_event(self, name: str, obj: LinuxNVDAObject, **kwargs: Any) -> None:
        """Percorre globalPlugins -> appModule -> treeInterceptor -> objeto."""
        method = f"event_{name}"
        handlers: list[Callable[..., Any]] = []
        for plugin in self.runtime.global_plugins.plugins:
            h = getattr(plugin, method, None)
            if callable(h):
                handlers.append(h)
        app = self.runtime.app_modules.get_for(obj)
        if app is not None:
            h = getattr(app, method, None)
            if callable(h):
                handlers.append(h)
        ti = self.runtime.tree_interceptors.get_for(obj)
        if ti is not None:
            h = getattr(ti, method, None)
            if callable(h):
                handlers.append(h)

        def run(i: int) -> None:
            if i < len(handlers):
                handler = handlers[i]
                called_next = False

                def next_handler() -> None:
                    nonlocal called_next
                    if not called_next:
                        called_next = True
                        run(i + 1)

                try:
                    if self._accepts_kwargs(handler, kwargs):
                        handler(obj, next_handler, **kwargs)
                    else:
                        handler(obj, next_handler)
                except Exception:
                    log.exception("Manipulador %s falhou", getattr(handler, "__qualname__", handler))
                    next_handler()
                return
            self._default(name, obj, kwargs)

        run(0)

    def _default(self, name: str, obj: LinuxNVDAObject, kwargs: dict[str, Any]) -> None:
        """Comportamento padrão no próprio NVDAObject."""
        try:
            if name == "foreground":
                ui.cancel()
                objectSpeech.speak_object(obj, OutputReason.FOCUS)
                return
            final = getattr(obj, f"event_{name}", None)
            if not callable(final):
                return
            if name == "stateChange":
                final(kwargs.get("state_name", ""), bool(kwargs.get("enabled", False)))
            elif name == "textChange":
                final(str(kwargs.get("inserted", "")), str(kwargs.get("deleted", "")))
            else:
                final()
        except Exception:
            log.exception("event_%s do objeto falhou", name)


def initial_focus() -> LinuxNVDAObject | None:
    """Foco atual na inicialização: janela ativa -> descendente FOCUSED (Collection)."""
    desktop = _atspi.desktop()
    if desktop is None:
        return None
    for app_raw in _atspi.children_of(desktop, 500):
        for win_raw in _atspi.children_of(app_raw, 200):
            states = _atspi.states_of(win_raw) or frozenset()
            if "ACTIVE" not in states:
                continue
            window = get_object(win_raw)
            if window is None:
                continue
            focused = window.find_descendants(states=("FOCUSED",), count=1)
            return focused[0] if focused else window
    return None


def active_window_of(obj: LinuxNVDAObject) -> LinuxNVDAObject | None:
    for ancestor in obj.ancestors():
        if ancestor.role in (Role.FRAME, Role.WINDOW, Role.DIALOG) and (
            ancestor.parent is None or ancestor.parent.role == Role.APPLICATION
        ):
            return ancestor
    return None
