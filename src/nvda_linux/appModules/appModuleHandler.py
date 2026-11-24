# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""appModules: comportamento específico por aplicativo (``appModuleHandler``).

Um appModule é escolhido pelo nome do aplicativo no AT-SPI2 (``Firefox``,
``Google Chrome``, ``gnome-terminal-server``), normalizado para um nome de
módulo Python (``firefox``, ``chromium``, ``gnome_terminal``). A busca é:
módulos registrados por add-ons -> ``nvda_linux.appModules.<nome>`` ->
:class:`AppModule` padrão.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from collections.abc import Hashable
from typing import TYPE_CHECKING

from nvda_linux.scripts import configUtils
from nvda_linux.scripts.scriptHandler import ScriptableObject

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

log = logging.getLogger(__name__)

#: Nomes de aplicativos que compartilham um appModule.
APP_ALIASES: dict[str, str] = {
    "google_chrome": "chromium",
    "chrome": "chromium",
    "chromium_browser": "chromium",
    "brave_browser": "chromium",
    "microsoft_edge": "chromium",
    "firefox_esr": "firefox",
    "mozilla_firefox": "firefox",
    "navigator": "firefox",
    "gnome_terminal_server": "gnome_terminal",
    "gnome_terminal": "gnome_terminal",
    "terminal": "gnome_terminal",
}


def normalize_app_name(name: str) -> str:
    """``"Google Chrome"`` -> ``"google_chrome"`` -> alias ``"chromium"``."""
    base = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")
    if base and base[0].isdigit():
        base = f"app_{base}"
    return APP_ALIASES.get(base, base)


def _process_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


class AppModule(ScriptableObject):
    """Base dos appModules. Subclasses podem definir scripts e ``event_*``.

    Eventos têm a assinatura do NVDA: ``event_gainFocus(self, obj, next_handler)``;
    chame ``next_handler()`` para seguir com o comportamento padrão.
    """

    #: Se verdadeiro, o leitor ignora o aplicativo (``sleepMode`` do NVDA).
    sleep_mode: bool = False

    def __init__(self, process_id: int, app_name: str, module_name: str = "") -> None:
        super().__init__()
        self.process_id = process_id
        self.app_name = app_name
        self.name = module_name or normalize_app_name(app_name)

    @property
    def is_alive(self) -> bool:
        return self.process_id <= 0 or os.path.exists(f"/proc/{self.process_id}")

    def should_use_browse_mode(self, doc: LinuxNVDAObject) -> bool:
        """Permite vetar o Browse Mode num documento."""
        return True

    def choose_overlay_classes(self, obj: LinuxNVDAObject, cls_list: list[type]) -> None:
        """Insere classes overlay para objetos deste aplicativo."""
        legacy = getattr(self, "chooseNVDAObjectOverlayClasses", None)
        if callable(legacy):
            legacy(obj, cls_list)

    def config_profile(self) -> str | None:
        """Perfil de configuração a ativar quando o app ganha foco."""
        value = configUtils.get(f"profileTriggers.app.{self.name}", None)
        return str(value) if value else None

    def terminate(self) -> None:
        """Chamado quando o processo termina ou o appModule é descarregado."""

    # Aliases do NVDA.
    @property
    def processID(self) -> int:
        return self.process_id

    @property
    def appName(self) -> str:
        return self.name

    @property
    def sleepMode(self) -> bool:
        return self.sleep_mode


class AppModuleManager:
    """Instancia e guarda um appModule por processo."""

    def __init__(self) -> None:
        self._instances: dict[Hashable, AppModule] = {}
        self._registered: dict[str, tuple[type[AppModule], str]] = {}

    # ------------------------------------------------------------ registro (add-ons)
    def register(self, module_name: str, cls: type[AppModule], source: str) -> None:
        self._registered[module_name] = (cls, source)
        self.reset_module(module_name)

    def unregister_source(self, source: str) -> list[str]:
        names = [n for n, (_cls, src) in self._registered.items() if src == source]
        for name in names:
            del self._registered[name]
            self.reset_module(name)
        return names

    def reset_module(self, module_name: str) -> None:
        """Descarta instâncias de ``module_name`` (recriadas no próximo foco)."""
        for key, app in list(self._instances.items()):
            if app.name == module_name:
                self._terminate(app)
                del self._instances[key]

    # ------------------------------------------------------------ busca
    def _class_for(self, module_name: str) -> type[AppModule]:
        registered = self._registered.get(module_name)
        if registered is not None:
            return registered[0]
        if module_name:
            try:
                module = importlib.import_module(f"nvda_linux.appModules.{module_name}")
            except ModuleNotFoundError:
                module = None
            except Exception:
                log.exception("appModule %s falhou ao importar", module_name)
                module = None
            cls = getattr(module, "AppModule", None) if module is not None else None
            if isinstance(cls, type) and issubclass(cls, AppModule):
                return cls
        return AppModule

    def get(self, process_id: int, app_name: str) -> AppModule:
        key: Hashable = process_id if process_id > 0 else ("name", app_name)
        app = self._instances.get(key)
        if app is not None:
            return app
        name = app_name or _process_name(process_id)
        module_name = normalize_app_name(name)
        cls = self._class_for(module_name)
        try:
            app = cls(process_id, name, module_name)
        except Exception:
            log.exception("appModule %s falhou ao iniciar", module_name)
            app = AppModule(process_id, name, module_name)
        self._instances[key] = app
        return app

    def get_for(self, obj: LinuxNVDAObject) -> AppModule | None:
        try:
            return self.get(obj.process_id, obj.app_name)
        except Exception:
            log.exception("Falha ao obter appModule")
            return None

    def choose_overlay_classes(self, obj: LinuxNVDAObject, cls_list: list[type]) -> None:
        app = self.get_for(obj)
        if app is None:
            return
        try:
            app.choose_overlay_classes(obj, cls_list)
        except Exception:
            log.exception("choose_overlay_classes de %s falhou", app.name)

    @property
    def running(self) -> list[AppModule]:
        return list(self._instances.values())

    def cleanup(self) -> None:
        for key, app in list(self._instances.items()):
            if not app.is_alive:
                self._terminate(app)
                del self._instances[key]

    @staticmethod
    def _terminate(app: AppModule) -> None:
        try:
            app.terminate()
        except Exception:
            log.exception("terminate de %s falhou", app.name)

    def terminate_all(self) -> None:
        for app in self._instances.values():
            self._terminate(app)
        self._instances.clear()
