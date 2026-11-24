# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Como um objeto é falado (``speech.getObjectSpeech``/``speakObject`` do NVDA).

Ordem dos campos: nome, papel, estados, valor, descrição, atalho, posição.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from nvda_linux.NVDAObjects.controlTypes import (
    CHECKABLE_ROLES,
    FALLBACK_ROLE_LABELS,
    NEGATIVE_STATE_LABELS,
    SILENT_ROLES,
    SILENT_ROLES_ON_FOCUS,
    OutputReason,
    Role,
    State,
    heading_label,
    landmark_label,
)
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, TextUnit
from nvda_linux.scripts import configUtils, ui

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

#: Ordem em que os estados são falados.
STATE_ORDER: tuple[State, ...] = (
    State.UNAVAILABLE,
    State.CHECKED,
    State.HALFCHECKED,
    State.PRESSED,
    State.ON,
    State.SELECTED,
    State.EXPANDED,
    State.COLLAPSED,
    State.VISITED,
    State.HASPOPUP,
    State.REQUIRED,
    State.INVALID_ENTRY,
    State.READONLY,
    State.BUSY,
    State.MODAL,
    State.AUTOCOMPLETE,
    State.MULTILINE,
    State.SORTED_ASCENDING,
    State.SORTED_DESCENDING,
    State.ICONIFIED,
)

_READONLY_ROLES = frozenset({Role.EDITABLETEXT, Role.COMBOBOX, Role.SPINBUTTON})
_MULTILINE_ROLES = frozenset({Role.EDITABLETEXT})

#: Nome AT-SPI2 do estado em ``object:state-changed:<nome>`` -> rótulos (ligado, desligado).
STATE_CHANGE_LABELS: dict[str, tuple[str, str]] = {
    "checked": ("marcado", "não marcado"),
    "pressed": ("pressionado", "não pressionado"),
    "expanded": ("expandido", "recolhido"),
    "selected": ("selecionado", "não selecionado"),
    "indeterminate": ("parcialmente marcado", ""),
    "invalid-entry": ("entrada inválida", ""),
    "required": ("obrigatório", ""),
    "busy": ("ocupado", ""),
    "visited": ("visitado", ""),
    "sensitive": ("", "indisponível"),
}


def is_focus(obj: LinuxNVDAObject) -> bool:
    from nvda_linux.scripts import runtime

    rt = runtime.current()
    return rt is not None and rt.focus.focus is not None and rt.focus.focus == obj


def role_speech(obj: LinuxNVDAObject, reason: OutputReason) -> str:
    """Rótulo do papel, respeitando papéis silenciosos e casos especiais."""
    role = obj.role
    if role == Role.HEADING:
        return heading_label(obj.heading_level)
    landmark = obj.landmark
    if landmark:
        return landmark_label(landmark)
    silent = SILENT_ROLES_ON_FOCUS if reason == OutputReason.FOCUS else SILENT_ROLES
    if role in silent:
        return ""
    return role.display_string


def state_speech(obj: LinuxNVDAObject, reason: OutputReason) -> list[str]:
    states = obj.states
    role = obj.role
    result: list[str] = []
    for state in STATE_ORDER:
        if state not in states:
            continue
        if state == State.SELECTED and reason == OutputReason.FOCUS and State.SELECTABLE in states:
            continue
        if state == State.READONLY and role not in _READONLY_ROLES:
            continue
        if state == State.MULTILINE and role not in _MULTILINE_ROLES:
            continue
        if state == State.VISITED and role != Role.LINK:
            continue
        label = state.display_string
        if label:
            result.append(label)
    if role in CHECKABLE_ROLES and not states & {State.CHECKED, State.HALFCHECKED}:
        result.insert(0, NEGATIVE_STATE_LABELS[State.CHECKED])
    elif role == Role.TOGGLEBUTTON and State.PRESSED not in states:
        result.insert(0, NEGATIVE_STATE_LABELS[State.PRESSED])
    elif role == Role.SWITCH and State.ON not in states:
        result.insert(0, NEGATIVE_STATE_LABELS[State.ON])
    return result


