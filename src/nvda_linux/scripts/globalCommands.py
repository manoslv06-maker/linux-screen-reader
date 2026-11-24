# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Comandos globais do NVDA (``globalCommands.GlobalCommands``).

Os nomes dos scripts são os mesmos do NVDA (``navigatorObject_parent``,
``review_currentCharacter``, ``reportStatusLine``...), então um
``gestures.ini`` do NVDA (seção ``[globalCommands.GlobalCommands]``) e a
tabela de equivalência Desktop/Laptop da PLATAFORMA funcionam diretamente.

Layout Desktop: teclado numérico para revisão e navegação por objetos.
Layout Laptop: NVDA+Shift+setas, NVDA+setas, NVDA+Ctrl+setas etc.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import inspect
import logging
import os
import signal
from collections.abc import Callable
from typing import TYPE_CHECKING

from nvda_linux import services
from nvda_linux.contracts import InputGesture, Script
from nvda_linux.NVDAObjects.controlTypes import OutputReason, Role
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, Position, TextUnit
from nvda_linux.scripts import configUtils, objectNav, objectSpeech, sayAll, ui
from nvda_linux.scripts.scriptHandler import ScriptableObject, script

if TYPE_CHECKING:
    from nvda_linux.NVDAObjects.base import LinuxNVDAObject
    from nvda_linux.scripts.runtime import Runtime

log = logging.getLogger(__name__)

CAT_NAV = "Navegação por objetos"
CAT_REVIEW = "Cursor de revisão"
CAT_SYSTEM = "Foco e sistema"
CAT_SPEECH = "Fala"
CAT_TOOLS = "Ferramentas"

WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
            "sábado", "domingo")
MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")

MSG_NO_FOCUS = "Sem foco"
MSG_NO_NAVIGATOR = "Sem objeto de navegação"


def format_time(now: _dt.datetime) -> str:
    return now.strftime("%H:%M")


def format_date(now: _dt.date) -> str:
    """``"sábado, 21 de novembro de 2026"``."""
    return f"{WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]} de {now.year}"


def _runtime() -> Runtime | None:
    from nvda_linux.scripts import runtime

    return runtime.current()


def _optional_service(name: str) -> object | None:
    """Serviço opcional fora do contrato (ex.: ``"app"`` da PLATAFORMA)."""
    registry = getattr(services, "_registry", None)
    if isinstance(registry, dict):
        return registry.get(name)
    return None


def request_quit() -> None:
    """Encerra o leitor pela PLATAFORMA (``app.request_exit``) ou por SIGTERM."""
    app = _optional_service("app")
    for method in ("request_exit", "request_quit", "quit"):
        fn = getattr(app, method, None)
        if callable(fn):
            try:
                result = fn()
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
                return
            except Exception:
                log.exception("%s falhou", method)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        os.kill(os.getpid(), signal.SIGTERM)
        return
    loop.call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)


class _SleepModeProvider:
    """Com o modo dormir ativo, só NVDA+Shift+Z responde."""

    def __init__(self, commands: GlobalCommands) -> None:
        self._commands = commands

    def get_script(self, gesture: InputGesture) -> Script | None:
        fn = self._commands.get_script(gesture)
        if fn is not None and getattr(fn, "__name__", "") == "script_toggleSleepMode":
            return fn
        return None


