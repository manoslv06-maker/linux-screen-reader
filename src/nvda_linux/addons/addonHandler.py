# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Carregador de add-ons (``addonHandler`` do NVDA).

Estrutura em ``~/.config/nvda-linux/addons/`` (ou ``$XDG_CONFIG_HOME``)::

    meu_plugin/
      manifest.ini
      globalPlugins/
        __init__.py          # opcional; pode definir GlobalPlugin
        atalhos.py           # define class GlobalPlugin(...)
      appModules/
        firefox.py           # define class AppModule(...)

* Cada add-on é importado como pacote ``nvdaAddons.<nome>`` (importações
  relativas funcionam).
* Instalar, ativar, desativar e remover acontecem sem reiniciar o leitor:
  plugins recebem ``terminate()`` e os appModules do add-on são trocados no
  próximo foco do aplicativo.
* Exceções de add-ons (na importação, no construtor, em scripts e eventos)
  vão ao log e ficam em :attr:`Addon.errors`; nunca derrubam o leitor.
* O estado (desativados) fica em ``addonsState.json`` na pasta de add-ons.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import sys
import tempfile
import types
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nvda_linux.addons import compat
from nvda_linux.addons.manifest import AddonManifest, ManifestError, read_manifest
from nvda_linux.scripts import configUtils

if TYPE_CHECKING:
    from nvda_linux.appModules.appModuleHandler import AppModuleManager
    from nvda_linux.globalPlugins.globalPluginHandler import GlobalPluginManager

log = logging.getLogger(__name__)

PACKAGE_ROOT = "nvdaAddons"
STATE_FILE = "addonsState.json"
BUNDLE_SUFFIX = ".nvda-addon"
_MAX_BUNDLE_BYTES = 200 * 1024 * 1024


def default_addons_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "nvda-linux" / "addons"


def _safe_module_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return cleaned if cleaned and not cleaned[0].isdigit() else f"a_{cleaned}"


class AddonError(RuntimeError):
    """Falha de instalação/remoção de add-on."""


@dataclass
class Addon:
    """Um add-on instalado."""

    name: str
    path: Path
    manifest: AddonManifest
    enabled: bool = True
    loaded: bool = False
    errors: list[str] = field(default_factory=list)
    global_plugins: int = 0
    app_modules: list[str] = field(default_factory=list)

    @property
    def source(self) -> str:
        return f"addon:{self.name}"

    @property
    def package(self) -> str:
        return f"{PACKAGE_ROOT}.{_safe_module_name(self.name)}"


