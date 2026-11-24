"""Bips senoidais (implementa ``contracts.ToneOutput``; equivale a ``tones.py``).

``beep(hz, duration_ms, left, right)`` gera a onda com NumPy (ou, sem ele,
com um gerador em Python puro) com rampa de
entrada/saída de 3 ms para não estalar, em estéreo com volume por canal na
escala 0..100 do NVDA, e agenda a reprodução numa tarefa: nunca bloqueia o
loop. Como no NVDA, um bip novo interrompe o anterior.
"""

from __future__ import annotations

import array
import asyncio
import functools
import math
import sys
from typing import Any, Final

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger
from nvda_linux.speech.audio import AudioPlayer, NullPlayer

log = get_logger(__name__)

SAMPLE_RATE: Final = 44100
RAMP_MS: Final = 3.0
MAX_DURATION_MS: Final = 10_000

# NumPy é importado de forma protegida: o leitor ainda bipa sem ele, e o mypy
# não precisa analisar os stubs do NumPy (que exigem Python >= 3.12).
_np: Any = optional_import("numpy")


def _tone_numpy(hz: float, n: int, rate: int, ramp: int, l_gain: float, r_gain: float) -> bytes:
    np = _np
    t = np.arange(n, dtype=np.float64) / rate
    wave = np.sin(2.0 * np.pi * float(hz) * t)
    if ramp > 0:
        envelope = np.ones(n)
        fade = np.linspace(0.0, 1.0, ramp, endpoint=False)
        envelope[:ramp] = fade
        envelope[n - ramp :] = fade[::-1]
        wave *= envelope
    stereo = np.empty((n, 2), dtype=np.int16)
    stereo[:, 0] = np.round(wave * l_gain).astype(np.int16)
    stereo[:, 1] = np.round(wave * r_gain).astype(np.int16)
    return bytes(stereo.astype("<i2").tobytes())


def _tone_python(hz: float, n: int, rate: int, ramp: int, l_gain: float, r_gain: float) -> bytes:
    samples = array.array("h", bytes(4 * n))
    step = 2.0 * math.pi * hz / rate
    for i in range(n):
        env = 1.0
        if ramp > 0:
            if i < ramp:
                env = i / ramp
            elif i >= n - ramp:
                env = (n - 1 - i) / ramp
        value = math.sin(step * i) * env
        samples[2 * i] = round(value * l_gain)
        samples[2 * i + 1] = round(value * r_gain)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


@functools.lru_cache(maxsize=64)
def generate_tone(
    hz: float,
    duration_ms: int,
    left: int = 50,
    right: int = 50,
    volume: int = 100,
    rate: int = SAMPLE_RATE,
) -> bytes:
    """PCM s16le estéreo intercalado de uma senoide.

    ``left``/``right``/``volume`` em 0..100. O resultado fica em cache, pois
    os mesmos bips (modos, progresso) se repetem o tempo todo.
    """
    duration_ms = max(0, min(int(duration_ms), MAX_DURATION_MS))
    n = int(rate * duration_ms / 1000)
    if n == 0 or hz <= 0:
        return b""
    ramp = min(n // 2, int(rate * RAMP_MS / 1000))
    gain = 0.9 * 32767 * max(0, min(volume, 100)) / 100.0
    l_gain = gain * max(0, min(left, 100)) / 100.0
    r_gain = gain * max(0, min(right, 100)) / 100.0
    generator = _tone_numpy if _np is not None else _tone_python
    return generator(float(hz), n, rate, ramp, l_gain, r_gain)


class ToneGenerator:
    """Implementação de :class:`nvda_linux.contracts.ToneOutput`."""

    def __init__(self, player: AudioPlayer | None = None, volume: int = 50) -> None:
        self.player: AudioPlayer = player or NullPlayer()
        self.volume = volume
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self.history: list[tuple[float, int, int, int]] = []  # últimos bips (depuração/testes)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def beep(self, hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
        """Toca um bip sem bloquear. Pode ser chamado de qualquer thread."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            target = self._loop
            if target is None or target.is_closed():
                log.debug("beep(%s) sem loop ativo; ignorado", hz)
                return
            target.call_soon_threadsafe(self._start, hz, duration_ms, left, right)
            return
        self._loop = loop
        self._start(hz, duration_ms, left, right)

    def _start(self, hz: float, duration_ms: int, left: int, right: int) -> None:
        self.history.append((hz, duration_ms, left, right))
        del self.history[:-32]
        pcm = generate_tone(float(hz), int(duration_ms), int(left), int(right), int(self.volume))
        if not pcm:
            return
        if self._task is not None and not self._task.done():
            self.player.stop()
            self._task.cancel()
        loop = self._loop or asyncio.get_running_loop()
        self._task = loop.create_task(self._play(pcm), name="beep")

    async def _play(self, pcm: bytes) -> None:
        try:
            await self.player.play(pcm, SAMPLE_RATE, 2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("Falha ao tocar bip: %s", exc)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
        await self.player.close()
