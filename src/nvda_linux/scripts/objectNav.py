# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Navegação por objetos (pai, irmãos, primeiro filho) com "revisão simples".

No modo simples (``reviewCursor.simpleReviewMode``, padrão do NVDA), objetos
de mero leiaute (painéis sem nome, fillers...) são achatados: os filhos deles
aparecem como irmãos do ponto de vista do usuário.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nvda_linux.NVDAObjects.controlTypes import Role

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

_MAX_FLATTEN_DEPTH = 12
_MAX_SIMPLE_CHILDREN = 500


def simple_children(obj: LinuxNVDAObject, depth: int = 0) -> list[LinuxNVDAObject]:
    """Filhos apresentáveis, descendo através dos contêineres de leiaute."""
    result: list[LinuxNVDAObject] = []
    for child in obj.children:
        if len(result) >= _MAX_SIMPLE_CHILDREN:
            break
        if child.is_presentable or depth >= _MAX_FLATTEN_DEPTH:
            result.append(child)
        else:
            result.extend(simple_children(child, depth + 1))
    return result


def parent(obj: LinuxNVDAObject, simple: bool = True) -> LinuxNVDAObject | None:
    node = obj.parent
    if not simple:
        return node
    while node is not None and not node.is_presentable and node.role != Role.APPLICATION:
        node = node.parent
    return node


def _siblings(obj: LinuxNVDAObject) -> tuple[list[LinuxNVDAObject], int] | None:
    container = parent(obj, simple=True)
    if container is None:
        return None
    siblings = simple_children(container)
    for i, sib in enumerate(siblings):
        if sib == obj:
            return siblings, i
    return None


def next_object(obj: LinuxNVDAObject, simple: bool = True) -> LinuxNVDAObject | None:
    if simple:
        found = _siblings(obj)
        if found is not None:
            siblings, i = found
            return siblings[i + 1] if i + 1 < len(siblings) else None
    return obj.next


def previous_object(obj: LinuxNVDAObject, simple: bool = True) -> LinuxNVDAObject | None:
    if simple:
        found = _siblings(obj)
        if found is not None:
            siblings, i = found
            return siblings[i - 1] if i > 0 else None
    return obj.previous


def first_child(obj: LinuxNVDAObject, simple: bool = True) -> LinuxNVDAObject | None:
    if simple:
        children = simple_children(obj)
        return children[0] if children else None
    return obj.first_child
