"""Fakes dos serviços da PLATAFORMA (speech, tones, braille, config, dispatcher).

Não dependem de nenhum código da PLATAFORMA: só dos Protocols de ``contracts``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nvda_linux.contracts import (
    InputGesture,
    KeyboardLayout,
    SpeechCommand,
    SpeechPriority,
    SpeechSequence,
)


class FakeSpeech:
    """Grava tudo o que seria falado."""

    def __init__(self) -> None:
        self.utterances: list[list[str]] = []
        self.priorities: list[SpeechPriority] = []
        self.spelled: list[str] = []
        self.cancel_count = 0
        self.paused: bool | None = None
        #: True = fala "instantânea": índices avisados assim que enfileirados.
        #: False = o teste avança com :meth:`reach_next`.
        self.auto_index = True
        self.pending_indexes: list[int] = []
        self._index_listeners: list[Callable[[int], None]] = []
        self._firing = False

    def speak(
        self, sequence: SpeechSequence, priority: SpeechPriority = SpeechPriority.NORMAL
    ) -> None:
        self.utterances.append([s for s in sequence if isinstance(s, str)])
        self.priorities.append(priority)
        self.pending_indexes.extend(
            int(s.value)  # type: ignore[arg-type]
            for s in sequence
            if isinstance(s, SpeechCommand) and s.kind == "index"
        )
        if self.auto_index:
            self._fire_pending()

    def add_index_listener(self, listener: Callable[[int], None]) -> Callable[[], None]:
        self._index_listeners.append(listener)

        def remove() -> None:
            if listener in self._index_listeners:
                self._index_listeners.remove(listener)

        return remove

    def reach_next(self) -> int | None:
        """A fala chega no próximo índice pendente (modo manual)."""
        if not self.pending_indexes:
            return None
        index = self.pending_indexes.pop(0)
        for listener in list(self._index_listeners):
            listener(index)
        return index

    def _fire_pending(self) -> None:
        if self._firing:  # um ouvinte falou de novo: o laço de fora continua
            return
        self._firing = True
        try:
            while self.pending_indexes:
                self.reach_next()
        finally:
            self._firing = False

    def speak_text(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
        self.speak([text], priority)

    def speak_spelling(self, text: str) -> None:
        self.spelled.append(text)

    def cancel(self) -> None:
        self.cancel_count += 1
        self.pending_indexes.clear()  # índices cancelados nunca são avisados

    def pause(self, paused: bool) -> None:
        self.paused = paused

    # ------------------------------------------------------------ utilidades de teste
    @property
    def text(self) -> str:
        """Tudo o que foi falado, unido por " | "."""
        return " | ".join(" ".join(u) for u in self.utterances)

    @property
    def last(self) -> list[str]:
        return self.utterances[-1] if self.utterances else []

    def clear(self) -> None:
        self.utterances.clear()
        self.priorities.clear()
        self.spelled.clear()


class EchoingSpeech(FakeSpeech):
    """Fala da PLATAFORMA com eco de digitação próprio (``on_typed_character``)."""

    def __init__(self) -> None:
        super().__init__()
        self.typed: list[str] = []

    def on_typed_character(self, char: str) -> None:
        self.typed.append(char)


class FakeTones:
    def __init__(self) -> None:
        self.beeps: list[tuple[float, int]] = []

    def beep(self, hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
        self.beeps.append((hz, duration_ms))


class FakeBraille:
    def __init__(self) -> None:
        self.shown: list[tuple[str, int | None]] = []
        self.messages: list[str] = []

    def show_text(self, text: str, cursor: int | None = None) -> None:
        self.shown.append((text, cursor))

    def show_message(self, text: str, timeout_ms: int = 4000) -> None:
        self.messages.append(text)

    @property
    def available(self) -> bool:
        return True


class FakeConfig:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.values: dict[str, Any] = dict(values or {})
        self.saved = 0
        self.profiles: list[str | None] = []
        self.reject: set[str] = set()

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in self.reject:
            raise TypeError(f"valor inválido para {key}")
        self.values[key] = value

    def save(self) -> None:
        self.saved += 1

    def activate_profile(self, name: str | None) -> None:
        self.profiles.append(name)


class FakeDispatcher:
    def __init__(self, layout: KeyboardLayout = KeyboardLayout.DESKTOP) -> None:
        self._layout = layout
        self._input_help = False
        self.sent: list[InputGesture] = []
        self.on_send: Callable[[InputGesture], None] | None = None

    def set_input_help(self, enabled: bool) -> None:
        self._input_help = enabled

    @property
    def input_help(self) -> bool:
        return self._input_help

    @property
    def layout(self) -> KeyboardLayout:
        return self._layout

    @layout.setter
    def layout(self, value: KeyboardLayout) -> None:
        self._layout = value

    def send_through(self, gesture: InputGesture) -> None:
        self.sent.append(gesture)
        if self.on_send is not None:
            self.on_send(gesture)


class FakeApp:
    """Serviço opcional ``"app"`` da PLATAFORMA (para NVDA+Q)."""

    def __init__(self) -> None:
        self.exit_requests = 0

    def request_exit(self, code: int = 0) -> None:
        self.exit_requests += 1


def command(kind: str, value: Any = None) -> SpeechCommand:
    return SpeechCommand(kind, value)


class ListeningSpeech(FakeSpeech):
    """Fala da PLATAFORMA com ``add_listener`` (Visualizador de Fala)."""

    def __init__(self) -> None:
        super().__init__()
        self.listeners: list[Callable[[str], None]] = []

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def speak(
        self, sequence: SpeechSequence, priority: SpeechPriority = SpeechPriority.NORMAL
    ) -> None:
        super().speak(sequence, priority)
        text = " ".join(s for s in sequence if isinstance(s, str))
        for listener in list(self.listeners):
            listener(text)


class GrabbingDispatcher(FakeDispatcher):
    """Dispatcher com ``refresh_grabs`` (KeyboardMonitor do GNOME)."""

    def __init__(self) -> None:
        super().__init__()
        self.refreshes = 0

    def refresh_grabs(self) -> None:
        self.refreshes += 1
