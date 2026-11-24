# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Tipos de elemento da navegação rápida (teclas de uma letra do NVDA)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuickNavType:
    """Uma tecla de navegação rápida e o ``kind`` indexado no buffer."""

    key: str  # tecla sem modificadores: "h", "1", "k"...
    kind: str  # chave do índice do VirtualBuffer
    singular: str  # "cabeçalho"
    feminine: bool = False  # concordância: "próxima tabela"

    @property
    def next_label(self) -> str:
        return f"{'próxima' if self.feminine else 'próximo'} {self.singular}"

    @property
    def previous_label(self) -> str:
        return f"{self.singular} anterior"

    @property
    def not_found_next(self) -> str:
        article = "Nenhuma" if self.feminine else "Nenhum"
        return f"{article} {self.singular} seguinte"

    @property
    def not_found_previous(self) -> str:
        article = "Nenhuma" if self.feminine else "Nenhum"
        return f"{article} {self.singular} anterior"

    @property
    def description_next(self) -> str:
        return f"Move para {'a' if self.feminine else 'o'} {self.next_label}"

    @property
    def description_previous(self) -> str:
        return f"Move para {'a' if self.feminine else 'o'} {self.previous_label}"


QUICK_NAV_TYPES: tuple[QuickNavType, ...] = (
    QuickNavType("h", "heading", "cabeçalho"),
    *(QuickNavType(str(n), f"heading{n}", f"cabeçalho de nível {n}") for n in range(1, 7)),
    QuickNavType("k", "link", "link"),
    QuickNavType("u", "unvisitedLink", "link não visitado"),
    QuickNavType("v", "visitedLink", "link visitado"),
    QuickNavType("f", "formField", "campo de formulário"),
    QuickNavType("t", "table", "tabela", feminine=True),
    QuickNavType("b", "button", "botão"),
    QuickNavType("e", "edit", "campo de edição"),
    QuickNavType("l", "list", "lista", feminine=True),
    QuickNavType("i", "listItem", "item de lista"),
    QuickNavType("g", "graphic", "gráfico"),
    QuickNavType("d", "landmark", "ponto de referência"),
    QuickNavType("c", "comboBox", "caixa de combinação", feminine=True),
    QuickNavType("x", "checkBox", "caixa de seleção", feminine=True),
    QuickNavType("r", "radioButton", "botão de opção"),
    QuickNavType("q", "blockQuote", "citação", feminine=True),
    QuickNavType("s", "separator", "separador"),
    QuickNavType("m", "frame", "quadro"),
    QuickNavType("o", "embeddedObject", "objeto embutido"),
)

QUICK_NAV_BY_KEY: dict[str, QuickNavType] = {t.key: t for t in QUICK_NAV_TYPES}
QUICK_NAV_BY_KIND: dict[str, QuickNavType] = {t.kind: t for t in QUICK_NAV_TYPES}

#: Tipos que são contêineres: ao navegar até eles, fala-se só a primeira linha.
CONTAINER_KINDS: frozenset[str] = frozenset(
    {"table", "list", "landmark", "blockQuote", "frame"}
)
