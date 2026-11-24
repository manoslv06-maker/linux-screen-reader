"""Driver de reserva: eSpeak-NG por subprocesso.

Usado quando o Speech Dispatcher não está disponível. Cada enunciado é um
processo ``espeak-ng -m --stdin`` (SSML na entrada padrão); o fim do
processo marca o fim do enunciado. ``cancel()`` mata o processo (SIGKILL),
``pause()`` usa SIGSTOP/SIGCONT.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
from collections.abc import Callable
from typing import Any

from nvda_linux.core.log import get_logger
from nvda_linux.speech.driver import (
    SynthDriver,
    SynthDriverError,
    Utterance,
    VoiceInfo,
    clamp,
    scale,
    segments_to_ssml,
)

log = get_logger(__name__)

ConfigGetter = Callable[[str, Any], Any]


def language_from_locale(environ: dict[str, str] | None = None) -> str:
    """``pt_BR.UTF-8`` -> ``pt-br`` (nome de voz do eSpeak-NG)."""
    env = dict(os.environ) if environ is None else environ
    raw = env.get("LC_ALL") or env.get("LC_MESSAGES") or env.get("LANG") or "en"
    lang = raw.split(".")[0].split("@")[0]
    if lang in ("C", "POSIX", ""):
        return "en"
    return lang.replace("_", "-").lower()


class EspeakDriver(SynthDriver):
    """eSpeak-NG chamado como programa externo."""

    name = "espeak"
    description = "eSpeak-NG (subprocesso)"
    supports_ssml = True
    supports_spelling = True

    def __init__(self, executable: str = "espeak-ng") -> None:
        super().__init__()
        self.executable = executable
        self._exe: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._generation = 0
        self._paused = False

    @classmethod
    def from_config(cls, get: ConfigGetter) -> EspeakDriver:
        return cls(str(get("speech.espeak.executable", "espeak-ng")))

    @classmethod
    def check(cls) -> bool:
        return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None

    async def initialize(self) -> None:
        self._exe = shutil.which(self.executable) or shutil.which("espeak")
        if self._exe is None:
            raise SynthDriverError(f"{self.executable} não encontrado no PATH")

    def build_argv(self) -> list[str]:
        """Linha de comando para o enunciado, a partir de ``self.settings``."""
        s = self.settings
        voice = s.voice or s.language or language_from_locale()
        if s.variant:
            voice = f"{voice}+{s.variant}"
        return [
            self._exe or self.executable,
            "-m",
            "--stdin",
            "-v",
            voice,
            "-s",
            str(round(scale(s.rate, 80, 450))),
            "-p",
            str(clamp(s.pitch, 0, 99)),
            "-a",
            str(round(scale(s.volume, 0, 200) / 2)),
        ]

    def speak(self, utterance: Utterance) -> None:
        generation = self._generation
        ssml = segments_to_ssml(utterance.segments)

        async def run() -> None:
            if generation != self._generation:
                return
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.build_argv(),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                log.warning("espeak-ng não iniciou: %s", exc)
                self.notify_done(utterance.id)
                return
            if generation != self._generation:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
                return
            self._proc = proc
            if self._paused:
                with contextlib.suppress(ProcessLookupError):
                    proc.send_signal(signal.SIGSTOP)
            assert proc.stdin is not None
            proc.stdin.write(ssml.encode("utf-8"))
            with contextlib.suppress(ConnectionError, BrokenPipeError):
                await proc.stdin.drain()
            proc.stdin.close()
            await proc.wait()
            if self._proc is proc:
                self._proc = None
            if generation == self._generation:
                self.notify_done(utterance.id)

        self._task = asyncio.get_running_loop().create_task(run(), name=f"espeak-{utterance.id}")

    def cancel(self) -> None:
        self._generation += 1
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
                if self._paused:
                    proc.send_signal(signal.SIGCONT)

    def pause(self, paused: bool) -> None:
        self._paused = paused
        proc = self._proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGSTOP if paused else signal.SIGCONT)

    async def available_voices(self) -> list[VoiceInfo]:
        if self._exe is None:
            return []
        try:
            proc = await asyncio.create_subprocess_exec(
                self._exe,
                "--voices",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), 5)
        except (TimeoutError, OSError):
            return []
        voices: list[VoiceInfo] = []
        for line in out.decode("utf-8", "replace").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4:
                voices.append(VoiceInfo(fields[1], fields[3], fields[1]))
        return voices

    async def terminate(self) -> None:
        self.cancel()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
