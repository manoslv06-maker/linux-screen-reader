"""Árvores falsas usadas nos testes: página web, diálogo GTK e terminal."""

from __future__ import annotations

from dataclasses import dataclass

from tests.semantics.fake_atspi import (
    FakeAccessible,
    FakeDesktop,
    FakeTable,
    FakeValue,
    app,
    container,
    hypertext,
)

FOCUSABLE = ("FOCUSABLE",)


@dataclass
class WebPage:
    desktop: FakeDesktop
    app: FakeAccessible
    frame: FakeAccessible
    doc: FakeAccessible
    nav: FakeAccessible
    nav_list: FakeAccessible
    links: list[FakeAccessible]
    h1: FakeAccessible
    intro: FakeAccessible
    news_link: FakeAccessible
    entry: FakeAccessible
    checkbox: FakeAccessible
    button: FakeAccessible
    table: FakeAccessible
    image: FakeAccessible
    quote: FakeAccessible
    footer: FakeAccessible
    url_bar: FakeAccessible


def link(name: str, visited: bool = False) -> FakeAccessible:
    states = ["FOCUSABLE"] + (["VISITED"] if visited else [])
    return hypertext("LINK", name, extra_states=states, actions=["jump"])


def heading(level: int, text: str) -> FakeAccessible:
    return hypertext("HEADING", text, attributes={"level": str(level)})


def cell(role: str, text: str) -> FakeAccessible:
    return hypertext(role, text)


def build_web_page(app_name: str = "Firefox") -> WebPage:
    """Página com landmark, lista de links, cabeçalhos, formulário, tabela etc."""
    links = [link("Início"), link("Notícias"), link("Contato")]
    items = [container("LIST_ITEM", lnk) for lnk in links]
    nav_list = FakeAccessible("LIST", children=items)
    nav = container(
        "LANDMARK", nav_list, name="Menu principal", attributes={"xml-roles": "navigation"}
    )
    h1 = heading(1, "Bem-vindo")
    news_link = link("notícias", visited=True)
    intro = hypertext("PARAGRAPH", "Leia as ", news_link, " de hoje.")
    h2_form = heading(2, "Formulário")
    entry = FakeAccessible(
        "ENTRY",
        "Nome",
        text="",
        extra_states=["FOCUSABLE", "EDITABLE", "SINGLE_LINE"],
        attributes={"required": "true"},
    )
    entry.states.add("REQUIRED")
    checkbox = FakeAccessible("CHECK_BOX", "Lembrar-me", extra_states=FOCUSABLE, actions=["click"])

    def toggle(acc: FakeAccessible) -> None:
        acc.states ^= {"CHECKED"}

    checkbox.on_action = toggle
    button = hypertext("PUSH_BUTTON", "Enviar", extra_states=FOCUSABLE, actions=["press"])
    form = container("FORM", entry, checkbox, button)
    h2_table = heading(2, "Tabela de preços")
    rows = [
        FakeAccessible("TABLE_ROW", children=[cell("COLUMN_HEADER", "Produto"),
                                              cell("COLUMN_HEADER", "Preço")]),
        FakeAccessible("TABLE_ROW", children=[cell("TABLE_CELL", "Café"),
                                              cell("TABLE_CELL", "R$ 5")]),
        FakeAccessible("TABLE_ROW", children=[cell("TABLE_CELL", "Pão"),
                                              cell("TABLE_CELL", "R$ 1")]),
    ]
    table = FakeAccessible("TABLE", children=rows, table=FakeTable(3, 2))
    image = FakeAccessible("IMAGE", "Logotipo")
    quote = hypertext("BLOCK_QUOTE", "Quem lê, viaja.")
    footer = hypertext("PARAGRAPH", "Fim da página.")
    doc = container(
        "DOCUMENT_WEB",
        nav,
        h1,
        intro,
        h2_form,
        form,
        h2_table,
        table,
        image,
        quote,
        footer,
        name="Página de Teste",
        extra_states=["FOCUSABLE", "READ_ONLY"],
    )
    url_bar = FakeAccessible(
        "ENTRY", "Endereço", text="https://exemplo.org",
        extra_states=["FOCUSABLE", "EDITABLE", "SINGLE_LINE"],
    )
    toolbar = FakeAccessible("TOOL_BAR", "Navegação", children=[url_bar])
    frame = FakeAccessible(
        "FRAME", "Página de Teste — Mozilla Firefox", children=[toolbar, doc],
        extra_states=["ACTIVE"],
    )
    application = app(app_name, frame, pid=1001)
    desktop = FakeDesktop()
    desktop.add_app(application)
    return WebPage(
        desktop, application, frame, doc, nav, nav_list, links, h1, intro, news_link,
        entry, checkbox, button, table, image, quote, footer, url_bar,
    )


