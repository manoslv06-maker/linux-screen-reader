"""Contêiner dos gerenciadores da SEMÂNTICA em execução.

Os módulos acessam os gerenciadores por :func:`current` no momento da
chamada, o que evita importações circulares e permite que os testes montem um
:class:`Runtime` com árvores falsas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nvda_linux.addons.addonHandler import AddonManager
    from nvda_linux.appModules.appModuleHandler import AppModuleManager
    from nvda_linux.globalPlugins.globalPluginHandler import GlobalPluginManager
    from nvda_linux.scripts.chain import ScriptChain
    from nvda_linux.scripts.eventHandler import EventHandler
    from nvda_linux.scripts.focus import FocusManager
    from nvda_linux.scripts.globalCommands import GlobalCommands
    from nvda_linux.treeInterceptors.manager import TreeInterceptorManager


@dataclass
class Runtime:
    """Referências aos gerenciadores. Campos ``None`` = ainda não criados."""

    focus: FocusManager
    app_modules: AppModuleManager
    global_plugins: GlobalPluginManager
    tree_interceptors: TreeInterceptorManager
    global_commands: GlobalCommands
    chain: ScriptChain
    events: EventHandler | None = None
    addons: AddonManager | None = None
    atspi_connected: bool = False
    extras: dict[str, object] = field(default_factory=dict)


_current: Runtime | None = None


def current() -> Runtime | None:
    return _current


def set_current(runtime: Runtime | None) -> None:
    global _current
    _current = runtime


def create(atspi_connected: bool = False) -> Runtime:
    """Cria um :class:`Runtime` completo (sem AT-SPI2 nem add-ons) e o ativa."""
    from nvda_linux.appModules.appModuleHandler import AppModuleManager
    from nvda_linux.globalPlugins.globalPluginHandler import GlobalPluginManager
    from nvda_linux.scripts.chain import ScriptChain
    from nvda_linux.scripts.eventHandler import EventHandler
    from nvda_linux.scripts.focus import FocusManager
    from nvda_linux.scripts.globalCommands import GlobalCommands
    from nvda_linux.treeInterceptors.manager import TreeInterceptorManager

    focus = FocusManager()
    app_modules = AppModuleManager()
    global_plugins = GlobalPluginManager()
    tree_interceptors = TreeInterceptorManager()
    commands = GlobalCommands()
    chain = ScriptChain(focus, app_modules, global_plugins, tree_interceptors, commands)
    runtime = Runtime(
        focus=focus,
        app_modules=app_modules,
        global_plugins=global_plugins,
        tree_interceptors=tree_interceptors,
        global_commands=commands,
        chain=chain,
        atspi_connected=atspi_connected,
    )
    runtime.events = EventHandler(runtime)
    set_current(runtime)
    return runtime
