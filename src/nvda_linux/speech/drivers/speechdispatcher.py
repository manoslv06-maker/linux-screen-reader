"""Driver do Speech Dispatcher.

Dois transportes, mesmo comportamento:

- ``native`` (padrão): :class:`~nvda_linux.speech.ssip.SSIPClient` sobre o
  socket Unix com asyncio. ``cancel()`` é uma escrita de ``CANCEL self`` no
  socket, sem esperar resposta: latência de microssegundos e zero threads.
- ``module``: o módulo ``speechd`` da distribuição (``python3-speechd``).
  Como as chamadas dele são síncronas (esperam a resposta do servidor), elas
  rodam num executor de um thread só: a ordem é preservada (FIFO) e o loop
  nunca bloqueia.

``transport = "auto"`` tenta o nativo e cai para o módulo se ele falhar.
Enunciados vão como SSML (``SSML_MODE on``), o que dá pausas, soletração e
mudança de tom ao mesmo tempo em qualquer módulo de saída do speechd.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import shutil
from collections.abc import Callable
from typing import Any

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger
from nvda_linux.speech.driver import (
    SynthDriver,
    SynthDriverError,
    Utterance,
    VoiceInfo,
    VoiceSettings,
    clamp,
    segments_to_ssml,
)
from nvda_linux.speech.ssip import (
    EVENT_CANCELED,
    EVENT_END,
    EVENT_INDEX_MARK,
    SSIPClient,
    SSIPError,
    SSIPEvent,
    resolve_address,
)

log = get_logger(__name__)

ConfigGetter = Callable[[str, Any], Any]


def nvda_to_ssip(value: int) -> int:
    """0..100 (NVDA) -> -100..100 (SSIP)."""
    return clamp(value) * 2 - 100


def mark_to_index(mark: object) -> int | None:
    """Nome de ``<mark name="n"/>`` devolvido pelo servidor -> índice ``n``.

    Marcas que não são números (ex.: as internas do speechd) são ignoradas.
    """
    try:
        return int(str(mark).strip())
    except (TypeError, ValueError):
        return None


class _NativeTransport:
    """Transporte SSIP próprio, 100% asyncio."""

    def __init__(self, driver: SpeechDispatcherDriver) -> None:
        self._driver = driver
        self.client = SSIPClient(on_event=self._on_event)
        self._msg_to_utt: dict[int, int] = {}
        self._early: dict[int, int] = {}  # msg_id -> código de evento recebido cedo

    async def open(self) -> None:
        await self.client.connect(autospawn=self._driver.autospawn)
        await self.client.command("SET self SSML_MODE on")
        with contextlib.suppress(SSIPError):
            await self.client.command(f"SET self PRIORITY {self._driver.priority}")
        if self._driver.output_module:
            with contextlib.suppress(SSIPError):
                await self.client.command(f"SET self OUTPUT_MODULE {self._driver.output_module}")

    async def speak(self, utterance: Utterance, ssml: str) -> None:
        msg_id = await self.client.speak(ssml)
        early = self._early.pop(msg_id, None)
        if early is not None:
            self._driver.notify_done(utterance.id)
        else:
            self._msg_to_utt[msg_id] = utterance.id

    def cancel(self) -> None:
        self._msg_to_utt.clear()
        self._early.clear()
        if self.client.connected:
            self.client.cancel()

    def pause(self, paused: bool) -> None:
        if self.client.connected:
            self.client.send_nowait("PAUSE self" if paused else "RESUME self")

    def apply(self, settings: VoiceSettings) -> None:
        if not self.client.connected:
            return
        send = self.client.send_nowait
        send(f"SET self RATE {nvda_to_ssip(settings.rate)}")
        send(f"SET self PITCH {nvda_to_ssip(settings.pitch)}")
        send(f"SET self VOLUME {nvda_to_ssip(settings.volume)}")
        if settings.language:
            send(f"SET self LANGUAGE {settings.language}")
        if settings.voice:
            send(f"SET self SYNTHESIS_VOICE {settings.voice}")

    async def voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(n, n, lang, var) for n, lang, var in await self.client.list_voices()]

    async def close(self) -> None:
        await self.client.close()

    @property
    def connected(self) -> bool:
        return self.client.connected

    def _on_event(self, event: SSIPEvent) -> None:
        if event.code == EVENT_INDEX_MARK:
            utt_id = self._msg_to_utt.get(event.msg_id)
            index = mark_to_index(event.mark)
            if utt_id is not None and index is not None:
                self._driver.notify_index(utt_id, index)
            return  # marca antes da resposta do SPEAK: o fim do enunciado cobre
        if event.code not in (EVENT_END, EVENT_CANCELED):
            return
        utt = self._msg_to_utt.pop(event.msg_id, None)
        if utt is None:
            self._early[event.msg_id] = event.code
            if len(self._early) > 64:  # evita crescer sem limite
                self._early.pop(next(iter(self._early)))
            return
        self._driver.notify_done(utt)


class _ModuleTransport:
    """Transporte via módulo ``speechd`` (síncrono, isolado num thread)."""

    def __init__(self, driver: SpeechDispatcherDriver, speechd: Any) -> None:
        self._driver = driver
        self._speechd = speechd
        self._client: Any = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="speechd"
        )
        self._generation = 0

    def _submit(self, fn: Callable[[], Any]) -> None:
        def run() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log.warning("Chamada ao speechd falhou: %s", exc)

        try:
            self._executor.submit(run)
        except RuntimeError:  # executor já encerrado
            pass

    async def open(self) -> None:
        sd = self._speechd
        loop = asyncio.get_running_loop()

        def connect() -> Any:
            client = sd.SSIPClient("nvda-linux", component="main", autospawn=self._driver.autospawn)
            client.set_data_mode(sd.DataMode.SSML)
            prio = getattr(sd.Priority, self._driver.priority.upper(), sd.Priority.MESSAGE)
            client.set_priority(prio)
            if self._driver.output_module:
                client.set_output_module(self._driver.output_module)
            return client

        try:
            self._client = await loop.run_in_executor(self._executor, connect)
        except Exception as exc:  # speechd levanta várias classes
            raise SynthDriverError(f"módulo speechd não conectou: {exc}") from exc

    async def speak(self, utterance: Utterance, ssml: str) -> None:
        sd = self._speechd
        generation = self._generation
        utt_id = utterance.id

        index_type = getattr(sd.CallbackType, "INDEX_MARK", None)

        def callback(callback_type: Any, index_mark: Any = None) -> None:
            if generation != self._generation:
                return
            if index_type is not None and callback_type == index_type:
                index = mark_to_index(index_mark)
                if index is not None:
                    self._driver.notify_index(utt_id, index)
                return
            self._driver.notify_done(utt_id)

        def do_speak() -> None:
            if generation != self._generation or self._client is None:
                return
            event_types = [sd.CallbackType.END, sd.CallbackType.CANCEL]
            if index_type is not None and utterance.indexes:
                event_types.append(index_type)
            self._client.speak(ssml, callback=callback, event_types=tuple(event_types))

        self._submit(do_speak)

    def cancel(self) -> None:
        self._generation += 1
        client = self._client
        if client is not None:
            self._submit(client.cancel)

    def pause(self, paused: bool) -> None:
        client = self._client
        if client is not None:
            self._submit(client.pause if paused else client.resume)

    def apply(self, settings: VoiceSettings) -> None:
        client = self._client
        if client is None:
            return

        def do_apply() -> None:
            client.set_rate(nvda_to_ssip(settings.rate))
            client.set_pitch(nvda_to_ssip(settings.pitch))
            client.set_volume(nvda_to_ssip(settings.volume))
            if settings.language:
                client.set_language(settings.language)
            if settings.voice:
                client.set_synthesis_voice(settings.voice)

        self._submit(do_apply)

    async def voices(self) -> list[VoiceInfo]:
        client = self._client
        if client is None:
            return []
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(self._executor, client.list_synthesis_voices)
        return [VoiceInfo(str(v[0]), str(v[0]), str(v[1]), str(v[2])) for v in raw]

    async def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            self._submit(client.close)
        self._executor.shutdown(wait=False, cancel_futures=False)

    @property
    def connected(self) -> bool:
        return self._client is not None


class SpeechDispatcherDriver(SynthDriver):
    """Sintetizador via Speech Dispatcher (todos os módulos: eSpeak-NG, RHVoice, Piper...)."""

    name = "speechd"
    description = "Speech Dispatcher"
    supports_ssml = True
    supports_spelling = True
    supports_index_marks = True  # <mark name="n"/> + eventos 700 INDEX_MARK

    def __init__(
        self,
        *,
        transport: str = "auto",
        output_module: str = "",
        priority: str = "message",
        autospawn: bool = True,
    ) -> None:
        super().__init__()
        self.transport_name = transport
        self.output_module = output_module
        self.priority = priority
        self.autospawn = autospawn
        self._transport: _NativeTransport | _ModuleTransport | None = None
        self._generation = 0
        self._tasks: set[asyncio.Task[None]] = set()

    @classmethod
    def from_config(cls, get: ConfigGetter) -> SpeechDispatcherDriver:
        return cls(
            transport=str(get("speech.speechd.transport", "auto")),
            output_module=str(get("speech.speechd.outputModule", "")),
            priority=str(get("speech.speechd.priority", "message")),
            autospawn=bool(get("speech.speechd.autospawn", True)),
        )

    @classmethod
    def check(cls) -> bool:
        address = resolve_address()
        if address.method == "inet_socket":
            return True
        return (
            os.path.exists(address.path)
            or shutil.which("speech-dispatcher") is not None
            or optional_import("speechd") is not None
        )

    @property
    def active_transport(self) -> str:
        if isinstance(self._transport, _NativeTransport):
            return "native"
        if isinstance(self._transport, _ModuleTransport):
            return "module"
        return "none"

    async def initialize(self) -> None:
        errors: list[str] = []
        if self.transport_name in ("auto", "native"):
            native = _NativeTransport(self)
            try:
                await native.open()
                self._transport = native
            except (SSIPError, OSError) as exc:
                errors.append(f"nativo: {exc}")
                with contextlib.suppress(Exception):
                    await native.close()
        if self._transport is None and self.transport_name in ("auto", "module"):
            speechd = optional_import("speechd")
            if speechd is None:
                errors.append("módulo speechd não instalado (python3-speechd)")
            else:
                module = _ModuleTransport(self, speechd)
                try:
                    await module.open()
                    self._transport = module
                except SynthDriverError as exc:
                    errors.append(str(exc))
        if self._transport is None:
            raise SynthDriverError("; ".join(errors) or "transporte desconhecido")
        self._transport.apply(self.settings)
        log.info("Speech Dispatcher conectado (transporte %s)", self.active_transport)

    def speak(self, utterance: Utterance) -> None:
        transport = self._transport
        if transport is None:
            self.notify_done(utterance.id)
            return
        generation = self._generation
        ssml = segments_to_ssml(utterance.segments)

        async def run() -> None:
            # Se cancel() veio antes desta tarefa rodar, nada é enviado.
            if generation != self._generation:
                return
            try:
                if not transport.connected:
                    await self._reconnect()
                    if generation != self._generation:
                        return
                current = self._transport
                if current is None:
                    raise SynthDriverError("sem conexão")
                await current.speak(utterance, ssml)
            except (SSIPError, SynthDriverError, OSError) as exc:
                log.warning("Falha ao falar pelo Speech Dispatcher: %s", exc)
                self.notify_done(utterance.id)

        task = asyncio.get_running_loop().create_task(run(), name=f"speechd-speak-{utterance.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _reconnect(self) -> None:
        log.info("Reconectando ao Speech Dispatcher")
        old = self._transport
        self._transport = None
        if old is not None:
            with contextlib.suppress(Exception):
                await old.close()
        await self.initialize()

    def cancel(self) -> None:
        self._generation += 1
        if self._transport is not None:
            self._transport.cancel()

    def pause(self, paused: bool) -> None:
        if self._transport is not None:
            self._transport.pause(paused)

    def apply_settings(self, settings: VoiceSettings) -> None:
        super().apply_settings(settings)
        if self._transport is not None:
            self._transport.apply(settings)

    async def available_voices(self) -> list[VoiceInfo]:
        if self._transport is None:
            return []
        try:
            return await self._transport.voices()
        except (SSIPError, OSError) as exc:
            log.warning("Não foi possível listar vozes: %s", exc)
            return []

    async def terminate(self) -> None:
        self.cancel()
        for task in list(self._tasks):
            task.cancel()
        if self._transport is not None:
            with contextlib.suppress(Exception):
                await self._transport.close()
        self._transport = None
