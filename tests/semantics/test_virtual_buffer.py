"""VirtualBuffer: renderização, índices por tipo, tabelas e atualização incremental."""

from __future__ import annotations

from nvda_linux.NVDAObjects.controlTypes import Role
from nvda_linux.NVDAObjects.textInfos import TextUnit
from nvda_linux.treeInterceptors.virtualBuffer import (
    MSG_TRUNCATED_MISSING,
    MSG_TRUNCATED_PARTIAL,
    VirtualBuffer,
)
from tests.semantics.fake_atspi import FakeAccessible, container, hypertext
from tests.semantics.helpers import obj
from tests.semantics.pages import build_web_page, heading


def built(page_doc: FakeAccessible, **kwargs: int) -> VirtualBuffer:
    buffer = VirtualBuffer(obj(page_doc), **kwargs)
    buffer.build()
    return buffer


def line_at(buffer: VirtualBuffer, offset: int) -> str:
    start, end = buffer.unit_bounds(offset, TextUnit.LINE)
    return buffer.text[start:end].rstrip("\n")


def test_render_blocks_inline_links_and_controls() -> None:
    page = build_web_page()
    buffer = built(page.doc)
    lines = buffer.text.split("\n")
    assert lines[:5] == ["Início", "Notícias", "Contato", "Bem-vindo", "Leia as notícias de hoje."]
    assert "  Enviar" in lines  # campo e caixa de seleção vazios ocupam um espaço
    assert ["Produto", "Preço", "Café", "R$ 5", "Pão", "R$ 1"] == lines[8:14]
    link = buffer.node_for(obj(page.news_link))
    assert link is not None and buffer.text[link.start:link.end] == "notícias"
    paragraph = buffer.node_for(obj(page.intro))
    assert paragraph is not None and paragraph.start < link.start < link.end < paragraph.end


def test_kind_index_and_bisect_navigation() -> None:
    buffer = built(build_web_page().doc)
    headings = [buffer.text[n.start:n.end] for n in buffer.nodes_of_kind("heading")]
    assert headings == ["Bem-vindo", "Formulário", "Tabela de preços"]
    first = buffer.next_of_kind("heading", 0)
    assert first is not None and first.level == 1
    second = buffer.next_of_kind("heading", first.start)
    assert second is not None and buffer.text[second.start:second.end] == "Formulário"
    back = buffer.next_of_kind("heading", second.start, forward=False)
    assert back is first
    assert buffer.next_of_kind("heading", first.start, forward=False) is None
    assert buffer.next_of_kind("heading2", 0) is second
    assert len(buffer.nodes_of_kind("link")) == 4
    assert len(buffer.nodes_of_kind("visitedLink")) == 1
    assert {n.role for n in buffer.nodes_of_kind("formField")} == {
        Role.EDITABLETEXT, Role.CHECKBOX, Role.BUTTON}
    assert buffer.nodes_of_kind("landmark")[0].landmark == "navigation"
    assert buffer.nodes_of_kind("list")[0].item_count == 3
    assert buffer.nodes_of_kind("graphic")[0].name == "Logotipo"
    assert buffer.kinds_present() >= {"table", "button", "edit", "blockQuote", "listItem"}


def test_tables_and_ancestors() -> None:
    page = build_web_page()
    buffer = built(page.doc)
    table_node = buffer.nodes_of_kind("table")[0]
    info = buffer.tables[table_node.index]
    assert (info.rows, info.cols) == (3, 2)
    cafe = buffer.text.index("Café")
    cell = buffer.cell_at(cafe)
    assert cell is not None and (cell.row, cell.col) == (2, 1)
    chain = [buffer.nodes[i].role for i in buffer.ancestors_at(cafe)]
    assert chain[:3] == [Role.DOCUMENT, Role.TABLE, Role.TABLEROW]
    assert buffer.cell_at(0) is None


