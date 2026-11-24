# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Ler tudo (``sayAll`` do NVDA) com marcadores de índice.

Em vez de enfileirar o documento inteiro de uma vez, o leitor manda lotes de
``BATCH_LINES`` linhas. Cada linha vai precedida de
``SpeechCommand("index", n)``; quando a PLATAFORMA avisa (por
``speech().add_index_listener``) que a fala chegou em ``n``, o cursor vai para
o começo daquela linha. Ao chegar na última linha do lote, o próximo lote é
enfileirado, enquanto essa linha ainda está sendo falada (sem pausa).

Se o usuário interrompe (qualquer tecla cancela a fala), os índices seguintes
nunca chegam: o cursor fica na linha que estava sendo lida, e as setas
continuam dali.

Fontes de linhas (:class:`LineSource`): o buffer do Browse Mode e um
:class:`~nvda_linux.NVDAObjects.textInfos.OffsetsTextInfo` (texto do foco ou
cursor de revisão).
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Sequence
from typing import Protocol

from nvda_linux import services
from nvda_linux.contracts import SpeechCommand
from nvda_linux.NVDAObjects.textInfos import OffsetsTextInfo, TextUnit
from nvda_linux.scripts import ui

log = logging.getLogger(__name__)

#: Linhas por lote enviado à fala.
BATCH_LINES = 10
#: Limite de segurança de linhas por leitura (documentos sem fim).
MAX_LINES = 100_000

SpeechItems = Sequence[str | SpeechCommand]


class LineSource(Protocol):
    """De onde o "ler tudo" tira as linhas e para onde leva o cursor."""

    def next_line(self) -> tuple[int, SpeechItems] | None:
        """``(posição, fala)`` da próxima linha com algo a falar; ``None`` no fim."""

    def move_to(self, position: int) -> None:
        """A fala chegou na linha que começa em ``position``: leva o cursor até ela."""


class TextInfoLines:
    """Linhas de um :class:`OffsetsTextInfo`, a partir da linha da posição dada."""

    def __init__(self, info: OffsetsTextInfo, on_move: Callable[[OffsetsTextInfo], None]) -> None:
        self._info = info.copy()
        self._info.expand(TextUnit.LINE)
        self._info.collapse()
        self._on_move = on_move
        self._ended = False

    def next_line(self) -> tuple[int, SpeechItems] | None:
        while not self._ended:
            line = self._info.copy()
            line.expand(TextUnit.LINE)
            position = self._info.start
            text = line.text.strip()
            if self._info.move(TextUnit.LINE, 1) == 0:
                self._ended = True
            if text:
                return position, [text]
        return None

    def move_to(self, position: int) -> None:
        at = self._info.copy()
        at.start = at.end = position
        self._on_move(at)


class SayAllController:
    """Conduz uma leitura contínua por vez."""

    def __init__(self) -> None:
        self._source: LineSource | None = None
        self._positions: dict[int, int] = {}
        self._trigger: int | None = None
        self._lines = 0
        self._unsubscribe: Callable[[], None] | None = None
        self._counter = itertools.count(1)

    @property
    def active(self) -> bool:
        """Há uma leitura em andamento (ainda não terminou nem foi trocada)."""
        return self._source is not None

    def start(self, source: LineSource, *, cancel: bool = True) -> None:
        """Começa a ler ``source``. ``cancel=False`` mantém o que já está na fila
        (ex.: o título da página, falado logo antes)."""
        self.stop()
        if cancel:
            ui.cancel()
        self._source = source
        self._lines = 0
        if not self._subscribe():
            self._read_without_indexes(source)
            return
        self._queue_batch()

    def stop(self) -> None:
        """Esquece a leitura atual (a fala em si é cancelada por quem chamou)."""
        self._source = None
        self._positions.clear()
        self._trigger = None
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                log.debug("Falha ao remover ouvinte de índice", exc_info=True)
            self._unsubscribe = None

    # ------------------------------------------------------------ interno
    def _subscribe(self) -> bool:
        try:
            self._unsubscribe = services.speech().add_index_listener(self._on_index)
        except Exception as exc:  # noqa: BLE001  (ServiceMissing, fala sem índices)
            log.debug("Ler tudo sem marcadores de índice: %s", exc)
            return False
        return True

    def _take_lines(self, source: LineSource, limit: int) -> list[tuple[int, SpeechItems]]:
        lines: list[tuple[int, SpeechItems]] = []
        while len(lines) < limit and self._lines < MAX_LINES:
            item = source.next_line()
            if item is None:
                break
            self._lines += 1
            lines.append(item)
        return lines

    def _queue_batch(self) -> None:
        source = self._source
        if source is None:
            return
        lines = self._take_lines(source, BATCH_LINES)
        if not lines:
            self.stop()  # fim do documento: o cursor já está na última linha lida
            return
        # Posições e gatilho registrados antes de falar: um índice pode ser
        # avisado na hora (fala ociosa) e não pode achar o lote pela metade.
        indexed = [(next(self._counter), position, speech) for position, speech in lines]
        for index, position, _speech in indexed:
            self._positions[index] = position
        self._trigger = indexed[-1][0]
        for index, _position, speech in indexed:
            ui.speak([SpeechCommand("index", index), *speech])

    def _on_index(self, index: int) -> None:
        source = self._source
        position = self._positions.pop(index, None)
        log.debug("Ler tudo: índice %d -> posição %s", index, position)
        if source is None or position is None:
            return  # índice de outra leitura
        try:
            source.move_to(position)
        except Exception:
            log.exception("Ler tudo: falha ao mover o cursor")
        if index == self._trigger and self._source is source:
            self._trigger = None
            self._queue_batch()

    def _read_without_indexes(self, source: LineSource) -> None:
        """Fala sem índices: enfileira tudo de uma vez e leva o cursor ao fim."""
        last: int | None = None
        for position, speech in self._take_lines(source, MAX_LINES):
            ui.speak(list(speech))
            last = position
        if last is not None:
            source.move_to(last)
        self._source = None


_controller = SayAllController()


def controller() -> SayAllController:
    """O controlador único do leitor."""
    return _controller


def start(source: LineSource, *, cancel: bool = True) -> None:
    _controller.start(source, cancel=cancel)


def stop() -> None:
    _controller.stop()
