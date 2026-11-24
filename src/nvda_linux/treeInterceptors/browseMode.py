# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Browse Mode / Focus Mode sobre um :class:`VirtualBuffer` (``browseMode`` do NVDA).

* Modo de navegação: o leitor mantém um cursor virtual no buffer; setas,
  Home/End, PageUp/PageDown e as teclas rápidas (H, K, F, T, B, E, L, I, G, D,
  1 a 6...; com Shift para voltar) movem esse cursor e falam o conteúdo com as
  informações de campo ("link", "cabeçalho nível 2", "lista com 3 itens").
* Modo de foco (``pass_through``): as teclas vão ao aplicativo. A troca é
  automática ao focar campos editáveis e de volta ao sair deles, com os bipes
  ``BROWSE_MODE_TONE``/``FOCUS_MODE_TONE`` do contrato (ou fala, se o
  usuário desligar a indicação sonora).
* Ctrl+Alt+setas navegam em tabelas; NVDA+F7 abre a lista de elementos.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any

from nvda_linux.contracts import (
    BROWSE_MODE_TONE,
    FOCUS_MODE_TONE,
    InputGesture,
    Script,
)
from nvda_linux.NVDAObjects import textUtils
from nvda_linux.NVDAObjects.controlTypes import (
    FOCUS_MODE_ROLES,
    OutputReason,
    Role,
    State,
    heading_label,
    landmark_label,
)
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, TextUnit
from nvda_linux.scripts import configUtils, objectSpeech, sayAll, ui
from nvda_linux.scripts.chain import refresh_grabs
from nvda_linux.scripts.scriptHandler import (
    gesture_modifiers,
    normalize_gesture_id,
    script,
)
from nvda_linux.treeInterceptors.base import NextHandler, TreeInterceptor
from nvda_linux.treeInterceptors.quickNav import (
    CONTAINER_KINDS,
    QUICK_NAV_TYPES,
    QuickNavType,
)
from nvda_linux.treeInterceptors.virtualBuffer import CELL_ROLES, BufferNode, VirtualBuffer

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject

log = logging.getLogger(__name__)

CATEGORY = "Modo de navegação"

ACTIVATABLE_ROLES = frozenset(
    {
        Role.LINK,
        Role.BUTTON,
        Role.TOGGLEBUTTON,
        Role.MENUBUTTON,
        Role.CHECKBOX,
        Role.RADIOBUTTON,
        Role.SWITCH,
        Role.COMBOBOX,
        Role.EDITABLETEXT,
        Role.PASSWORDEDIT,
        Role.TAB,
        Role.MENUITEM,
        Role.TREEVIEWITEM,
        Role.SLIDER,
        Role.SPINBUTTON,
    }
)
_CHECKABLE = frozenset({Role.CHECKBOX, Role.RADIOBUTTON, Role.SWITCH, Role.TOGGLEBUTTON})

MSG_FOCUS_MODE = "modo de foco"
MSG_BROWSE_MODE = "modo de navegação"
MSG_TOP = "início do documento"
MSG_BOTTOM = "fim do documento"
MSG_NOT_IN_TABLE = "Não está em uma tabela"
MSG_TABLE_EDGE = "borda da tabela"


class BufferTextBackend:
    """``TextBackend`` sobre o buffer; o cursor é o cursor virtual."""

    def __init__(self, ti: BrowseModeTreeInterceptor) -> None:
        self._ti = ti

    def length(self) -> int:
        return len(self._ti.buffer.text)

    def get_text(self, start: int, end: int) -> str:
        return self._ti.buffer.text[max(0, start) : max(0, end)]

    def unit_bounds(self, offset: int, unit: TextUnit) -> tuple[int, int]:
        return self._ti.buffer.unit_bounds(offset, unit)

    def caret(self) -> int:
        return self._ti.caret

    def set_caret(self, offset: int) -> bool:
        self._ti.caret = textUtils.clamp(offset, self.length())
        return True

    def selection(self) -> tuple[int, int] | None:
        return self._ti.selection

    def set_selection(self, start: int, end: int) -> bool:
        self._ti.selection = (start, end) if start != end else None
        return True

    def attributes_at(self, offset: int) -> dict[str, str]:
        return {}


