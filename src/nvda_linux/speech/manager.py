"""Gerenciador de fala (implementa ``contracts.SpeechOutput``).

Equivale ao ``speech``/``speech.manager`` do NVDA:

- três filas por :class:`~nvda_linux.contracts.SpeechPriority`
  (``NOW`` > ``NEXT`` > ``NORMAL``). ``NOW`` interrompe o enunciado atual de
  prioridade menor, que volta para a frente da sua fila e é retomado depois;
- ``SpeechSequence`` (texto + :class:`~nvda_linux.contracts.SpeechCommand`)
  é compilada em segmentos: ``pitch``/``rate`` (deslocamento em %, 0 volta
  ao normal), ``break`` (ms), ``spell`` (texto a soletrar), ``beep``
  (``hz`` ou ``"hz,ms"``) e ``lang`` (código de idioma);
- soletração com aviso de maiúsculas (tom, palavra "maiúscula" ou bip);
- eco de caracteres e de palavras digitadas;
- ``cancel()`` é O(1): esvazia as filas e chama ``driver.cancel()``, que só
  escreve no socket/mata o processo.

Nenhum método público bloqueia o loop.
"""

from __future__ import annotations

import asyncio
import collections
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nvda_linux import services
from nvda_linux.contracts import (
    ConfigStore,
    SpeechCommand,
    SpeechPriority,
    SpeechSequence,
    ToneOutput,
)
from nvda_linux.core.log import IO, get_logger
from nvda_linux.speech.characters import cap_word, describe_character, letter_name, symbol_name
from nvda_linux.speech.driver import (
    BreakSegment,
    IndexSegment,
    Segment,
    SynthDriver,
    TextSegment,
    Utterance,
    VoiceSettings,
)

log = get_logger(__name__)

SpeechListener = Callable[[str], None]
CAPITAL_BEEP = (2000.0, 50)


@dataclass(frozen=True, slots=True)
class _Beep:
    hz: float
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _Index:
    """Índice entre enunciados: dispara quando o anterior termina."""

    index: int


_Item = Utterance | _Beep | _Index
IndexListener = Callable[[int], None]


def _parse_index(value: float | str | None) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        log.debug("Comando index inválido: %r", value)
        return None


def _parse_beep(value: float | str | None) -> _Beep | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _Beep(float(value), 50)
    raw = value.replace(":", ",")
    hz_text, _, ms_text = raw.partition(",")
    try:
        return _Beep(float(hz_text), int(float(ms_text)) if ms_text else 50)
    except ValueError:
        log.debug("Comando beep inválido: %r", value)
        return None


