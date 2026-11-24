"""Browse Mode / Focus Mode numa página web falsa."""

from __future__ import annotations

import asyncio

import pytest

from nvda_linux.contracts import BROWSE_MODE_TONE, FOCUS_MODE_TONE
from nvda_linux.NVDAObjects.textInfos import TextUnit
from nvda_linux.scripts.runtime import Runtime
from nvda_linux.treeInterceptors.browseMode import BrowseModeTreeInterceptor
from nvda_linux.treeInterceptors.elementsList import ElementsListModel
from nvda_linux.treeInterceptors.virtualBuffer import (
    MSG_TRUNCATED_MISSING,
    MSG_TRUNCATED_PARTIAL,
)
from tests.semantics.conftest import Platform
from tests.semantics.fake_atspi import EMBED, FakeAccessible, container, hypertext
from tests.semantics.helpers import event, focus, obj, press
from tests.semantics.pages import WebPage, build_web_page, heading


def open_page(rt: Runtime, platform: Platform) -> tuple[WebPage, BrowseModeTreeInterceptor]:
    page = build_web_page()
    focus(rt, page.doc)
    ti = rt.tree_interceptors.get_for(obj(page.doc))
    assert isinstance(ti, BrowseModeTreeInterceptor)
    platform.speech.clear()
    return page, ti


async def say(rt: Runtime, platform: Platform, identifier: str, **kw: object) -> str:
    platform.speech.clear()
    assert await press(rt, identifier, **kw), identifier  # type: ignore[arg-type]
    return platform.speech.text


def test_page_load_announces_title_and_says_all(rt: Runtime, platform: Platform) -> None:
    page = build_web_page()
    focus(rt, page.doc)
    spoken = platform.speech.text
    assert spoken.startswith("Página de Teste documento")
    assert "Menu principal navegação ponto de referência lista com 3 itens link Início" in spoken
    assert "cabeçalho nível 1 Bem-vindo" in spoken
    assert "Leia as link visitado notícias de hoje." in spoken
    assert "tabela com 3 linhas e 2 colunas linha 1 coluna 1 Produto" in spoken
    assert "Fim da página." in spoken
    assert "em branco" not in spoken  # ler tudo pula linhas vazias


def test_label_equal_to_field_name_is_spoken_once() -> None:
    # Como o Firefox expõe <label>Nome <input></label>: o rótulo tem o texto
    # "Nome " e o campo dentro dele também se chama "Nome".
    entry = FakeAccessible("ENTRY", "Nome", text="", extra_states=["FOCUSABLE", "EDITABLE"])
    other = FakeAccessible("ENTRY", "Cidade", text="", extra_states=["FOCUSABLE", "EDITABLE"])
    doc = container(
        "DOCUMENT_WEB",
        hypertext("LABEL", "Nome ", entry),
        hypertext("PARAGRAPH", "Seu endereço: ", other),
        name="Formulário",
    )
    ti = BrowseModeTreeInterceptor(obj(doc))
    ti.build()
    text = ti.buffer.text

    def line(word: str) -> str:
        start, end = ti.buffer.unit_bounds(text.index(word), TextUnit.LINE)
        return " ".join(ti.speech_for_range(start, end, None))

    first = line("Nome")
    assert first.count("Nome") == 1 and "caixa de edição" in first
    assert line("Seu endereço").startswith("Seu endereço: Cidade caixa de edição")


@pytest.mark.parametrize("has_collection", [True, False])
async def test_large_page_warns_it_was_cut(
    rt: Runtime, platform: Platform, has_collection: bool
) -> None:
    platform.config.set("browseMode.maxNodes", 5)
    page = build_web_page()
    if not has_collection:
        page.doc.collection = None
    expected = MSG_TRUNCATED_PARTIAL if has_collection else MSG_TRUNCATED_MISSING
    focus(rt, page.doc)
    assert expected in platform.speech.text
    assert await say(rt, platform, "kb:nvda+f5") == f"Atualizado. {expected}"


def test_small_page_has_no_cut_warning(rt: Runtime, platform: Platform) -> None:
    focus(rt, build_web_page().doc)
    assert "Página muito grande" not in platform.speech.text


