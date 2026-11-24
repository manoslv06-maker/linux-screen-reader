"""Driver opcional: Piper TTS (vozes neurais locais).

Usa o executável ``piper`` (rhasspy/piper) com ``--output_raw``: o texto vai
no stdin e o PCM s16 mono sai no stdout, que é repassado em fluxo para a
saída de áudio (:mod:`nvda_linux.speech.audio`). A taxa de amostragem vem do
``<modelo>.onnx.json`` (``audio.sample_rate``) ou de
``speech.piper.sampleRate``.

Limitações: sem SSML (pausas viram pontuação, soletração usa nomes de
letras) e a latência inicial é maior que a do Speech Dispatcher, porque o
modelo é carregado a cada enunciado. Para uso diário, prefira o Piper como
módulo de saída do próprio Speech Dispatcher.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nvda_linux.core.log import get_logger
from nvda_linux.speech.audio import AudioPlayer, AudioStream, create_player
from nvda_linux.speech.driver import (
    SynthDriver,
    SynthDriverError,
    Utterance,
    scale,
    segments_to_text,
)

log = get_logger(__name__)

ConfigGetter = Callable[[str, Any], Any]
DEFAULT_RATE = 22050


def model_sample_rate(model: Path) -> int:
    """Lê ``audio.sample_rate`` do JSON do modelo (22050 se não achar)."""
    for candidate in (Path(str(model) + ".json"), model.with_suffix(".json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rate = data.get("audio", {}).get("sample_rate")
        if isinstance(rate, int) and rate > 0:
            return rate
    return DEFAULT_RATE


class PiperDriver(SynthDriver):
    """Piper TTS por subprocesso, com áudio em fluxo."""

    name = "piper"
    description = "Piper TTS (neural, local)"
    supports_ssml = False
    supports_spelling = False

    def __init__(
        self,
        executable: str = "piper",
        model: str = "",
        sample_rate: int = 0,
        player: AudioPlayer | None = None,
    ) -> None:
        super().__init__()
        self.executable = executable
        self.model = Path(model).expanduser() if model else None
        self.sample_rate = sample_rate
        self._player = player
        self._exe: str | None = None
        self._generation = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._stream: AudioStream | None = None
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def from_config(cls, get: ConfigGetter) -> PiperDriver:
        return cls(
            executable=str(get("speech.piper.executable", "piper")),
            model=str(get("speech.piper.model", "")),
            sample_rate=int(get("speech.piper.sampleRate", 0)),
            player=create_player(device=str(get("audio.outputDevice", ""))),
        )

    @classmethod
    def check(cls) -> bool:
        return shutil.which("piper") is not None

    async def initialize(self) -> None:
        self._exe = shutil.which(self.executable)
        if self._exe is None:
            raise SynthDriverError(f"{self.executable} não encontrado")
        if self.model is None or not self.model.exists():
            raise SynthDriverError("speech.piper.model não configurado ou inexistente")
        if self.sample_rate <= 0:
            self.sample_rate = model_sample_rate(self.model)
        if self._player is None:
            self._player = create_player()

    def build_argv(self) -> list[str]:
        # length_scale > 1 = mais lento. rate 50 -> 1.0; 100 -> 0.5; 0 -> 2.0
        length_scale = 2.0 ** (-(scale(self.settings.rate, -1.0, 1.0)))
        return [
            self._exe or self.executable,
            "--model",
            str(self.model),
            "--output_raw",
            "--length_scale",
            f"{length_scale:.3f}",
        ]

    def speak(self, utterance: Utterance) -> None:
        generation = self._generation
        text = segments_to_text(utterance.segments)

        async def run() -> None:
            if generation != self._generation or not text or self._player is None:
                self.notify_done(utterance.id)
                return
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.build_argv(),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stream = await self._player.open_stream(self.sample_rate, 1)
            except OSError as exc:
                log.warning("Piper não iniciou: %s", exc)
                self.notify_done(utterance.id)
                return
            self._proc, self._stream = proc, stream
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write((text + "\n").encode("utf-8"))
            with contextlib.suppress(ConnectionError, BrokenPipeError):
                await proc.stdin.drain()
            proc.stdin.close()
            while generation == self._generation:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                await stream.write(chunk)
            if generation == self._generation:
                await stream.finish()
                await proc.wait()
                self.notify_done(utterance.id)

        self._task = asyncio.get_running_loop().create_task(run(), name=f"piper-{utterance.id}")

    def cancel(self) -> None:
        self._generation += 1
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()
        if self._stream is not None:
            self._stream.abort()
        self._proc = None
        self._stream = None

    def pause(self, paused: bool) -> None:
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.send_signal(signal.SIGSTOP if paused else signal.SIGCONT)

    async def terminate(self) -> None:
        self.cancel()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
