"""Cadeia de scripts (ordem do NVDA) e comandos globais nos layouts Desktop e Laptop."""

from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar

from nvda_linux import services
from nvda_linux.appModules.appModuleHandler import AppModule
from nvda_linux.contracts import InputGesture, KeyboardLayout
from nvda_linux.globalPlugins.globalPluginHandler import GlobalPlugin
from nvda_linux.scripts.chain import SafeProvider
from nvda_linux.scripts.globalCommands import GlobalCommands, format_date, format_time
from nvda_linux.scripts.runtime import Runtime
from nvda_linux.scripts.scriptHandler import (
    describe_gesture,
    normalize_gesture_id,
    run_script,
    script,
)
from nvda_linux.treeInterceptors.browseMode import BrowseModeTreeInterceptor
from tests.semantics.conftest import Platform
from tests.semantics.fakes import FakeApp
from tests.semantics.helpers import event, focus, gesture, obj, press
from tests.semantics.pages import build_dialog, build_web_page


async def say(rt: Runtime, platform: Platform, identifier: str, repeat: int = 0) -> str:
    platform.speech.clear()
    assert await press(rt, identifier, repeat), identifier
    return platform.speech.text


def test_gesture_normalization_and_names() -> None:
    assert normalize_gesture_id("kb:Shift+NVDA+DownArrow") == "kb:nvda+shift+downarrow"
    assert normalize_gesture_id("kb:ctrl+alt+Down") == "kb:alt+control+downarrow"
    assert normalize_gesture_id("NVDA+t") == "kb:nvda+t"
    assert describe_gesture("kb:nvda+shift+downarrow") == "NVDA+Shift+seta para baixo"
    assert describe_gesture("kb:numpad8") == "8 do teclado numérico"
    assert describe_gesture("kb:nvda+f12") == "NVDA+F12"


def test_chain_order(rt: Runtime, platform: Platform) -> None:
    class Plugin(GlobalPlugin):
        pass

    rt.global_plugins.load(Plugin, "test")
    page = build_web_page()
    focus(rt, page.doc)
    providers = rt.chain.chain()
    assert all(isinstance(p, SafeProvider) for p in providers)
    inner = [p.inner for p in providers]  # type: ignore[attr-defined]
    assert isinstance(inner[0], Plugin)
    assert isinstance(inner[1], AppModule) and inner[1].name == "firefox"
    assert isinstance(inner[2], BrowseModeTreeInterceptor)
    assert inner[3] == obj(page.doc)
    assert isinstance(inner[4], GlobalCommands)


async def test_plugin_scripts_take_precedence_and_are_isolated(
    rt: Runtime, platform: Platform
) -> None:
    class Plugin(GlobalPlugin):
        @script(description="Hora do plugin", gesture="kb:nvda+f12")
        def script_myTime(self, gesture: InputGesture) -> None:
            raise RuntimeError("falhou")

        __gestures: ClassVar[dict[str, str]] = {"kb:nvda+shift+v": "version"}  # estilo NVDA

        def script_version(self, gesture: InputGesture) -> None:
            services.speech().speak_text("versão 1")

    rt.global_plugins.load(Plugin, "test")
    found = rt.chain.find_script(gesture("kb:nvda+f12"))
    assert found is not None and found.__doc__ == "Hora do plugin"
    await run_script(found, gesture("kb:nvda+f12"))  # exceção só vai ao log
    assert await say(rt, platform, "kb:nvda+shift+v") == "versão 1"