def test_colspan_cells() -> None:
    rows = [
        FakeAccessible("TABLE_ROW", children=[hypertext("TABLE_CELL", "Largo",
                                                         attributes={"colspan": "2"})]),
        FakeAccessible("TABLE_ROW", children=[hypertext("TABLE_CELL", "A"),
                                              hypertext("TABLE_CELL", "B")]),
    ]
    doc = container("DOCUMENT_WEB", FakeAccessible("TABLE", children=rows))
    buffer = built(doc)
    info = next(iter(buffer.tables.values()))
    assert info.cells[(1, 1)] == info.cells[(1, 2)]
    assert (info.rows, info.cols) == (2, 2)


def test_line_wrapping() -> None:
    long_text = " ".join(["palavra"] * 40)
    doc = container("DOCUMENT_WEB", hypertext("PARAGRAPH", long_text))
    buffer = built(doc, max_line_length=30)
    assert len(buffer.line_starts) > 5
    assert all(len(line_at(buffer, s)) <= 30 for s in buffer.line_starts)


def test_incremental_update_shifts_following_nodes() -> None:
    page = build_web_page()
    buffer = built(page.doc)
    before_heading = buffer.next_of_kind("heading", buffer.text.index("Leia"))
    assert before_heading is not None
    old_start = before_heading.start
    text = page.intro.text_iface
    assert text is not None
    text.text = text.text.replace("de hoje", "de ontem e de hoje")
    assert buffer.update_subtree(obj(page.intro))
    assert "Leia as notícias de ontem e de hoje." in buffer.text
    moved = buffer.next_of_kind("heading", buffer.text.index("Leia"))
    assert moved is not None and moved.start == old_start + len("ontem e de ")
    assert buffer.text[moved.start:moved.end] == "Formulário"
    root = buffer.nodes[0]
    assert root.end == len(buffer.text) - 1 or root.end == len(buffer.text)
    # Inserção de um filho novo dentro de um contêiner.
    new_item = container("LIST_ITEM", hypertext("LINK", "Blog", extra_states=["FOCUSABLE"]))
    page.nav_list.add(new_item)
    obj(page.nav_list).invalidate_cache()
    assert buffer.update_subtree(obj(page.nav_list))
    assert buffer.nodes_of_kind("list")[0].item_count == 4
    assert [buffer.text[n.start:n.end] for n in buffer.nodes_of_kind("link")][:4] == [
        "Início", "Notícias", "Contato", "Blog"]
    assert [buffer.text[n.start:n.end] for n in buffer.nodes_of_kind("heading")] == [
        "Bem-vindo", "Formulário", "Tabela de preços"]
    # Raiz ou célula de tabela pedem reconstrução completa.
    assert not buffer.update_subtree(obj(page.doc))


def test_truncated_page_appends_collection_matches() -> None:
    headings = [heading(2, f"Seção {i}") for i in range(30)]
    doc = container("DOCUMENT_WEB", *headings)
    buffer = built(doc, max_nodes=10)
    assert buffer.truncated
    texts = [buffer.text[n.start:n.end] for n in buffer.nodes_of_kind("heading")]
    assert texts[0] == "Seção 0" and texts[-1] == "Seção 29" and len(texts) == 30
    assert doc.collection is not None and doc.collection.calls == 1
    assert not buffer.collection_failed
    assert buffer.truncation_notice() == MSG_TRUNCATED_PARTIAL


def test_truncated_page_without_collection_reports_missing_content() -> None:
    doc = container("DOCUMENT_WEB", *[heading(2, f"Seção {i}") for i in range(30)])
    doc.collection = None
    buffer = built(doc, max_nodes=10)
    texts = [buffer.text[n.start:n.end] for n in buffer.nodes_of_kind("heading")]
    assert buffer.truncated and buffer.collection_failed
    assert "Seção 29" not in texts
    assert buffer.truncation_notice() == MSG_TRUNCATED_MISSING


def test_small_page_has_no_truncation_notice() -> None:
    buffer = built(build_web_page().doc)
    assert not buffer.truncated and buffer.truncation_notice() is None
