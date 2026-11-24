"""Despacho de gestos (implementa ``contracts.GestureDispatcher``).

Equivale ao ``inputCore.InputManager`` do NVDA. Para cada gesto:

1. comandos embutidos que precisam funcionar sempre: ``NVDA+1`` (ajuda de
   entrada) e ``NVDA+F2`` (passar a próxima tecla);
2. modo "passar próxima tecla": o gesto vai direto ao aplicativo;
3. modo ajuda de entrada: anuncia o gesto e o script (docstring), sem
   executar, e engole a tecla;
4. percorre ``services.script_chain().chain()`` (globalPlugins -> appModule
   -> treeInterceptor -> foco -> globalCommands) e agenda o primeiro script
   encontrado (síncrono ou ``async``); antes, interrompe a fala, a menos que o
   script declare ``speechEffectWhenExecuted = None``;
5. sem script: gestos com NVDA são engolidos (a tecla NVDA não chegou ao
   aplicativo), os demais seguem para o aplicativo, com eco de caractere e
   interrupção de fala conforme ``keyboard.*``.

A decisão (engolir ou repassar) é síncrona e rápida; o script roda logo
depois, no mesmo loop, para não atrasar o repasse das teclas.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from nvda_linux import services
from nvda_linux.contracts import (
    BrailleOutput,
    ConfigStore,
    InputGesture,
    KeyboardLayout,
    Script,
    ScriptProvider,
    SpeechOutput,
)
from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.gesture import display_name, gesture_has_modifier
from nvda_linux.inputCore.gesture_map import GestureMap
from nvda_linux.inputCore.layouts import parse_layout

log = get_logger(__name__)

ChainGetter = Callable[[], Sequence[ScriptProvider]]
GestureSender = Callable[[InputGesture], bool]
StateListener = Callable[[], None]

SPEECH_EFFECT_CANCEL = "cancel"

MSG_INPUT_HELP_ON = "Ajuda de entrada ativada"
MSG_INPUT_HELP_OFF = "Ajuda de entrada desativada"
MSG_PASS_NEXT = "Passar a próxima tecla"
MSG_NO_SEND = "Não é possível repassar teclas neste ambiente"


def _services_chain() -> Sequence[ScriptProvider]:
    try:
        return services.script_chain().chain()
    except services.ServiceMissing:
        return ()


def script_description(script: Script) -> str:
    """Descrição para a ajuda de entrada: 1ª linha da docstring ou o nome."""
    doc = inspect.getdoc(script)
    if doc:
        return doc.strip().splitlines()[0]
    name = getattr(script, "__name__", "") or type(script).__name__
    return name.removeprefix("script_")


class InputManager:
    """Despachante de gestos da PLATAFORMA."""

    def __init__(
        self,
        *,
        config: ConfigStore | None = None,
        speech: SpeechOutput | None = None,
        braille: BrailleOutput | None = None,
        chain: ChainGetter | None = None,
        gesture_map: GestureMap | None = None,
        layout: KeyboardLayout | None = None,
    ) -> None:
        self.config = config
        self.speech = speech
        self.braille = braille
        self._chain = chain or _services_chain
        self.gesture_map = gesture_map or GestureMap()
        self._layout_override = layout
        self._input_help = False
        self._pass_next = False
        self._sender: GestureSender | None = None
        self._state_listeners: list[StateListener] = []
        self._script_listeners: list[Callable[[InputGesture], None]] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._pending_calls = 0
        self._builtins: dict[str, Script] = {
            "kb:nvda+1": self.script_toggleInputHelp,
            "kb:nvda+f2": self.script_passNextKeyThrough,
        }
        self.last_gesture: InputGesture | None = None
        self._speech_paused = False

    # ------------------------------------------------------------ contrato
    @property
    def input_help(self) -> bool:
        return self._input_help

    def set_input_help(self, enabled: bool) -> None:
        """Liga/desliga a ajuda de entrada (silencioso: quem chama anuncia)."""
        if enabled == self._input_help:
            return
        self._input_help = enabled
        self._notify_state()

    @property
    def layout(self) -> KeyboardLayout:
        if self._layout_override is not None:
            return self._layout_override
        value = self._cfg("keyboard.keyboardLayout", "desktop")
        return parse_layout(value)

    def set_layout(self, layout: KeyboardLayout | None) -> None:
        """Força um layout (``--layout``); None volta a seguir a configuração."""
        self._layout_override = layout

    def send_through(self, gesture: InputGesture) -> None:
        """Reenvia ``gesture`` ao aplicativo (injeção por uinput)."""
        sender = self._sender
        if sender is None or not sender(gesture):
            log.warning("send_through(%s) não suportado pelo backend atual", gesture.identifier)

    # ------------------------------------------------------------ ligações
    def set_sender(self, sender: GestureSender | None) -> None:
        self._sender = sender

    def add_state_listener(self, listener: StateListener) -> None:
        """Avisado quando ajuda de entrada / passar tecla mudam (grabs do KeyboardMonitor)."""
        self._state_listeners.append(listener)

    def add_script_listener(self, listener: Callable[[InputGesture], None]) -> None:
        """Avisado depois de cada script executado."""
        self._script_listeners.append(listener)

    @property
    def pass_next(self) -> bool:
        return self._pass_next

    def refresh_grabs(self) -> None:
        """Avisa que os scripts disponíveis mudaram (ex.: navegação <-> foco).

        No KeyboardMonitor isso recalcula na hora quais teclas o compositor
        deve engolir. Extensão fora do contrato: use via ``getattr``.
        """
        self._notify_state()

    def _notify_state(self) -> None:
        for listener in list(self._state_listeners):
            try:
                listener()
            except Exception:
                log.exception("Ouvinte de estado do despachante falhou")

    # ------------------------------------------------------------ embutidos
    def script_toggleInputHelp(self, gesture: InputGesture) -> None:
        """Liga ou desliga a ajuda de entrada"""
        self.set_input_help(not self._input_help)
        self._say(MSG_INPUT_HELP_ON if self._input_help else MSG_INPUT_HELP_OFF)

    def script_passNextKeyThrough(self, gesture: InputGesture) -> None:
        """Passa a próxima tecla diretamente ao aplicativo"""
        self._pass_next = True
        self._say(MSG_PASS_NEXT)
        self._notify_state()

    # ------------------------------------------------------------ busca
    def _lookup_ids(self, gesture: InputGesture) -> list[InputGesture]:
        """Gestos a tentar, em ordem (equivalente Desktop primeiro no Laptop)."""
        equivalent = gesture.extra.get("desktop_equivalent")
        if isinstance(equivalent, str) and self.layout is KeyboardLayout.LAPTOP:
            extra = dict(gesture.extra)
            extra["laptop_identifier"] = gesture.identifier
            alias = dataclasses.replace(gesture, identifier=equivalent, extra=extra)
            return [alias, gesture]
        return [gesture]

    def find_script(self, gesture: InputGesture) -> tuple[Script, InputGesture] | None:
        """Primeiro script da cadeia para ``gesture`` (sem executar)."""
        builtin = self._builtins.get(gesture.identifier)
        if builtin is not None:
            return builtin, gesture
        if self.gesture_map is not None and "bindings" not in gesture.extra:
            ids = gesture.extra.get("normalized_identifiers") or [gesture.identifier]
            gesture.extra["bindings"] = self.gesture_map.bindings_for(ids)
        try:
            providers = list(self._chain())
        except Exception:
            log.exception("script_chain().chain() falhou")
            providers = []
        for candidate in self._lookup_ids(gesture):
            for provider in providers:
                try:
                    script = provider.get_script(candidate)
                except Exception:
                    log.exception("get_script falhou em %r", provider)
                    continue
                if script is not None:
                    return script, candidate
        return None

    def probe(self, gestures: Sequence[InputGesture]) -> list[InputGesture]:
        """Quais destes gestos têm script agora (para grabs do KeyboardMonitor)."""
        return [g for g in gestures if self.find_script(g) is not None]

    # ------------------------------------------------------------ despacho
    def process_gesture(self, gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        """Decide e agenda. True = gesto usado (a tecla deve ser engolida).

        ``suppressed`` vem de backends em que o compositor já decidiu:
        False = a tecla já foi entregue ao aplicativo (não executar scripts,
        exceto na ajuda de entrada, que só fala); True = já foi engolida.
        """
        self.last_gesture = gesture
        if self._pass_next and not gesture.is_modifier_only:
            self._pass_next = False
            self._notify_state()
            log.debug("Passando %s ao aplicativo", gesture.identifier)
            return False

        if self._input_help:
            if gesture.identifier == "kb:nvda+1":
                self._cancel_speech()
                self._schedule(self.script_toggleInputHelp, gesture)
            else:
                self._report_gesture(gesture)
            return True

        if suppressed is False:
            self._passthrough_effects(gesture)
            return False

        found = None if gesture.is_modifier_only else self.find_script(gesture)
        if found is not None:
            script, effective = found
            effect = getattr(script, "speechEffectWhenExecuted", SPEECH_EFFECT_CANCEL)
            if effect == SPEECH_EFFECT_CANCEL:
                self._cancel_speech()
            self._schedule(script, effective)
            return True

        if suppressed is True or gesture.is_modifier_only:
            return True
        if gesture_has_modifier(gesture, "nvda"):
            return True  # NVDA+tecla sem script: o aplicativo nunca viu a tecla NVDA
        self._passthrough_effects(gesture)
        return False

    def modifier_event(self, modifier: str, pressed: bool, lone: bool) -> None:
        """Ctrl sozinho: cala a fala. Toque em Shift sozinho: pausa/retoma."""
        if not lone or self.speech is None:
            return
        if modifier == "control" and pressed:
            self._cancel_speech()
        elif modifier == "shift" and not pressed:
            paused = not self._speech_paused
            self._speech_paused = paused
            try:
                self.speech.pause(paused)
            except Exception:
                log.exception("speech.pause falhou")

    def _passthrough_effects(self, gesture: InputGesture) -> None:
        speech = self.speech
        if speech is None or gesture.is_modifier_only:
            return
        if self._speech_paused:
            self._speech_paused = False
            speech.pause(False)
        key = gesture.identifier.rsplit("+", 1)[-1].split(":")[-1]
        char = gesture.character
        if char is not None:
            if self._cfg("keyboard.speechInterruptForCharacters", True):
                self._cancel_speech()
            echo = getattr(speech, "on_typed_character", None)
            if callable(echo):
                echo(char)
        elif key in ("enter", "numpadenter"):
            if self._cfg("keyboard.speechInterruptForEnter", True):
                self._cancel_speech()
            self._call_optional(speech, "flush_typed_word")
        elif key == "tab":
            self._call_optional(speech, "flush_typed_word")
        else:
            self._call_optional(speech, "reset_typed_word")

    @staticmethod
    def _call_optional(obj: object, name: str) -> None:
        fn = getattr(obj, name, None)
        if callable(fn):
            fn()

    def _report_gesture(self, gesture: InputGesture) -> None:
        self._cancel_speech()
        found = None if gesture.is_modifier_only else self.find_script(gesture)
        label = display_name(gesture.identifier)
        if found is not None:
            text = f"{label}: {script_description(found[0])}"
        elif gesture.character and gesture.character.strip():
            text = f"{label}, {gesture.character}"
        else:
            text = label
        self._say(text)
        if self.braille is not None and self.braille.available:
            try:
                self.braille.show_message(text)
            except Exception:
                log.exception("Braille falhou na ajuda de entrada")

    # ------------------------------------------------------------ execução
    def _schedule(self, script: Script, gesture: InputGesture) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._run_script(script, gesture)
            return
        self._pending_calls += 1
        loop.call_soon(self._run_script, script, gesture)

    def _run_script(self, script: Script, gesture: InputGesture) -> None:
        self._pending_calls = max(0, self._pending_calls - 1)
        try:
            result = script(gesture)
        except Exception:
            log.exception(
                "Script %s falhou para %s", script_description(script), gesture.identifier
            )
            self._after_script(gesture)
            return
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(self._await_script(result, script, gesture))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            self._after_script(gesture)

    async def _await_script(
        self, awaitable: Awaitable[None], script: Script, gesture: InputGesture
    ) -> None:
        try:
            await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Script %s falhou para %s", script_description(script), gesture.identifier
            )
        finally:
            self._after_script(gesture)

    def _after_script(self, gesture: InputGesture) -> None:
        for listener in list(self._script_listeners):
            try:
                listener(gesture)
            except Exception:
                log.exception("Ouvinte de script falhou")

    async def drain(self) -> None:
        """Espera scripts agendados terminarem (testes e desligamento)."""
        for _ in range(100):
            await asyncio.sleep(0)
            if self._pending_calls == 0 and not self._tasks:
                return
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------ utilidades
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def _cancel_speech(self) -> None:
        if self.speech is not None:
            try:
                self.speech.cancel()
            except Exception:
                log.exception("speech.cancel falhou")

    def _say(self, text: str) -> None:
        if self.speech is not None:
            try:
                self.speech.speak_text(text)
            except Exception:
                log.exception("speech.speak_text falhou")
