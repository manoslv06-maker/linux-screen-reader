"""Carregador de add-ons: manifesto, carga, isolamento e operações sem reiniciar."""

from __future__ import annotations

import json
import re
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from nvda_linux.addons import AddonError, AddonManager
from nvda_linux.addons.manifest import parse_manifest_text
from nvda_linux.scripts.runtime import Runtime
from tests.semantics.conftest import Platform
from tests.semantics.helpers import focus, press
from tests.semantics.pages import build_dialog, build_web_page

MANIFEST = '''name = {name}
summary = "Complemento {name}"
description = """Linha 1
Linha 2"""
author = "Fulana <fulana@example.org>"
version = 1.2
'''

PLUGIN = '''
from nvda_linux.globalPlugins import GlobalPlugin
from nvda_linux.scripts import ui
from nvda_linux.scripts.scriptHandler import script

TERMINATED = []


class GlobalPlugin(GlobalPlugin):
    @script(description="Diz olá", gesture="kb:nvda+shift+h")
    def script_hello(self, gesture):
        ui.message("olá do add-on")

    def event_gainFocus(self, obj, next_handler):
        ui.message("plugin viu o foco")
        next_handler()

    def terminate(self):
        TERMINATED.append(True)
'''

APP_MODULE = '''
from nvda_linux.appModules import AppModule as Base
from nvda_linux.scripts import ui


class AppModule(Base):
    def script_sayApp(self, gesture):
        ui.message("app do add-on")

    gesture_map = {"kb:nvda+shift+a": "sayApp"}
'''

NVDA_STYLE = '''
import addonHandler
import globalPluginHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    @script(description=_("Estilo NVDA"), gesture="kb:NVDA+Shift+N", bypassInputHelp=False)
    def script_nvdaStyle(self, gesture):
        ui.message(_("funciona"))
'''


def make_addon(root: Path, name: str, files: dict[str, str]) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "manifest.ini").write_text(MANIFEST.format(name=name), encoding="utf-8")
    for rel, content in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    return folder


@pytest.fixture
def addons_dir(tmp_path: Path) -> Path:
    return tmp_path / "addons"


def manager_for(rt: Runtime, addons_dir: Path) -> AddonManager:
    manager = AddonManager(rt.global_plugins, rt.app_modules, addons_dir)
    rt.addons = manager
    return manager


def test_manifest_parsing() -> None:
    data = parse_manifest_text(MANIFEST.format(name="teste") + "# comentário\nurl = 'x' \n")
    assert data["name"] == "teste"
    assert data["summary"] == "Complemento teste"
    assert data["description"] == "Linha 1\nLinha 2"
    assert data["version"] == "1.2"
    assert data["url"] == "x"


async def test_load_scripts_events_and_app_modules(
    rt: Runtime, platform: Platform, addons_dir: Path
) -> None:
    make_addon(addons_dir, "saudacao", {
        "globalPlugins/hello.py": PLUGIN,
        "appModules/gedit.py": APP_MODULE,
    })
    manager = manager_for(rt, addons_dir)
    [addon] = manager.load_all()
    assert addon.loaded and addon.global_plugins == 1 and addon.app_modules == ["gedit"]
    assert addon.errors == []
    d = build_dialog()
    focus(rt, d.ok)
    assert "plugin viu o foco" in platform.speech.text
    platform.speech.clear()
    assert await press(rt, "kb:nvda+shift+h")
    assert platform.speech.text == "olá do add-on"
    assert await press(rt, "kb:nvda+shift+a")
    assert platform.speech.last == ["app do add-on"]


async def test_disable_enable_remove_without_restart(
    rt: Runtime, platform: Platform, addons_dir: Path
) -> None:
    make_addon(addons_dir, "saudacao", {"globalPlugins/hello.py": PLUGIN,
                                        "appModules/gedit.py": APP_MODULE})
    manager = manager_for(rt, addons_dir)
    manager.load_all()
    module = sys.modules["nvdaAddons.saudacao.globalPlugins.hello"]
    terminated = module.TERMINATED
    d = build_dialog()
    focus(rt, d.ok)
    assert manager.disable("saudacao")
    assert terminated == [True]
    assert rt.global_plugins.plugins == []
    assert "nvdaAddons.saudacao.globalPlugins.hello" not in sys.modules
    assert not await press(rt, "kb:nvda+shift+h")
    assert not await press(rt, "kb:nvda+shift+a")  # appModule do add-on saiu
    state = json.loads((addons_dir / "addonsState.json").read_text(encoding="utf-8"))
    assert state == {"disabled": ["saudacao"]}
    # Um novo gerenciador respeita o estado salvo.
    assert not manager_for(rt, addons_dir).load_all()[0].loaded
    manager = manager_for(rt, addons_dir)
    manager.discover()
    assert manager.enable("saudacao")
    assert await press(rt, "kb:nvda+shift+h")
    assert manager.remove("saudacao")
    assert not (addons_dir / "saudacao").exists()
    assert not await press(rt, "kb:nvda+shift+h")


