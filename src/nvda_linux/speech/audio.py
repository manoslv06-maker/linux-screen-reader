"""Saída de áudio PCM (para bips e para o driver Piper).

Ordem de preferência:

1. ``sounddevice`` (PortAudio, em processo, cada som numa stream própria);
2. ``pw-play -a`` (PipeWire), ``pacat --raw`` (PulseAudio/pipewire-pulse),
   ``aplay -t raw`` (ALSA), por subprocesso com o PCM no stdin;
3. :class:`NullPlayer` (descarta), para máquinas sem áudio e testes.

Todas as operações são assíncronas; ``stop()`` é síncrono e imediato.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import shutil
import subprocess
import threading
from collections.abc import Sequence
from typing import Any

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger

log = get_logger(__name__)

SAMPLE_WIDTH = 2  # s16le


class AudioPlayer(abc.ABC):
    """Toca PCM s16le intercalado."""

    name = "abstract"

    @abc.abstractmethod
    async def play(self, pcm: bytes, rate: int, channels: int) -> None:
        """Toca e retorna quando terminar (ou quando ``stop()`` for chamado)."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Interrompe tudo o que estiver tocando."""

    async def open_stream(self, rate: int, channels: int) -> AudioStream:
        """Stream incremental (Piper). Padrão: acumula e toca ao fechar."""
        return _BufferedStream(self, rate, channels)

    async def close(self) -> None:
        self.stop()


class AudioStream(abc.ABC):
    """Destino incremental de PCM."""

    @abc.abstractmethod
    async def write(self, pcm: bytes) -> None: ...

    @abc.abstractmethod
    async def finish(self) -> None:
        """Fecha a entrada e espera o fim da reprodução."""

    @abc.abstractmethod
    def abort(self) -> None: ...


class _BufferedStream(AudioStream):
    def __init__(self, player: AudioPlayer, rate: int, channels: int) -> None:
        self._player, self._rate, self._channels = player, rate, channels
        self._chunks: list[bytes] = []
        self._aborted = False

    async def write(self, pcm: bytes) -> None:
        self._chunks.append(pcm)

    async def finish(self) -> None:
        if not self._aborted:
            await self._player.play(b"".join(self._chunks), self._rate, self._channels)

    def abort(self) -> None:
        self._aborted = True
        self._player.stop()


class NullPlayer(AudioPlayer):
    """Não toca nada (registra o pedido). Usado sem áudio e em testes."""

    name = "null"

    def __init__(self) -> None:
        self.played: list[tuple[int, int, int]] = []  # (bytes, rate, channels)

    async def play(self, pcm: bytes, rate: int, channels: int) -> None:
        self.played.append((len(pcm), rate, channels))

    def stop(self) -> None:
        pass


