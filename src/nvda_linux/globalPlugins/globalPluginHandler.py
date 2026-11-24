# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""globalPlugins: scripts e eventos ativos em qualquer aplicativo."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nvda_linux.scripts.scriptHandler import ScriptableObject

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

log = logging.getLogger(__name__)


class GlobalPlugin(ScriptableObject):
    """Base dos plugins globais (``globalPluginHandler.GlobalPlugin``).

    Defina scripts com ``@script`` e eventos ``event_<nome>(self, obj, next_handler)``.
    ``terminate`` é chamado ao desativar o add-on ou encerrar o leitor.
    """

    def choose_overlay_classes(self, obj: LinuxNVDAObject, cls_list: list[type]) -> None:
        legacy = getattr(self, "chooseNVDAObjectOverlayClasses", None)
        if callable(legacy):
            legacy(obj, cls_list)

    def terminate(self) -> None:
        """Libera recursos do plugin."""


class GlobalPluginManager:
    """Instâncias ativas de globalPlugins, com a origem (add-on) de cada uma."""

    def __init__(self) -> None:
        self._plugins: list[tuple[GlobalPlugin, str]] = []

    @property
    def plugins(self) -> list[GlobalPlugin]:
        return [p for p, _src in self._plugins]

    def load(self, cls: type[GlobalPlugin], source: str) -> GlobalPlugin | None:
        """Instancia ``cls``; falhas vão ao log e não afetam o leitor."""
        try:
            plugin = cls()
        except Exception:
            log.exception("globalPlugin %s (%s) falhou ao iniciar", cls.__name__, source)
            return None
        self._plugins.append((plugin, source))
        return plugin

    def add(self, plugin: GlobalPlugin, source: str) -> None:
        self._plugins.append((plugin, source))

    def unload_source(self, source: str) -> int:
        """Encerra e remove os plugins de ``source``; devolve quantos."""
        keep: list[tuple[GlobalPlugin, str]] = []
        removed = 0
        for plugin, src in self._plugins:
            if src == source:
                self._terminate(plugin)
                removed += 1
            else:
                keep.append((plugin, src))
        self._plugins = keep
        return removed

    def choose_overlay_classes(self, obj: LinuxNVDAObject, cls_list: list[type]) -> None:
        for plugin in self.plugins:
            try:
                plugin.choose_overlay_classes(obj, cls_list)
            except Exception:
                log.exception("choose_overlay_classes de %s falhou", type(plugin).__name__)

    @staticmethod
    def _terminate(plugin: GlobalPlugin) -> None:
        try:
            plugin.terminate()
        except Exception:
            log.exception("terminate de %s falhou", type(plugin).__name__)

    def terminate_all(self) -> None:
        for plugin, _src in self._plugins:
            self._terminate(plugin)
        self._plugins.clear()
