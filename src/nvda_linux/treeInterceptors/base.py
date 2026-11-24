"""Base dos treeInterceptors (``treeInterceptorHandler.TreeInterceptor``)."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING

from nvda_linux.contracts import InputGesture, Script
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo
from nvda_linux.scripts.scriptHandler import ScriptableObject, allowed_in_pass_through

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

NextHandler = Callable[[], None]

_CONTAINS_LIMIT = 300


class TreeInterceptor(ScriptableObject):
    """Intercepta gestos e eventos de toda uma subárvore (um documento)."""

    def __init__(self, root: LinuxNVDAObject) -> None:
        super().__init__()
        self.root = root
        self._pass_through = False
        self._contains_cache: dict[Hashable, bool] = {}

    # ------------------------------------------------------------ estado
    @property
    def pass_through(self) -> bool:
        """``True`` = modo de foco (teclas vão direto ao aplicativo)."""
        return self._pass_through

    @pass_through.setter
    def pass_through(self, value: bool) -> None:
        self._pass_through = value

    @property
    def is_alive(self) -> bool:
        return not self.root.is_dead

    @property
    def is_ready(self) -> bool:
        return True

    def contains(self, obj: LinuxNVDAObject) -> bool:
        """``obj`` é a raiz ou está dentro dela?"""
        if obj == self.root:
            return True
        cached = self._contains_cache.get(obj.key)
        if cached is not None:
            return cached
        result = obj.is_descendant_of(self.root, _CONTAINS_LIMIT)
        self._contains_cache[obj.key] = result
        return result

    def forget_containment(self) -> None:
        self._contains_cache.clear()

    def make_text_info(self, obj: LinuxNVDAObject | None = None) -> OffsetsTextInfo | None:
        """TextInfo do documento (para o cursor de revisão)."""
        return None

    def terminate(self) -> None:
        """Chamado quando o documento morre ou o leitor encerra."""
        self._contains_cache.clear()

    # ------------------------------------------------------------ gestos
    def get_script(self, gesture: InputGesture) -> Script | None:
        fn = super().get_script(gesture)
        if fn is not None and self._pass_through and not allowed_in_pass_through(fn):
            return None
        return fn
