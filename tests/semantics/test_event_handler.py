"""eventHandler: foco, janela, mudanças de estado/nome/valor, eco e cadeia de eventos."""

from __future__ import annotations

from collections.abc import Callable

from nvda_linux import services
from nvda_linux.appModules.appModuleHandler import AppModule
from nvda_linux.globalPlugins.globalPluginHandler import GlobalPlugin
from nvda_linux.NVDAObjects._atspi import RawEvent
from nvda_linux.NVDAObjects.base import LinuxNVDAObject
from nvda_linux.scripts.runtime import Runtime
from tests.semantics.conftest import Platform
from tests.semantics.fake_atspi import FakeAccessible, FakeValue
from tests.semantics.fakes import EchoingSpeech
from tests.semantics.helpers import event, focus, obj, press
from tests.semantics.pages import build_dialog

Next = Callable[[], None]


class ShellObject(FakeAccessible):
    """Objeto morto do gnome-shell: cada consulta remota faz o shell emitir outro
    ``state-changed:defunct`` (comportamento visto no GNOME 51 real)."""

    def __init__(self, rt: Runtime) -> None:
        super().__init__("LABEL", "relógio")
        self.rt = rt
        self.remote_calls = 0

    def _check(self) -> None:
        self.remote_calls += 1
        if self.remote_calls < 1000:  # trava de segurança do próprio teste
            event(self.rt, "object:state-changed:defunct", self, 1)
        raise RuntimeError("The application no longer exists")


def test_defunct_event_never_queries_the_dead_object(rt: Runtime) -> None:
    shell_obj = ShellObject(rt)
    event(rt, "object:state-changed:defunct", shell_obj, 1)
    assert shell_obj.remote_calls == 0  # sem consulta, sem ciclo


def test_defunct_event_forgets_cached_wrapper(rt: Runtime) -> None:
    d = build_dialog()
    wrapped = obj(d.ok)
    assert wrapped.name == "OK"
    d.ok.name = "Morto"
    event(rt, "object:state-changed:defunct", d.ok, 1)
    assert wrapped.name == "Morto"  # cache esquecido: o próximo acesso relê