@dataclass
class Dialog:
    desktop: FakeDesktop
    app: FakeAccessible
    window: FakeAccessible
    panel: FakeAccessible
    group: FakeAccessible
    ok: FakeAccessible
    cancel: FakeAccessible
    check: FakeAccessible
    entry: FakeAccessible
    password: FakeAccessible
    progress: FakeAccessible
    status: FakeAccessible
    menu_item: FakeAccessible


def build_dialog() -> Dialog:
    """Diálogo GTK: painéis de leiaute sem nome, agrupamento, botões, campo."""
    entry = FakeAccessible(
        "TEXT", "Nome do arquivo", text="relatorio.txt\nsegunda linha",
        extra_states=["FOCUSABLE", "EDITABLE", "MULTI_LINE"],
    )
    password = FakeAccessible(
        "PASSWORD_TEXT", "Senha", text="", extra_states=["FOCUSABLE", "EDITABLE"]
    )
    check = FakeAccessible("CHECK_BOX", "Sobrescrever", extra_states=FOCUSABLE, actions=["toggle"])
    group = FakeAccessible("PANEL", "Opções", children=[entry, password, check])
    ok = FakeAccessible("PUSH_BUTTON", "OK", extra_states=FOCUSABLE, actions=["click"],
                        key_binding="o;;<Alt>o")
    cancel = FakeAccessible("PUSH_BUTTON", "Cancelar", extra_states=FOCUSABLE, actions=["click"])
    buttons = FakeAccessible("FILLER", children=[ok, cancel])
    panel = FakeAccessible("PANEL", children=[group, buttons])
    progress = FakeAccessible("PROGRESS_BAR", "Progresso", value=FakeValue(30, 0, 60))
    status_label = FakeAccessible("LABEL", "Pronto")
    status = FakeAccessible("STATUS_BAR", "", children=[status_label])
    menu_item = FakeAccessible("MENU_ITEM", "Abrir", actions=["click"], key_binding="a;;<Control>o")
    menu = FakeAccessible("MENU", "Arquivo", children=[menu_item, FakeAccessible("MENU_ITEM", "Salvar")])
    window = FakeAccessible("DIALOG", "Salvar como", children=[panel, progress, status, menu],
                            extra_states=["ACTIVE", "MODAL"])
    application = app("gedit", window, pid=2002)
    desktop = FakeDesktop()
    desktop.add_app(application)
    return Dialog(desktop, application, window, panel, group, ok, cancel, check, entry, password,
                  progress, status, menu_item)


@dataclass
class TerminalApp:
    desktop: FakeDesktop
    app: FakeAccessible
    window: FakeAccessible
    terminal: FakeAccessible


def build_terminal() -> TerminalApp:
    terminal = FakeAccessible(
        "TERMINAL", "Terminal", text="$ ", extra_states=["FOCUSABLE", "EDITABLE"]
    )
    window = FakeAccessible("FRAME", "usuario@host: ~", children=[terminal], extra_states=["ACTIVE"])
    application = app("gnome-terminal-server", window, pid=3003)
    desktop = FakeDesktop()
    desktop.add_app(application)
    return TerminalApp(desktop, application, window, terminal)
