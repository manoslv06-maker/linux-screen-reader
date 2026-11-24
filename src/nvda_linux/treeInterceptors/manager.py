"""Criação e ciclo de vida dos treeInterceptors (``treeInterceptorHandler``)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from nvda_linux.NVDAObjects.controlTypes import Role, State
from nvda_linux.treeInterceptors.base import TreeInterceptor

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

log = logging.getLogger(__name__)

_STOP_ROLES = frozenset({Role.FRAME, Role.WINDOW, Role.APPLICATION, Role.DESKTOPPANE})
_MAX_DEPTH = 300

TreeInterceptorFactory = Callable[["LinuxNVDAObject"], TreeInterceptor]


def find_document_root(obj: LinuxNVDAObject) -> LinuxNVDAObject | None:
    """Documento web mais externo que contém ``obj`` (ou o próprio ``obj``)."""
    found: LinuxNVDAObject | None = None
    node: LinuxNVDAObject | None = obj
    steps = 0
    while node is not None and steps < _MAX_DEPTH:
        if node.role in _STOP_ROLES:
            break
        if node.is_web_document:
            found = node
        node = node.parent
        steps += 1
    return found


def _default_factory(root: LinuxNVDAObject) -> TreeInterceptor:
    from nvda_linux.treeInterceptors.browseMode import BrowseModeTreeInterceptor

    return BrowseModeTreeInterceptor(root)


class TreeInterceptorManager:
    """Mantém um treeInterceptor por documento."""

    def __init__(self, factory: TreeInterceptorFactory | None = None) -> None:
        self._factory = factory or _default_factory
        self._interceptors: list[TreeInterceptor] = []

    @property
    def interceptors(self) -> list[TreeInterceptor]:
        return list(self._interceptors)

    def cleanup(self) -> None:
        """Remove treeInterceptors de documentos mortos."""
        alive: list[TreeInterceptor] = []
        for ti in self._interceptors:
            if ti.is_alive:
                alive.append(ti)
            else:
                self._terminate(ti)
        self._interceptors = alive

    def get_for(self, obj: LinuxNVDAObject) -> TreeInterceptor | None:
        """treeInterceptor existente que contém ``obj``."""
        for ti in self._interceptors:
            if ti.contains(obj):
                return ti
        return None

    def get_for_root(self, root: LinuxNVDAObject) -> TreeInterceptor | None:
        for ti in self._interceptors:
            if ti.root == root:
                return ti
        return None

    def should_create(self, doc: LinuxNVDAObject) -> bool:
        if State.EDITABLE in doc.states:
            return False
        app = doc.app_module
        return app is None or app.should_use_browse_mode(doc)

    def update_for_focus(self, obj: LinuxNVDAObject) -> TreeInterceptor | None:
        """Garante um treeInterceptor para o documento do foco (``update``)."""
        self.cleanup()
        existing = self.get_for(obj)
        if existing is not None:
            return existing
        doc = find_document_root(obj)
        if doc is None or not self.should_create(doc):
            return None
        return self.create(doc)

    def create(self, doc: LinuxNVDAObject) -> TreeInterceptor | None:
        existing = self.get_for_root(doc)
        if existing is not None:
            return existing
        try:
            ti = self._factory(doc)
        except Exception:
            log.exception("Falha ao criar treeInterceptor")
            return None
        self._interceptors.append(ti)
        return ti

    def kill(self, ti: TreeInterceptor) -> None:
        if ti in self._interceptors:
            self._interceptors.remove(ti)
        self._terminate(ti)

    @staticmethod
    def _terminate(ti: TreeInterceptor) -> None:
        try:
            ti.terminate()
        except Exception:
            log.exception("Falha ao encerrar treeInterceptor")

    def terminate_all(self) -> None:
        for ti in self._interceptors:
            self._terminate(ti)
        self._interceptors.clear()