class SpeechManager:
    """Fila de fala com prioridades sobre um :class:`SynthDriver`."""

    def __init__(
        self,
        driver: SynthDriver,
        *,
        config: ConfigStore | None = None,
        tones: ToneOutput | None = None,
        language: str = "pt",
    ) -> None:
        self._driver = driver
        self._config = config
        self._tones = tones
        self.language = language
        self._queues: dict[SpeechPriority, collections.deque[_Item]] = {
            p: collections.deque() for p in SpeechPriority
        }
        self._current: Utterance | None = None
        self._current_priority = SpeechPriority.NORMAL
        self._paused = False
        self._next_id = 1
        self._listeners: list[SpeechListener] = []
        self._index_listeners: list[IndexListener] = []
        self._marks_fired: dict[int, int] = {}  # utterance_id -> índices já avisados
        self._word_buffer: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self.last_cancel_ns = 0

    # ------------------------------------------------------------ ciclo de vida
    @property
    def driver(self) -> SynthDriver:
        return self._driver

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Liga o driver ao loop e aplica a configuração de voz."""
        self._loop = loop or asyncio.get_running_loop()
        self._driver.bind(self._loop, self._on_done, self._on_index)
        self.apply_config()
        subscribe = getattr(self._config, "subscribe", None)
        if callable(subscribe):
            self._unsubscribe = subscribe("speech", lambda _k, _v: self.apply_config())

    async def set_driver(self, driver: SynthDriver) -> None:
        """Troca o sintetizador em uso (o anterior é encerrado)."""
        self.cancel()
        old, self._driver = self._driver, driver
        try:
            await old.terminate()
        except Exception:
            log.exception("Falha ao encerrar o sintetizador %s", old.name)
        if self._loop is not None:
            driver.bind(self._loop, self._on_done, self._on_index)
        self.apply_config()

    async def stop(self) -> None:
        self.cancel()
        if self._unsubscribe is not None:
            self._unsubscribe()
        await self._driver.terminate()

    def apply_config(self) -> None:
        """Lê ``speech.*`` e repassa ao driver."""
        get = self._get
        settings = VoiceSettings(
            rate=int(get("speech.rate", 50)),
            pitch=int(get("speech.pitch", 50)),
            volume=int(get("speech.volume", 100)),
            voice=str(get("speech.voice", "")),
            language=str(get("speech.language", "")),
            variant=str(get("speech.variant", "")),
        )
        if settings.language:
            self.language = settings.language
        try:
            self._driver.apply_settings(settings)
        except Exception:
            log.exception("Driver %s rejeitou a configuração", self._driver.name)

    def _get(self, key: str, default: Any) -> Any:
        if self._config is None:
            return default
        try:
            return self._config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def add_listener(self, listener: SpeechListener) -> Callable[[], None]:
        """Recebe o texto de cada fala (Visualizador de Fala). Devolve o cancelador."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def add_index_listener(self, listener: IndexListener) -> Callable[[], None]:
        """Avisa quando a fala alcança um ``SpeechCommand("index", n)``. Devolve o cancelador.

        Índices de fala cancelada (``cancel()``) nunca são avisados.
        """
        self._index_listeners.append(listener)

        def remove() -> None:
            if listener in self._index_listeners:
                self._index_listeners.remove(listener)

        return remove

    # ------------------------------------------------------------ contrato
    def speak(
        self, sequence: SpeechSequence, priority: SpeechPriority = SpeechPriority.NORMAL
    ) -> None:
        """Enfileira ``sequence`` com ``priority``. Nunca bloqueia."""
        items = self._compile(sequence)
        if not items:
            return
        text = " ".join(i.plain_text for i in items if isinstance(i, Utterance)).strip()
        if text:
            log.log(IO, "Falando [%s]: %r", priority.name, text)
            for listener in list(self._listeners):
                try:
                    listener(text)
                except Exception:
                    log.exception("Ouvinte de fala falhou")
        if (
            priority == SpeechPriority.NOW
            and self._current is not None
            and self._current_priority < SpeechPriority.NOW
        ):
            interrupted = self._current
            self._current = None
            self._driver.cancel()
            self._queues[self._current_priority].appendleft(interrupted)
        self._queues[priority].extend(items)
        self._push_next()

    def speak_text(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
        self.speak([text], priority)

    def speak_spelling(self, text: str) -> None:
        """Soletra ``text`` caractere a caractere."""
        self.speak(self.spelling_sequence(text))

    def cancel(self) -> None:
        """Esvazia as filas e interrompe o driver (alvo: < 30 ms; na prática µs)."""
        start = time.perf_counter_ns()
        for queue in self._queues.values():
            queue.clear()
        self._current = None
        self._marks_fired.clear()
        try:
            self._driver.cancel()
        except Exception:
            log.exception("driver.cancel() falhou")
        self.last_cancel_ns = time.perf_counter_ns() - start

    def pause(self, paused: bool) -> None:
        self._paused = paused
        try:
            self._driver.pause(paused)
        except Exception:
            log.exception("driver.pause() falhou")
        if not paused:
            self._push_next()

    @property
    def is_speaking(self) -> bool:
        return self._current is not None or any(self._queues.values())

    # ------------------------------------------------------------ eco de teclado
    def on_typed_character(self, char: str) -> None:
        """Eco de caracteres/palavras digitados (``keyboard.speakTyped*``).

        Em campo de senha nunca fala o caractere nem guarda a palavra: diz
        "asterisco" (ou nada, com o eco de caracteres desligado).
        """
        if not char:
            return
        if self._focus_is_protected():
            self._word_buffer.clear()
            if self._get("keyboard.speakTypedCharacters", True) and char.isprintable():
                self.speak_spelling("*")
            return
        is_word_char = char.isalnum() or char in "'-_"
        if self._get("keyboard.speakTypedWords", False) and not is_word_char:
            word = "".join(self._word_buffer).strip()
            self._word_buffer.clear()
            if word:
                self.speak_text(word)
        elif is_word_char:
            self._word_buffer.append(char)
        if self._get("keyboard.speakTypedCharacters", True) and char.isprintable():
            if char.isspace():
                self.speak_text(describe_character(char, self.language))
            else:
                self.speak_spelling(char)

    @staticmethod
    def _focus_is_protected() -> bool:
        """O foco é campo de senha? Sem SEMÂNTICA: não; se a consulta falhar: sim."""
        try:
            return bool(services.focus().focus_is_protected())
        except services.ServiceMissing:
            return False
        except Exception:
            log.exception("focus_is_protected() falhou; tratando o campo como senha")
            return True

    def flush_typed_word(self) -> None:
        """Fala a palavra digitada pendente (Enter/Tab), se o eco de palavras estiver ligado."""
        word = "".join(self._word_buffer).strip()
        self._word_buffer.clear()
        if word and self._get("keyboard.speakTypedWords", False):
            self.speak_text(word)

    def reset_typed_word(self) -> None:
        self._word_buffer.clear()

    # ------------------------------------------------------------ compilação
    def spelling_sequence(self, text: str) -> list[str | SpeechCommand]:
        """Sequência de soletração com o tratamento de maiúsculas do NVDA."""
        cap_pitch = int(self._get("speech.capPitchChange", 30))
        say_cap = bool(self._get("speech.sayCapForCapitals", False))
        beep_cap = bool(self._get("speech.beepForCapitals", False))
        seq: list[str | SpeechCommand] = []
        for char in text:
            upper = char.isupper()
            if upper and beep_cap:
                hz, ms = CAPITAL_BEEP
                seq.append(SpeechCommand("beep", f"{hz},{ms}"))
            if upper and cap_pitch:
                seq.append(SpeechCommand("pitch", cap_pitch))
            if upper and say_cap:
                seq.append(cap_word(self.language))
            seq.append(SpeechCommand("spell", char))
            if upper and cap_pitch:
                seq.append(SpeechCommand("pitch", 0))
        return seq

    def _spell_segments(self, text: str, pitch: int, rate: int, lang: str | None) -> list[Segment]:
        use_engine = self._driver.supports_spelling and bool(
            self._get("speech.useSpellingFunctionality", True)
        )
        out: list[Segment] = []
        for char in text:
            name = symbol_name(char, self.language)
            if name is not None:
                out.append(TextSegment(name, pitch, rate, False, lang))
            elif use_engine:
                out.append(TextSegment(char, pitch, rate, True, lang))
            else:
                spoken = letter_name(char, self.language) or describe_character(char, self.language)
                out.append(TextSegment(spoken, pitch, rate, False, lang))
        return out

    def _compile(self, sequence: SpeechSequence) -> list[_Item]:
        items: list[_Item] = []
        segments: list[Segment] = []
        pitch = rate = 0
        lang: str | None = None

        def flush() -> None:
            if any(isinstance(s, TextSegment) and s.text.strip() for s in segments):
                items.append(Utterance(self._next_id, tuple(segments)))
                self._next_id += 1
            else:  # sem texto: os índices não podem se perder
                items.extend(_Index(s.index) for s in segments if isinstance(s, IndexSegment))
            segments.clear()

        if isinstance(sequence, str):  # tolera speak("texto")
            sequence = [sequence]
        for element in sequence:
            if isinstance(element, str):
                if element.strip():
                    segments.append(TextSegment(element, pitch, rate, False, lang))
                continue
            if not isinstance(element, SpeechCommand):
                log.debug("Elemento de fala ignorado: %r", element)
                continue
            kind, value = element.kind, element.value
            if kind == "pitch":
                pitch = int(value) if isinstance(value, (int, float)) else 0
            elif kind == "rate":
                rate = int(value) if isinstance(value, (int, float)) else 0
            elif kind == "break":
                ms = int(value) if isinstance(value, (int, float)) else 0
                if ms > 0:
                    segments.append(BreakSegment(ms))
            elif kind == "spell":
                if value is not None:
                    segments.extend(self._spell_segments(str(value), pitch, rate, lang))
            elif kind == "beep":
                beep = _parse_beep(value)
                if beep is not None:
                    flush()
                    items.append(beep)
            elif kind in ("lang", "language"):
                lang = str(value) if value else None
            elif kind == "index":
                index = _parse_index(value)
                if index is None:
                    continue
                if self._driver.supports_index_marks:
                    segments.append(IndexSegment(index))
                else:  # corta aqui: o índice dispara quando o trecho anterior termina
                    flush()
                    items.append(_Index(index))
            else:
                log.debug("Comando de fala desconhecido: %s", kind)
        flush()
        return items

    # ------------------------------------------------------------ fila
    def _push_next(self) -> None:
        while self._current is None and not self._paused:
            for priority in (SpeechPriority.NOW, SpeechPriority.NEXT, SpeechPriority.NORMAL):
                queue = self._queues[priority]
                if queue:
                    item = queue.popleft()
                    break
            else:
                return
            if isinstance(item, _Beep):
                if self._tones is not None:
                    try:
                        self._tones.beep(item.hz, item.duration_ms)
                    except Exception:
                        log.exception("Bip da sequência de fala falhou")
                continue
            if isinstance(item, _Index):
                self._fire_index(item.index)
                continue
            self._current = item
            self._current_priority = priority
            try:
                self._driver.speak(item)
            except Exception:
                log.exception("driver.speak() falhou")
                self._current = None

    def _fire_index(self, index: int) -> None:
        log.debug("Índice %d alcançado (%d ouvintes)", index, len(self._index_listeners))
        for listener in list(self._index_listeners):
            try:
                listener(index)
            except Exception:
                log.exception("Ouvinte de índice falhou")

    def _fire_marks_until(self, utterance: Utterance, stop: int) -> None:
        """Avisa os índices de ``utterance`` ainda não avisados, até a posição ``stop``."""
        indexes = utterance.indexes
        while self._current is utterance:
            pos = self._marks_fired.get(utterance.id, 0)
            if pos >= min(stop, len(indexes)):
                return
            self._marks_fired[utterance.id] = pos + 1
            self._fire_index(indexes[pos])  # o ouvinte pode cancelar: o laço confere

    def _on_index(self, utterance_id: int, index: int) -> None:
        current = self._current
        if current is None or current.id != utterance_id:
            log.debug(
                "Índice %d do enunciado %d ignorado (atual: %s)",
                index,
                utterance_id,
                current.id if current is not None else None,
            )
            return  # enunciado cancelado ou já terminado
        indexes = current.indexes
        start = self._marks_fired.get(utterance_id, 0)
        if index in indexes[start:]:
            # Marcadores pulados pelo motor saem antes, na ordem.
            self._fire_marks_until(current, indexes.index(index, start) + 1)

    def _on_done(self, utterance_id: int) -> None:
        current = self._current
        if current is not None and current.id == utterance_id:
            # Motor que não avisou algum marcador: avisa o resto ao terminar.
            self._fire_marks_until(current, len(current.indexes))
            self._marks_fired.pop(utterance_id, None)
            if self._current is current:
                self._current = None
                self._push_next()