def test_foreground_then_focus_speaks_window_once(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    event(rt, "window:activate", d.window)
    focus(rt, d.ok)
    assert platform.speech.utterances == [["Salvar como", "diálogo", "modal"],
                                          ["OK", "botão", "Alt+O"]]
    assert rt.focus.focus == obj(d.ok)
    assert rt.focus.navigator == obj(d.ok)
    assert rt.focus.focus_description() == "OK botão Alt+O"


def test_focus_ancestors_are_spoken_only_when_entered(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    event(rt, "window:activate", d.window)
    platform.speech.clear()
    focus(rt, d.entry)
    assert platform.speech.last == [
        "Opções", "Nome do arquivo", "caixa de edição", "multilinha", "relatorio.txt"]
    focus(rt, d.check)
    assert platform.speech.last == ["Sobrescrever", "caixa de seleção", "não marcado"]
    focus(rt, d.ok)
    assert platform.speech.last == ["OK", "botão", "Alt+O"]
    assert platform.braille.shown[-1][0] == "OK  botão  Alt+O"


def test_duplicate_stale_and_dead_focus_events_are_ignored(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.ok)
    count = len(platform.speech.utterances)
    event(rt, "object:state-changed:focused", d.ok, 1)  # duplicado
    event(rt, "focus:", d.ok)
    assert len(platform.speech.utterances) == count
    event(rt, "object:state-changed:focused", d.cancel, 1)  # sem estado FOCUSED: atrasado
    assert rt.focus.focus == obj(d.ok)
    d.cancel.kill()
    event(rt, "focus:", d.cancel)
    assert rt.focus.focus == obj(d.ok)
    event(rt, "object:state-changed:focused", d.ok, 0)  # perda de foco não fala
    assert len(platform.speech.utterances) == count


def test_coalescing_keeps_last_focus_and_deduplicates(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    for acc in (d.ok, d.cancel, d.check):
        acc.states.add("FOCUSED")
    assert rt.events is not None
    rt.events._queue.extend([
        RawEvent("object:state-changed:focused", d.ok, 1),
        RawEvent("object:property-change:accessible-name", d.check),
        RawEvent("object:state-changed:focused", d.cancel, 1),
        RawEvent("object:property-change:accessible-name", d.check),
        RawEvent("object:state-changed:focused", d.check, 1),
    ])
    rt.events.flush()
    assert rt.focus.focus == obj(d.check)
    spoken = platform.speech.text
    assert "OK" not in spoken and "Cancelar" not in spoken
    # Uma fala de foco + um único nameChange (deduplicado) do foco.
    assert platform.speech.utterances[-1] == ["Sobrescrever"]
    assert spoken.count("Sobrescrever") == 2


def test_state_name_and_value_changes_of_focus(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.check)
    d.check.states.add("CHECKED")
    event(rt, "object:state-changed:checked", d.check, 1)
    assert platform.speech.last == ["marcado"]
    d.check.states.discard("CHECKED")
    event(rt, "object:state-changed:checked", d.check, 0)
    assert platform.speech.last == ["não marcado"]
    d.ok.states.add("PRESSED")
    event(rt, "object:state-changed:pressed", d.ok, 1)  # não é o foco: silêncio
    assert platform.speech.last == ["não marcado"]
    d.check.name = "Substituir"
    event(rt, "object:property-change:accessible-name", d.check)
    assert platform.speech.last == ["Substituir"]
    slider = FakeAccessible("SLIDER", "Volume", value=FakeValue(3, 0, 10), extra_states=["FOCUSABLE"])
    d.group.add(slider)
    focus(rt, slider)
    assert slider.value is not None
    slider.value.current = 4
    event(rt, "object:value-changed", slider)
    assert platform.speech.last == ["4"]


def test_typed_character_and_word_echo(rt: Runtime, platform: Platform) -> None:
    platform.config.values["keyboard.speakTypedWords"] = True
    d = build_dialog()
    focus(rt, d.entry)
    for ch in "oi ":
        event(rt, "object:text-changed:insert", d.entry, 0, 1, ch)
    assert platform.speech.utterances[-4:] == [["o"], ["i"], ["espaço"], ["oi"]]
    focus(rt, d.password)
    event(rt, "object:text-changed:insert", d.password, 0, 1, "x")
    assert platform.speech.last == ["asterisco"]
    event(rt, "object:text-changed:insert", d.entry, 0, 1, "z")  # não é o foco
    assert platform.speech.last == ["asterisco"]


def test_platform_echo_disables_semantic_echo(rt: Runtime, platform: Platform) -> None:
    echo = EchoingSpeech()
    services.register("speech", echo)
    d = build_dialog()
    focus(rt, d.entry)
    echo.clear()
    event(rt, "object:text-changed:insert", d.entry, 0, 1, "a")
    assert echo.utterances == []
    focus(rt, d.password)
    assert rt.focus.focus_is_protected()


async def test_caret_scripts_wait_for_caret_event(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    focus(rt, d.entry)
    text = d.entry.text_iface
    assert text is not None

    def app_moves_caret(gesture: object) -> None:
        assert text is not None
        text.caret = text.text.index("segunda")
        event(rt, "object:text-caret-moved", d.entry, text.caret)

    platform.dispatcher.on_send = app_moves_caret
    platform.speech.clear()
    assert await press(rt, "kb:downarrow")
    assert platform.dispatcher.sent[-1].identifier == "kb:downarrow"
    assert platform.speech.last == ["segunda linha"]

    def app_moves_right(gesture: object) -> None:
        assert text is not None
        text.caret += 1
        event(rt, "object:text-caret-moved", d.entry, text.caret)

    platform.dispatcher.on_send = app_moves_right
    assert await press(rt, "kb:rightarrow")
    assert platform.speech.last == ["e"]
    text.selections = [(0, 0)]

    def app_selects(gesture: object) -> None:
        assert text is not None
        text.selections = [(text.caret, text.caret + 3)]

    platform.dispatcher.on_send = app_selects
    assert await press(rt, "kb:shift+rightarrow")
    assert platform.speech.last == ["egu", "selecionado"]


def test_event_chain_order_and_isolation(rt: Runtime, platform: Platform) -> None:
    calls: list[str] = []

    class Spy(GlobalPlugin):
        def event_gainFocus(self, obj: LinuxNVDAObject, next_handler: Next) -> None:
            calls.append("plugin")
            next_handler()

    class Broken(GlobalPlugin):
        def event_gainFocus(self, obj: LinuxNVDAObject, next_handler: Next) -> None:
            calls.append("broken")
            raise RuntimeError("bug no add-on")

    class Gedit(AppModule):
        def event_gainFocus(self, obj: LinuxNVDAObject, next_handler: Next) -> None:
            calls.append("app")
            if obj.name != "Cancelar":
                next_handler()

    rt.global_plugins.load(Spy, "test")
    rt.global_plugins.load(Broken, "test")
    rt.app_modules.register("gedit", Gedit, "test")
    d = build_dialog()
    focus(rt, d.ok)
    assert calls == ["plugin", "broken", "app"]
    # A exceção do plugin não impediu a fala (diálogo entrado + botão).
    assert platform.speech.last == ["Salvar como", "diálogo", "modal", "OK", "botão", "Alt+O"]
    platform.speech.clear()
    focus(rt, d.cancel)
    assert platform.speech.utterances == []  # o appModule consumiu o evento


def test_window_switch_allows_repeating_focus(rt: Runtime, platform: Platform) -> None:
    d = build_dialog()
    other = FakeAccessible("FRAME", "Outra janela")
    d.app.add(other)
    event(rt, "window:activate", d.window)
    focus(rt, d.ok)
    event(rt, "window:activate", other)
    event(rt, "window:activate", d.window)
    platform.speech.clear()
    event(rt, "focus:", d.ok)
    assert platform.speech.last == ["OK", "botão", "Alt+O"]


def test_active_descendant_becomes_focus(rt: Runtime, platform: Platform) -> None:
    items = [FakeAccessible("LIST_ITEM", n, extra_states=["SELECTABLE"]) for n in ("A", "B")]
    listbox = FakeAccessible("LIST_BOX", "Arquivos", children=items, extra_states=["FOCUSABLE"])
    d = build_dialog()
    d.group.add(listbox)
    focus(rt, listbox)
    event(rt, "object:active-descendant-changed", listbox, 0, 0, items[1])
    assert rt.focus.focus == obj(items[1])
    assert platform.speech.last == ["B", "2 de 2"]