def test_busy_document_waits_for_load_complete(rt: Runtime, platform: Platform) -> None:
    page = build_web_page()
    page.doc.states.add("BUSY")
    focus(rt, page.doc)
    assert "Bem-vindo" not in platform.speech.text
    page.doc.states.discard("BUSY")
    event(rt, "object:state-changed:busy", page.doc, 0)
    assert "cabeçalho nível 1 Bem-vindo" in platform.speech.text


async def test_quick_navigation(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    assert "lista com 3 itens link Início" in await say(rt, platform, "kb:control+home")
    assert await say(rt, platform, "kb:h") == "fora da lista cabeçalho nível 1 Bem-vindo"
    assert await say(rt, platform, "kb:h") == "cabeçalho nível 2 Formulário"
    assert await say(rt, platform, "kb:shift+h") == "cabeçalho nível 1 Bem-vindo"
    assert await say(rt, platform, "kb:shift+h") == "Nenhum cabeçalho anterior"
    assert await say(rt, platform, "kb:3") == "Nenhum cabeçalho de nível 3 seguinte"
    assert await say(rt, platform, "kb:2") == "cabeçalho nível 2 Formulário"
    assert await say(rt, platform, "kb:f") == "Nome caixa de edição obrigatório"
    assert await say(rt, platform, "kb:x") == "Lembrar-me caixa de seleção não marcado"
    assert await say(rt, platform, "kb:b") == "botão Enviar"
    assert (await say(rt, platform, "kb:t")).startswith(
        "tabela com 3 linhas e 2 colunas linha 1 coluna 1 Produto")
    assert await say(rt, platform, "kb:g") == "fora da tabela gráfico Logotipo"
    assert await say(rt, platform, "kb:q") == "citação Quem lê, viaja."
    assert await say(rt, platform, "kb:shift+k") == "fora da citação link visitado notícias"
    nav_prefix = "Menu principal navegação ponto de referência lista com 3 itens"
    assert await say(rt, platform, "kb:shift+u") == f"{nav_prefix} link Contato"
    assert await say(rt, platform, "kb:control+end") == "fora da lista Fim da página."
    assert await say(rt, platform, "kb:shift+d") == f"{nav_prefix} link Início"
    assert await say(rt, platform, "kb:e") == "fora da lista Nome caixa de edição obrigatório"
    assert await say(rt, platform, "kb:shift+l") == f"{nav_prefix} link Início"
    assert await say(rt, platform, "kb:i") == "link Notícias"
    assert ti.caret == ti.buffer.text.index("Notícias")
    assert await say(rt, platform, "kb:shift+i") == "link Início"
    assert await say(rt, platform, "kb:l") == "Nenhuma lista seguinte"
    assert ti.caret == 0


async def test_line_character_and_word_navigation(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    await say(rt, platform, "kb:control+home")
    assert await say(rt, platform, "kb:downarrow") == "link Notícias"
    assert await say(rt, platform, "kb:downarrow") == "link Contato"
    assert await say(rt, platform, "kb:downarrow") == "fora da lista cabeçalho nível 1 Bem-vindo"
    assert await say(rt, platform, "kb:downarrow") == "Leia as link visitado notícias de hoje."
    assert await say(rt, platform, "kb:control+rightarrow") == "as"
    assert await say(rt, platform, "kb:rightarrow") == "s"
    assert await say(rt, platform, "kb:rightarrow") == "espaço"
    assert await say(rt, platform, "kb:home") == "L"
    assert await say(rt, platform, "kb:end") == "ponto"
    assert await say(rt, platform, "kb:uparrow") == "cabeçalho nível 1 Bem-vindo"
    await say(rt, platform, "kb:control+home")
    assert await say(rt, platform, "kb:uparrow") == (
        "início do documento | Menu principal navegação ponto de referência lista com 3 itens"
        " link Início")
    assert "Fim da página." in await say(rt, platform, "kb:control+end")
    assert (await say(rt, platform, "kb:downarrow")).startswith("fim do documento")
    assert ti.caret == ti.buffer.text.index("Fim da página.")


async def test_table_navigation(rt: Runtime, platform: Platform) -> None:
    _page, _ti = open_page(rt, platform)
    await say(rt, platform, "kb:control+home")
    assert await say(rt, platform, "kb:control+alt+downarrow") == "Não está em uma tabela"
    await say(rt, platform, "kb:t")
    assert await say(rt, platform, "kb:control+alt+downarrow") == "linha 2 Café"
    assert await say(rt, platform, "kb:control+alt+rightarrow") == "Preço coluna 2 R$ 5"
    assert await say(rt, platform, "kb:control+alt+rightarrow") == "borda da tabela"
    assert await say(rt, platform, "kb:control+alt+downarrow") == "linha 3 R$ 1"
    assert await say(rt, platform, "kb:control+alt+leftarrow") == "Produto coluna 1 Pão"
    assert await say(rt, platform, "kb:control+alt+uparrow") == "linha 2 Café"


async def test_auto_focus_mode_and_tones(rt: Runtime, platform: Platform) -> None:
    page, ti = open_page(rt, platform)
    focus(rt, page.entry)
    assert ti.pass_through
    assert platform.tones.beeps[-1] == FOCUS_MODE_TONE
    assert "Nome caixa de edição obrigatório" in platform.speech.text
    assert ti.caret == ti.buffer.node_for(obj(page.entry)).start  # type: ignore[union-attr]
    # No modo de foco, as setas vão ao campo (script do EditableText, que repassa a tecla).
    assert await press(rt, "kb:downarrow")
    assert platform.dispatcher.sent[-1].identifier == "kb:downarrow"
    assert not await press(rt, "kb:h")  # sem navegação rápida no modo de foco
    focus(rt, page.button)
    assert not ti.pass_through
    assert platform.tones.beeps[-1] == BROWSE_MODE_TONE
    assert await press(rt, "kb:h")


async def test_manual_mode_toggle_and_escape(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    assert not await press(rt, "kb:escape")  # Esc no modo de navegação vai ao aplicativo
    assert await press(rt, "kb:nvda+space")
    assert ti.pass_through and platform.tones.beeps[-1] == FOCUS_MODE_TONE
    assert await press(rt, "kb:nvda+space")
    assert not ti.pass_through and platform.tones.beeps[-1] == BROWSE_MODE_TONE
    await press(rt, "kb:nvda+space")
    assert await press(rt, "kb:escape")
    assert not ti.pass_through
    platform.config.values["browseMode.passThroughAudioIndication"] = False
    await say(rt, platform, "kb:nvda+space")
    assert platform.speech.text == "modo de foco"


async def test_activation(rt: Runtime, platform: Platform) -> None:
    page, ti = open_page(rt, platform)
    await say(rt, platform, "kb:control+home")
    await say(rt, platform, "kb:k")
    assert await press(rt, "kb:enter")
    assert page.links[1].action is not None and page.links[1].action.performed == [0]
    await say(rt, platform, "kb:x")
    platform.speech.clear()
    assert await press(rt, "kb:space")
    await asyncio.sleep(0.2)
    assert "CHECKED" in page.checkbox.states
    assert platform.speech.text == "marcado"
    await say(rt, platform, "kb:shift+e")
    assert await press(rt, "kb:enter")
    assert page.entry.focus_requests == 1 and ti.pass_through


async def test_trap_and_single_letter_navigation(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    assert await press(rt, "kb:z", character="z")  # engolida
    assert platform.speech.utterances == []
    assert await say(rt, platform, "kb:nvda+shift+space") == "Navegação por letra única desativada"
    assert not await press(rt, "kb:h", character="h")
    assert not await press(rt, "kb:z", character="z")
    await press(rt, "kb:nvda+shift+space")
    assert await press(rt, "kb:h", character="h")
    platform.config.values["browseMode.trapNonCommandGestures"] = False
    assert not await press(rt, "kb:z", character="z")
    assert ti.single_letter_navigation


async def test_elements_list_model_and_fallback(rt: Runtime, platform: Platform) -> None:
    page, ti = open_page(rt, platform)
    summary = await say(rt, platform, "kb:nvda+f7")
    assert summary == ("Lista de elementos: 4 links, 3 cabeçalhos, 3 campos de formulário, "
                       "1 botão, 1 ponto de referência")
    model = ElementsListModel(ti)
    headings = model.items("heading")
    assert [(h.label, h.depth) for h in headings] == [
        ("Bem-vindo", 0), ("Formulário", 1), ("Tabela de preços", 1)]
    assert [i.label for i in model.items("link", "not")] == ["Notícias", "notícias"]
    assert model.items("formField")[0].label == "Nome caixa de edição"
    assert model.items("landmark")[0].label == "Menu principal navegação ponto de referência"
    platform.speech.clear()
    model.move_to(headings[2])
    assert platform.speech.text == "cabeçalho nível 2 Tabela de preços"
    model.activate(model.items("link")[2])
    assert page.links[2].action is not None and page.links[2].action.performed == [0]


def test_incremental_update_from_events(rt: Runtime, platform: Platform) -> None:
    page, ti = open_page(rt, platform)
    new_heading = heading(3, "Novidade")
    page.doc.add(new_heading, index=2)
    assert page.doc.text_iface is not None
    page.doc.text_iface.text = EMBED * len(page.doc.children)
    event(rt, "object:children-changed:add", page.doc, 2, 0, new_heading)
    texts = [ti.buffer.text[n.start:n.end] for n in ti.buffer.nodes_of_kind("heading")]
    assert texts == ["Bem-vindo", "Novidade", "Formulário", "Tabela de preços"]
    assert page.quote.text_iface is not None
    page.quote.text_iface.text = "Quem lê, viaja muito."
    event(rt, "object:text-changed:insert", page.quote, 14, 6, " muito")
    assert "Quem lê, viaja muito." in ti.buffer.text


def test_live_region_is_announced(rt: Runtime, platform: Platform) -> None:
    page, _ti = open_page(rt, platform)
    live = hypertext("SECTION", "", attributes={"container-live": "polite"})
    page.doc.add(live)
    assert live.text_iface is not None
    live.text_iface.text = "3 novas mensagens"
    event(rt, "object:text-changed:insert", live, 0, 17, "3 novas mensagens")
    assert "3 novas mensagens" in platform.speech.text


async def test_say_all_and_current_line(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    await say(rt, platform, "kb:control+home")
    await say(rt, platform, "kb:h")
    assert await say(rt, platform, "kb:nvda+uparrow") == "cabeçalho nível 1 Bem-vindo"
    await press(rt, "kb:nvda+uparrow", repeat=1)
    assert platform.speech.spelled[-1] == "Bem-vindo"
    spoken = await say(rt, platform, "kb:nvda+downarrow")
    assert spoken.startswith("cabeçalho nível 1 Bem-vindo") and spoken.endswith("Fim da página.")
    assert ti.caret == ti.buffer.text.index("Fim da página.")


def test_focus_outside_document_has_no_tree_interceptor(rt: Runtime, platform: Platform) -> None:
    page = build_web_page()
    focus(rt, page.url_bar)
    assert rt.tree_interceptors.get_for(obj(page.url_bar)) is None
    assert "Navegação barra de ferramentas Endereço caixa de edição" in platform.speech.text


def test_review_cursor_follows_virtual_buffer(rt: Runtime, platform: Platform) -> None:
    _page, ti = open_page(rt, platform)
    review = rt.focus.review
    assert review is not None and review.backend.length() == len(ti.buffer.text)


@pytest.mark.parametrize("enabled", [False])
def test_browse_mode_disabled_on_load(rt: Runtime, platform: Platform, enabled: bool) -> None:
    platform.config.values["browseMode.enableOnPageLoad"] = enabled
    page = build_web_page()
    focus(rt, page.doc)
    ti = rt.tree_interceptors.get_for(obj(page.doc))
    assert ti is not None and ti.pass_through


async def test_braille_routing(rt: Runtime, platform: Platform) -> None:
    page, ti = open_page(rt, platform)
    await say(rt, platform, "kb:control+home")
    await say(rt, platform, "kb:h")
    await say(rt, platform, "kb:downarrow")  # "Leia as notícias de hoje."
    text, cursor = platform.braille.shown[-1]
    assert text == "Leia as notícias de hoje." and cursor == 0
    assert await press(rt, "br(brltty):routing", routing_index=10, text_offset=10)
    assert page.news_link.action is not None and page.news_link.action.performed == [0]
    platform.speech.clear()
    assert await press(rt, "br(brltty):routing", routing_index=2, text_offset=2)
    assert platform.speech.text == "i"
    assert ti.caret == ti.buffer.text.index("Leia") + 2


def test_mode_changes_refresh_keyboard_grabs(rt: Runtime, platform: Platform) -> None:
    from nvda_linux import services
    from tests.semantics.fakes import GrabbingDispatcher

    dispatcher = GrabbingDispatcher()
    services.register("dispatcher", dispatcher)
    page = build_web_page()
    focus(rt, page.doc)
    before = dispatcher.refreshes
    focus(rt, page.entry)  # foco + modo de foco automático
    assert dispatcher.refreshes >= before + 2