class AddonManager:
    """Descobre, carrega e gerencia add-ons."""

    def __init__(
        self,
        global_plugins: GlobalPluginManager,
        app_modules: AppModuleManager,
        base_dir: Path | None = None,
    ) -> None:
        self.base_dir = base_dir or default_addons_dir()
        self.global_plugins = global_plugins
        self.app_modules = app_modules
        self._addons: dict[str, Addon] = {}

    # ------------------------------------------------------------ estado
    @property
    def addons(self) -> list[Addon]:
        return sorted(self._addons.values(), key=lambda a: a.name.lower())

    def get(self, name: str) -> Addon | None:
        return self._addons.get(name)

    def _state_path(self) -> Path:
        return self.base_dir / STATE_FILE

    def _read_disabled(self) -> set[str]:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        disabled = data.get("disabled", []) if isinstance(data, dict) else []
        return {str(d) for d in disabled}

    def _write_state(self) -> None:
        disabled = sorted(a.name for a in self._addons.values() if not a.enabled)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path().with_suffix(".tmp")
            tmp.write_text(json.dumps({"disabled": disabled}, indent=2), encoding="utf-8")
            tmp.replace(self._state_path())
        except OSError as exc:
            log.warning("Não foi possível gravar o estado dos add-ons: %s", exc)

    # ------------------------------------------------------------ descoberta
    def discover(self) -> list[Addon]:
        """Lê os manifestos em :attr:`base_dir` (sem importar código)."""
        disabled = self._read_disabled()
        found: dict[str, Addon] = {}
        if self.base_dir.is_dir():
            for entry in sorted(self.base_dir.iterdir()):
                manifest_path = entry / "manifest.ini"
                if not entry.is_dir() or not manifest_path.is_file():
                    continue
                try:
                    manifest = read_manifest(manifest_path, fallback_name=entry.name)
                except ManifestError as exc:
                    log.warning("Add-on %s ignorado: %s", entry.name, exc)
                    continue
                existing = self._addons.get(manifest.name)
                if existing is not None and existing.path == entry:
                    found[manifest.name] = existing
                    continue
                found[manifest.name] = Addon(
                    manifest.name, entry, manifest, enabled=manifest.name not in disabled
                )
        self._addons = found
        return self.addons

    def load_all(self) -> list[Addon]:
        """Descobre e carrega todos os add-ons ativados."""
        self.discover()
        for addon in self.addons:
            if addon.enabled and not addon.loaded:
                self._load(addon)
        return self.addons

    # ------------------------------------------------------------ carga
    def _ensure_packages(self, addon: Addon) -> None:
        root = sys.modules.get(PACKAGE_ROOT)
        if root is None:
            root = types.ModuleType(PACKAGE_ROOT, "Pacotes dos add-ons do nvda-linux")
            root.__path__ = []
            sys.modules[PACKAGE_ROOT] = root
        pkg = types.ModuleType(addon.package, f"Add-on {addon.name}")
        pkg.__path__ = [str(addon.path)]
        sys.modules[addon.package] = pkg
        setattr(root, addon.package.rsplit(".", 1)[1], pkg)

    def _import(self, addon: Addon, dotted: str) -> types.ModuleType | None:
        try:
            return importlib.import_module(dotted)
        except Exception as exc:
            message = f"falha ao importar {dotted}: {type(exc).__name__}: {exc}"
            log.exception("Add-on %s: %s", addon.name, message)
            addon.errors.append(message)
            return None

    @staticmethod
    def _submodules(directory: Path) -> list[str]:
        names: list[str] = []
        if not directory.is_dir():
            return names
        for entry in sorted(directory.iterdir()):
            if entry.name.startswith((".", "_")):
                continue
            if entry.is_file() and entry.suffix == ".py":
                names.append(entry.stem)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                names.append(entry.name)
        return names

    def _load(self, addon: Addon) -> None:
        from nvda_linux.appModules.appModuleHandler import AppModule
        from nvda_linux.globalPlugins.globalPluginHandler import GlobalPlugin

        if configUtils.get_bool("addons.nvdaCompatAliases", True):
            compat.install()
        addon.errors.clear()
        addon.global_plugins = 0
        addon.app_modules = []
        importlib.invalidate_caches()
        self._ensure_packages(addon)

        gp_dir = addon.path / "globalPlugins"
        gp_modules: list[types.ModuleType] = []
        if gp_dir.is_dir():
            package = self._import(addon, f"{addon.package}.globalPlugins")
            if package is not None and (gp_dir / "__init__.py").is_file():
                gp_modules.append(package)
            for sub in self._submodules(gp_dir):
                module = self._import(addon, f"{addon.package}.globalPlugins.{sub}")
                if module is not None:
                    gp_modules.append(module)
        for module in gp_modules:
            cls = getattr(module, "GlobalPlugin", None)
            if isinstance(cls, type) and issubclass(cls, GlobalPlugin) and cls is not GlobalPlugin:
                if self.global_plugins.load(cls, addon.source) is not None:
                    addon.global_plugins += 1
                else:
                    addon.errors.append(f"GlobalPlugin de {module.__name__} falhou ao iniciar")

        am_dir = addon.path / "appModules"
        if am_dir.is_dir() and self._import(addon, f"{addon.package}.appModules") is not None:
            for sub in self._submodules(am_dir):
                module = self._import(addon, f"{addon.package}.appModules.{sub}")
                cls = getattr(module, "AppModule", None) if module is not None else None
                if isinstance(cls, type) and issubclass(cls, AppModule):
                    self.app_modules.register(sub, cls, addon.source)
                    addon.app_modules.append(sub)
        addon.loaded = True
        log.info(
            "Add-on %s carregado: %d globalPlugins, appModules %s",
            addon.name,
            addon.global_plugins,
            addon.app_modules,
        )

    def _unload(self, addon: Addon) -> None:
        self.global_plugins.unload_source(addon.source)
        self.app_modules.unregister_source(addon.source)
        prefix = addon.package
        for name in [n for n in sys.modules if n == prefix or n.startswith(prefix + ".")]:
            del sys.modules[name]
        addon.loaded = False

    # ------------------------------------------------------------ operações
    def enable(self, name: str) -> bool:
        addon = self._addons.get(name)
        if addon is None:
            return False
        addon.enabled = True
        self._write_state()
        if not addon.loaded:
            self._load(addon)
        return True

    def disable(self, name: str) -> bool:
        addon = self._addons.get(name)
        if addon is None:
            return False
        if addon.loaded:
            self._unload(addon)
        addon.enabled = False
        self._write_state()
        return True

    def reload(self, name: str) -> bool:
        addon = self._addons.get(name)
        if addon is None:
            return False
        if addon.loaded:
            self._unload(addon)
        if addon.enabled:
            self._load(addon)
        return True

    def remove(self, name: str) -> bool:
        addon = self._addons.pop(name, None)
        if addon is None:
            return False
        if addon.loaded:
            self._unload(addon)
        try:
            shutil.rmtree(addon.path)
        except OSError as exc:
            log.warning("Não foi possível apagar %s: %s", addon.path, exc)
            self._addons[name] = addon
            return False
        self._write_state()
        return True

    def install(self, source: Path, enable: bool = True) -> Addon:
        """Instala de uma pasta ou de um pacote ``.nvda-addon`` (zip).

        Um add-on com o mesmo nome é substituído (descarregado antes).
        """
        source = Path(source)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=self.base_dir))
        try:
            content = staging / "content"
            if source.is_dir():
                shutil.copytree(source, content, ignore=shutil.ignore_patterns("__pycache__"))
            elif source.is_file() and zipfile.is_zipfile(source):
                _safe_extract(source, content)
            else:
                raise AddonError(f"{source} não é uma pasta nem um pacote {BUNDLE_SUFFIX}")
            manifest_path = content / "manifest.ini"
            if not manifest_path.is_file():
                raise AddonError("manifest.ini não encontrado")
            try:
                manifest = read_manifest(manifest_path, fallback_name=source.stem)
            except ManifestError as exc:
                raise AddonError(str(exc)) from exc
            target = self.base_dir / manifest.name
            previous = self._addons.get(manifest.name)
            if previous is not None and previous.loaded:
                self._unload(previous)
            if target.exists():
                shutil.rmtree(target)
            content.replace(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        addon = Addon(manifest.name, target, manifest, enabled=enable)
        self._addons[manifest.name] = addon
        self._write_state()
        if enable:
            self._load(addon)
        return addon

    def terminate(self) -> None:
        for addon in self._addons.values():
            if addon.loaded:
                self._unload(addon)
        compat.uninstall()


def _safe_extract(bundle: Path, destination: Path) -> None:
    """Extrai o zip recusando caminhos absolutos, ``..``, links e bombas."""
    destination.mkdir(parents=True)
    root = destination.resolve()
    total = 0
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise AddonError(f"caminho inválido no pacote: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise AddonError(f"link simbólico no pacote: {info.filename}")
            total += info.file_size
            if total > _MAX_BUNDLE_BYTES:
                raise AddonError("pacote grande demais")
            target = (destination / name).resolve()
            if root not in target.parents and target != root:
                raise AddonError(f"caminho fora do destino: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
