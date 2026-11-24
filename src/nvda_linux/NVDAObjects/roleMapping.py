# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Mapeamento completo ``Atspi.Role``/``Atspi.StateSet`` -> ``controlTypes``.

Os papéis e estados AT-SPI2 chegam aqui já normalizados como strings em
maiúsculas (ver :func:`nvda_linux.NVDAObjects._atspi.enum_name`).
"""

from __future__ import annotations

from collections.abc import Mapping

from nvda_linux.NVDAObjects.controlTypes import CHECKABLE_ROLES, EDITABLE_ROLES, Role, State

#: Todos os papéis do ``AtspiRole`` (libatspi 2.52) e o equivalente NVDA.
ATSPI_ROLE_MAP: Mapping[str, Role] = {
    "INVALID": Role.UNKNOWN,
    "ACCELERATOR_LABEL": Role.STATICTEXT,
    "ALERT": Role.ALERT,
    "ANIMATION": Role.ANIMATION,
    "ARROW": Role.ICON,
    "CALENDAR": Role.CALENDAR,
    "CANVAS": Role.CANVAS,
    "CHECK_BOX": Role.CHECKBOX,
    "CHECK_MENU_ITEM": Role.CHECKMENUITEM,
    "COLOR_CHOOSER": Role.COLORCHOOSER,
    "COLUMN_HEADER": Role.TABLECOLUMNHEADER,
    "COMBO_BOX": Role.COMBOBOX,
    "DATE_EDITOR": Role.DATEEDITOR,
    "DESKTOP_ICON": Role.DESKTOPICON,
    "DESKTOP_FRAME": Role.DESKTOPPANE,
    "DIAL": Role.DIAL,
    "DIALOG": Role.DIALOG,
    "DIRECTORY_PANE": Role.DIRECTORYPANE,
    "DRAWING_AREA": Role.CANVAS,
    "FILE_CHOOSER": Role.FILECHOOSER,
    "FILLER": Role.FILLER,
    "FOCUS_TRAVERSABLE": Role.UNKNOWN,
    "FONT_CHOOSER": Role.FONTCHOOSER,
    "FRAME": Role.FRAME,
    "GLASS_PANE": Role.GLASSPANE,
    "HTML_CONTAINER": Role.SECTION,
    "ICON": Role.ICON,
    "IMAGE": Role.GRAPHIC,
    "INTERNAL_FRAME": Role.INTERNALFRAME,
    "LABEL": Role.LABEL,
    "LAYERED_PANE": Role.LAYEREDPANE,
    "LIST": Role.LIST,
    "LIST_ITEM": Role.LISTITEM,
    "MENU": Role.MENU,
    "MENU_BAR": Role.MENUBAR,
    "MENU_ITEM": Role.MENUITEM,
    "OPTION_PANE": Role.OPTIONPANE,
    "PAGE_TAB": Role.TAB,
    "PAGE_TAB_LIST": Role.TABCONTROL,
    "PANEL": Role.PANEL,
    "PASSWORD_TEXT": Role.PASSWORDEDIT,
    "POPUP_MENU": Role.POPUPMENU,
    "PROGRESS_BAR": Role.PROGRESSBAR,
    "PUSH_BUTTON": Role.BUTTON,
    "BUTTON": Role.BUTTON,  # nome no at-spi2-core recente (Firefox no Fedora 45)
    "RADIO_BUTTON": Role.RADIOBUTTON,
    "RADIO_MENU_ITEM": Role.RADIOMENUITEM,
    "ROOT_PANE": Role.ROOTPANE,
    "ROW_HEADER": Role.TABLEROWHEADER,
    "SCROLL_BAR": Role.SCROLLBAR,
    "SCROLL_PANE": Role.SCROLLPANE,
    "SEPARATOR": Role.SEPARATOR,
    "SLIDER": Role.SLIDER,
    "SPIN_BUTTON": Role.SPINBUTTON,
    "SPLIT_PANE": Role.SPLITPANE,
    "STATUS_BAR": Role.STATUSBAR,
    "TABLE": Role.TABLE,
    "TABLE_CELL": Role.TABLECELL,
    "TABLE_COLUMN_HEADER": Role.TABLECOLUMNHEADER,
    "TABLE_ROW_HEADER": Role.TABLEROWHEADER,
    "TEAROFF_MENU_ITEM": Role.TEAROFFMENU,
    "TERMINAL": Role.TERMINAL,
    "TEXT": Role.EDITABLETEXT,  # refinado por estado em map_role()
    "TOGGLE_BUTTON": Role.TOGGLEBUTTON,
    "TOOL_BAR": Role.TOOLBAR,
    "TOOL_TIP": Role.TOOLTIP,
    "TREE": Role.TREEVIEW,
    "TREE_TABLE": Role.TREEVIEW,
    "UNKNOWN": Role.UNKNOWN,
    "VIEWPORT": Role.VIEWPORT,
    "WINDOW": Role.WINDOW,
    "EXTENDED": Role.UNKNOWN,
    "HEADER": Role.HEADER,
    "FOOTER": Role.FOOTER,
    "PARAGRAPH": Role.PARAGRAPH,
    "RULER": Role.RULER,
    "APPLICATION": Role.APPLICATION,
    "AUTOCOMPLETE": Role.COMBOBOX,
    "EDITBAR": Role.EDITBAR,
    "EMBEDDED": Role.EMBEDDEDOBJECT,
    "ENTRY": Role.EDITABLETEXT,
    "CHART": Role.CHART,
    "CAPTION": Role.CAPTION,
    "DOCUMENT_FRAME": Role.DOCUMENT,
    "HEADING": Role.HEADING,
    "PAGE": Role.PAGE,
    "SECTION": Role.SECTION,
    "REDUNDANT_OBJECT": Role.REDUNDANTOBJECT,
    "FORM": Role.FORM,
    "LINK": Role.LINK,
    "INPUT_METHOD_WINDOW": Role.INPUTWINDOW,
    "TABLE_ROW": Role.TABLEROW,
    "TREE_ITEM": Role.TREEVIEWITEM,
    "DOCUMENT_SPREADSHEET": Role.DOCUMENT,
    "DOCUMENT_PRESENTATION": Role.DOCUMENT,
    "DOCUMENT_TEXT": Role.DOCUMENT,
    "DOCUMENT_WEB": Role.DOCUMENT,
    "DOCUMENT_EMAIL": Role.DOCUMENT,
    "COMMENT": Role.COMMENT,
    "LIST_BOX": Role.LIST,
    "GROUPING": Role.GROUPING,
    "IMAGE_MAP": Role.IMAGEMAP,
    "NOTIFICATION": Role.ALERT,
    "INFO_BAR": Role.INFOBAR,
    "LEVEL_BAR": Role.PROGRESSBAR,
    "TITLE_BAR": Role.TITLEBAR,
    "BLOCK_QUOTE": Role.BLOCKQUOTE,
    "AUDIO": Role.AUDIO,
    "VIDEO": Role.VIDEO,
    "DEFINITION": Role.DEFINITION,
    "ARTICLE": Role.ARTICLE,
    "LANDMARK": Role.LANDMARK,
    "LOG": Role.SECTION,
    "MARQUEE": Role.SECTION,
    "MATH": Role.MATH,
    "RATING": Role.SLIDER,
    "TIMER": Role.CLOCK,
    "STATIC": Role.STATICTEXT,
    "MATH_FRACTION": Role.MATH,
    "MATH_ROOT": Role.MATH,
    "SUBSCRIPT": Role.SUBSCRIPT,
    "SUPERSCRIPT": Role.SUPERSCRIPT,
    "DESCRIPTION_LIST": Role.LIST,
    "DESCRIPTION_TERM": Role.LISTITEM,
    "DESCRIPTION_VALUE": Role.DEFINITION,
    "FOOTNOTE": Role.FOOTNOTE,
    "CONTENT_DELETION": Role.DELETED_CONTENT,
    "CONTENT_INSERTION": Role.INSERTED_CONTENT,
    "MARK": Role.MARKED_CONTENT,
    "SUGGESTION": Role.SUGGESTION,
    "PUSH_BUTTON_MENU": Role.MENUBUTTON,
    "SWITCH": Role.SWITCH,
}

#: Papéis AT-SPI2 de documento web (candidatos ao Browse Mode).
WEB_DOCUMENT_ROLES: frozenset[str] = frozenset({"DOCUMENT_WEB", "DOCUMENT_FRAME"})

#: Estados AT-SPI2 com equivalente direto.
_DIRECT_STATES: Mapping[str, State] = {
    "FOCUSED": State.FOCUSED,
    "SELECTED": State.SELECTED,
    "BUSY": State.BUSY,
    "PRESSED": State.PRESSED,
    "CHECKED": State.CHECKED,
    "READ_ONLY": State.READONLY,
    "EXPANDED": State.EXPANDED,
    "COLLAPSED": State.COLLAPSED,
    "VISITED": State.VISITED,
    "HAS_POPUP": State.HASPOPUP,
    "REQUIRED": State.REQUIRED,
    "DEFUNCT": State.DEFUNCT,
    "INVALID_ENTRY": State.INVALID_ENTRY,
    "MODAL": State.MODAL,
    "SUPPORTS_AUTOCOMPLETION": State.AUTOCOMPLETE,
    "MULTI_LINE": State.MULTILINE,
    "ICONIFIED": State.ICONIFIED,
    "SELECTABLE": State.SELECTABLE,
    "FOCUSABLE": State.FOCUSABLE,
    "EDITABLE": State.EDITABLE,
    "CHECKABLE": State.CHECKABLE,
    "MULTISELECTABLE": State.MULTISELECTABLE,
}


def map_role(atspi_role: str, atspi_states: frozenset[str] = frozenset()) -> Role:
    """Converte o papel AT-SPI2 em :class:`Role`, refinando pelo estado.

    ``TEXT`` é usado pelo AT-SPI2 tanto para texto estático quanto para
    campos de edição; o estado ``EDITABLE`` decide.
    """
    role = ATSPI_ROLE_MAP.get(atspi_role, Role.UNKNOWN)
    if atspi_role == "TEXT" and "EDITABLE" not in atspi_states and atspi_states:
        return Role.STATICTEXT
    return role


def map_states(
    atspi_states: frozenset[str],
    role: Role,
    attributes: Mapping[str, str] | None = None,
) -> frozenset[State]:
    """Converte o ``Atspi.StateSet`` (já normalizado) em estados do NVDA.

    Regras além do mapeamento direto, como no NVDA:

    * sem ``ENABLED`` nem ``SENSITIVE`` -> ``UNAVAILABLE``;
    * sem ``VISIBLE`` -> ``INVISIBLE``; sem ``SHOWING`` -> ``OFFSCREEN``;
    * ``EXPANDABLE`` sem ``EXPANDED`` -> ``COLLAPSED``;
    * ``INDETERMINATE`` em papel marcável -> ``HALFCHECKED``;
    * papel editável sem ``EDITABLE`` -> ``READONLY``;
    * senha -> ``PROTECTED``; ``SWITCH`` marcado -> ``ON``;
    * atributo ``sort`` -> ``SORTED_ASCENDING``/``SORTED_DESCENDING``.
    """
    if not atspi_states:
        return frozenset()
    result: set[State] = {_DIRECT_STATES[s] for s in atspi_states if s in _DIRECT_STATES}
    if "ENABLED" not in atspi_states and "SENSITIVE" not in atspi_states:
        result.add(State.UNAVAILABLE)
    if "VISIBLE" not in atspi_states:
        result.add(State.INVISIBLE)
    if "SHOWING" not in atspi_states:
        result.add(State.OFFSCREEN)
    if "EXPANDABLE" in atspi_states and "EXPANDED" not in atspi_states:
        result.add(State.COLLAPSED)
    if "EXPANDED" in atspi_states:
        result.discard(State.COLLAPSED)
    if "INDETERMINATE" in atspi_states and role in CHECKABLE_ROLES:
        result.add(State.HALFCHECKED)
        result.discard(State.CHECKED)
    if role in CHECKABLE_ROLES:
        result.add(State.CHECKABLE)
    if (
        role in EDITABLE_ROLES
        and role != Role.DOCUMENT
        and role != Role.TERMINAL
        and "EDITABLE" not in atspi_states
    ):
        result.add(State.READONLY)
    if role == Role.PASSWORDEDIT:
        result.add(State.PROTECTED)
    if role == Role.SWITCH and ("CHECKED" in atspi_states or "PRESSED" in atspi_states):
        result.add(State.ON)
        result.discard(State.CHECKED)
        result.discard(State.PRESSED)
    if role == Role.LINK:
        result.add(State.LINKED)
    if attributes:
        sort = attributes.get("sort", "").lower()
        if sort == "ascending":
            result.add(State.SORTED_ASCENDING)
        elif sort == "descending":
            result.add(State.SORTED_DESCENDING)
    return frozenset(result)
