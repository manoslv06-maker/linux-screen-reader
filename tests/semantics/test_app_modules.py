"""appModules embutidos (Firefox, Chromium, GNOME Terminal) e perfis por aplicativo."""

from __future__ import annotations

from nvda_linux.appModules import chromium, firefox, gnome_terminal
from nvda_linux.appModules.appModuleHandler import AppModule, normalize_app_name
from nvda_linux.scripts.runtime import Runtime
from tests.semantics.conftest import Platform
from tests.semantics.fake_atspi import FakeAccessible
from tests.semantics.helpers import event, focus, obj
from tests.semantics.pages import build_dialog, build_terminal, build_web_page


def test_normalize_app_names() -> None:
    assert normalize_app_name("Firefox") == "firefox"
    assert normalize_app_name("Google Chrome") == "chromium"
    assert normalize_app_name("gnome-terminal-server") == "gnome_terminal"
    assert normalize_app_name("3D Viewer") == "app_3d_viewer"


def test_builtin_modules_are_selected(rt: Runtime) -> None:
    assert isinstance(rt.app_modules.get(1, "Firefox"), firefox.AppModule)
    assert isinstance(rt.app_modules.get(2, "Chromium"), chromium.AppModule)
    assert isinstance(rt.app_modules.get(3, "Google Chrome"), chromium.AppModule)
    assert isinstance(rt.app_modules.get(4, "gnome-terminal-server"), gnome_terminal.AppModule)
    plain = rt.app_modules.get(5, "gedit")
    assert type(plain) is AppModule and plain.name == "gedit"
    assert rt.app_modules.get(1, "Firefox") is rt.app_modules.get(1, "Firefox")


def test_terminal_output_and_echo(rt: Runtime, platform: Platform) -> None:
    t = build_terminal()
    terminal = focus(rt, t.terminal)
    assert isinstance(terminal, gnome_terminal.GnomeTerminal)
    assert rt.tree_interceptors.get_for(terminal) is None
    platform.speech.clear()
    event(rt, "object:text-changed:insert", t.terminal, 2, 1, "l")
    assert platform.speech.last == ["l"]
    output = "arquivo1.txt  arquivo2.txt\n$ "
    event(rt, "object:text-changed:insert", t.terminal, 3, len(output), output)
    assert platform.speech.last == ["arquivo1.txt  arquivo2.txt\n$"]
    count = len(platform.speech.utterances)
    event(rt, "object:text-changed:insert", t.terminal, 3, len(output), output)  # redesenho
    assert len(platform.speech.utterances) == count


def test_chromium_ignores_unnamed_frame_focus(rt: Runtime, platform: Platform) -> None:
    page = build_web_page("Chromium")
    unnamed = FakeAccessible("FRAME", "", extra_states=["FOCUSABLE"])
    page.app.add(unnamed)
    focus(rt, unnamed)
    assert platform.speech.utterances == []
    focus(rt, page.doc)
    assert "Bem-vindo" in platform.speech.text


def test_firefox_suppresses_busy_document_name_changes(rt: Runtime, platform: Platform) -> None:
    page = build_web_page()
    focus(rt, page.doc)
    page.doc.states.add("BUSY")
    event(rt, "object:state-changed:busy", page.doc, 1)
    platform.speech.clear()
    page.doc.name = "Carregando..."
    event(rt, "object:property-change:accessible-name", page.doc)
    assert platform.speech.utterances == []


def test_profile_switch_on_app_change(rt: Runtime, platform: Platform) -> None:
    platform.config.values["profileTriggers.app.firefox"] = "web"
    page = build_web_page()
    focus(rt, page.doc)
    d = build_dialog()
    focus(rt, d.ok)
    assert platform.config.profiles == ["web", None]
    assert obj(d.ok).app_module is not None