class SoundDevicePlayer(AudioPlayer):
    """PortAudio via ``sounddevice``: uma ``RawOutputStream`` por som."""

    name = "sounddevice"

    def __init__(self, sd: Any, device: str | None = None) -> None:
        self._sd = sd
        self._device = device or None
        self._streams: set[Any] = set()
        self._lock = threading.Lock()
        self._generation = 0

    async def play(self, pcm: bytes, rate: int, channels: int) -> None:
        generation = self._generation
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._play_blocking, pcm, rate, channels, generation)

    def _play_blocking(self, pcm: bytes, rate: int, channels: int, generation: int) -> None:
        stream = self._sd.RawOutputStream(
            samplerate=rate, channels=channels, dtype="int16", device=self._device
        )
        with self._lock:
            self._streams.add(stream)
        try:
            stream.start()
            frame = channels * SAMPLE_WIDTH
            chunk = max(frame, (rate // 50) * frame)  # 20 ms
            for i in range(0, len(pcm), chunk):
                if generation != self._generation:
                    stream.abort()
                    return
                stream.write(pcm[i : i + chunk])
            stream.stop()
        except Exception as exc:  # PortAudioError e afins  # noqa: BLE001
            log.debug("sounddevice falhou: %s", exc)
        finally:
            with self._lock:
                self._streams.discard(stream)
            with contextlib.suppress(Exception):
                stream.close()

    def stop(self) -> None:
        self._generation += 1
        with self._lock:
            streams = list(self._streams)
        for stream in streams:
            with contextlib.suppress(Exception):
                stream.abort()


class SubprocessPlayer(AudioPlayer):
    """Toca enviando PCM ao stdin de ``pw-play``, ``pacat`` ou ``aplay``."""

    def __init__(self, name: str, argv_template: Sequence[str]) -> None:
        self.name = name
        self._template = tuple(argv_template)
        self._procs: set[asyncio.subprocess.Process] = set()

    def argv(self, rate: int, channels: int) -> list[str]:
        return [a.format(rate=rate, channels=channels) for a in self._template]

    async def _spawn(self, rate: int, channels: int) -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            *self.argv(rate, channels),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._procs.add(proc)
        return proc

    async def play(self, pcm: bytes, rate: int, channels: int) -> None:
        try:
            proc = await self._spawn(rate, channels)
        except OSError as exc:
            log.debug("%s não iniciou: %s", self.name, exc)
            return
        try:
            assert proc.stdin is not None
            proc.stdin.write(pcm)
            with contextlib.suppress(ConnectionError, BrokenPipeError):
                await proc.stdin.drain()
            proc.stdin.close()
            await proc.wait()
        finally:
            self._procs.discard(proc)

    async def open_stream(self, rate: int, channels: int) -> AudioStream:
        proc = await self._spawn(rate, channels)
        return _ProcessStream(self, proc)

    def stop(self) -> None:
        for proc in list(self._procs):
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        self._procs.clear()


class _ProcessStream(AudioStream):
    def __init__(self, owner: SubprocessPlayer, proc: asyncio.subprocess.Process) -> None:
        self._owner, self._proc = owner, proc

    async def write(self, pcm: bytes) -> None:
        if self._proc.stdin is None or self._proc.returncode is not None:
            return
        self._proc.stdin.write(pcm)
        with contextlib.suppress(ConnectionError, BrokenPipeError):
            await self._proc.stdin.drain()

    async def finish(self) -> None:
        if self._proc.stdin is not None:
            with contextlib.suppress(Exception):
                self._proc.stdin.close()
        await self._proc.wait()
        self._owner._procs.discard(self._proc)

    def abort(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self._proc.kill()
        self._owner._procs.discard(self._proc)


def _pw_play_supports_raw(exe: str) -> bool:
    try:
        out = subprocess.run(
            [exe, "--help"], capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "--raw" in (out.stdout + out.stderr)


def create_player(preferred: str = "auto", device: str = "") -> AudioPlayer:
    """Escolhe o melhor reprodutor disponível nesta máquina."""
    order = ["sounddevice", "pw-play", "pacat", "aplay"]
    if preferred not in ("", "auto") and preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    for name in order:
        if name == "sounddevice":
            sd = optional_import("sounddevice")
            if sd is not None:
                return SoundDevicePlayer(sd, device or None)
        elif name == "pw-play":
            exe = shutil.which("pw-play")
            if exe and _pw_play_supports_raw(exe):
                argv = [exe, "-a", "--format=s16", "--rate={rate}", "--channels={channels}"]
                if device:
                    argv.append(f"--target={device}")
                return SubprocessPlayer("pw-play", [*argv, "-"])
        elif name == "pacat":
            exe = shutil.which("pacat")
            if exe:
                argv = [exe, "--playback", "--raw", "--format=s16le"]
                argv += ["--rate={rate}", "--channels={channels}", "--latency-msec=20"]
                if device:
                    argv.append(f"--device={device}")
                return SubprocessPlayer("pacat", argv)
        elif name == "aplay":
            exe = shutil.which("aplay")
            if exe:
                argv = [exe, "-q", "-t", "raw", "-f", "S16_LE", "-r", "{rate}", "-c", "{channels}"]
                if device:
                    argv += ["-D", device]
                return SubprocessPlayer("aplay", [*argv, "-"])
    log.warning("Nenhuma saída de áudio encontrada (sounddevice, pw-play, pacat, aplay)")
    return NullPlayer()
