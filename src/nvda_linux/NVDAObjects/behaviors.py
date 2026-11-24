"""Comportamentos overlay (``NVDAObjects.behaviors`` do NVDA).

* :class:`EditableText`: scripts das setas/Home/End/PageUp/PageDown que
  repassam a tecla ao aplicativo, esperam o ``object:text-caret-moved`` e falam
  o caractere, a palavra ou a linha (como o ``editableText`` do NVDA); eco de
  digitação por caractere e por palavra a partir de ``text-changed:insert``.
* :class:`Terminal`: além disso, fala a saída nova do terminal.
"""

from __future__ import annotations

import asyncio
import logging

from nvda_linux import services
from nvda_linux.contracts import InputGesture
from nvda_linux.NVDAObjects.base import LinuxNVDAObject, register_overlay_chooser
from nvda_linux.NVDAObjects.controlTypes import Role, State
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, Position, TextUnit
from nvda_linux.scripts import configUtils, ui
from nvda_linux.scripts.scriptHandler import script

log = logging.getLogger(__name__)

_WORD_CHARS_EXTRA = "-_'"


class EditableText(LinuxNVDAObject):
    """Campo de texto editável com anúncio de movimento do cursor."""

    #: Tempo máximo (s) esperando o evento de cursor após repassar a tecla.
    caret_timeout: float = 0.15
    _nvda_caret_event: asyncio.Event | None = None
    _nvda_word_buffer: str = ""

    def _caret_event(self) -> asyncio.Event | None:
        return self._nvda_caret_event

    def _echo_word(self) -> str:
        return self._nvda_word_buffer

    def _set_echo_word(self, value: str) -> None:
        self._nvda_word_buffer = value

    def _caret_offset(self) -> int:
        return self.make_text_info(Position.CARET).start

    async def _send_and_wait(self, gesture: InputGesture) -> bool:
        """Repassa a tecla e espera o cursor mover. ``True`` se moveu."""
        before = self._caret_offset()
        event = asyncio.Event()
        self._nvda_caret_event = event
        try:
            services.dispatcher().send_through(gesture)
        except Exception as exc:  # noqa: BLE001
            log.debug("send_through indisponível: %s", exc)
        try:
            await asyncio.wait_for(event.wait(), self.caret_timeout)
        except TimeoutError:
            pass
        finally:
            self._nvda_caret_event = None
        self.invalidate_cache("value")
        return self._caret_offset() != before

    async def _move_and_speak(self, gesture: InputGesture, unit: TextUnit) -> None:
        await self._send_and_wait(gesture)
        from nvda_linux.scripts import objectSpeech

        info = self.make_text_info(Position.CARET)
        info.expand(unit)
        ui.cancel()
        objectSpeech.speak_text_unit(info, unit)
        self._update_review_and_braille(info)

    def _update_review_and_braille(self, info: OffsetsTextInfo) -> None:
        from nvda_linux.scripts import runtime

        rt = runtime.current()
        if (
            rt is not None
            and rt.focus.navigator == self
            and configUtils.get_bool("reviewCursor.followCaret", True)
        ):
            rt.focus.reset_review_to_caret()
        line = self.make_text_info(Position.CARET)
        caret = line.start
        line.expand(TextUnit.LINE)
        line_start = line.start

        def route(offset: int) -> None:
            target = OffsetsTextInfo(line.backend, line_start + offset)
            target.update_caret()

        ui.braille_show(line.text.rstrip("\n"), caret - line.start, route)

    @script(
        description="Move o cursor por linha e fala a linha",
        gestures=(
            "kb:uparrow",
            "kb:downarrow",
            "kb:pageup",
            "kb:pagedown",
            "kb:control+home",
            "kb:control+end",
        ),
    )
    async def script_caret_moveByLine(self, gesture: InputGesture) -> None:
        await self._move_and_speak(gesture, TextUnit.LINE)

    @script(
        description="Move o cursor por caractere e fala o caractere",
        gestures=("kb:leftarrow", "kb:rightarrow", "kb:home", "kb:end"),
    )
    async def script_caret_moveByCharacter(self, gesture: InputGesture) -> None:
        await self._move_and_speak(gesture, TextUnit.CHARACTER)

    @script(
        description="Move o cursor por palavra e fala a palavra",
        gestures=("kb:control+leftarrow", "kb:control+rightarrow"),
    )
    async def script_caret_moveByWord(self, gesture: InputGesture) -> None:
        await self._move_and_speak(gesture, TextUnit.WORD)

    @script(
        description="Move o cursor por parágrafo e fala o parágrafo",
        gestures=("kb:control+uparrow", "kb:control+downarrow"),
    )
    async def script_caret_moveByParagraph(self, gesture: InputGesture) -> None:
        await self._move_and_speak(gesture, TextUnit.PARAGRAPH)

    @script(description="Apaga o caractere antes do cursor e o fala", gesture="kb:backspace")
    async def script_caret_backspaceCharacter(self, gesture: InputGesture) -> None:
        info = self.make_text_info(Position.CARET)
        deleted = ""
        if info.start > 0:
            prev = OffsetsTextInfo(info.backend, (info.start - 1, info.start))
            deleted = prev.text
        moved = await self._send_and_wait(gesture)
        if moved and deleted:
            ui.cancel()
            ui.speak_character(deleted)
        self._set_echo_word(self._echo_word()[:-1])

    @script(description="Apaga o caractere sob o cursor e fala o seguinte", gesture="kb:delete")
    async def script_caret_delete(self, gesture: InputGesture) -> None:
        await self._move_and_speak(gesture, TextUnit.CHARACTER)

    @script(
        description="Seleciona texto e fala a seleção",
        gestures=(
            "kb:shift+leftarrow",
            "kb:shift+rightarrow",
            "kb:shift+uparrow",
            "kb:shift+downarrow",
            "kb:control+shift+leftarrow",
            "kb:control+shift+rightarrow",
            "kb:shift+home",
            "kb:shift+end",
            "kb:control+shift+home",
            "kb:control+shift+end",
            "kb:control+a",
        ),
    )
    async def script_caret_changeSelection(self, gesture: InputGesture) -> None:
        before = self.make_text_info(Position.SELECTION)
        old = (before.start, before.end)
        await self._send_and_wait(gesture)
        after = self.make_text_info(Position.SELECTION)
        ui.cancel()
        speak_selection_change(after, old)

    # ------------------------------------------------------------ eventos
    def event_caret(self) -> None:
        event = self._caret_event()
        if event is not None:
            event.set()
        self.invalidate_cache("value")

    def event_textChange(self, inserted: str, deleted: str) -> None:
        from nvda_linux.scripts import objectSpeech

        self.invalidate_cache("value")
        if not objectSpeech.is_focus(self):
            return
        if deleted and not inserted:
            return
        if len(inserted) != 1:
            self._set_echo_word("")
            return
        if platform_echoes_typing():
            return  # a PLATAFORMA já faz o eco a partir do teclado
        ch = inserted
        protected = State.PROTECTED in self.states
        if configUtils.get_bool("keyboard.speakTypedCharacters", True):
            ui.speak(["asterisco" if protected else ui.character_name(ch)])
        if ch.isalnum() or ch in _WORD_CHARS_EXTRA:
            self._set_echo_word(self._echo_word() + ch)
            return
        word = self._echo_word()
        self._set_echo_word("")
        if word and not protected and configUtils.get_bool("keyboard.speakTypedWords", False):
            ui.speak([word])


