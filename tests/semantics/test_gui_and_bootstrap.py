"""Modelos da GUI (sem GTK), gancho do Visualizador de Fala e bootstrap start/stop."""

from __future__ import annotations

from pathlib import Path

import pytest

from nvda_linux import gui, services
from nvda_linux.gui import _gtk, nvdaMenu, settingsModel, speechViewer
from nvda_linux.NVDAObjects import _atspi
from nvda_linux.scripts import bootstrap, runtime, speechHooks, ui
from nvda_linux.treeInterceptors.browseMode import BrowseModeTreeInterceptor
from nvda_linux.treeInterceptors.elementsList import ElementsListModel
from tests.semantics.conftest import Platform
from tests.semantics.helpers import focus, gesture, obj
from tests.semantics.pages import build_web_page


@pytest.fixture
def no_gtk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simula máquina sem GTK/display (também num Linux com GTK)."""
    monkeypatch.setattr(_gtk, "available", lambda: False)


@pytest.mark.usefixtures("no_gtk")
def test_gui_functions_degrade_without_gtk() -> None:
    assert not gui.available()
    assert not gui.show_nvda_menu()
    assert not gui.show_settings()
    assert not gui.show_addons_manager()
    assert not gui.confirm_exit(lambda: None)
    page = build_web_page()
    ti = BrowseModeTreeInterceptor(obj(page.doc))
    assert not gui.show_elements_list(ElementsListModel(ti))
    assert [label for label, _ in nvdaMenu.menu_entries()] == [
        "Configurações...", "Visualizador de Fala", "Gerenciador de complementos...", "Sair"]


def test_settings_model_load_coerce_and_apply(platform: Platform) -> None:
    platform.config.values.update({"speech.rate": 250, "keyboard.keyboardLayout": "laptop"})
    values = settingsModel.load_values()
    assert values["speech.rate"] == 100  # limitado ao máximo
    assert values["keyboard.keyboardLayout"] == "laptop"
    assert values["browseMode.autoSayAllOnPageLoad"] is True
    platform.config.reject.add("speech.voice")
    failed = settingsModel.apply_values(
        {"speech.rate": "70", "speech.voice": "pt-br", "browseMode.linesPerPage": 1,
         "desconhecida": 1})
    assert failed == ["speech.voice"]
    assert platform.config.values["speech.rate"] == 70
    assert platform.config.values["browseMode.linesPerPage"] == 5
    assert platform.config.saved == 1
    keys = {s.key for c in settingsModel.CATEGORIES for s in c.settings}
    assert {"speech.rate", "keyboard.speakTypedCharacters",
            "browseMode.passThroughAudioIndication", "braille.tetherTo"} <= keys
    assert [c.name for c in settingsModel.CATEGORIES] == [
        "Voz", "Teclado", "Modo de navegação", "Braille"]


@pytest.mark.usefixtures("no_gtk")
def test_speech_viewer_hook(platform: Platform) -> None:
    model = speechViewer.SpeechViewerModel(max_lines=2)
    seen: list[str] = []
    model.add_listener(seen.append)
    model.start()
    ui.speak(["Olá", "mundo"])
    ui.message("segunda")
    ui.speak_spelling("abc")
    assert seen == ["Olá  mundo", "segunda", "abc"]
    assert list(model.lines) == ["segunda", "abc"]
    speechHooks.set_platform_notifies(True)  # a PLATAFORMA passa a notificar
    ui.speak(["não duplica"])
    assert "não duplica" not in model.text
    speechHooks.notify(["da plataforma"])
    assert model.lines[-1] == "da plataforma"
    model.stop()
    assert not speechViewer.show()  # sem GTK, mas começa a gravar
    assert speechViewer.model().active
    speechViewer.close()


async def test_bootstrap_start_stop(platform: Platform, tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    rt = await bootstrap.start(addons_dir=addons, connect_atspi=False)
    assert services.focus() is rt.focus
    assert services.script_chain() is rt.chain
    assert rt.addons is not None and rt.addons.base_dir == addons
    assert await bootstrap.start(addons_dir=addons, connect_atspi=False) is rt
    page = build_web_page()
    focus(rt, page.doc)
    assert services.focus().focus_description() == "Página de Teste documento"
    providers = services.script_chain().chain()
    assert any(p.get_script(gesture("kb:h")) for p in providers)
    await bootstrap.stop()
    assert runtime.current() is None
    await bootstrap.stop()  # idempotente


async def test_bootstrap_degrades_without_atspi(
    platform: Platform, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_atspi, "init", lambda: False)
    rt = await bootstrap.start(addons_dir=tmp_path, connect_atspi=True)
    assert not rt.atspi_connected
    assert "Acessibilidade AT-SPI2 indisponível" in platform.speech.text
    await bootstrap.stop()


def test_speech_viewer_uses_platform_listener(platform: Platform) -> None:
    from tests.semantics.fakes import ListeningSpeech

    speech = ListeningSpeech()
    services.register("speech", speech)
    model = speechViewer.SpeechViewerModel()
    model.start()
    assert speechHooks.platform_notifies() and len(speech.listeners) == 1
    ui.message("uma vez")
    speech.speak(["fala da plataforma"])
    assert list(model.lines) == ["uma vez", "fala da plataforma"]
    model.stop()
    assert speech.listeners == [] and not speechHooks.platform_notifies()
