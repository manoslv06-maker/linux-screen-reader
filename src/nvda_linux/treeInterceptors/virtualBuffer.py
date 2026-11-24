# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Buffer virtual plano de um documento web exposto pelo AT-SPI2.

O documento (``DOCUMENT_WEB``/``DOCUMENT_FRAME`` do Firefox ou Chromium) é
"renderizado" num único texto, como os virtualBuffers do NVDA:

* objetos com ``Atspi.Text`` contribuem com o próprio texto; cada caractere
  ``U+FFFC`` marca um filho embutido (links, imagens...), renderizado no lugar;
* papéis de bloco (parágrafo, cabeçalho, item de lista, célula...) começam e
  terminam em linha nova; controles (campos, botões, caixas de seleção) viram
  folhas com o seu valor/nome;
* cada objeto vira um :class:`BufferNode` com ``[start, end)`` no texto, em
  pré-ordem; há índices ordenados por tipo (``heading``, ``link``...) para a
  navegação rápida com ``bisect``;
* páginas grandes são cortadas em ``max_nodes``; os elementos navegáveis
  restantes são buscados em lote via ``Atspi.Collection`` e anexados ao fim;
* :meth:`VirtualBuffer.update_subtree` re-renderiza só a subárvore que mudou e
  desloca o resto (atualização incremental).
