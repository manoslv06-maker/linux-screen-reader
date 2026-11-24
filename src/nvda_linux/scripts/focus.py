"""Foco, janela em primeiro plano, objeto de navegação e cursor de revisão.

Implementa ``contracts.FocusTracker`` (registrado como ``"focus"``). Faz o
papel do ``api``/``eventHandler.doPreGainFocus`` do NVDA: guarda o foco,
calcula os ancestrais recém-entrados (falados antes do foco), faz o
navegador seguir o foco e troca o perfil de configuração ao mudar de app.
"""

from __future__ import annotations

import logging
from collections.abc import Hashable
from typing import TYPE_CHECKING

from nvda_linux.NVDAObjects.controlTypes import Role
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, Position
from nvda_linux.scripts import configUtils

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

log = logging.getLogger(__name__)

#: Ancestrais nunca falados ao entrar (leiaute, janelas já anunciadas...).
_ANCESTOR_EXCLUDED_ROLES = frozenset(
    {
        Role.APPLICATION,
        Role.FRAME,
        Role.WINDOW,
        Role.DESKTOPPANE,
        Role.UNKNOWN,
        Role.ROOTPANE,
        Role.LAYEREDPANE,
        Role.SCROLLPANE,
        Role.VIEWPORT,
        Role.REDUNDANTOBJECT,
        Role.FILLER,
        Role.STATICTEXT,
        Role.PARAGRAPH,
        Role.LABEL,
        Role.TABLECELL,
        Role.TABLEROW,
        Role.LISTITEM,
        Role.MENUITEM,
        Role.TREEVIEWITEM,
        Role.SECTION,
        Role.PANEL,
        Role.GLASSPANE,
    }
)
#: Ancestrais falados mesmo sem nome.
_ANCESTOR_ALWAYS_ROLES = frozenset(
    {Role.DIALOG, Role.TABLE, Role.MENUBAR, Role.POPUPMENU, Role.TOOLBAR, Role.ALERT}
)


def speakable_ancestor(obj: LinuxNVDAObject) -> bool:
    role = obj.role
    if role in _ANCESTOR_ALWAYS_ROLES:
        return True
    named = bool(obj.name.strip())
    if role in (Role.PANEL, Role.SECTION, Role.PANE):
        return named or obj.landmark is not None
    if role in _ANCESTOR_EXCLUDED_ROLES:
        return False
    return named or obj.landmark is not None


class FocusManager:
    """Estado de foco do leitor de tela (implementa ``FocusTracker``)."""

    def __init__(self) -> None:
        self.focus: LinuxNVDAObject | None = None
        self.foreground: LinuxNVDAObject | None = None
        self.navigator: LinuxNVDAObject | None = None
        self._ancestors: list[LinuxNVDAObject] = []
        self._new_ancestors: list[LinuxNVDAObject] = []
        self._review: OffsetsTextInfo | None = None
        self._review_owner: Hashable | None = None
        self._last_pid: int | None = None

    # ------------------------------------------------------------ contrato
    def focus_description(self) -> str:
        """Texto curto do foco, para braille e depuração."""
        obj = self.focus
        if obj is None:
            return ""
        from nvda_linux.NVDAObjects.controlTypes import OutputReason
        from nvda_linux.scripts.objectSpeech import get_object_speech

        try:
            return " ".join(get_object_speech(obj, OutputReason.FOCUS))
        except Exception:
            log.exception("focus_description falhou")
            return obj.name

    def focus_is_protected(self) -> bool:
        """Foco num campo de senha? A PLATAFORMA deve suprimir o eco nesse caso."""
        obj = self.focus
        if obj is None:
            return False
        from nvda_linux.NVDAObjects.controlTypes import State

        try:
            return State.PROTECTED in obj.states
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ foco
    @property
    def ancestors(self) -> list[LinuxNVDAObject]:
        """Ancestrais do foco, do mais externo ao mais interno."""
        return list(self._ancestors)

    def set_focus(self, obj: LinuxNVDAObject) -> None:
        """Equivalente ao ``doPreGainFocus``: atualiza estado antes do anúncio."""
        old_keys = {a.key for a in self._ancestors}
        if self.focus is not None:
            old_keys.add(self.focus.key)
        chain = list(reversed(obj.ancestors()))
        self._ancestors = chain
        self._new_ancestors = [a for a in chain if a.key not in old_keys and speakable_ancestor(a)]
        self.focus = obj
        if configUtils.get_bool("reviewCursor.followFocus", True):
            self.set_navigator(obj)
        self._maybe_switch_profile(obj)

    def consume_new_ancestors(self) -> list[LinuxNVDAObject]:
        """Ancestrais a falar antes do foco (só uma vez por mudança de foco)."""
        result, self._new_ancestors = self._new_ancestors, []
        return result

    def set_foreground(self, obj: LinuxNVDAObject) -> None:
        """Nova janela em primeiro plano; ela (e os seus ancestrais) já foram
        anunciados, então não se repetem ao falar o próximo foco."""
        self.foreground = obj
        self._ancestors = [*reversed(obj.ancestors()), obj]
        self._new_ancestors = []

    def _maybe_switch_profile(self, obj: LinuxNVDAObject) -> None:
        pid = obj.process_id
        if pid == self._last_pid:
            return
        self._last_pid = pid
        app = obj.app_module
        profile = app.config_profile() if app is not None else None
        configUtils.activate_profile(profile)

    def clear(self) -> None:
        self.focus = self.foreground = self.navigator = None
        self._ancestors.clear()
        self._new_ancestors.clear()
        self._review = None
        self._review_owner = None
        self._last_pid = None

    # ------------------------------------------------------------ navegador/revisão
    def set_navigator(self, obj: LinuxNVDAObject) -> None:
        self.navigator = obj
        self._review = None
        self._review_owner = None

    def _make_review(self, obj: LinuxNVDAObject) -> OffsetsTextInfo:
        ti = obj.tree_interceptor
        if ti is not None and not ti.pass_through:
            info = ti.make_text_info(obj)
            if info is not None:
                return info
        follow_caret = obj == self.focus and obj.has_text
        return obj.make_text_info(Position.CARET if follow_caret else Position.FIRST)

    @property
    def review(self) -> OffsetsTextInfo | None:
        """Posição do cursor de revisão (recolhida) no objeto de navegação."""
        obj = self.navigator or self.focus
        if obj is None:
            return None
        if self._review is None or self._review_owner != obj.key:
            self._review = self._make_review(obj)
            self._review_owner = obj.key
        return self._review.copy()

    @review.setter
    def review(self, info: OffsetsTextInfo | None) -> None:
        obj = self.navigator or self.focus
        self._review = info.copy() if info is not None else None
        self._review_owner = obj.key if obj is not None and info is not None else None

    def reset_review_to_caret(self) -> None:
        """Usado quando o cursor do sistema move e ``followCaret`` está ligado."""
        self._review = None
        self._review_owner = None
