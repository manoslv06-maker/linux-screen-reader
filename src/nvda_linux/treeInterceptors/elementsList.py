# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Dados da Lista de Elementos (NVDA+F7), independentes da GUI.

O diálogo GTK (``gui/elementsListDialog.py``) só exibe :class:`ElementItem` e
chama :meth:`ElementsListModel.activate` / :meth:`ElementsListModel.move_to`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nvda_linux.NVDAObjects.controlTypes import landmark_label
from nvda_linux.treeInterceptors.virtualBuffer import BufferNode

if TYPE_CHECKING:
    from nvda_linux.treeInterceptors.browseMode import BrowseModeTreeInterceptor

#: (kind do buffer, rótulo do tipo na lista), na ordem do NVDA.
ELEMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("link", "Links"),
    ("heading", "Cabeçalhos"),
    ("formField", "Campos de formulário"),
    ("button", "Botões"),
    ("landmark", "Pontos de referência"),
)

_SINGULAR = {
    "link": ("link", "links"),
    "heading": ("cabeçalho", "cabeçalhos"),
    "formField": ("campo de formulário", "campos de formulário"),
    "button": ("botão", "botões"),
    "landmark": ("ponto de referência", "pontos de referência"),
}


@dataclass(frozen=True, slots=True)
class ElementItem:
    label: str
    kind: str
    node_index: int
    depth: int = 0


class ElementsListModel:
    """Itens por tipo, com filtro, a partir do buffer de um documento."""

    def __init__(self, ti: BrowseModeTreeInterceptor) -> None:
        self.ti = ti

    @property
    def title(self) -> str:
        return self.ti.root.name or "Documento"

    def _label(self, node: BufferNode, kind: str) -> str:
        text = self.ti.buffer.text[node.start : node.end].strip()
        text = " ".join(text.split())
        if kind == "landmark":
            base = landmark_label(node.landmark or "region")
            return f"{node.name} {base}".strip() if node.name else base
        if kind == "formField":
            parts = [p for p in (node.name, node.role.display_string, text) if p]
            unique: list[str] = []
            for p in parts:
                if p not in unique:
                    unique.append(p)
            return " ".join(unique)
        return text or node.name or node.role.display_string

    def items(self, kind: str, filter_text: str = "") -> list[ElementItem]:
        wanted = filter_text.strip().lower()
        result: list[ElementItem] = []
        for node in self.ti.buffer.nodes_of_kind(kind):
            label = self._label(node, kind)
            if wanted and wanted not in label.lower():
                continue
            depth = (node.level - 1) if kind == "heading" and node.level else 0
            result.append(ElementItem(label, kind, node.index, depth))
        return result

    def counts(self) -> dict[str, int]:
        return {kind: len(self.ti.buffer.nodes_of_kind(kind)) for kind, _ in ELEMENT_TYPES}

    def summary(self) -> str:
        """Resumo falado quando a GUI não está disponível."""
        parts: list[str] = []
        for kind, count in self.counts().items():
            singular, plural = _SINGULAR[kind]
            parts.append(f"{count} {singular if count == 1 else plural}")
        return "Lista de elementos: " + ", ".join(parts)

    def move_to(self, item: ElementItem) -> None:
        """Leva o cursor virtual ao elemento e o fala."""
        self.ti.move_to_node(self.ti.buffer.nodes[item.node_index])

    def activate(self, item: ElementItem) -> None:
        """Move até o elemento e o ativa (clicar link/botão, focar campo)."""
        node = self.ti.buffer.nodes[item.node_index]
        self.ti.caret = node.start
        self.ti.activate_node(node)