"""

from __future__ import annotations

import logging
from bisect import bisect_left, bisect_right
from collections.abc import Hashable
from dataclasses import dataclass, field

from nvda_linux.NVDAObjects import _atspi, textUtils
from nvda_linux.NVDAObjects.base import LinuxNVDAObject, get_object
from nvda_linux.NVDAObjects.controlTypes import Role, State
from nvda_linux.NVDAObjects.textInfos import AtspiTextBackend, TextUnit

log = logging.getLogger(__name__)

BLOCK_ROLES: frozenset[Role] = frozenset(
    {
        Role.DOCUMENT,
        Role.PARAGRAPH,
        Role.HEADING,
        Role.LIST,
        Role.LISTITEM,
        Role.BLOCKQUOTE,
        Role.SECTION,
        Role.FORM,
        Role.TABLE,
        Role.TABLEROW,
        Role.TABLECELL,
        Role.TABLECOLUMNHEADER,
        Role.TABLEROWHEADER,
        Role.CAPTION,
        Role.HEADER,
        Role.FOOTER,
        Role.LANDMARK,
        Role.ARTICLE,
        Role.REGION,
        Role.FIGURE,
        Role.SEPARATOR,
        Role.GROUPING,
        Role.PANEL,
        Role.INTERNALFRAME,
        Role.DEFINITION,
        Role.FOOTNOTE,
        Role.ALERT,
        Role.DIALOG,
    }
)

#: Controles renderizados como folha (não se desce nos filhos).
LEAF_ROLES: frozenset[Role] = frozenset(
    {
        Role.EDITABLETEXT,
        Role.PASSWORDEDIT,
        Role.COMBOBOX,
        Role.CHECKBOX,
        Role.RADIOBUTTON,
        Role.SWITCH,
        Role.GRAPHIC,
        Role.SEPARATOR,
        Role.SLIDER,
        Role.PROGRESSBAR,
        Role.SPINBUTTON,
        Role.BUTTON,
        Role.TOGGLEBUTTON,
        Role.MENUBUTTON,
        Role.EMBEDDEDOBJECT,
        Role.CANVAS,
    }
)

#: Campos cujo nome é falado como informação de campo (não vira texto).
NAMED_FIELD_ROLES: frozenset[Role] = frozenset(
    {
        Role.EDITABLETEXT,
        Role.PASSWORDEDIT,
        Role.COMBOBOX,
        Role.CHECKBOX,
        Role.RADIOBUTTON,
        Role.SWITCH,
        Role.SLIDER,
        Role.SPINBUTTON,
        Role.PROGRESSBAR,
        Role.SEPARATOR,
    }
)

CELL_ROLES: frozenset[Role] = frozenset(
    {Role.TABLECELL, Role.TABLECOLUMNHEADER, Role.TABLEROWHEADER}
)
TABLE_STRUCTURE_ROLES: frozenset[Role] = CELL_ROLES | {Role.TABLE, Role.TABLEROW}

FORM_FIELD_ROLES: frozenset[Role] = frozenset(
    {
        Role.EDITABLETEXT,
        Role.PASSWORDEDIT,
        Role.COMBOBOX,
        Role.CHECKBOX,
        Role.RADIOBUTTON,
        Role.BUTTON,
        Role.TOGGLEBUTTON,
        Role.MENUBUTTON,
        Role.SLIDER,
        Role.SPINBUTTON,
        Role.SWITCH,
        Role.TREEVIEW,
    }
)

MSG_TRUNCATED_PARTIAL = (
    "Página muito grande: depois do corte, só títulos, links, campos e tabelas "
    "estão no modo de navegação."
)
MSG_TRUNCATED_MISSING = (
    "Página muito grande: parte do conteúdo não está no modo de navegação."
)

#: Papéis AT-SPI2 buscados em lote via Collection quando a página é cortada.
COLLECTION_ROLES: tuple[str, ...] = (
    "HEADING",
    "LINK",
    "PUSH_BUTTON",
    "BUTTON",
    "TOGGLE_BUTTON",
    "ENTRY",
    "PASSWORD_TEXT",
    "COMBO_BOX",
    "CHECK_BOX",
    "RADIO_BUTTON",
    "TABLE",
    "LANDMARK",
    "LIST",
    "IMAGE",
)

_EMBED = _atspi.EMBEDDED_OBJECT_CHAR


@dataclass(slots=True)
class BufferNode:
    """Um objeto do documento e o seu intervalo no texto do buffer."""

    index: int
    obj: LinuxNVDAObject
    role: Role
    states: frozenset[State]
    name: str
    start: int
    end: int
    parent: int
    depth: int
    subtree_end: int = 0  # índice (exclusivo) após o último descendente
    level: int | None = None
    landmark: str | None = None
    kinds: frozenset[str] = frozenset()
    table: int | None = None  # índice do nó TABLE, para células
    row: int | None = None
    col: int | None = None
    item_count: int = 0  # filhos LISTITEM (listas)

    def contains(self, offset: int) -> bool:
        return self.start <= offset < self.end


@dataclass(slots=True)
class TableInfo:
    """Coordenadas das células de uma tabela (para Ctrl+Alt+setas)."""

    node: int
    rows: int = 0
    cols: int = 0
    cells: dict[tuple[int, int], int] = field(default_factory=dict)
    _row: int = 0
    _col: int = 0

    def shifted(self, count_delta: int, threshold: int) -> TableInfo:
        def shift(i: int) -> int:
            return i + count_delta if i >= threshold else i

        return TableInfo(
            shift(self.node),
            self.rows,
            self.cols,
            {k: shift(v) for k, v in self.cells.items()},
        )


def compute_kinds(obj: LinuxNVDAObject, role: Role, states: frozenset[State], nested: bool) -> set[str]:
    """Tipos de navegação rápida de um objeto."""
    kinds: set[str] = set()
    if role == Role.HEADING:
        kinds.add("heading")
        level = obj.heading_level
        if level:
            kinds.add(f"heading{level}")
    elif role == Role.LINK:
        kinds.add("link")
        kinds.add("visitedLink" if State.VISITED in states else "unvisitedLink")
    if role in FORM_FIELD_ROLES and State.READONLY not in states:
        kinds.add("formField")
    if role in (Role.BUTTON, Role.TOGGLEBUTTON, Role.MENUBUTTON):
        kinds.add("button")
    if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT) and State.READONLY not in states:
        kinds.add("edit")
    if role == Role.TABLE and obj.attributes.get("layout-guess", "") != "true":
        kinds.add("table")
    if role == Role.LIST and State.FOCUSABLE not in states:
        kinds.add("list")
    if role == Role.LIST and State.FOCUSABLE in states:
        kinds.add("formField")
    if role == Role.LISTITEM:
        kinds.add("listItem")
    if role == Role.GRAPHIC and obj.name.strip():
        kinds.add("graphic")
    if obj.landmark:
        kinds.add("landmark")
    if role == Role.COMBOBOX:
        kinds.add("comboBox")
    if role == Role.CHECKBOX:
        kinds.add("checkBox")
    if role == Role.RADIOBUTTON:
        kinds.add("radioButton")
    if role == Role.BLOCKQUOTE:
        kinds.add("blockQuote")
    if role == Role.SEPARATOR:
        kinds.add("separator")
    if role in (Role.EMBEDDEDOBJECT, Role.VIDEO, Role.AUDIO, Role.CANVAS):
        kinds.add("embeddedObject")
    if nested and role in (Role.DOCUMENT, Role.INTERNALFRAME):
        kinds.add("frame")
    if State.FOCUSABLE in states:
        kinds.add("focusable")
    return kinds


def control_text(obj: LinuxNVDAObject, role: Role, states: frozenset[State]) -> str:
    """Texto de um controle folha no buffer (pode ser vazio)."""
    if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
        if State.PROTECTED in states:
            return ""
        text_iface = obj.text_iface
        if text_iface is not None:
            backend = AtspiTextBackend(text_iface)
            return backend.get_text(0, min(backend.length(), 100_000)).replace(_EMBED, "")
        return obj.value
    if role in (Role.COMBOBOX, Role.SLIDER, Role.PROGRESSBAR, Role.SPINBUTTON):
        return obj.value or obj.name
    if role in (Role.BUTTON, Role.TOGGLEBUTTON, Role.MENUBUTTON):
        text_iface = obj.text_iface
        if text_iface is not None:
            backend = AtspiTextBackend(text_iface)
            text = backend.get_text(0, min(backend.length(), 10_000)).replace(_EMBED, "").strip()
            if text:
                return text
        return obj.name
    if role in (Role.CHECKBOX, Role.RADIOBUTTON, Role.SWITCH, Role.SEPARATOR):
        return ""
    return obj.name


class _Builder:
    """Renderiza uma (sub)árvore em texto + nós."""

    def __init__(
        self,
        max_nodes: int,
        base_offset: int = 0,
        base_index: int = 0,
        last_char: str = "\n",
    ) -> None:
        self.max_nodes = max_nodes
        self.base_offset = base_offset
        self.base_index = base_index
        self.chunks: list[str] = []
        self.length = 0
        self.last_char = last_char
        self.nodes: list[BufferNode] = []
        self.tables: dict[int, TableInfo] = {}
        self.truncated = False
        self._table_stack: list[TableInfo] = []
        self._seen: set[Hashable] = set()

    @property
    def offset(self) -> int:
        return self.base_offset + self.length

    @property
    def text(self) -> str:
        return "".join(self.chunks)

    def emit(self, text: str) -> None:
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.chunks.append(text)
        self.length += len(text)
        self.last_char = text[-1]

    def newline(self) -> None:
        if self.last_char != "\n":
            self.emit("\n")

    def render(self, obj: LinuxNVDAObject, parent: int, depth: int) -> None:
        if len(self.nodes) >= self.max_nodes:
            self.truncated = True
            return
        if obj.key in self._seen or depth > 200:
            return
        self._seen.add(obj.key)
        states = obj.states
        if State.DEFUNCT in states:
            return
        role = obj.role
        block = role in BLOCK_ROLES
        if block:
            self.newline()
        index = self.base_index + len(self.nodes)
        nested = depth > 0
        node = BufferNode(
            index=index,
            obj=obj,
            role=role,
            states=states,
            name=obj.name,
            start=self.offset,
            end=self.offset,
            parent=parent,
            depth=depth,
            level=obj.heading_level,
            landmark=obj.landmark,
            kinds=frozenset(compute_kinds(obj, role, states, nested)),
        )
        self.nodes.append(node)
        self._enter_table(node)

        if role in LEAF_ROLES:
            self.emit(control_text(obj, role, states))
        elif obj.has_text and role != Role.TABLE:
            self._render_hypertext(obj, index, depth)
        else:
            for child in obj.children:
                self.render(child, index, depth + 1)

        needs_extent = bool(node.kinds - {"focusable"}) or role in LEAF_ROLES
        if node.start == self.offset and needs_extent and (role != Role.GRAPHIC or node.kinds):
            # Elementos navegáveis sempre ocupam ao menos um caractere. Campos
            # cujo nome já vai na informação de campo ficam com um espaço.
            label = "" if role in NAMED_FIELD_ROLES else node.name.strip()
            self.emit(label or " ")
        node.end = self.offset
        node.subtree_end = self.base_index + len(self.nodes)
        if role == Role.LIST:
            node.item_count = sum(
                1 for n in self.nodes[index - self.base_index + 1 :] if n.parent == index and n.role == Role.LISTITEM
            )
        self._leave_table(node)
        if block:
            self.newline()

    def _render_hypertext(self, obj: LinuxNVDAObject, index: int, depth: int) -> None:
        text_iface = obj.text_iface
        backend = AtspiTextBackend(text_iface)
        text = backend.get_text(0, min(backend.length(), 500_000))
        children = obj.children
        if _EMBED not in text:
            if text.strip() or not children:
                self.emit(text)
                return
            for child in children:
                self.render(child, index, depth + 1)
            return
        child_iter = iter(children)
        pieces = text.split(_EMBED)
        for i, piece in enumerate(pieces):
            self.emit(piece)
            if i == len(pieces) - 1:
                break
            embedded = next(child_iter, None)
            if embedded is not None:
                self.render(embedded, index, depth + 1)

    # ------------------------------------------------------------ tabelas
    def _enter_table(self, node: BufferNode) -> None:
        if node.role == Role.TABLE:
            info = TableInfo(node.index)
            self._table_stack.append(info)
            self.tables[node.index] = info
            return
        if not self._table_stack:
            return
        table = self._table_stack[-1]
        if node.role == Role.TABLEROW:
            table._row += 1
            table._col = 0
        elif node.role in CELL_ROLES:
            if table._row == 0:
                table._row = 1
            row = table._row
            col = table._col + 1
            while (row, col) in table.cells:
                col += 1
            span_cols = _span(node.obj, "colspan")
            span_rows = _span(node.obj, "rowspan")
            for r in range(row, row + span_rows):
                for c in range(col, col + span_cols):
                    table.cells.setdefault((r, c), node.index)
            table._col = col + span_cols - 1
            node.table = table.node
            node.row = row
            node.col = col
            table.rows = max(table.rows, row + span_rows - 1)
            table.cols = max(table.cols, col + span_cols - 1)

    def _leave_table(self, node: BufferNode) -> None:
        if node.role == Role.TABLE and self._table_stack:
            info = self._table_stack.pop()
            table_iface = _atspi.iface(node.obj.raw, "table")
            if table_iface is not None:
                try:
                    info.rows = max(info.rows, int(_atspi.call(table_iface, "get_n_rows", default=0)))
                    info.cols = max(
                        info.cols, int(_atspi.call(table_iface, "get_n_columns", default=0))
                    )
                except (TypeError, ValueError):
                    pass


def _span(obj: LinuxNVDAObject, attr: str) -> int:
    try:
        return max(1, min(1000, int(obj.attributes.get(attr, "1"))))
    except ValueError:
        return 1


class VirtualBuffer:
    """Representação plana e pesquisável de um documento."""

    def __init__(
        self,
        root: LinuxNVDAObject,
        max_line_length: int = 100,
        max_nodes: int = 20000,
    ) -> None:
        self.root = root
        self.max_line_length = max_line_length
        self.max_nodes = max_nodes
        self.text = ""
        self.nodes: list[BufferNode] = []
        self.tables: dict[int, TableInfo] = {}
        self.line_starts: list[int] = [0]
        self.truncated = False
        #: Página cortada e a busca em lote (Collection) falhou: o resto sumiu.
        self.collection_failed = False
        self.ready = False
        self._starts: list[int] = []
        self._by_key: dict[Hashable, int] = {}
        self._kind_index: dict[str, list[int]] = {}
        self._kind_starts: dict[str, list[int]] = {}

    # ------------------------------------------------------------ construção
    def build(self) -> None:
        """(Re)constrói o buffer inteiro a partir da raiz."""
        builder = _Builder(self.max_nodes)
        builder.render(self.root, -1, 0)
        self.collection_failed = False
        if builder.truncated:
            self.collection_failed = not self._append_collection_matches(builder)
            if self.collection_failed:
                log.warning(
                    "Página cortada em %d nós e sem Atspi.Collection: o resto ficou de fora",
                    self.max_nodes,
                )
        self.text = builder.text
        self.nodes = builder.nodes
        self.tables = builder.tables
        self.truncated = builder.truncated
        self._reindex()
        self.ready = True
        log.debug("Buffer construído: %d nós, %d caracteres", len(self.nodes), len(self.text))

    def _append_collection_matches(self, builder: _Builder) -> bool:
        """Anexa, via ``Atspi.Collection``, elementos navegáveis não renderizados.

        Devolve ``False`` se a busca em lote não está disponível ou falhou.
        """
        rendered = {n.obj.key for n in builder.nodes}
        matches = _atspi.get_matches(self.root.raw, COLLECTION_ROLES)
        if matches is None:
            return False
        builder.max_nodes += max(1000, self.max_nodes // 4)
        for raw in matches:
            match = get_object(raw)
            if match is None or match.key in rendered:
                continue
            builder.newline()
            builder.render(match, 0, 1)
            if len(builder.nodes) >= builder.max_nodes:
                break
        if builder.nodes:
            root = builder.nodes[0]
            root.end = builder.offset
            root.subtree_end = len(builder.nodes)
        return True

    def truncation_notice(self) -> str | None:
        """Aviso para o usuário quando a página não coube inteira no buffer."""
        if not self.truncated:
            return None
        if self.collection_failed:
            return MSG_TRUNCATED_MISSING
        return MSG_TRUNCATED_PARTIAL

    def _reindex(self) -> None:
        self._starts = [n.start for n in self.nodes]
        self._by_key = {}
        for n in self.nodes:
            self._by_key.setdefault(n.obj.key, n.index)
        self._kind_index = {}
        for n in self.nodes:
            for kind in n.kinds:
                self._kind_index.setdefault(kind, []).append(n.index)
        self._kind_starts = {
            kind: [self.nodes[i].start for i in idxs] for kind, idxs in self._kind_index.items()
        }
        self.line_starts = textUtils.wrap_line_starts(self.text, self.max_line_length)

    def update_subtree(self, obj: LinuxNVDAObject) -> bool:
        """Re-renderiza só a subárvore de ``obj``. ``False`` = precisa de ``build``."""
        if not self.ready:
            return False
        idx = self._by_key.get(obj.key)
        if idx is None or idx == 0:
            return False
        old = self.nodes[idx]
        if old.role in TABLE_STRUCTURE_ROLES:
            return False
        old_last = old.subtree_end
        old_start, old_end = old.start, old.end
        prev_char = self.text[old_start - 1] if old_start > 0 else "\n"
        obj.invalidate_cache()
        for stale in self.nodes[idx:old_last]:
            stale.obj.invalidate_cache()
        builder = _Builder(self.max_nodes, base_offset=old_start, base_index=idx, last_char=prev_char)
        # Objetos já presentes fora da subárvore não podem ser renderizados de novo.
        builder._seen = {n.obj.key for n in self.nodes[:idx]} | {
            n.obj.key for n in self.nodes[old_last:]
        }
        try:
            builder.render(obj, old.parent, old.depth)
        except Exception:
            log.exception("Atualização incremental falhou")
            return False
        if not builder.nodes or builder.truncated:
            return False
        new_root = builder.nodes[0]
        new_text = builder.text[: new_root.end - old_start]
        delta = len(new_text) - (old_end - old_start)
        count_delta = len(builder.nodes) - (old_last - idx)

        tail = self.nodes[old_last:]
        for n in tail:
            n.start += delta
            n.end += delta
            n.index += count_delta
            if n.parent >= old_last:
                n.parent += count_delta
            n.subtree_end += count_delta
            if n.table is not None and n.table >= old_last:
                n.table += count_delta
        parent = old.parent
        while parent >= 0:
            anc = self.nodes[parent]
            anc.end += delta
            anc.subtree_end += count_delta
            parent = anc.parent
        tables = {
            k: t.shifted(count_delta, old_last)
            for k, t in self.tables.items()
            if not (idx <= k < old_last)
        }
        self.tables = {t.node: t for t in tables.values()}
        self.tables.update(builder.tables)
        self.nodes = self.nodes[:idx] + builder.nodes + tail
        self.text = self.text[:old_start] + new_text + self.text[old_end:]
        self._reindex()
        return True

    # ------------------------------------------------------------ consultas
    def __len__(self) -> int:
        return len(self.text)

    def node_for(self, obj: LinuxNVDAObject) -> BufferNode | None:
        idx = self._by_key.get(obj.key)
        return self.nodes[idx] if idx is not None else None

    def deepest_node_at(self, offset: int) -> BufferNode | None:
        if not self.nodes:
            return None
        offset = max(0, min(offset, len(self.text) - 1))
        idx = bisect_right(self._starts, offset) - 1
        while idx >= 0:
            node = self.nodes[idx]
            if node.contains(offset):
                return node
            idx = node.parent
        return self.nodes[0]

    def ancestors_at(self, offset: int) -> list[int]:
        """Índices dos nós que contêm ``offset``, do mais externo ao mais interno."""
        node = self.deepest_node_at(offset)
        chain: list[int] = []
        while node is not None:
            chain.append(node.index)
            node = self.nodes[node.parent] if node.parent >= 0 else None
        chain.reverse()
        return chain

    def nodes_starting_in(self, start: int, end: int) -> list[BufferNode]:
        """Nós com ``start < node.start < end`` (campos que começam no meio)."""
        lo = bisect_right(self._starts, start)
        hi = bisect_left(self._starts, end)
        return [self.nodes[i] for i in range(lo, hi) if self.nodes[i].end > self.nodes[i].start]

    def nodes_of_kind(self, kind: str) -> list[BufferNode]:
        return [self.nodes[i] for i in self._kind_index.get(kind, [])]

    def kinds_present(self) -> set[str]:
        return set(self._kind_index)

    def next_of_kind(self, kind: str, offset: int, forward: bool = True) -> BufferNode | None:
        """Próximo/anterior nó do tipo a partir de ``offset`` (busca com bisect)."""
        starts = self._kind_starts.get(kind)
        if not starts:
            return None
        indices = self._kind_index[kind]
        if forward:
            pos = bisect_right(starts, offset)
            while pos < len(indices):
                node = self.nodes[indices[pos]]
                if node.end > node.start:
                    return node
                pos += 1
            return None
        pos = bisect_left(starts, offset) - 1
        while pos >= 0:
            node = self.nodes[indices[pos]]
            if node.end > node.start:
                return node
            pos -= 1
        return None

    def cell_at(self, offset: int) -> BufferNode | None:
        for idx in reversed(self.ancestors_at(offset)):
            node = self.nodes[idx]
            if node.role in CELL_ROLES and node.table is not None:
                return node
        return None

    # ------------------------------------------------------------ unidades de texto
    def unit_bounds(self, offset: int, unit: TextUnit) -> tuple[int, int]:
        n = len(self.text)
        if unit == TextUnit.CHARACTER:
            return textUtils.char_bounds(self.text, offset)
        if unit == TextUnit.WORD:
            line_start, line_end = self.unit_bounds(offset, TextUnit.LINE)
            start, end = textUtils.word_bounds(self.text, offset)
            return max(start, line_start), min(end, line_end) if line_end > line_start else end
        if unit == TextUnit.LINE:
            return textUtils.bounds_from_starts(self.line_starts, n, offset)
        if unit == TextUnit.PARAGRAPH:
            return textUtils.line_bounds(self.text, offset)
        return 0, n