def test_broken_addons_are_isolated(rt: Runtime, platform: Platform, addons_dir: Path) -> None:
    make_addon(addons_dir, "quebrado", {"globalPlugins/ruim.py": "def oops(:\n"})
    make_addon(addons_dir, "construtor", {"globalPlugins/c.py": '''
        from nvda_linux.globalPlugins import GlobalPlugin as Base
        class GlobalPlugin(Base):
            def __init__(self):
                raise RuntimeError("não inicia")
    '''})
    make_addon(addons_dir, "bom", {"globalPlugins/hello.py": PLUGIN})
    (addons_dir / "sem_manifesto").mkdir()
    bad_manifest = addons_dir / "nome_invalido"
    bad_manifest.mkdir()
    (bad_manifest / "manifest.ini").write_text("name = ../fora\n", encoding="utf-8")
    manager = manager_for(rt, addons_dir)
    addons = {a.name: a for a in manager.load_all()}
    assert set(addons) == {"quebrado", "construtor", "bom"}
    assert addons["quebrado"].errors and "SyntaxError" in addons["quebrado"].errors[0]
    assert addons["construtor"].errors and addons["construtor"].global_plugins == 0
    assert addons["bom"].global_plugins == 1 and not addons["bom"].errors


async def test_install_from_folder_and_bundle(
    rt: Runtime, platform: Platform, addons_dir: Path, tmp_path: Path
) -> None:
    source = make_addon(tmp_path / "src", "pacote", {"globalPlugins/hello.py": PLUGIN})
    manager = manager_for(rt, addons_dir)
    addon = manager.install(source)
    assert addon.loaded and (addons_dir / "pacote" / "manifest.ini").is_file()
    assert await press(rt, "kb:nvda+shift+h")
    bundle = tmp_path / "zipado.nvda-addon"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("manifest.ini", MANIFEST.format(name="zipado"))
        zf.writestr("globalPlugins/estilo.py", NVDA_STYLE)
    addon = manager.install(bundle)
    assert addon.name == "zipado" and addon.errors == []
    platform.speech.clear()
    assert await press(rt, "kb:nvda+shift+n")
    assert platform.speech.text == "funciona"
    # Reinstalar substitui (o plugin antigo é encerrado antes).
    again = manager.install(source)
    assert again.loaded and len([p for p in rt.global_plugins.plugins
                                 if type(p).__module__.endswith("hello")]) == 1


def test_bundle_with_path_traversal_is_rejected(
    rt: Runtime, addons_dir: Path, tmp_path: Path
) -> None:
    bundle = tmp_path / "mau.nvda-addon"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("manifest.ini", MANIFEST.format(name="mau"))
        zf.writestr("../../fora.txt", "x")
    manager = manager_for(rt, addons_dir)
    with pytest.raises(AddonError):
        manager.install(bundle)
    assert not (tmp_path / "fora.txt").exists()
    assert [p.name for p in addons_dir.iterdir()] == []
    with pytest.raises(AddonError):
        manager.install(tmp_path / "nao_existe")


def test_app_module_from_addon_replaces_builtin(rt: Runtime, addons_dir: Path) -> None:
    make_addon(addons_dir, "ff", {"appModules/firefox.py": '''
        from nvda_linux.appModules.firefox import AppModule as Builtin
        class AppModule(Builtin):
            custom = True
    '''})
    manager = manager_for(rt, addons_dir)
    manager.load_all()
    page = build_web_page()
    focus(rt, page.doc)
    app = rt.app_modules.get(1001, "Firefox")
    assert getattr(app, "custom", False)
    manager.disable("ff")
    app = rt.app_modules.get(1001, "Firefox")
    assert not getattr(app, "custom", False) and app.name == "firefox"


async def test_documented_example_addon_works(
    rt: Runtime, platform: Platform, addons_dir: Path
) -> None:
    """O exemplo completo de docs/semantics/ADDONS.md carrega e funciona."""
    doc = Path(__file__).resolve().parents[2] / "docs" / "semantics" / "ADDONS.md"
    text = doc.read_text(encoding="utf-8")
    example = text.split("## Exemplo completo", 1)[1]
    blocks = re.findall(r"`~/\.config/nvda-linux/addons/relogio/([^`]+)`:\n\n```\w+\n(.*?)```",
                        example, re.DOTALL)
    assert [path for path, _ in blocks] == [
        "manifest.ini", "globalPlugins/relogio.py", "appModules/firefox.py"]
    folder = addons_dir / "relogio"
    for path, content in blocks:
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    manager = manager_for(rt, addons_dir)
    [addon] = manager.load_all()
    assert addon.errors == [] and addon.global_plugins == 1 and addon.app_modules == ["firefox"]
    page = build_web_page()
    focus(rt, page.doc)
    platform.speech.clear()
    assert await press(rt, "kb:nvda+shift+f12")
    assert platform.speech.text.endswith("segundos")
    assert await press(rt, "kb:nvda+shift+u")
    assert platform.speech.last == ["comando só do Firefox"]
    manager.disable("relogio")
    assert "Relógio encerrado depois de 1 focos" in platform.speech.text