class GlobalCommands(ScriptableObject):
    """Último elo da cadeia de scripts."""

    def __init__(self) -> None:
        super().__init__()
        self._speech_paused = False

    def sleep_mode_provider(self) -> _SleepModeProvider:
        return _SleepModeProvider(self)

    # ------------------------------------------------------------ utilidades
    @staticmethod
    def _focus() -> LinuxNVDAObject | None:
        rt = _runtime()
        return rt.focus.focus if rt is not None else None

    @staticmethod
    def _navigator() -> LinuxNVDAObject | None:
        rt = _runtime()
        if rt is None:
            return None
        return rt.focus.navigator or rt.focus.focus

    @staticmethod
    def _simple() -> bool:
        return configUtils.get_bool("reviewCursor.simpleReviewMode", True)

    def _foreground(self) -> LinuxNVDAObject | None:
        rt = _runtime()
        if rt is None:
            return None
        if rt.focus.foreground is not None:
            return rt.focus.foreground
        focus = rt.focus.focus
        if focus is None:
            return None
        from nvda_linux.scripts.eventHandler import active_window_of

        return active_window_of(focus)

    # ------------------------------------------------------------ foco e sistema
    @script(description="Fala o título da janela em primeiro plano; duas vezes soletra",
            category=CAT_SYSTEM, gesture="kb:nvda+t")
    def script_title(self, gesture: InputGesture) -> None:
        window = self._foreground()
        title = window.name.strip() if window is not None else ""
        if not title:
            ui.message("Sem título")
        elif gesture.repeat_count >= 1:
            ui.speak_spelling(title)
        else:
            ui.message(title)

    @script(description="Fala a barra de status; duas vezes soletra", category=CAT_SYSTEM,
            desktop_gestures=("kb:nvda+end",), laptop_gestures=("kb:nvda+shift+end",))
    def script_reportStatusLine(self, gesture: InputGesture) -> None:
        window = self._foreground()
        text = ""
        if window is not None:
            found = window.find_descendants(roles=("STATUS_BAR",), count=1)
            if found:
                bar = found[0]
                parts = [bar.name.strip()] if bar.name.strip() else []
                for child in bar.children[:30]:
                    piece = child.name.strip() or child.make_text_info(Position.ALL).text.strip()
                    if piece and piece not in parts:
                        parts.append(piece)
                text = "  ".join(parts)
        if not text:
            ui.message("Barra de status não encontrada")
        elif gesture.repeat_count >= 1:
            ui.speak_spelling(text)
        else:
            ui.message(text)

    @script(description="Fala a hora; duas vezes fala a data", category=CAT_SYSTEM,
            gesture="kb:nvda+f12")
    def script_dateTime(self, gesture: InputGesture) -> None:
        now = _dt.datetime.now()
        ui.message(format_date(now) if gesture.repeat_count >= 1 else format_time(now))

    @script(description="Fala o objeto em foco; duas vezes soletra o nome", category=CAT_SYSTEM,
            gestures=("kb:nvda+tab",))
    def script_reportCurrentFocus(self, gesture: InputGesture) -> None:
        focus = self._focus()
        if focus is None:
            ui.message(MSG_NO_FOCUS)
        elif gesture.repeat_count >= 1:
            ui.speak_spelling(focus.name)
        else:
            objectSpeech.speak_object(focus, OutputReason.QUERY)

    @script(description="Lê a janela em primeiro plano", category=CAT_SYSTEM, gesture="kb:nvda+b")
    def script_speakForeground(self, gesture: InputGesture) -> None:
        window = self._foreground()
        if window is None:
            ui.message("Sem janela em primeiro plano")
            return
        sequence = objectSpeech.get_object_speech(window, OutputReason.QUERY)
        count = 0
        for obj in window.iter_descendants(2000):
            if obj.role in (Role.STATICTEXT, Role.LABEL) and obj.name.strip():
                sequence.append(obj.name.strip())
                count += 1
            if count >= 50:
                break
        ui.speak(sequence)

    @script(description="Fala a linha atual do cursor; duas vezes soletra", category=CAT_SYSTEM,
            desktop_gestures=("kb:nvda+uparrow",), laptop_gestures=("kb:nvda+l",))
    def script_reportCurrentLine(self, gesture: InputGesture) -> None:
        focus = self._focus()
        if focus is None:
            ui.message(MSG_NO_FOCUS)
            return
        if not focus.has_text:
            objectSpeech.speak_object(focus, OutputReason.QUERY)
            return
        info = focus.make_text_info(Position.CARET)
        info.expand(TextUnit.LINE)
        if gesture.repeat_count >= 1:
            ui.speak_spelling(info.text.strip())
        else:
            objectSpeech.speak_text_unit(info, TextUnit.LINE)

    @script(description="Fala o texto selecionado", category=CAT_SYSTEM,
            desktop_gestures=("kb:nvda+shift+uparrow",), laptop_gestures=("kb:nvda+shift+s",))
    def script_reportCurrentSelection(self, gesture: InputGesture) -> None:
        focus = self._focus()
        info: OffsetsTextInfo | None = None
        if focus is not None:
            ti = focus.tree_interceptor
            if ti is not None and not ti.pass_through:
                selection = getattr(ti, "selection", None)
                if selection:
                    info = ti.make_text_info()
                    if info is not None:
                        info.start, info.end = selection
            elif focus.has_text:
                info = focus.make_text_info(Position.SELECTION)
        if info is None or info.is_collapsed:
            ui.message("Nenhuma seleção")
        else:
            ui.speak([info.text, "selecionado"])

    @script(description="Lê tudo a partir do cursor", category=CAT_SYSTEM,
            desktop_gestures=("kb:nvda+downarrow",), laptop_gestures=("kb:nvda+a",))
    def script_sayAll(self, gesture: InputGesture) -> None:
        focus = self._focus()
        if focus is None:
            ui.message(MSG_NO_FOCUS)
            return
        if focus.has_text:
            self._say_all_text(focus.make_text_info(Position.CARET))
            return
        navigator = self._navigator()
        if navigator is not None:
            self._say_all_text(navigator.make_text_info(Position.FIRST))

    def _say_all_text(self, info: OffsetsTextInfo) -> None:
        """Lê em lotes; o cursor de revisão acompanha a fala e para onde ela parar.

        O cursor do sistema não é movido: mexer nele gera eventos de cursor que
        fariam o leitor falar a linha de novo no meio da leitura.
        """
        sayAll.start(sayAll.TextInfoLines(info, self._store_review))

    @script(description="Fala a formatação do texto sob o cursor", category=CAT_SYSTEM,
            gesture="kb:nvda+f")
    def script_reportFormatting(self, gesture: InputGesture) -> None:
        focus = self._focus()
        if focus is None or not focus.has_text:
            ui.message("Sem informação de formatação")
            return
        attrs = focus.make_text_info(Position.CARET).attributes
        parts: list[str] = []
        if attrs.get("family-name"):
            parts.append(f"fonte {attrs['family-name']}")
        if attrs.get("size"):
            parts.append(f"{attrs['size']} pontos")
        try:
            if int(attrs.get("weight", "400")) >= 700:
                parts.append("negrito")
        except ValueError:
            pass
        if attrs.get("style") in ("italic", "oblique"):
            parts.append("itálico")
        if attrs.get("underline", "none") not in ("none", "false", ""):
            parts.append("sublinhado")
        ui.message(", ".join(parts) if parts else "Sem informação de formatação")

    # ------------------------------------------------------------ modos e ferramentas
    @script(description="Liga ou desliga a ajuda de entrada", category=CAT_TOOLS,
            gesture="kb:nvda+1", bypass_input_help=True)
    def script_toggleInputHelp(self, gesture: InputGesture) -> None:
        try:
            dispatcher = services.dispatcher()
            enabled = not dispatcher.input_help
            dispatcher.set_input_help(enabled)
        except Exception:  # noqa: BLE001
            ui.message("Ajuda de entrada indisponível")
            return
        ui.message("Ajuda de entrada " + ("ativada" if enabled else "desativada"))

    @script(description="Alterna entre modo de navegação e modo de foco", category=CAT_SYSTEM,
            gesture="kb:nvda+space")
    def script_toggleBrowseMode(self, gesture: InputGesture) -> None:
        ui.message("Modo de navegação não disponível aqui")

    @script(description="Lista de elementos do documento", category=CAT_TOOLS,
            gesture="kb:nvda+f7")
    def script_elementsList(self, gesture: InputGesture) -> None:
        ui.message("Lista de elementos só disponível em documentos no modo de navegação")

    @script(description="Abre o menu do NVDA", category=CAT_TOOLS, gesture="kb:nvda+n")
    def script_showGui(self, gesture: InputGesture) -> None:
        from nvda_linux import gui

        if not gui.show_nvda_menu():
            ui.message("Interface gráfica indisponível")

    @script(description="Sai do NVDA", category=CAT_TOOLS, gesture="kb:nvda+q")
    def script_quit(self, gesture: InputGesture) -> None:
        from nvda_linux import gui

        if configUtils.get_bool("general.askToExit", True) and gui.confirm_exit(request_quit):
            return
        ui.message("Saindo do NVDA")
        request_quit()

    @script(description="Passa a próxima tecla diretamente ao aplicativo", category=CAT_TOOLS,
            gesture="kb:nvda+f2")
    def script_passNextKeyThrough(self, gesture: InputGesture) -> None:
        rt = _runtime()
        if rt is not None:
            rt.chain.pass_next_key = True
        ui.message("Passar próxima tecla")

    @script(description="Liga ou desliga o modo dormir para o aplicativo atual",
            category=CAT_TOOLS, gesture="kb:nvda+shift+z")
    def script_toggleSleepMode(self, gesture: InputGesture) -> None:
        focus = self._focus()
        app = focus.app_module if focus is not None else None
        if app is None:
            return
        app.sleep_mode = not app.sleep_mode
        ui.message("Modo dormir " + ("ativado" if app.sleep_mode else "desativado"))

    @script(description="Para a fala", category=CAT_SPEECH,
            gestures=("kb:control", "kb:leftcontrol", "kb:rightcontrol"))
    def script_speechCancel(self, gesture: InputGesture) -> None:
        self._speech_paused = False
        ui.cancel()

    @script(description="Pausa ou retoma a fala", category=CAT_SPEECH,
            gestures=("kb:shift", "kb:leftshift", "kb:rightshift"))
    def script_speechPause(self, gesture: InputGesture) -> None:
        self._speech_paused = not self._speech_paused
        ui.pause(self._speech_paused)

    @script(description="Roteamento braille: move o cursor ou ativa o item sob a célula",
            category=CAT_SYSTEM, gesture="br(brltty):routing")
    def script_braille_routeTo(self, gesture: InputGesture) -> None:
        offset = gesture.extra.get("text_offset")
        if isinstance(offset, int):
            ui.route_braille(offset)

    # ------------------------------------------------------------ navegação por objetos
    def _set_navigator_and_speak(self, obj: LinuxNVDAObject) -> None:
        rt = _runtime()
        if rt is not None:
            rt.focus.set_navigator(obj)
        objectSpeech.speak_object(obj, OutputReason.QUERY)
        ui.braille_show("  ".join(objectSpeech.get_object_speech(obj, OutputReason.QUERY)))

    def _navigate(self, move: Callable[[LinuxNVDAObject, bool], LinuxNVDAObject | None],
                  failure: str) -> None:
        nav = self._navigator()
        if nav is None:
            ui.message(MSG_NO_NAVIGATOR)
            return
        target = move(nav, self._simple())
        if target is None or target.is_dead:
            ui.message(failure)
            return
        self._set_navigator_and_speak(target)

    @script(description="Fala o objeto de navegação; duas vezes soletra", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpad5",), laptop_gestures=("kb:nvda+shift+o",))
    def script_navigatorObject_current(self, gesture: InputGesture) -> None:
        nav = self._navigator()
        if nav is None:
            ui.message(MSG_NO_NAVIGATOR)
        elif gesture.repeat_count >= 1:
            ui.speak_spelling(nav.name or nav.value)
        else:
            objectSpeech.speak_object(nav, OutputReason.QUERY)

    @script(description="Vai ao objeto que contém o objeto de navegação", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpad8",), laptop_gestures=("kb:nvda+shift+uparrow",))
    def script_navigatorObject_parent(self, gesture: InputGesture) -> None:
        self._navigate(objectNav.parent, "Sem objeto pai")

    @script(description="Vai ao próximo objeto", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpad6",), laptop_gestures=("kb:nvda+shift+rightarrow",))
    def script_navigatorObject_next(self, gesture: InputGesture) -> None:
        self._navigate(objectNav.next_object, "Nenhum próximo")

    @script(description="Vai ao objeto anterior", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpad4",), laptop_gestures=("kb:nvda+shift+leftarrow",))
    def script_navigatorObject_previous(self, gesture: InputGesture) -> None:
        self._navigate(objectNav.previous_object, "Nenhum anterior")

    @script(description="Vai ao primeiro objeto contido", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpad2",), laptop_gestures=("kb:nvda+shift+downarrow",))
    def script_navigatorObject_firstChild(self, gesture: InputGesture) -> None:
        self._navigate(objectNav.first_child, "Sem objetos contidos")

    @script(description="Leva o objeto de navegação ao foco", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpadminus",), laptop_gestures=("kb:nvda+backspace",))
    def script_navigatorObject_toFocus(self, gesture: InputGesture) -> None:
        focus = self._focus()
        if focus is None:
            ui.message(MSG_NO_FOCUS)
            return
        self._set_navigator_and_speak(focus)

    @script(description="Move o foco do sistema para o objeto de navegação", category=CAT_NAV,
            desktop_gestures=("kb:nvda+shift+numpadminus",),
            laptop_gestures=("kb:nvda+shift+backspace",))
    def script_navigatorObject_moveFocus(self, gesture: InputGesture) -> None:
        nav = self._navigator()
        if nav is None or not nav.set_focus():
            ui.message("Não é possível focar este objeto")

    @script(description="Ativa o objeto de navegação", category=CAT_NAV,
            desktop_gestures=("kb:nvda+numpadenter",), laptop_gestures=("kb:nvda+enter",))
    def script_review_activate(self, gesture: InputGesture) -> None:
        nav = self._navigator()
        if nav is None:
            ui.message(MSG_NO_NAVIGATOR)
        elif not nav.do_action(0) and not nav.set_focus():
            ui.message("Sem ação disponível")

    # ------------------------------------------------------------ cursor de revisão
    def _review(self) -> OffsetsTextInfo | None:
        rt = _runtime()
        info = rt.focus.review if rt is not None else None
        if info is None:
            ui.message(MSG_NO_NAVIGATOR)
        return info

    def _store_review(self, info: OffsetsTextInfo) -> None:
        rt = _runtime()
        if rt is not None:
            rt.focus.review = info

    def _speak_review_unit(self, info: OffsetsTextInfo, unit: TextUnit, repeat: int = 0) -> None:
        span = info.copy()
        span.expand(unit)
        if unit == TextUnit.CHARACTER and repeat >= 2 and span.text:
            ui.message(f"código {ord(span.text[0])}")
        elif repeat >= 1:
            ui.speak_spelling(span.text.strip() if unit != TextUnit.CHARACTER else span.text)
        else:
            objectSpeech.speak_text_unit(span, unit)
        line = info.copy()
        line.expand(TextUnit.LINE)
        ui.braille_show(line.text.rstrip("\n"), info.start - line.start)

    def _review_move(self, unit: TextUnit, direction: int) -> None:
        info = self._review()
        if info is None:
            return
        info.expand(unit)
        info.collapse()
        if info.move(unit, direction) == 0:
            ui.speak(["fim" if direction > 0 else "início"])
        self._store_review(info)
        self._speak_review_unit(info, unit)

    def _review_current(self, unit: TextUnit, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            self._speak_review_unit(info, unit, gesture.repeat_count)

    @script(description="Revisão: linha anterior", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad7",), laptop_gestures=("kb:nvda+uparrow",))
    def script_review_previousLine(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.LINE, -1)

    @script(description="Revisão: linha atual; duas vezes soletra", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad8",), laptop_gestures=("kb:nvda+shift+.",))
    def script_review_currentLine(self, gesture: InputGesture) -> None:
        self._review_current(TextUnit.LINE, gesture)

    @script(description="Revisão: próxima linha", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad9",), laptop_gestures=("kb:nvda+downarrow",))
    def script_review_nextLine(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.LINE, 1)

    @script(description="Revisão: palavra anterior", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad4",), laptop_gestures=("kb:control+nvda+leftarrow",))
    def script_review_previousWord(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.WORD, -1)

    @script(description="Revisão: palavra atual; duas vezes soletra", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad5",), laptop_gestures=("kb:control+nvda+.",))
    def script_review_currentWord(self, gesture: InputGesture) -> None:
        self._review_current(TextUnit.WORD, gesture)

    @script(description="Revisão: próxima palavra", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad6",), laptop_gestures=("kb:control+nvda+rightarrow",))
    def script_review_nextWord(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.WORD, 1)

    @script(description="Revisão: caractere anterior", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad1",), laptop_gestures=("kb:nvda+leftarrow",))
    def script_review_previousCharacter(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.CHARACTER, -1)

    @script(description="Revisão: caractere atual; duas vezes soletra, três vezes o código",
            category=CAT_REVIEW, desktop_gestures=("kb:numpad2",),
            laptop_gestures=("kb:nvda+.",))
    def script_review_currentCharacter(self, gesture: InputGesture) -> None:
        self._review_current(TextUnit.CHARACTER, gesture)

    @script(description="Revisão: próximo caractere", category=CAT_REVIEW,
            desktop_gestures=("kb:numpad3",), laptop_gestures=("kb:nvda+rightarrow",))
    def script_review_nextCharacter(self, gesture: InputGesture) -> None:
        self._review_move(TextUnit.CHARACTER, 1)

    @script(description="Revisão: primeira linha", category=CAT_REVIEW,
            desktop_gestures=("kb:shift+numpad7",), laptop_gestures=("kb:control+nvda+home",))
    def script_review_top(self, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            info = OffsetsTextInfo(info.backend, Position.FIRST)
            self._store_review(info)
            self._speak_review_unit(info, TextUnit.LINE)

    @script(description="Revisão: última linha", category=CAT_REVIEW,
            desktop_gestures=("kb:shift+numpad9",), laptop_gestures=("kb:control+nvda+end",))
    def script_review_bottom(self, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            last = OffsetsTextInfo(info.backend, Position.LAST)
            last.expand(TextUnit.LINE)
            last.collapse()
            if last.start == info.backend.length() and last.start > 0:
                last.move(TextUnit.LINE, -1)
            self._store_review(last)
            self._speak_review_unit(last, TextUnit.LINE)

    @script(description="Revisão: início da linha", category=CAT_REVIEW,
            desktop_gestures=("kb:shift+numpad1",), laptop_gestures=("kb:nvda+home",))
    def script_review_startOfLine(self, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            info.expand(TextUnit.LINE)
            info.collapse()
            self._store_review(info)
            self._speak_review_unit(info, TextUnit.CHARACTER)

    @script(description="Revisão: fim da linha", category=CAT_REVIEW,
            desktop_gestures=("kb:shift+numpad3",), laptop_gestures=("kb:nvda+end",))
    def script_review_endOfLine(self, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            info.expand(TextUnit.LINE)
            end = info.end
            text = info.text
            last = end - 1 - (1 if text.endswith("\n") and len(text) > 1 else 0)
            info.start = info.end = max(info.start, last)
            self._store_review(info)
            self._speak_review_unit(info, TextUnit.CHARACTER)

    @script(description="Lê tudo a partir do cursor de revisão", category=CAT_REVIEW,
            desktop_gestures=("kb:numpadplus",), laptop_gestures=("kb:nvda+shift+a",))
    def script_review_sayAll(self, gesture: InputGesture) -> None:
        info = self._review()
        if info is not None:
            self._say_all_text(info)
