"""Cadeia de scripts na ordem do NVDA (implementa ``contracts.ScriptChainSource``).

globalPlugins -> appModule -> treeInterceptor -> foco -> globalCommands.

Cada provedor é embrulhado em :class:`SafeProvider`, que:

* isola exceções (um add-on com erro nunca derruba o despacho de gestos);
* com a ajuda de entrada ligada (``services.dispatcher().input_help``), troca
  o script por um que só fala a descrição e o nome do gesto, exceto para
  scripts marcados com ``bypass_input_help`` (o próprio NVDA+1).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING

from nvda_linux import services
from nvda_linux.contracts import InputGesture, Script, ScriptProvider
from nvda_linux.scripts import ui
from nvda_linux.scripts.scriptHandler import (
    bypasses_input_help,
    describe_gesture,
    script_description,
)

if TYPE_CHECKING:
    from nvda_linux.appModules.appModuleHandler import AppModuleManager
    from nvda_linux.globalPlugins.globalPluginHandler import GlobalPluginManager
    from nvda_linux.scripts.focus import FocusManager
    from nvda_linux.scripts.globalCommands import GlobalCommands
    from nvda_linux.treeInterceptors.manager import TreeInterceptorManager

log = logging.getLogger(__name__)


def input_help_enabled() -> bool:
    try:
        return bool(services.dispatcher().input_help)
    except Exception:  # noqa: BLE001
        return False


def refresh_grabs() -> None:
    """Avisa a PLATAFORMA que o conjunto de teclas com script mudou.

    No GNOME/Wayland o compositor decide antes da tecla se ela é engolida; o
    ``InputManager.refresh_grabs()`` (opcional, fora do contrato) refaz essa
    lista na hora, em vez de esperar a sondagem de 300 ms.
    """
    try:
        refresh = getattr(services.dispatcher(), "refresh_grabs", None)
    except Exception:  # noqa: BLE001
        return
    if callable(refresh):
        try:
            refresh()
        except Exception:
            log.exception("refresh_grabs falhou")


def guard_script(fn: Script, origin: str) -> Script:
    """Embrulha ``fn`` para que exceções (síncronas ou assíncronas) só vão ao log."""

    async def await_guarded(awaitable: Awaitable[None]) -> None:
        try:
            await awaitable
        except Exception:
            log.exception("Script assíncrono de %s falhou", origin)

    def guarded(gesture: InputGesture) -> None | Awaitable[None]:
        try:
            result = fn(gesture)
        except Exception:
            log.exception("Script de %s falhou", origin)
            return None
        if inspect.isawaitable(result):
            return await_guarded(result)
        return None

    # A ajuda de entrada da PLATAFORMA usa a docstring; o efeito na fala também
    # é lido do script (``speechEffectWhenExecuted``).
    guarded.__doc__ = script_description(fn) or fn.__doc__
    guarded.__name__ = getattr(fn, "__name__", "script")
    guarded.__qualname__ = getattr(fn, "__qualname__", guarded.__name__)
    for attr in ("speechEffectWhenExecuted", "_nvda_quick_nav"):
        if hasattr(fn, attr):
            setattr(guarded, attr, getattr(fn, attr))
    guarded.__wrapped__ = fn  # type: ignore[attr-defined]
    return guarded


def input_help_script(fn: Script | None, gesture: InputGesture) -> Script:
    """Script que fala o que ``fn`` faria (ou só o gesto, sem script)."""

    description = script_description(fn) if fn is not None else ""

    def speak_help(_gesture: InputGesture) -> None:
        name = describe_gesture(gesture.identifier)
        ui.message(f"{name}: {description}" if description else name)

    speak_help.__doc__ = description or None
    return speak_help


class SafeProvider:
    """Provedor com isolamento de exceções e suporte à ajuda de entrada."""

    def __init__(self, inner: ScriptProvider, origin: str, input_help: bool) -> None:
        self.inner = inner
        self.origin = origin
        self.input_help = input_help

    def get_script(self, gesture: InputGesture) -> Script | None:
        try:
            fn = self.inner.get_script(gesture)
        except Exception:
            log.exception("get_script de %s falhou", self.origin)
            return None
        if fn is None:
            return None
        if self.input_help and not bypasses_input_help(fn):
            # A PLATAFORMA, com a ajuda ligada, só pede o script para ler a
            # descrição (docstring) e não o executa; se algum despachante o
            # executar, ele só fala a descrição.
            return input_help_script(fn, gesture)
        return guard_script(fn, self.origin)


class _PassNextKeyProvider:
    """Depois de NVDA+F2: a próxima tecla vai direto ao aplicativo."""

    def __init__(self, chain: ScriptChain) -> None:
        self._chain = chain

    def get_script(self, gesture: InputGesture) -> Script | None:
        if gesture.is_modifier_only:
            return None

        def send(g: InputGesture) -> None:
            self._chain.pass_next_key = False
            try:
                services.dispatcher().send_through(g)
            except Exception as exc:  # noqa: BLE001
                log.debug("send_through indisponível: %s", exc)

        return send


class ScriptChain:
    """Implementa ``ScriptChainSource`` (registrado como ``"script_chain"``)."""

    def __init__(
        self,
        focus: FocusManager,
        app_modules: AppModuleManager,
        global_plugins: GlobalPluginManager,
        tree_interceptors: TreeInterceptorManager,
        global_commands: GlobalCommands,
    ) -> None:
        self.focus = focus
        self.app_modules = app_modules
        self.global_plugins = global_plugins
        self.tree_interceptors = tree_interceptors
        self.global_commands = global_commands
        self.pass_next_key = False

    def chain(self) -> Sequence[ScriptProvider]:
        if self.pass_next_key:
            return [_PassNextKeyProvider(self)]
        help_on = input_help_enabled()
        providers: list[ScriptProvider] = []
        for plugin in self.global_plugins.plugins:
            providers.append(SafeProvider(plugin, f"globalPlugin {type(plugin).__name__}", help_on))
        focus = self.focus.focus
        if focus is not None:
            app = self.app_modules.get_for(focus)
            if app is not None:
                if app.sleep_mode:
                    return [SafeProvider(self.global_commands.sleep_mode_provider(), "sleep", help_on)]
                providers.append(SafeProvider(app, f"appModule {app.name}", help_on))
            ti = self.tree_interceptors.get_for(focus)
            if ti is not None:
                providers.append(SafeProvider(ti, f"treeInterceptor {type(ti).__name__}", help_on))
            providers.append(SafeProvider(focus, f"foco {type(focus).__name__}", help_on))
        providers.append(SafeProvider(self.global_commands, "globalCommands", help_on))
        return providers

    def find_script(self, gesture: InputGesture) -> Script | None:
        """Primeiro script da cadeia para o gesto (o que a PLATAFORMA faz)."""
        for provider in self.chain():
            fn = provider.get_script(gesture)
            if fn is not None:
                return fn
        return None