async def test_title_status_time_and_focus(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    event(rt, "window:activate", d.window)
    focus(rt, d.ok)
    assert await say(rt, platform, "kb:nvda+t") == "Salvar como"
    await press(rt, "kb:nvda+t", 1)
    assert platform.speech.spelled[-1] == "Salvar como"
    assert await say(rt, platform, "kb:nvda+end") == "Pronto"
    assert re.fullmatch(r"\d\d:\d\d", await say(rt, platform, "kb:nvda+f12"))
    assert "de" in await say(rt, platform, "kb:nvda+f12", repeat=1)
    assert await say(rt, platform, "kb:nvda+tab") == "OK botão Alt+O"
    assert "Salvar como diálogo modal" in await say(rt, platform, "kb:nvda+b")
    assert await say(rt, platform, "kb:nvda+space") == "Modo de navegação não disponível aqui"


def test_date_time_formatting() -> None:
    moment = dt.datetime(2026, 11, 21, 9, 5)
    assert format_time(moment) == "09:05"
    assert format_date(moment) == "sábado, 21 de novembro de 2026"


async def test_laptop_layout_bindings(rt: Runtime, platform: Platform) -> None:
    platform.dispatcher.layout = KeyboardLayout.LAPTOP
    d = build_dialog()
    event(rt, "window:activate", d.window)
    focus(rt, d.entry)
    assert await say(rt, platform, "kb:nvda+shift+end") == "Pronto"
    assert not await press(rt, "kb:nvda+numpad8")  # gesto Desktop não vale no Laptop
    assert await say(rt, platform, "kb:nvda+shift+uparrow") == "Opções"
    assert await say(rt, platform, "kb:nvda+shift+downarrow") == (
        "Nome do arquivo caixa de edição multilinha relatorio.txt")
    assert await say(rt, platform, "kb:nvda+l") == "relatorio.txt"
    assert await say(rt, platform, "kb:nvda+backspace") == (
        "Nome do arquivo caixa de edição multilinha relatorio.txt")
    # Revisão no Laptop: NVDA+setas e NVDA+ponto.
    assert await say(rt, platform, "kb:nvda+downarrow") == "segunda linha"
    assert await say(rt, platform, "kb:nvda+.") == "s"
    assert await say(rt, platform, "kb:nvda+rightarrow") == "e"
    assert await say(rt, platform, "kb:control+nvda+home") == "relatorio.txt"


async def test_object_navigation_simple_mode(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    event(rt, "window:activate", d.window)
    focus(rt, d.ok)
    assert await say(rt, platform, "kb:nvda+numpad8") == "Salvar como diálogo modal"
    assert await say(rt, platform, "kb:nvda+numpad2") == "Opções"
    assert await say(rt, platform, "kb:nvda+numpad6") == "OK botão Alt+O"
    assert await say(rt, platform, "kb:nvda+numpad6") == "Cancelar botão"
    assert await say(rt, platform, "kb:nvda+numpad6") == "Progresso barra de progresso 50%"
    assert await say(rt, platform, "kb:nvda+numpad4") == "Cancelar botão"
    assert await say(rt, platform, "kb:nvda+numpad5") == "Cancelar botão"
    await press(rt, "kb:nvda+numpad5", 1)
    assert platform.speech.spelled[-1] == "Cancelar"
    assert await say(rt, platform, "kb:nvda+numpadminus") == "OK botão Alt+O"
    assert await say(rt, platform, "kb:nvda+numpad2") == "Sem objetos contidos"
    await press(rt, "kb:nvda+numpad8")
    await press(rt, "kb:nvda+numpad2")
    assert await say(rt, platform, "kb:nvda+numpad4") == "Nenhum anterior"
    await press(rt, "kb:nvda+numpad6")  # OK
    await press(rt, "kb:nvda+numpad6")  # Cancelar
    assert await press(rt, "kb:nvda+numpadenter")
    assert d.cancel.action is not None and d.cancel.action.performed == [0]
    assert await press(rt, "kb:nvda+shift+numpadminus")
    assert d.cancel.focus_requests == 1
    platform.config.values["reviewCursor.simpleReviewMode"] = False
    await press(rt, "kb:nvda+numpadminus")
    # Modo completo: o FILLER sem nome não é pulado.
    assert await say(rt, platform, "kb:nvda+numpad8") == "preenchimento"
    assert rt.focus.navigator is not None and rt.focus.navigator.name == ""


async def test_review_cursor_desktop(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.entry)
    assert await say(rt, platform, "kb:numpad8") == "relatorio.txt"
    assert await say(rt, platform, "kb:numpad9") == "segunda linha"
    assert await say(rt, platform, "kb:numpad9") == "fim | segunda linha"
    assert await say(rt, platform, "kb:numpad5") == "segunda"
    assert await say(rt, platform, "kb:numpad6") == "linha"
    assert await say(rt, platform, "kb:numpad2") == "l"
    await press(rt, "kb:numpad2", 1)
    assert platform.speech.spelled[-1] == "l"
    assert await say(rt, platform, "kb:numpad2", repeat=2) == "código 108"
    assert await say(rt, platform, "kb:numpad3") == "i"
    assert await say(rt, platform, "kb:shift+numpad3") == "a"
    assert await say(rt, platform, "kb:shift+numpad1") == "s"
    assert await say(rt, platform, "kb:numpad1") == "nova linha"
    assert await say(rt, platform, "kb:shift+numpad7") == "relatorio.txt"
    assert await say(rt, platform, "kb:numpad7") == "início | relatorio.txt"
    assert await say(rt, platform, "kb:shift+numpad9") == "segunda linha"
    assert await say(rt, platform, "kb:numpadplus") == "segunda linha"
    # Objeto sem Atspi.Text: revisão sobre nome/valor.
    focus(rt, d.ok)
    assert await say(rt, platform, "kb:numpad8") == "OK"


async def test_caret_commands_in_text(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.entry)
    assert await say(rt, platform, "kb:nvda+uparrow") == "relatorio.txt"
    await press(rt, "kb:nvda+uparrow", 1)
    assert platform.speech.spelled[-1] == "relatorio.txt"
    assert await say(rt, platform, "kb:nvda+downarrow") == "relatorio.txt | segunda linha"
    assert await say(rt, platform, "kb:nvda+shift+uparrow") == "Nenhuma seleção"
    assert d.entry.text_iface is not None
    d.entry.text_iface.selections = [(0, 9)]
    assert await say(rt, platform, "kb:nvda+shift+uparrow") == "relatorio selecionado"
    d.entry.text_iface.attributes = {"family-name": "Cantarell", "size": "11", "weight": "700"}
    assert await say(rt, platform, "kb:nvda+f") == "fonte Cantarell, 11 pontos, negrito"


async def test_input_help(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.ok)
    assert await say(rt, platform, "kb:nvda+1") == "Ajuda de entrada ativada"
    assert platform.dispatcher.input_help
    found = rt.chain.find_script(gesture("kb:nvda+t"))
    assert found is not None and (found.__doc__ or "").startswith("Fala o título")
    platform.speech.clear()
    await run_script(found, gesture("kb:nvda+t"))
    assert platform.speech.text.startswith("NVDA+T: Fala o título")
    assert await say(rt, platform, "kb:nvda+1") == "Ajuda de entrada desativada"


async def test_speech_quit_menu_and_pass_next(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.ok)
    assert await press(rt, "kb:control")
    assert platform.speech.cancel_count > 0
    await press(rt, "kb:shift")
    assert platform.speech.paused is True
    await press(rt, "kb:shift")
    assert platform.speech.paused is False
    assert await say(rt, platform, "kb:nvda+n") == "Interface gráfica indisponível"
    app = FakeApp()
    services.register("app", app)
    assert await say(rt, platform, "kb:nvda+q") == "Saindo do NVDA"
    assert app.exit_requests == 1
    await press(rt, "kb:nvda+f2")
    assert await press(rt, "kb:a", character="a")
    assert platform.dispatcher.sent[-1].identifier == "kb:a"
    assert not rt.chain.pass_next_key


async def test_sleep_mode(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.ok)
    assert await say(rt, platform, "kb:nvda+shift+z") == "Modo dormir ativado"
    assert not await press(rt, "kb:nvda+t")
    assert await say(rt, platform, "kb:nvda+shift+z") == "Modo dormir desativado"
    assert await press(rt, "kb:nvda+t")


async def test_gestures_ini_bindings(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.ok)
    remapped = gesture("kb:nvda+x", bindings=[("globalCommands.GlobalCommands", "dateTime")])
    found = rt.chain.find_script(remapped)
    assert found is not None
    platform.speech.clear()
    await run_script(found, remapped)
    assert re.fullmatch(r"\d\d:\d\d", platform.speech.text)
    other = gesture("kb:nvda+x", bindings=[("browseMode.BrowseModeTreeInterceptor", "nextLine")])
    assert rt.chain.find_script(other) is None
