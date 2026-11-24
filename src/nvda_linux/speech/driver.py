"""Classe abstrata dos sintetizadores (equivalente ao ``synthDriverHandler``).

O :class:`~nvda_linux.speech.manager.SpeechManager` transforma cada
``SpeechSequence`` do contrato numa lista de *segmentos* já resolvidos
(texto com prosódia relativa, pausas, caracteres soletrados) e entrega um
enunciado (utterance) por vez ao driver. O driver avisa o fim de cada
enunciado chamando ``self.notify_done(utterance_id)``, de qualquer thread.

Parâmetros de voz usam a escala 0..100 do NVDA; cada driver converte para a
escala do seu motor.
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import ClassVar
from xml.sax.saxutils import escape

from nvda_linux.core.log import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------
# Segmentos de um enunciado
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TextSegment:
    """Texto a falar. ``pitch``/``rate`` são deslocamentos em % sobre a base."""

    text: str
    pitch: int = 0
    rate: int = 0
    spell: bool = False  # True = ler como caracteres (soletrar)
    language: str | None = None


@dataclass(frozen=True, slots=True)
class BreakSegment:
    """Pausa em milissegundos."""

    ms: int


@dataclass(frozen=True, slots=True)
class IndexSegment:
    """Marcador de índice (``SpeechCommand("index", n)``) no meio do enunciado.

    Só aparece em enunciados de drivers com ``supports_index_marks``; o driver
    chama ``notify_index(utterance_id, index)`` quando a fala chega nele.
    """

    index: int


Segment = TextSegment | BreakSegment | IndexSegment


@dataclass(frozen=True, slots=True)
class Utterance:
    """Um enunciado: unidade enviada ao driver e confirmada por ``notify_done``."""

    id: int
    segments: tuple[Segment, ...]

    @property
    def plain_text(self) -> str:
        return " ".join(s.text for s in self.segments if isinstance(s, TextSegment))

    @property
    def indexes(self) -> tuple[int, ...]:
        """Marcadores de índice, na ordem em que aparecem."""
        return tuple(s.index for s in self.segments if isinstance(s, IndexSegment))


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """Voz disponível num sintetizador."""

    id: str
    name: str
    language: str = ""
    variant: str = ""


@dataclass(slots=True)
class VoiceSettings:
    """Parâmetros de voz na escala do NVDA (0..100)."""

    rate: int = 50
    pitch: int = 50
    volume: int = 100
    voice: str = ""
    language: str = ""
    variant: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def scale(value: int, low: float, high: float) -> float:
    """Converte 0..100 para o intervalo [low, high]."""
    return low + (high - low) * clamp(value) / 100.0


# --------------------------------------------------------------------------
# SSML
# --------------------------------------------------------------------------
def segments_to_ssml(segments: Sequence[Segment]) -> str:
    """Gera SSML aceito pelo Speech Dispatcher e pelo eSpeak-NG (``-m``)."""
    parts: list[str] = ["<speak>"]
    for seg in segments:
        if isinstance(seg, BreakSegment):
            parts.append(f'<break time="{max(0, seg.ms)}ms"/>')
            continue
        if isinstance(seg, IndexSegment):
            parts.append(f'<mark name="{int(seg.index)}"/>')
            continue
        body = escape(seg.text)
        if seg.spell:
            body = f'<say-as interpret-as="characters">{body}</say-as>'
        attrs: list[str] = []
        if seg.pitch:
            attrs.append(f'pitch="{seg.pitch:+d}%"')
        if seg.rate:
            attrs.append(f'rate="{100 + seg.rate}%"')
        if attrs:
            body = f"<prosody {' '.join(attrs)}>{body}</prosody>"
        if seg.language:
            body = f'<voice xml:lang="{escape(seg.language)}">{body}</voice>'
        parts.append(body)
    parts.append("</speak>")
    return "".join(parts)


def segments_to_text(segments: Sequence[Segment]) -> str:
    """Texto puro (para motores sem SSML). Pausas viram vírgula/ponto."""
    out: list[str] = []
    for seg in segments:
        if isinstance(seg, BreakSegment):
            out.append("." if seg.ms >= 300 else ",")
        elif isinstance(seg, IndexSegment):
            continue
        elif seg.spell:
            out.append(" ".join(seg.text))
        else:
            out.append(seg.text)
    return " ".join(p for p in out if p).strip()


# --------------------------------------------------------------------------
# SynthDriver
# --------------------------------------------------------------------------
DoneCallback = Callable[[int], None]
#: ``(utterance_id, index)``: a fala alcançou o marcador ``index``.
IndexCallback = Callable[[int, int], None]


class SynthDriverError(RuntimeError):
    """Falha ao iniciar ou usar um sintetizador."""


class SynthDriver(abc.ABC):
    """Base de todos os sintetizadores.

    Subclasses implementam :meth:`check`, :meth:`initialize`, :meth:`speak`,
    :meth:`cancel`, :meth:`pause` e :meth:`apply_settings`. ``speak`` e
    ``cancel`` nunca podem bloquear o loop: ``cancel`` deve apenas escrever
    no socket/matar o processo e retornar.
    """

    name: ClassVar[str] = "abstract"
    description: ClassVar[str] = ""
    supports_ssml: ClassVar[bool] = False
    supports_spelling: ClassVar[bool] = False
    #: True = o motor avisa marcadores no meio do enunciado (``notify_index``).
    #: False = o gerenciador corta o enunciado em cada índice e dispara ao fim
    #: de cada trecho.
    supports_index_marks: ClassVar[bool] = False

    def __init__(self) -> None:
        self.settings = VoiceSettings()
        self._done_callback: DoneCallback | None = None
        self._index_callback: IndexCallback | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    @abc.abstractmethod
    def check(cls) -> bool:
        """Verificação barata: o motor parece instalado/acessível?"""

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Conecta/inicia o motor. Levanta :class:`SynthDriverError` se falhar."""

    @abc.abstractmethod
    def speak(self, utterance: Utterance) -> None:
        """Começa a falar ``utterance``. Ao terminar: ``notify_done(utterance.id)``."""

    @abc.abstractmethod
    def cancel(self) -> None:
        """Interrompe imediatamente. Não chama ``notify_done`` do cancelado."""

    @abc.abstractmethod
    def pause(self, paused: bool) -> None:
        """Pausa ou retoma."""

    def apply_settings(self, settings: VoiceSettings) -> None:
        """Aplica parâmetros de voz (padrão: só guarda)."""
        self.settings = settings

    async def available_voices(self) -> list[VoiceInfo]:
        """Vozes conhecidas (padrão: nenhuma)."""
        return []

    async def terminate(self) -> None:
        """Libera recursos. Padrão: cancela."""
        self.cancel()

    # ------------------------------------------------------------ callbacks
    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        on_done: DoneCallback,
        on_index: IndexCallback | None = None,
    ) -> None:
        """Liga o driver ao loop e aos callbacks de fim de enunciado e de índice."""
        self._loop = loop
        self._done_callback = on_done
        self._index_callback = on_index

    def notify_done(self, utterance_id: int) -> None:
        """Avisa o gerenciador que ``utterance_id`` terminou (thread-safe)."""
        callback = self._done_callback
        if callback is not None:
            self._call_on_loop(callback, utterance_id)

    def notify_index(self, utterance_id: int, index: int) -> None:
        """Avisa que a fala de ``utterance_id`` alcançou ``index`` (thread-safe)."""
        callback = self._index_callback
        if callback is not None:
            self._call_on_loop(callback, utterance_id, index)

    def _call_on_loop(self, callback: Callable[..., None], *args: int) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            callback(*args)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.call_soon(callback, *args)
        else:
            try:
                loop.call_soon_threadsafe(callback, *args)
            except RuntimeError:
                log.debug("Loop fechado; aviso do sintetizador %s descartado", args)


SynthFactory = Callable[[], SynthDriver]
