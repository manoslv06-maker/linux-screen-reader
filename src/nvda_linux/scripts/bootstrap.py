"""Ganchos de ciclo de vida da SEMÂNTICA, chamados pela PLATAFORMA em ``core/app.py``.

``start()``:

1. inicializa o AT-SPI2 (em modo degradado se o barramento não responde) e
   liga ``org.a11y.Status.ScreenReaderEnabled``;
2. cria o :class:`~nvda_linux.scripts.runtime.Runtime` (foco, appModules,
   globalPlugins, treeInterceptors, globalCommands, cadeia de scripts);
3. registra ``services.register("focus", ...)`` e ``("script_chain", ...)``;
4. carrega os add-ons de ``~/.config/nvda-linux/addons``;
5. liga o ``eventHandler`` aos eventos AT-SPI2 e anuncia o foco atual.

``stop()`` desfaz tudo e é idempotente.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from nvda_linux import services
from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects.base import clear_registry
from nvda_linux.scripts import runtime as runtime_module
from nvda_linux.scripts import ui
from nvda_linux.scripts.runtime import Runtime

log = logging.getLogger(__name__)

_lock = asyncio.Lock()


async def start(addons_dir: Path | None = None, connect_atspi: bool = True) -> Runtime:
    """Inicia a SEMÂNTICA. Nunca levanta por falta de AT-SPI2 ou de add-ons."""
    async with _lock:
        existing = runtime_module.current()
        if existing is not None:
            return existing
        connected = False
        if connect_atspi:
            connected = _atspi.init()
            if connected:
                _atspi.set_screen_reader_enabled(True)
            else:
                log.warning(
                    "AT-SPI2 indisponível (%s); a SEMÂNTICA funciona em modo degradado",
                    _atspi.IMPORT_ERROR or "barramento de acessibilidade sem resposta",
                )
        rt = runtime_module.create(atspi_connected=connected)
        services.register("focus", rt.focus)
        services.register("script_chain", rt.chain)

        try:
            from nvda_linux.addons.addonHandler import AddonManager

            rt.addons = AddonManager(rt.global_plugins, rt.app_modules, addons_dir)
            rt.addons.load_all()
        except Exception:
            log.exception("Falha ao carregar add-ons")

        if connected and rt.events is not None:
            try:
                loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            registered = rt.events.start(loop)
            log.info("Eventos AT-SPI2 registrados: %s", ", ".join(registered))
            _announce_initial_focus(rt)
        elif not connected:
            ui.message("Acessibilidade AT-SPI2 indisponível")
        return rt


def _announce_initial_focus(rt: Runtime) -> None:
    from nvda_linux.scripts.eventHandler import active_window_of, initial_focus

    try:
        focus = initial_focus()
    except Exception:
        log.exception("Falha ao obter o foco inicial")
        return
    if focus is None or rt.events is None:
        return
    window = active_window_of(focus)
    if window is not None:
        rt.events.foreground(window)
    rt.events.gain_focus(focus, check_state=False)


async def stop() -> None:
    """Encerra a SEMÂNTICA (idempotente)."""
    async with _lock:
        rt = runtime_module.current()
        if rt is None:
            return
        if rt.events is not None:
            try:
                rt.events.stop()
            except Exception:
                log.exception("Falha ao parar eventos")
        if rt.addons is not None:
            try:
                rt.addons.terminate()
            except Exception:
                log.exception("Falha ao descarregar add-ons")
        for step in (
            rt.global_plugins.terminate_all,
            rt.tree_interceptors.terminate_all,
            rt.app_modules.terminate_all,
            rt.focus.clear,
        ):
            try:
                step()
            except Exception:
                log.exception("Falha ao encerrar %s", getattr(step, "__qualname__", step))
        try:
            from nvda_linux import gui

            gui.close_all()
        except Exception:  # noqa: BLE001
            log.debug("GUI não fechou")
        clear_registry()
        runtime_module.set_current(None)
        if rt.atspi_connected:
            _atspi.shutdown()
