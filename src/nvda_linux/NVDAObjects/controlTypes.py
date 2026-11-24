# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Papéis, estados e motivos de saída no estilo do ``controlTypes`` do NVDA.

Os nomes dos membros seguem o NVDA (``Role.EDITABLETEXT``, ``State.CHECKED``)
para que add-ons escritos para o NVDA sejam fáceis de portar. Os rótulos
falados estão em português do Brasil.
"""

from __future__ import annotations

from enum import Enum, IntEnum, auto


class Role(IntEnum):
    """Papel de um objeto, independente da API de acessibilidade."""

    UNKNOWN = 0
    WINDOW = auto()
    TITLEBAR = auto()
    PANE = auto()
    DIALOG = auto()
    CHECKBOX = auto()
    RADIOBUTTON = auto()
    STATICTEXT = auto()
    EDITABLETEXT = auto()
    BUTTON = auto()
    MENUBAR = auto()
    MENUITEM = auto()
    POPUPMENU = auto()
    COMBOBOX = auto()
    LIST = auto()
    LISTITEM = auto()
    GRAPHIC = auto()
    HELPBALLOON = auto()
    TOOLTIP = auto()
    LINK = auto()
    TREEVIEW = auto()
    TREEVIEWITEM = auto()
    TAB = auto()
    TABCONTROL = auto()
    SLIDER = auto()
    PROGRESSBAR = auto()
    SCROLLBAR = auto()
    STATUSBAR = auto()
    TABLE = auto()
    TABLECELL = auto()
    TABLECOLUMN = auto()
    TABLEROW = auto()
    TABLECOLUMNHEADER = auto()
    TABLEROWHEADER = auto()
    FRAME = auto()
    TOOLBAR = auto()
    DROPDOWNBUTTON = auto()
    CLOCK = auto()
    SEPARATOR = auto()
    FORM = auto()
    HEADING = auto()
    PARAGRAPH = auto()
    BLOCKQUOTE = auto()
    DOCUMENT = auto()
    ANIMATION = auto()
    APPLICATION = auto()
    GROUPING = auto()
    CANVAS = auto()
    CAPTION = auto()
    CHECKMENUITEM = auto()
    DATEEDITOR = auto()
    ICON = auto()
    DIRECTORYPANE = auto()
    EMBEDDEDOBJECT = auto()
    FOOTER = auto()
    FOOTNOTE = auto()
    GLASSPANE = auto()
    HEADER = auto()
    IMAGEMAP = auto()
    INPUTWINDOW = auto()
    LABEL = auto()
    PAGE = auto()
    RADIOMENUITEM = auto()
    LAYEREDPANE = auto()
    REDUNDANTOBJECT = auto()
    ROOTPANE = auto()
    EDITBAR = auto()
    TERMINAL = auto()
    RULER = auto()
    SCROLLPANE = auto()
    SECTION = auto()
    SPLITPANE = auto()
    VIEWPORT = auto()
    TEAROFFMENU = auto()
    TOGGLEBUTTON = auto()
    CHART = auto()
    DIAL = auto()
    MENUBUTTON = auto()
    MATH = auto()
    SPINBUTTON = auto()
    DESKTOPICON = auto()
    INTERNALFRAME = auto()
    DESKTOPPANE = auto()
    OPTIONPANE = auto()
    COLORCHOOSER = auto()
    FILECHOOSER = auto()
    FILLER = auto()
    MENU = auto()
    PANEL = auto()
    PASSWORDEDIT = auto()
    FONTCHOOSER = auto()
    ALERT = auto()
    CALENDAR = auto()
    VIDEO = auto()
    AUDIO = auto()
    DELETED_CONTENT = auto()
    INSERTED_CONTENT = auto()
    LANDMARK = auto()
    ARTICLE = auto()
    REGION = auto()
    FIGURE = auto()
    MARKED_CONTENT = auto()
    COMMENT = auto()
    SUGGESTION = auto()
    DEFINITION = auto()
    SUBSCRIPT = auto()
    SUPERSCRIPT = auto()
    SWITCH = auto()
    INFOBAR = auto()

    @property
    def display_string(self) -> str:
        """Rótulo falado do papel (vazio para papéis que não são anunciados)."""
        return ROLE_LABELS.get(self, "")


class State(Enum):
    """Estado de um objeto. Os objetos expõem ``frozenset[State]``."""

    UNAVAILABLE = auto()
    FOCUSED = auto()
    SELECTED = auto()
    BUSY = auto()
    PRESSED = auto()
    CHECKED = auto()
    HALFCHECKED = auto()
    READONLY = auto()
    EXPANDED = auto()
    COLLAPSED = auto()
    INVISIBLE = auto()
    VISITED = auto()
    LINKED = auto()
    HASPOPUP = auto()
    PROTECTED = auto()
    REQUIRED = auto()
    DEFUNCT = auto()
    INVALID_ENTRY = auto()
    MODAL = auto()
    AUTOCOMPLETE = auto()
    MULTILINE = auto()
    ICONIFIED = auto()
    OFFSCREEN = auto()
    SELECTABLE = auto()
    FOCUSABLE = auto()
    CLICKABLE = auto()
    EDITABLE = auto()
    CHECKABLE = auto()
    SORTED_ASCENDING = auto()
    SORTED_DESCENDING = auto()
    MULTISELECTABLE = auto()
    ON = auto()

    @property
    def display_string(self) -> str:
        return STATE_LABELS.get(self, "")


class OutputReason(Enum):
    """Por que um objeto está sendo falado (``controlTypes.OutputReason``)."""

    FOCUS = auto()
    FOCUSENTERED = auto()
    QUERY = auto()
    CHANGE = auto()
    MESSAGE = auto()
    SAYALL = auto()
    CARET = auto()
    QUICKNAV = auto()
    ONLYCACHE = auto()


ROLE_LABELS: dict[Role, str] = {
    Role.WINDOW: "janela",
    Role.TITLEBAR: "barra de título",
    Role.PANE: "painel",
    Role.DIALOG: "diálogo",
    Role.CHECKBOX: "caixa de seleção",
    Role.RADIOBUTTON: "botão de opção",
    Role.EDITABLETEXT: "caixa de edição",
    Role.BUTTON: "botão",
    Role.MENUBAR: "barra de menus",
    Role.MENUITEM: "item de menu",
    Role.POPUPMENU: "menu",
    Role.COMBOBOX: "caixa de combinação",
    Role.LIST: "lista",
    Role.LISTITEM: "item de lista",
    Role.GRAPHIC: "gráfico",
    Role.HELPBALLOON: "balão de ajuda",
    Role.TOOLTIP: "dica de ferramenta",
    Role.LINK: "link",
    Role.TREEVIEW: "visualização em árvore",
    Role.TREEVIEWITEM: "item de árvore",
    Role.TAB: "guia",
    Role.TABCONTROL: "controle de guias",
    Role.SLIDER: "controle deslizante",
    Role.PROGRESSBAR: "barra de progresso",
    Role.SCROLLBAR: "barra de rolagem",
    Role.STATUSBAR: "barra de status",
    Role.TABLE: "tabela",
    Role.TABLECELL: "célula",
    Role.TABLECOLUMN: "coluna",
    Role.TABLEROW: "linha",
    Role.TABLECOLUMNHEADER: "cabeçalho de coluna",
    Role.TABLEROWHEADER: "cabeçalho de linha",
    Role.FRAME: "quadro",
    Role.TOOLBAR: "barra de ferramentas",
    Role.DROPDOWNBUTTON: "botão suspenso",
    Role.CLOCK: "relógio",
    Role.SEPARATOR: "separador",
    Role.FORM: "formulário",
    Role.HEADING: "cabeçalho",
    Role.BLOCKQUOTE: "citação",
    Role.DOCUMENT: "documento",
    Role.ANIMATION: "animação",
    Role.GROUPING: "agrupamento",
    Role.CANVAS: "tela de desenho",
    Role.CAPTION: "legenda",
    Role.CHECKMENUITEM: "item de menu de seleção",
    Role.DATEEDITOR: "editor de data",
    Role.ICON: "ícone",
    Role.DIRECTORYPANE: "painel de diretório",
    Role.EMBEDDEDOBJECT: "objeto embutido",
    Role.FOOTER: "rodapé",
    Role.FOOTNOTE: "nota de rodapé",
    Role.HEADER: "cabeçalho de página",
    Role.IMAGEMAP: "mapa de imagem",
    Role.INPUTWINDOW: "janela de entrada",
    Role.PAGE: "página",
    Role.RADIOMENUITEM: "item de menu de opção",
    Role.EDITBAR: "barra de edição",
    Role.TERMINAL: "terminal",
    Role.RULER: "régua",
    Role.SPLITPANE: "painel dividido",
    Role.TEAROFFMENU: "menu destacável",
    Role.TOGGLEBUTTON: "botão de alternância",
    Role.CHART: "gráfico de dados",
    Role.DIAL: "seletor giratório",
    Role.MENUBUTTON: "botão de menu",
    Role.MATH: "matemática",
    Role.SPINBUTTON: "botão giratório",
    Role.DESKTOPICON: "ícone da área de trabalho",
    Role.INTERNALFRAME: "quadro interno",
    Role.DESKTOPPANE: "área de trabalho",
    Role.OPTIONPANE: "painel de opções",
    Role.COLORCHOOSER: "seletor de cores",
    Role.FILECHOOSER: "seletor de arquivos",
    Role.MENU: "menu",
    Role.PASSWORDEDIT: "caixa de edição de senha",
    Role.FONTCHOOSER: "seletor de fontes",
    Role.ALERT: "alerta",
    Role.CALENDAR: "calendário",
    Role.VIDEO: "vídeo",
    Role.AUDIO: "áudio",
    Role.DELETED_CONTENT: "excluído",
    Role.INSERTED_CONTENT: "inserido",
    Role.LANDMARK: "ponto de referência",
    Role.ARTICLE: "artigo",
    Role.REGION: "região",
    Role.FIGURE: "figura",
    Role.MARKED_CONTENT: "destacado",
    Role.COMMENT: "comentário",
    Role.SUGGESTION: "sugestão",
    Role.DEFINITION: "definição",
    Role.SWITCH: "interruptor",
    Role.INFOBAR: "barra de informações",
}

#: Rótulos usados só quando um objeto de papel silencioso não tem mais nada a falar.
FALLBACK_ROLE_LABELS: dict[Role, str] = {
    Role.UNKNOWN: "desconhecido",
    Role.STATICTEXT: "texto",
    Role.PARAGRAPH: "parágrafo",
    Role.SECTION: "seção",
    Role.FILLER: "preenchimento",
    Role.PANEL: "painel",
    Role.REDUNDANTOBJECT: "objeto redundante",
    Role.ROOTPANE: "painel raiz",
    Role.LAYEREDPANE: "painel em camadas",
    Role.SCROLLPANE: "painel de rolagem",
    Role.VIEWPORT: "área de visualização",
    Role.APPLICATION: "aplicativo",
    Role.GLASSPANE: "painel de vidro",
    Role.LABEL: "rótulo",
}

STATE_LABELS: dict[State, str] = {
    State.UNAVAILABLE: "indisponível",
    State.SELECTED: "selecionado",
    State.BUSY: "ocupado",
    State.PRESSED: "pressionado",
    State.CHECKED: "marcado",
    State.HALFCHECKED: "parcialmente marcado",
    State.READONLY: "somente leitura",
    State.EXPANDED: "expandido",
    State.COLLAPSED: "recolhido",
    State.INVISIBLE: "invisível",
    State.VISITED: "visitado",
    State.HASPOPUP: "submenu",
    State.PROTECTED: "protegido",
    State.REQUIRED: "obrigatório",
    State.INVALID_ENTRY: "entrada inválida",
    State.MODAL: "modal",
    State.AUTOCOMPLETE: "preenchimento automático",
    State.MULTILINE: "multilinha",
    State.ICONIFIED: "minimizado",
    State.SORTED_ASCENDING: "ordenado crescente",
    State.SORTED_DESCENDING: "ordenado decrescente",
    State.ON: "ligado",
}

#: Estados negativos anunciados (``"não marcado"``) para papéis marcáveis.
NEGATIVE_STATE_LABELS: dict[State, str] = {
    State.CHECKED: "não marcado",
    State.PRESSED: "não pressionado",
    State.ON: "desligado",
}

#: Papéis cujo rótulo nunca é falado.
SILENT_ROLES: frozenset[Role] = frozenset(
    {
        Role.UNKNOWN,
        Role.STATICTEXT,
        Role.PARAGRAPH,
        Role.SECTION,
        Role.FILLER,
        Role.PANEL,
        Role.REDUNDANTOBJECT,
        Role.ROOTPANE,
        Role.LAYEREDPANE,
        Role.SCROLLPANE,
        Role.VIEWPORT,
        Role.APPLICATION,
        Role.GLASSPANE,
        Role.LABEL,
    }
)

#: Papéis não falados quando o objeto recebe o foco (``silentRolesOnFocus``).
SILENT_ROLES_ON_FOCUS: frozenset[Role] = SILENT_ROLES | frozenset(
    {
        Role.PANE,
        Role.FRAME,
        Role.TABLECELL,
        Role.LISTITEM,
        Role.MENUITEM,
        Role.CHECKMENUITEM,
        Role.TREEVIEWITEM,
    }
)

#: Papéis de mero leiaute, pulados na navegação simples por objetos.
LAYOUT_ROLES: frozenset[Role] = frozenset(
    {
        Role.UNKNOWN,
        Role.FILLER,
        Role.PANEL,
        Role.SECTION,
        Role.REDUNDANTOBJECT,
        Role.ROOTPANE,
        Role.LAYEREDPANE,
        Role.SCROLLPANE,
        Role.VIEWPORT,
        Role.GLASSPANE,
        Role.SPLITPANE,
        Role.PANE,
    }
)

#: Papéis de texto editável.
EDITABLE_ROLES: frozenset[Role] = frozenset(
    {Role.EDITABLETEXT, Role.PASSWORDEDIT, Role.TERMINAL, Role.DOCUMENT}
)

#: Papéis que, com foco dentro de um documento, pedem o modo de foco.
FOCUS_MODE_ROLES: frozenset[Role] = frozenset(
    {
        Role.EDITABLETEXT,
        Role.PASSWORDEDIT,
        Role.COMBOBOX,
        Role.LIST,
        Role.TREEVIEW,
        Role.TREEVIEWITEM,
        Role.SLIDER,
        Role.SPINBUTTON,
        Role.MENUITEM,
        Role.CHECKMENUITEM,
        Role.RADIOMENUITEM,
        Role.MENU,
        Role.POPUPMENU,
        Role.MENUBAR,
        Role.TABCONTROL,
        Role.TAB,
        Role.APPLICATION,
        Role.DATEEDITOR,
        Role.TERMINAL,
    }
)

#: Papéis com estado "marcado/não marcado".
CHECKABLE_ROLES: frozenset[Role] = frozenset(
    {Role.CHECKBOX, Role.RADIOBUTTON, Role.CHECKMENUITEM, Role.RADIOMENUITEM}
)

LANDMARK_LABELS: dict[str, str] = {
    "banner": "banner",
    "complementary": "complementar",
    "contentinfo": "informações de conteúdo",
    "form": "formulário",
    "main": "principal",
    "navigation": "navegação",
    "region": "região",
    "search": "pesquisa",
}


def heading_label(level: int | None) -> str:
    """``"cabeçalho nível 2"`` (ou só ``"cabeçalho"`` sem nível)."""
    if level:
        return f"cabeçalho nível {level}"
    return ROLE_LABELS[Role.HEADING]


def landmark_label(landmark: str) -> str:
    """``"navegação ponto de referência"``, como o NVDA fala."""
    base = LANDMARK_LABELS.get(landmark, landmark)
    return f"{base} ponto de referência"