def position_speech(obj: LinuxNVDAObject) -> list[str]:
    if not configUtils.get_bool("presentation.reportObjectPositionInformation", True):
        return []
    info = obj.position_info
    result: list[str] = []
    index, count = info.index_in_group, info.similar_count
    if index is not None and count is not None and count > 0:
        result.append(f"{index} de {count}")
    if info.level is not None and obj.role in (Role.TREEVIEWITEM, Role.LISTITEM):
        result.append(f"nível {info.level}")
    return result


def get_object_speech(obj: LinuxNVDAObject, reason: OutputReason = OutputReason.QUERY) -> list[str]:
    """Sequência de fala de um objeto."""
    parts: list[str] = []
    name = obj.name.strip()
    if name:
        parts.append(name)
    role_text = role_speech(obj, reason)
    if role_text:
        parts.append(role_text)
    parts.extend(state_speech(obj, reason))
    value = obj.value.strip()
    if value and value != name:
        parts.append(value)
    if configUtils.get_bool("presentation.reportObjectDescriptions", True):
        description = obj.description.strip()
        if description and description != name and description != value:
            parts.append(description)
    if configUtils.get_bool("presentation.reportKeyboardShortcuts", True):
        shortcut = obj.keyboard_shortcut
        if shortcut:
            parts.append(shortcut)
    parts.extend(position_speech(obj))
    return parts


def speak_object(obj: LinuxNVDAObject, reason: OutputReason = OutputReason.QUERY) -> None:
    """Fala o objeto; para o foco, inclui antes os ancestrais recém-entrados."""
    sequence: list[str] = []
    if reason == OutputReason.FOCUS:
        from nvda_linux.scripts import runtime

        rt = runtime.current()
        if rt is not None:
            for ancestor in rt.focus.consume_new_ancestors():
                sequence.extend(get_object_speech(ancestor, OutputReason.FOCUSENTERED))
    sequence.extend(get_object_speech(obj, reason))
    if not sequence:
        role_label = obj.role.display_string or FALLBACK_ROLE_LABELS.get(obj.role, "")
        sequence = [role_label] if role_label else [ui.BLANK]
    ui.speak(sequence)
    if reason == OutputReason.FOCUS:

        def route(_offset: int) -> None:
            if not obj.do_action(0):
                obj.set_focus()

        ui.braille_show("  ".join(get_object_speech(obj, reason)), None, route)


def speak_name_change(obj: LinuxNVDAObject) -> None:
    if obj.name:
        ui.speak([obj.name])


def state_change_label(state_name: str, enabled: bool) -> str:
    labels = STATE_CHANGE_LABELS.get(state_name.lower())
    if labels is None:
        return ""
    return labels[0] if enabled else labels[1]


def speak_state_change(obj: LinuxNVDAObject, state_name: str, enabled: bool) -> None:
    label = state_change_label(state_name, enabled)
    if label:
        ui.speak([label])


def speak_value_change(obj: LinuxNVDAObject) -> None:
    value = obj.value
    if value:
        ui.speak([value])


def text_unit_speech(info: OffsetsTextInfo, unit: TextUnit) -> list[str]:
    """Fala de uma unidade de texto (caractere por nome, linha vazia = em branco)."""
    text = info.text
    if unit == TextUnit.CHARACTER:
        return [ui.character_name(text)]
    stripped = text.rstrip()
    if not stripped.strip():
        return [ui.BLANK]
    return [stripped]


def speak_text_unit(info: OffsetsTextInfo, unit: TextUnit) -> None:
    ui.speak(text_unit_speech(info, unit))


def speak_sequence_of(objects: Sequence[LinuxNVDAObject], reason: OutputReason) -> None:
    sequence: list[str] = []
    for obj in objects:
        sequence.extend(get_object_speech(obj, reason))
    ui.speak(sequence)
