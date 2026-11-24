"""Cliente SSIP (Speech Synthesis Interface Protocol) assíncrono e nativo.

O Speech Dispatcher fala SSIP, um protocolo de texto por socket Unix. Este
cliente usa ``asyncio`` diretamente sobre o socket, sem threads, para que o
cancelamento seja uma simples escrita de ``CANCEL self`` no socket
(microssegundos) e nunca espere resposta. É o transporte padrão do
:class:`~nvda_linux.speech.drivers.speechdispatcher.SpeechDispatcherDriver`;
o módulo ``speechd`` da distribuição fica como alternativa.

Formato das respostas::

    NNN-linha de continuação\\r\\n
    NNN linha final\\r\\n

Códigos 700..799 são notificações assíncronas (BEGIN, END, CANCELED...),
que chegam intercaladas com as respostas dos comandos.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from nvda_linux.core.log import get_logger

log = get_logger(__name__)

EVENT_INDEX_MARK: Final = 700
EVENT_BEGIN: Final = 701
EVENT_END: Final = 702
EVENT_CANCELED: Final = 703
EVENT_PAUSED: Final = 704
EVENT_RESUMED: Final = 705

_EVENT_NAMES: Final = {
    EVENT_INDEX_MARK: "index_mark",
    EVENT_BEGIN: "begin",
    EVENT_END: "end",
    EVENT_CANCELED: "canceled",
    EVENT_PAUSED: "paused",
    EVENT_RESUMED: "resumed",
}


class SSIPError(RuntimeError):
    """Resposta de erro do servidor ou falha de conexão."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SSIPReply:
    code: int
    lines: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return 200 <= self.code < 300

    @property
    def data(self) -> tuple[str, ...]:
        """Linhas de continuação (sem a linha final de status)."""
        return self.lines[:-1]


@dataclass(frozen=True, slots=True)
class SSIPEvent:
    code: int
    kind: str
    msg_id: int
    client_id: int
    mark: str | None = None


EventCallback = Callable[[SSIPEvent], None]


@dataclass(frozen=True, slots=True)
class SSIPAddress:
    """Endereço do servidor: socket Unix ou TCP."""

    method: str  # "unix_socket" | "inet_socket"
    path: str = ""
    host: str = "127.0.0.1"
    port: int = 6560

    def describe(self) -> str:
        if self.method == "unix_socket":
            return f"unix_socket:{self.path}"
        return f"inet_socket:{self.host}:{self.port}"


def resolve_address(environ: dict[str, str] | None = None) -> SSIPAddress:
    """Mesma regra do libspeechd: ``SPEECHD_ADDRESS`` ou o socket no runtime dir."""
    env = dict(os.environ) if environ is None else environ
    raw = env.get("SPEECHD_ADDRESS", "").strip()
    if raw:
        method, _, rest = raw.partition(":")
        if method == "unix_socket" and rest:
            return SSIPAddress("unix_socket", path=os.path.expanduser(rest))
        if method == "inet_socket":
            host, _, port = rest.partition(":")
            return SSIPAddress(
                "inet_socket", host=host or "127.0.0.1", port=int(port) if port else 6560
            )
        log.warning("SPEECHD_ADDRESS inválido: %r; usando o padrão", raw)
    runtime = env.get("XDG_RUNTIME_DIR")
    if runtime:
        path = Path(runtime) / "speech-dispatcher" / "speechd.sock"
    else:
        path = Path.home() / ".cache" / "speech-dispatcher" / "speechd.sock"
    return SSIPAddress("unix_socket", path=str(path))


