"""Driver de silêncio: não fala nada, mas respeita o protocolo de enunciados.

Útil em testes e quando nenhum sintetizador está disponível (o leitor segue
funcionando com braille e bips). Cada enunciado "dura" ``ms_per_char``
milissegundos por caractere, para que filas e prioridades se comportem como
num sintetizador real; com ``instant=True`` termina na próxima iteração.
"""

from __future__ import annotations

import asyncio

from nvda_linux.speech.driver import SynthDriver, Utterance


class SilenceDriver(SynthDriver):
    """Sintetizador que só registra o que deveria ser falado."""

    name = "silence"
    description = "Sem fala"
    supports_ssml = False
    supports_spelling = True

    def __init__(self, *, instant: bool = True, ms_per_char: float = 0.0) -> None:
        super().__init__()
        self.instant = instant
        self.ms_per_char = ms_per_char
        self.spoken: list[Utterance] = []
        self.cancel_count = 0
        self.paused = False
        self._timer: asyncio.TimerHandle | None = None

    @classmethod
    def check(cls) -> bool:
        return True

    async def initialize(self) -> None:
        return None

    def speak(self, utterance: Utterance) -> None:
        self.spoken.append(utterance)
        loop = asyncio.get_running_loop()
        delay = 0.0 if self.instant else len(utterance.plain_text) * self.ms_per_char / 1000.0
        self._timer = loop.call_later(delay, self.notify_done, utterance.id)

    def cancel(self) -> None:
        self.cancel_count += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def pause(self, paused: bool) -> None:
        self.paused = paused