def platform_echoes_typing() -> bool:
    """A fala da PLATAFORMA tem eco de digitação próprio (``on_typed_character``)?"""
    try:
        return callable(getattr(services.speech(), "on_typed_character", None))
    except Exception:  # noqa: BLE001
        return False


def speak_selection_change(after: OffsetsTextInfo, old: tuple[int, int]) -> None:
    """Fala o que foi selecionado ou desmarcado (como o NVDA)."""
    old_start, old_end = old
    if after.start == after.end:
        if old_start != old_end:
            ui.speak(["seleção removida"])
        return
    if after.start == old_start and after.end > old_end:
        added = OffsetsTextInfo(after.backend, (max(old_end, after.start), after.end))
        ui.speak([added.text or ui.BLANK, "selecionado"])
    elif after.end == old_end and after.start < old_start:
        added = OffsetsTextInfo(after.backend, (after.start, old_start))
        ui.speak([added.text or ui.BLANK, "selecionado"])
    elif after.start == old_start and after.end < old_end:
        removed = OffsetsTextInfo(after.backend, (after.end, old_end))
        ui.speak([removed.text or ui.BLANK, "desmarcado"])
    elif after.end == old_end and after.start > old_start:
        removed = OffsetsTextInfo(after.backend, (old_start, after.start))
        ui.speak([removed.text or ui.BLANK, "desmarcado"])
    else:
        ui.speak([after.text or ui.BLANK, "selecionado"])


class Terminal(EditableText):
    """Terminal: fala a saída nova (``text-changed:insert`` com mais de um caractere)."""

    def event_textChange(self, inserted: str, deleted: str) -> None:
        if len(inserted) == 1 and inserted != "\n":
            super().event_textChange(inserted, deleted)
            return
        self.invalidate_cache("value")
        if not inserted.strip():
            return
        if not configUtils.get_bool("presentation.reportDynamicContentChanges", True):
            return
        ui.speak([inserted.strip()])


def _choose(obj: LinuxNVDAObject, cls_list: list[type]) -> None:
    role = obj.role
    if role == Role.TERMINAL:
        cls_list.insert(0, Terminal)
    elif obj.has_text and (
        role in (Role.EDITABLETEXT, Role.PASSWORDEDIT)
        or (role == Role.DOCUMENT and State.EDITABLE in obj.states)
    ):
        cls_list.insert(0, EditableText)


register_overlay_chooser(_choose)