def escape_data(text: str) -> bytes:
    """Prepara o corpo de SPEAK: CRLF e "dot-stuffing" de linhas iniciadas por '.'."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    stuffed = [("." + line) if line.startswith(".") else line for line in lines]
    return ("\r\n".join(stuffed) + "\r\n.\r\n").encode("utf-8")


class SSIPClient:
    """Conexão SSIP com fila de respostas e notificações assíncronas."""

    def __init__(self, on_event: EventCallback | None = None) -> None:
        self.on_event = on_event
        self.on_disconnect: Callable[[], None] | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: collections.deque[asyncio.Future[SSIPReply]] = collections.deque()
        self._deferred: list[tuple[bytes, asyncio.Future[SSIPReply] | None]] = []
        self._in_data_phase = False
        self._speak_lock = asyncio.Lock()
        self._read_task: asyncio.Task[None] | None = None
        self.address: SSIPAddress | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # ----------------------------------------------------------- conexão
    async def connect(
        self,
        address: SSIPAddress | None = None,
        *,
        client_name: str = "user:nvda-linux:main",
        autospawn: bool = True,
        timeout: float = 3.0,
    ) -> None:
        """Conecta, identifica o cliente e liga as notificações."""
        self.address = address or resolve_address()
        try:
            await asyncio.wait_for(self._open(self.address), timeout)
        except (TimeoutError, OSError) as first_error:
            if not autospawn or not await spawn_server():
                raise SSIPError(
                    f"Speech Dispatcher inacessível em {self.address.describe()}: {first_error}"
                ) from first_error
            last: BaseException = first_error
            for _ in range(20):  # até ~2 s para o servidor subir
                await asyncio.sleep(0.1)
                try:
                    await asyncio.wait_for(self._open(self.address), timeout)
                    break
                except (TimeoutError, OSError) as exc:
                    last = exc
            else:
                raise SSIPError(f"Speech Dispatcher não respondeu após autospawn: {last}") from last
        self._read_task = asyncio.get_running_loop().create_task(
            self._read_loop(), name="ssip-reader"
        )
        await self.command(f"SET self CLIENT_NAME {client_name}")
        await self.command("SET self NOTIFICATION all on")

    async def _open(self, address: SSIPAddress) -> None:
        if address.method == "unix_socket":
            reader, writer = await asyncio.open_unix_connection(address.path)
        else:
            reader, writer = await asyncio.open_connection(address.host, address.port)
        self._reader, self._writer = reader, writer

    async def close(self) -> None:
        """Envia QUIT e fecha o socket."""
        if self._writer is not None and not self._writer.is_closing():
            with contextlib.suppress(Exception):
                self._write(b"QUIT\r\n", expect_reply=False)
                await self._writer.drain()
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._read_task
        self._fail_pending(SSIPError("conexão fechada"))
        self._writer = None
        self._reader = None

    # ----------------------------------------------------------- escrita
    def _write(self, data: bytes, *, expect_reply: bool = True) -> asyncio.Future[SSIPReply] | None:
        """Escreve já (ou adia, se um SPEAK estiver no meio). Nunca bloqueia."""
        if self._writer is None or self._writer.is_closing():
            raise SSIPError("não conectado")
        fut: asyncio.Future[SSIPReply] | None = None
        if expect_reply:
            fut = asyncio.get_running_loop().create_future()
        if self._in_data_phase:
            self._deferred.append((data, fut))
        else:
            self._writer.write(data)
            if fut is not None:
                self._pending.append(fut)
        return fut

    def _flush_deferred(self) -> None:
        deferred, self._deferred = self._deferred, []
        for data, fut in deferred:
            if self._writer is None or self._writer.is_closing():
                if fut is not None and not fut.done():
                    fut.set_exception(SSIPError("não conectado"))
                continue
            self._writer.write(data)
            if fut is not None:
                self._pending.append(fut)

    def send_nowait(self, line: str) -> asyncio.Future[SSIPReply] | None:
        """Envia um comando sem esperar a resposta (a resposta é consumida)."""
        fut = self._write((line + "\r\n").encode("utf-8"))
        if fut is not None:
            fut.add_done_callback(_consume_result)
        return fut

    async def command(self, line: str) -> SSIPReply:
        """Envia um comando e espera a resposta; erro do servidor vira exceção."""
        fut = self._write((line + "\r\n").encode("utf-8"))
        assert fut is not None
        reply = await fut
        if not reply.ok:
            raise SSIPError(f"{line!r} -> {reply.code} {reply.lines[-1]}", reply.code)
        return reply

    def cancel(self) -> None:
        """``CANCEL self``: escrita imediata no socket, sem esperar resposta."""
        self.send_nowait("CANCEL self")

    async def speak(self, text: str) -> int:
        """Envia um SPEAK e devolve o ``msg_id`` atribuído pelo servidor."""
        async with self._speak_lock:
            self._in_data_phase = False
            fut = self._write(b"SPEAK\r\n")
            assert fut is not None
            self._in_data_phase = True
            try:
                reply = await fut
                if reply.code != 230:
                    raise SSIPError(f"SPEAK recusado: {reply.code} {reply.lines[-1]}", reply.code)
                assert self._writer is not None
                self._writer.write(escape_data(text))
                done = asyncio.get_running_loop().create_future()
                self._pending.append(done)
            finally:
                self._in_data_phase = False
                self._flush_deferred()
            final: SSIPReply = await done
        if not final.ok:
            raise SSIPError(f"mensagem recusada: {final.code} {final.lines[-1]}", final.code)
        try:
            return int(final.data[0]) if final.data else -1
        except ValueError:
            return -1

    async def list_voices(self) -> list[tuple[str, str, str]]:
        """``LIST SYNTHESIS_VOICES`` -> [(nome, idioma, variante)]."""
        reply = await self.command("LIST SYNTHESIS_VOICES")
        voices: list[tuple[str, str, str]] = []
        for line in reply.data:
            fields = line.split("\t")
            while len(fields) < 3:
                fields.append("")
            voices.append((fields[0], fields[1], fields[2]))
        return voices

    async def list_output_modules(self) -> list[str]:
        reply = await self.command("LIST OUTPUT_MODULES")
        return list(reply.data)

    # ----------------------------------------------------------- leitura
    async def _read_loop(self) -> None:
        assert self._reader is not None
        block: list[str] = []
        try:
            while True:
                raw = await self._reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if len(line) < 4 or not line[:3].isdigit():
                    log.debug("Linha SSIP inesperada: %r", line)
                    continue
                code = int(line[:3])
                block.append(line[4:])
                if line[3] == "-":
                    continue
                lines, block = tuple(block), []
                if 700 <= code < 800:
                    self._dispatch_event(code, lines)
                else:
                    self._resolve(SSIPReply(code, lines))
        except (ConnectionError, OSError) as exc:
            log.warning("Conexão SSIP perdida: %s", exc)
        except asyncio.CancelledError:
            raise
        finally:
            self._fail_pending(SSIPError("conexão com o Speech Dispatcher perdida"))
            if self._writer is not None:
                self._writer.close()
            self._writer = None
            if self.on_disconnect is not None:
                with contextlib.suppress(Exception):
                    self.on_disconnect()

    def _resolve(self, reply: SSIPReply) -> None:
        while self._pending:
            fut = self._pending.popleft()
            if not fut.done():
                fut.set_result(reply)
                return
        log.debug("Resposta SSIP sem comando pendente: %s", reply)

    def _fail_pending(self, exc: Exception) -> None:
        while self._pending:
            fut = self._pending.popleft()
            if not fut.done():
                fut.set_exception(exc)
                fut.add_done_callback(_consume_result)
        for _data, deferred in self._deferred:
            if deferred is not None and not deferred.done():
                deferred.set_exception(exc)
                deferred.add_done_callback(_consume_result)
        self._deferred.clear()

    def _dispatch_event(self, code: int, lines: tuple[str, ...]) -> None:
        if self.on_event is None:
            return
        try:
            msg_id = int(lines[0]) if lines else -1
            client_id = int(lines[1]) if len(lines) > 1 else -1
        except ValueError:
            return
        mark = lines[2] if code == EVENT_INDEX_MARK and len(lines) > 3 else None
        event = SSIPEvent(code, _EVENT_NAMES.get(code, str(code)), msg_id, client_id, mark)
        try:
            self.on_event(event)
        except Exception:
            log.exception("Callback de evento SSIP falhou")


def _consume_result(fut: asyncio.Future[SSIPReply]) -> None:
    if not fut.cancelled():
        exc = fut.exception()
        if exc is not None:
            log.debug("Comando SSIP sem espera falhou: %s", exc)


async def spawn_server(timeout: float = 3.0) -> bool:
    """Roda ``speech-dispatcher --spawn`` (sai na hora se já estiver ativo)."""
    exe = shutil.which("speech-dispatcher")
    if exe is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "--spawn",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout)
    except (TimeoutError, OSError) as exc:
        log.warning("Falha ao iniciar o speech-dispatcher: %s", exc)
        return False
    log.info("speech-dispatcher iniciado por autospawn")
    return True