class _BufferLines:
    """Linhas do buffer virtual para o "ler tudo" (:mod:`nvda_linux.scripts.sayAll`)."""

    def __init__(self, ti: BrowseModeTreeInterceptor, offset: int) -> None:
        self._ti = ti
        self._pos = ti.buffer.unit_bounds(offset, TextUnit.LINE)[0]
        self._previous: int | None = None

    def next_line(self) -> tuple[int, list[str]] | None:
        buffer = self._ti.buffer
        while self._pos < len(buffer.text):
            start, end = buffer.unit_bounds(self._pos, TextUnit.LINE)
            if end <= start:
                return None
            seq = self._ti.speech_for_range(start, end, self._previous, blank_ok=False)
            self._previous = start
            self._pos = end
            if seq:
                return start, seq
        return None

    def move_to(self, position: int) -> None:
        # O buffer pode ter sido reconstruído durante a leitura.
        self._ti.caret = textUtils.clamp(position, max(0, len(self._ti.buffer.text) - 1))


class BrowseModeTreeInterceptor(TreeInterceptor):
    """Modo de navegação de um documento web."""

    def __init__(self, root: LinuxNVDAObject, buffer: VirtualBuffer | None = None) -> None:
        super().__init__(root)
        self.buffer = buffer or VirtualBuffer(
            root,
            max_line_length=configUtils.get_int("browseMode.maxLineLength", 100),
            max_nodes=configUtils.get_int("browseMode.maxNodes", 20000),
        )
        self.caret = 0
        self.selection: tuple[int, int] | None = None
        self.single_letter_navigation = True
        self._pass_through_auto = False
        self._announced = False
        self._ignore_focus_key: Hashable | None = None
        self._pending: dict[Hashable, LinuxNVDAObject] = {}
        self._update_handle: asyncio.TimerHandle | None = None
        if not configUtils.get_bool("browseMode.enableOnPageLoad", True):
            self._pass_through = True

    # ------------------------------------------------------------ estado
    @property
    def is_ready(self) -> bool:
        return self.buffer.ready

    def build(self) -> None:
        """Constrói (ou reconstrói) o buffer preservando o cursor."""
        saved = self._save_caret()
        try:
            self.buffer.build()
        except Exception:
            log.exception("Falha ao construir o buffer virtual")
        self.forget_containment()
        self._restore_caret(saved)

    def ensure_ready(self) -> bool:
        if not self.buffer.ready:
            self.build()
        return self.buffer.ready and len(self.buffer.text) > 0

    def _save_caret(self) -> tuple[Hashable, int] | None:
        if not self.buffer.ready:
            return None
        node = self.buffer.deepest_node_at(self.caret)
        if node is None:
            return None
        return node.obj.key, self.caret - node.start

    def _restore_caret(self, saved: tuple[Hashable, int] | None) -> None:
        length = len(self.buffer.text)
        if saved is not None:
            key, rel = saved
            idx = self.buffer._by_key.get(key)
            if idx is not None:
                node = self.buffer.nodes[idx]
                self.caret = min(node.start + rel, max(node.start, node.end - 1))
                return
        self.caret = textUtils.clamp(self.caret, max(0, length - 1))

    def make_text_info(self, obj: LinuxNVDAObject | None = None) -> OffsetsTextInfo | None:
        if not self.ensure_ready():
            return None
        backend = BufferTextBackend(self)
        position = self.caret
        if obj is not None and obj != self.root:
            node = self.buffer.node_for(obj)
            if node is not None:
                position = node.start
        return OffsetsTextInfo(backend, position)

    def terminate(self) -> None:
        if self._update_handle is not None:
            self._update_handle.cancel()
            self._update_handle = None
        self._pending.clear()
        super().terminate()

    # ------------------------------------------------------------ modo de foco
    def set_pass_through(self, value: bool, auto: bool = False, announce: bool = True) -> None:
        if value == self._pass_through:
            return
        self._pass_through = value
        self._pass_through_auto = auto and value
        refresh_grabs()
        if announce:
            self.announce_mode()

    def announce_mode(self) -> None:
        if configUtils.get_bool("browseMode.passThroughAudioIndication", True):
            hz, duration = FOCUS_MODE_TONE if self._pass_through else BROWSE_MODE_TONE
            ui.beep(hz, duration)
        else:
            ui.message(MSG_FOCUS_MODE if self._pass_through else MSG_BROWSE_MODE)

    def requires_focus_mode(self, obj: LinuxNVDAObject) -> bool:
        """Objetos que, focados, pedem modo de foco (campos, listas, menus...)."""
        role = obj.role
        states = obj.states
        if obj == self.root:
            return False
        if role in (Role.EDITABLETEXT, Role.PASSWORDEDIT):
            return State.READONLY not in states
        if State.EDITABLE in states and role != Role.DOCUMENT:
            return True
        if role == Role.LIST:
            return State.FOCUSABLE in states
        if role == Role.LISTITEM:
            return State.SELECTABLE in states and State.FOCUSABLE in states
        if role in FOCUS_MODE_ROLES:
            return True
        node = obj.parent
        for _ in range(10):
            if node is None or node == self.root:
                break
            if node.role == Role.APPLICATION:
                return True
            node = node.parent
        return False

    # ------------------------------------------------------------ fala do buffer
    def field_start_speech(self, node: BufferNode) -> list[str]:
        """Informações faladas ao entrar num campo (como o NVDA em browse mode)."""
        role = node.role
        states = node.states
        if node.landmark:
            label = landmark_label(node.landmark)
            return [node.name, label] if node.name and role != Role.FORM else [label]
        if role == Role.HEADING:
            return [heading_label(node.level)]
        if role == Role.LINK:
            return ["link visitado" if State.VISITED in states else "link"]
        if role == Role.GRAPHIC:
            return ["gráfico"]
        if role == Role.LIST and node.item_count:
            return [f"lista com {node.item_count} {'item' if node.item_count == 1 else 'itens'}"]
        if role == Role.LIST:
            return ["lista"]
        if role == Role.TABLE:
            info = self.buffer.tables.get(node.index)
            if info is None or "table" not in node.kinds:
                return []
            return [f"tabela com {info.rows} linhas e {info.cols} colunas"]
        if role in CELL_ROLES and node.row is not None and node.col is not None:
            if configUtils.get_bool("documentFormatting.reportTableCellCoords", True):
                return [f"linha {node.row} coluna {node.col}"]
            return []
        if role == Role.BLOCKQUOTE:
            return ["citação"]
        if role == Role.SEPARATOR:
            return ["separador"]
        if role in (Role.DOCUMENT, Role.INTERNALFRAME) and "frame" in node.kinds:
            return [node.name, "quadro"] if node.name else ["quadro"]
        if role in (Role.BUTTON, Role.TOGGLEBUTTON, Role.MENUBUTTON):
            return [role.display_string, *objectSpeech.state_speech(node.obj, _QUICKNAV)]
        if role in (
            Role.EDITABLETEXT,
            Role.PASSWORDEDIT,
            Role.COMBOBOX,
            Role.CHECKBOX,
            Role.RADIOBUTTON,
            Role.SWITCH,
            Role.SLIDER,
            Role.SPINBUTTON,
            Role.PROGRESSBAR,
        ):
            parts = [node.name] if node.name else []
            parts.append(role.display_string)
            parts.extend(objectSpeech.state_speech(node.obj, _QUICKNAV))
            return parts
        return []

    @staticmethod
    def exit_speech(node: BufferNode) -> str:
        if node.role == Role.LIST:
            return "fora da lista"
        if node.role == Role.TABLE and "table" in node.kinds:
            return "fora da tabela"
        if node.role == Role.BLOCKQUOTE:
            return "fora da citação"
        if "frame" in node.kinds:
            return "fora do quadro"
        return ""

    def speech_for_range(
        self,
        start: int,
        end: int,
        previous_offset: int | None = None,
        unit: TextUnit = TextUnit.LINE,
        blank_ok: bool = True,
    ) -> list[str]:
        """Sequência de fala do intervalo com entradas e saídas de campos."""
        buffer = self.buffer
        seq: list[str] = []
        new_chain = buffer.ancestors_at(start)
        old_chain = buffer.ancestors_at(previous_offset) if previous_offset is not None else []
        new_set, old_set = set(new_chain), set(old_chain)
        for idx in reversed(old_chain):
            if idx not in new_set:
                label = self.exit_speech(buffer.nodes[idx])
                if label:
                    seq.append(label)
        for idx in new_chain:
            if idx == 0 or idx in old_set:
                continue
            seq.extend(s for s in self.field_start_speech(buffer.nodes[idx]) if s)
        content: list[str] = []
        if unit == TextUnit.CHARACTER:
            content.append(ui.character_name(buffer.text[start:end]))
        else:
            pos = start
            for node in buffer.nodes_starting_in(start, end):
                piece = buffer.text[pos : node.start].strip()
                field = [s for s in self.field_start_speech(node) if s]
                # Rótulo visível igual ao nome do campo ("Nome" + "Nome caixa de
                # edição"): fala uma vez só, pelo campo.
                if piece and not (field and piece.casefold() == field[0].strip().casefold()):
                    content.append(piece)
                content.extend(field)
                pos = node.start
            piece = buffer.text[pos:end]
            if piece.strip():
                content.append(piece.strip())
        seq.extend(content)
        if not seq and unit != TextUnit.CHARACTER and blank_ok:
            seq.append(ui.BLANK)
        return seq

    def _speak_range(
        self, start: int, end: int, previous: int | None, unit: TextUnit = TextUnit.LINE
    ) -> None:
        ui.cancel()
        ui.speak(self.speech_for_range(start, end, previous, unit))
        self._braille_line()

    def _braille_line(self) -> None:
        start, end = self.buffer.unit_bounds(self.caret, TextUnit.LINE)

        def route(offset: int) -> None:
            self.route_to(start + offset)

        ui.braille_show(self.buffer.text[start:end].rstrip("\n"), self.caret - start, route)

    def route_to(self, offset: int) -> None:
        """Roteamento braille: ativa o elemento sob a célula ou move o cursor até ela."""
        if not self.ensure_ready():
            return
        offset = textUtils.clamp(offset, max(0, len(self.buffer.text) - 1))
        node = self.actionable_node_at(offset)
        if node is not None and not self._pass_through:
            self.caret = offset
            self.activate_node(node)
            return
        self.move_caret_to(offset, TextUnit.CHARACTER)

    def report_current_line(self) -> None:
        if not self.ensure_ready():
            return
        start, end = self.buffer.unit_bounds(self.caret, TextUnit.LINE)
        self._speak_range(start, end, None)

    # ------------------------------------------------------------ movimento
    def move_by_unit(self, unit: TextUnit, direction: int) -> None:
        if not self.ensure_ready():
            ui.message("Documento vazio")
            return
        info = self.make_text_info()
        if info is None:
            return
        info.expand(unit)
        info.collapse()
        moved = info.move(unit, direction)
        if moved and unit == TextUnit.CHARACTER and self.buffer.text[info.start : info.start + 1] == "\n":
            extra = info.copy()
            if extra.move(unit, 1 if direction > 0 else -1):
                info = extra
        if moved == 0:
            ui.cancel()
            ui.speak([MSG_BOTTOM if direction > 0 else MSG_TOP])
            current = self.make_text_info()
            if current is not None:
                current.expand(unit)
                ui.speak(self.speech_for_range(current.start, current.end, None, unit))
            return
        self.move_caret_to(info.start, unit)

    def move_caret_to(self, offset: int, unit: TextUnit = TextUnit.LINE) -> None:
        """Move o cursor virtual, fala a unidade e trata foco automático."""
        old = self.caret
        self.caret = textUtils.clamp(offset, max(0, len(self.buffer.text) - 1))
        start, end = self.buffer.unit_bounds(self.caret, unit)
        if unit == TextUnit.CHARACTER:
            end = min(end, start + 1)
        self._speak_range(start, end, old, unit)
        self._after_caret_move()

    def move_to_node(self, node: BufferNode, quick_nav: bool = True) -> None:
        """Leva o cursor ao início do nó e fala o elemento (navegação rápida)."""
        old = self.caret
        self.caret = node.start
        end = node.end
        if CONTAINER_KINDS & node.kinds or end <= node.start:
            end = max(node.start + 1, min(node.end, self.buffer.unit_bounds(node.start, TextUnit.LINE)[1]))
        self._speak_range(node.start, end, old)
        self._after_caret_move()

    def _after_caret_move(self) -> None:
        node = self.buffer.deepest_node_at(self.caret)
        if node is None:
            return
        obj = node.obj
        if (
            configUtils.get_bool("browseMode.autoPassThroughOnCaretMove", False)
            and self.requires_focus_mode(obj)
        ):
            self._ignore_focus_key = obj.key
            obj.set_focus()
            self.set_pass_through(True, auto=True)
            return
        if configUtils.get_bool("browseMode.autoFocusFocusableElements", False):
            target = self._focusable_at(node)
            if target is not None:
                self._ignore_focus_key = target.key
                target.set_focus()

    def _focusable_at(self, node: BufferNode) -> LinuxNVDAObject | None:
        current: BufferNode | None = node
        while current is not None and current.index != 0:
            if State.FOCUSABLE in current.states:
                return current.obj
            current = self.buffer.nodes[current.parent] if current.parent >= 0 else None
        return None

    def quick_nav(self, qtype: QuickNavType, forward: bool) -> None:
        if not self.ensure_ready():
            return
        node = self.buffer.next_of_kind(qtype.kind, self.caret, forward)
        if node is None:
            ui.message(qtype.not_found_next if forward else qtype.not_found_previous)
            return
        self.move_to_node(node)

    # ------------------------------------------------------------ ativação
    def actionable_node_at(self, offset: int) -> BufferNode | None:
        node = self.buffer.deepest_node_at(offset)
        while node is not None and node.index != 0:
            if node.role in ACTIVATABLE_ROLES:
                return node
            node = self.buffer.nodes[node.parent] if node.parent >= 0 else None
        return None

    def activate_node(self, node: BufferNode) -> None:
        obj = node.obj
        if self.requires_focus_mode(obj):
            self._ignore_focus_key = None
            obj.set_focus()
            self.set_pass_through(True)
            return
        if obj.do_action(0):
            if node.role in _CHECKABLE:
                self._report_state_later(obj)
            return
        if not obj.set_focus():
            ui.message("Sem ação disponível")

    def _report_state_later(self, obj: LinuxNVDAObject) -> None:
        def report() -> None:
            obj.invalidate_cache()
            labels = objectSpeech.state_speech(obj, _QUICKNAV)
            if labels:
                ui.speak(labels)

        _call_later(0.15, report)

    # ------------------------------------------------------------ tabelas
    def table_move(self, drow: int, dcol: int) -> None:
        if not self.ensure_ready():
            return
        cell = self.buffer.cell_at(self.caret)
        if cell is None or cell.table is None or cell.row is None or cell.col is None:
            ui.message(MSG_NOT_IN_TABLE)
            return
        table = self.buffer.tables.get(cell.table)
        if table is None:
            ui.message(MSG_NOT_IN_TABLE)
            return
        row, col = cell.row + drow, cell.col + dcol
        target_idx = table.cells.get((row, col))
        while target_idx == cell.index and 1 <= row <= table.rows and 1 <= col <= table.cols:
            row, col = row + drow, col + dcol
            target_idx = table.cells.get((row, col))
        if target_idx is None:
            ui.message(MSG_TABLE_EDGE)
            return
        target = self.buffer.nodes[target_idx]
        self.caret = target.start
        seq: list[str] = []
        if drow:
            seq.append(f"linha {target.row}")
        if dcol:
            header_idx = table.cells.get((1, target.col or 1))
            if header_idx is not None and header_idx != target.index:
                header = self.buffer.nodes[header_idx]
                if header.role == Role.TABLECOLUMNHEADER:
                    seq.append(self.buffer.text[header.start : header.end].strip())
            seq.append(f"coluna {target.col}")
        content = self.buffer.text[target.start : target.end].strip()
        seq.append(content or ui.BLANK)
        ui.cancel()
        ui.speak(seq)
        self._braille_line()

    # ------------------------------------------------------------ ler tudo
    def say_all(self, from_offset: int | None = None, *, cancel: bool = True) -> None:
        """Lê do cursor até o fim em lotes; o cursor acompanha a fala (índices)."""
        if not self.ensure_ready():
            return
        offset = self.caret if from_offset is None else from_offset
        sayAll.start(_BufferLines(self, offset), cancel=cancel)

    def announce_load(self) -> None:
        """Página carregada: fala o título e lê tudo (ou a primeira linha)."""
        self._announced = True
        title = self.root.name.strip()
        ui.cancel()
        if title:
            ui.speak([title])
        notice = self.buffer.truncation_notice()
        if notice:
            ui.speak([notice])
        if configUtils.get_bool("browseMode.autoSayAllOnPageLoad", True):
            self.say_all(0, cancel=False)  # o título e o aviso acima continuam na fila
        else:
            self.caret = 0
            start, end = self.buffer.unit_bounds(0, TextUnit.LINE)
            ui.speak(self.speech_for_range(start, end, None))

    # ------------------------------------------------------------ atualização incremental
    def schedule_update(self, obj: LinuxNVDAObject) -> None:
        """Agenda a re-renderização de ``obj`` (com coalescência)."""
        if not self.buffer.ready:
            return
        self._pending[obj.key] = obj
        if self._update_handle is not None:
            return
        delay = configUtils.get_int("browseMode.updateDelayMs", 150) / 1000.0
        self._update_handle = _call_later(delay, self.flush_updates)

    def flush_updates(self) -> None:
        self._update_handle = None
        pending = list(self._pending.values())
        self._pending.clear()
        if not pending or not self.buffer.ready:
            return
        saved = self._save_caret()
        keys = {p.key for p in pending}
        full = False
        for obj in pending:
            if any(a.key in keys for a in obj.ancestors(50)):
                continue  # um ancestral também será atualizado
            if obj == self.root or not self.buffer.update_subtree(obj):
                full = True
                break
        if full:
            try:
                self.buffer.build()
            except Exception:
                log.exception("Falha ao reconstruir o buffer")
        self.forget_containment()
        self._restore_caret(saved)

    def on_load_complete(self, active: bool) -> None:
        self.build()
        if active and not self._announced:
            self.announce_load()

    # ------------------------------------------------------------ eventos
    def event_gainFocus(self, obj: LinuxNVDAObject, next_handler: NextHandler) -> None:
        if obj == self.root:
            busy = State.BUSY in obj.states
            if not busy:
                self.ensure_ready()
            if self._pass_through and self._pass_through_auto:
                self.set_pass_through(False)
            next_handler()
            if not busy and self.buffer.ready:
                if not self._announced:
                    self.announce_load()
                else:
                    self.report_current_line()
            return
        if self.buffer.ready:
            node = self.buffer.node_for(obj)
            if node is None:
                self.build()
                node = self.buffer.node_for(obj)
            if node is not None:
                self.caret = node.start
        if self._ignore_focus_key is not None and self._ignore_focus_key == obj.key:
            self._ignore_focus_key = None
            return
        self._ignore_focus_key = None
        needs_focus_mode = self.requires_focus_mode(obj)
        if (
            needs_focus_mode
            and not self._pass_through
            and configUtils.get_bool("browseMode.autoPassThroughOnFocusChange", True)
        ):
            self.set_pass_through(True, auto=True)
        elif not needs_focus_mode and self._pass_through and self._pass_through_auto:
            self.set_pass_through(False)
        next_handler()

    def event_caret(self, obj: LinuxNVDAObject, next_handler: NextHandler) -> None:
        next_handler()

    # ------------------------------------------------------------ gestos
    def get_script(self, gesture: InputGesture) -> Script | None:
        gid = normalize_gesture_id(gesture.identifier)
        if gid == "kb:escape" and not self._pass_through:
            return None
        fn = super().get_script(gesture)
        if (
            fn is not None
            and getattr(fn, "_nvda_quick_nav", False)
            and not self.single_letter_navigation
        ):
            return None
        if fn is None and not self._pass_through and self._should_trap(gesture):
            return self._trap
        return fn

    def _should_trap(self, gesture: InputGesture) -> bool:
        if not configUtils.get_bool("browseMode.trapNonCommandGestures", True):
            return False
        if gesture.is_modifier_only or not self.single_letter_navigation:
            return False
        ch = gesture.character
        if not ch or not ch.isprintable() or ch.isspace():
            return False
        mods = gesture_modifiers(gesture.identifier)
        return not mods - {"shift"}

    def _trap(self, gesture: InputGesture) -> None:
        """Engole teclas de digitação no modo de navegação (como o NVDA)."""

    @script(description="Próxima linha", category=CATEGORY, gesture="kb:downarrow")
    def script_nextLine(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.LINE, 1)

    @script(description="Linha anterior", category=CATEGORY, gesture="kb:uparrow")
    def script_previousLine(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.LINE, -1)

    @script(description="Próximo caractere", category=CATEGORY, gesture="kb:rightarrow")
    def script_nextCharacter(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.CHARACTER, 1)

    @script(description="Caractere anterior", category=CATEGORY, gesture="kb:leftarrow")
    def script_previousCharacter(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.CHARACTER, -1)

    @script(description="Próxima palavra", category=CATEGORY, gesture="kb:control+rightarrow")
    def script_nextWord(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.WORD, 1)

    @script(description="Palavra anterior", category=CATEGORY, gesture="kb:control+leftarrow")
    def script_previousWord(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.WORD, -1)

    @script(description="Próximo parágrafo", category=CATEGORY, gesture="kb:control+downarrow")
    def script_nextParagraph(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.PARAGRAPH, 1)

    @script(description="Parágrafo anterior", category=CATEGORY, gesture="kb:control+uparrow")
    def script_previousParagraph(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.PARAGRAPH, -1)

    @script(description="Início da linha", category=CATEGORY, gesture="kb:home")
    def script_startOfLine(self, gesture: InputGesture) -> None:
        if self.ensure_ready():
            start, _end = self.buffer.unit_bounds(self.caret, TextUnit.LINE)
            self.move_caret_to(start, TextUnit.CHARACTER)

    @script(description="Fim da linha", category=CATEGORY, gesture="kb:end")
    def script_endOfLine(self, gesture: InputGesture) -> None:
        if self.ensure_ready():
            start, end = self.buffer.unit_bounds(self.caret, TextUnit.LINE)
            last = end - 1
            if last > start and self.buffer.text[last] == "\n":
                last -= 1
            self.move_caret_to(max(start, last), TextUnit.CHARACTER)

    @script(description="Início do documento", category=CATEGORY, gesture="kb:control+home")
    def script_top(self, gesture: InputGesture) -> None:
        if self.ensure_ready():
            self.move_caret_to(0)

    @script(description="Fim do documento", category=CATEGORY, gesture="kb:control+end")
    def script_bottom(self, gesture: InputGesture) -> None:
        if self.ensure_ready():
            last_start = self.buffer.unit_bounds(max(0, len(self.buffer.text) - 1), TextUnit.LINE)[0]
            self.move_caret_to(last_start)

    @script(description="Página abaixo", category=CATEGORY, gesture="kb:pagedown")
    def script_pageDown(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.LINE, configUtils.get_int("browseMode.linesPerPage", 25))

    @script(description="Página acima", category=CATEGORY, gesture="kb:pageup")
    def script_pageUp(self, gesture: InputGesture) -> None:
        self.move_by_unit(TextUnit.LINE, -configUtils.get_int("browseMode.linesPerPage", 25))

    @script(
        description="Ativa o elemento sob o cursor",
        category=CATEGORY,
        gestures=("kb:enter", "kb:numpadenter", "kb:space"),
    )
    def script_activatePosition(self, gesture: InputGesture) -> None:
        if not self.ensure_ready():
            return
        node = self.actionable_node_at(self.caret)
        if node is None:
            ui.message("Nada para ativar aqui")
            return
        self.activate_node(node)

    @script(
        description="Alterna entre modo de navegação e modo de foco",
        category=CATEGORY,
        gesture="kb:nvda+space",
        allow_in_pass_through=True,
    )
    def script_togglePassThrough(self, gesture: InputGesture) -> None:
        if not self._pass_through and self.ensure_ready():
            node = self.buffer.deepest_node_at(self.caret)
            target = self._focusable_at(node) if node is not None else None
            if target is not None:
                self._ignore_focus_key = target.key
                target.set_focus()
        self.set_pass_through(not self._pass_through)

    @script(
        description="Volta ao modo de navegação",
        category=CATEGORY,
        gesture="kb:escape",
        allow_in_pass_through=True,
    )
    def script_disablePassThrough(self, gesture: InputGesture) -> None:
        self.set_pass_through(False)

    @script(
        description="Lista de elementos (links, cabeçalhos, campos, botões, pontos de referência)",
        category=CATEGORY,
        gesture="kb:nvda+f7",
        allow_in_pass_through=True,
    )
    def script_elementsList(self, gesture: InputGesture) -> None:
        if not self.ensure_ready():
            return
        from nvda_linux import gui
        from nvda_linux.treeInterceptors.elementsList import ElementsListModel

        model = ElementsListModel(self)
        if not gui.show_elements_list(model):
            ui.message(model.summary())

    @script(description="Recarrega o documento no buffer", category=CATEGORY, gesture="kb:nvda+f5")
    def script_refreshBuffer(self, gesture: InputGesture) -> None:
        self.build()
        notice = self.buffer.truncation_notice()
        ui.message(f"Atualizado. {notice}" if notice else "Atualizado")

    @script(
        description="Liga ou desliga a navegação por letra única",
        category=CATEGORY,
        gesture="kb:nvda+shift+space",
    )
    def script_toggleSingleLetterNavigation(self, gesture: InputGesture) -> None:
        self.single_letter_navigation = not self.single_letter_navigation
        refresh_grabs()
        ui.message(
            "Navegação por letra única "
            + ("ativada" if self.single_letter_navigation else "desativada")
        )

    @script(description="Lê tudo a partir do cursor", category=CATEGORY,
            desktop_gestures=("kb:nvda+downarrow",), laptop_gestures=("kb:nvda+a",))
    def script_sayAll(self, gesture: InputGesture) -> None:
        self.say_all()

    @script(description="Fala a linha atual", category=CATEGORY,
            desktop_gestures=("kb:nvda+uparrow",), laptop_gestures=("kb:nvda+l",))
    def script_reportCurrentLine(self, gesture: InputGesture) -> None:
        if gesture.repeat_count >= 1 and self.ensure_ready():
            start, end = self.buffer.unit_bounds(self.caret, TextUnit.LINE)
            ui.speak_spelling(self.buffer.text[start:end].strip())
            return
        self.report_current_line()

    @script(description="Próxima linha da tabela", category=CATEGORY,
            gesture="kb:control+alt+downarrow")
    def script_nextRow(self, gesture: InputGesture) -> None:
        self.table_move(1, 0)

    @script(description="Linha anterior da tabela", category=CATEGORY,
            gesture="kb:control+alt+uparrow")
    def script_previousRow(self, gesture: InputGesture) -> None:
        self.table_move(-1, 0)

    @script(description="Próxima coluna da tabela", category=CATEGORY,
            gesture="kb:control+alt+rightarrow")
    def script_nextColumn(self, gesture: InputGesture) -> None:
        self.table_move(0, 1)

    @script(description="Coluna anterior da tabela", category=CATEGORY,
            gesture="kb:control+alt+leftarrow")
    def script_previousColumn(self, gesture: InputGesture) -> None:
        self.table_move(0, -1)


_QUICKNAV = OutputReason.QUICKNAV


def _call_later(delay: float, callback: Callable[[], None]) -> asyncio.TimerHandle | None:
    """Agenda no loop asyncio corrente; sem loop, executa já (testes, modo degradado)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        callback()
        return None
    return loop.call_later(delay, callback)


def _make_quick_nav_script(qtype: QuickNavType, forward: bool) -> Callable[..., Any]:
    def quick_nav_script(self: BrowseModeTreeInterceptor, gesture: InputGesture) -> None:
        self.quick_nav(qtype, forward)

    gesture = f"kb:{qtype.key}" if forward else f"kb:shift+{qtype.key}"
    description = qtype.description_next if forward else qtype.description_previous
    decorated = script(description=description, category=CATEGORY, gesture=gesture)(
        quick_nav_script
    )
    decorated._nvda_quick_nav = True  # type: ignore[attr-defined]
    return decorated


for _qtype in QUICK_NAV_TYPES:
    for _forward in (True, False):
        _name = f"script_{'next' if _forward else 'previous'}_{_qtype.kind}"
        setattr(BrowseModeTreeInterceptor, _name, _make_quick_nav_script(_qtype, _forward))
