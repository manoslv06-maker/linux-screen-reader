"""Cliente SSIP nativo e SpeechDispatcherDriver contra um servidor SSIP falso."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nvda_linux.speech.driver import IndexSegment, TextSegment, Utterance
from nvda_linux.speech.drivers.speechdispatcher import (
    SpeechDispatcherDriver,
    mark_to_index,
    nvda_to_ssip,
)
from nvda_linux.speech.ssip import (
    EVENT_END,
    SSIPAddress,
    SSIPClient,
    SSIPError,
    SSIPEvent,
    escape_data,
    resolve_address,
)
from tests.platform.fakes import wait_for


class FakeSSIPServer:
    """Servidor SSIP mínimo: responde comandos, recebe SPEAK e emite eventos."""

    def __init__(self, path: Path, *, auto_end: bool = True) -> None:
        self.path = path
        self.auto_end = auto_end
        self.lines: list[str] = []
        self.messages: list[str] = []
        self._next_id = 100
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self.delay_230 = 0.0

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(self._client, path=str(self.path))

    async def close(self) -> None:
        for w in self._writers:
            w.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def drop_clients(self) -> None:
        for w in self._writers:
            w.close()
        self._writers.clear()

    @property
    def commands(self) -> list[str]:
        return [line for line in self.lines if not line.startswith("DATA:")]

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.append(writer)

        def send(text: str) -> None:
            writer.write(text.encode())

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    return
                line = raw.decode().rstrip("\r\n")
                self.lines.append(line)
                if line == "SPEAK":
                    if self.delay_230:
                        await asyncio.sleep(self.delay_230)
                    send("230 OK RECEIVING DATA\r\n")
                    body: list[str] = []
                    while True:
                        data = (await reader.readline()).decode().rstrip("\r\n")
                        if data == ".":
                            break
                        body.append(data[1:] if data.startswith("..") else data)
                    text = "\n".join(body)
                    self.lines.append("DATA:" + text)
                    self.messages.append(text)
                    msg_id = self._next_id
                    self._next_id += 1
                    send(f"225-{msg_id}\r\n225 OK MESSAGE QUEUED\r\n")
                    if self.auto_end:
                        send(f"701-{msg_id}\r\n701-1\r\n701 BEGIN\r\n")
                        send(f"702-{msg_id}\r\n702-1\r\n702 END\r\n")
                elif line.startswith("CANCEL"):
                    send("210 OK CANCELED\r\n")
                elif line.startswith("LIST SYNTHESIS_VOICES"):
                    send("249-pt-br\tpt\tnone\r\n249-en\ten\tnone\r\n249 OK VOICE LIST SENT\r\n")
                elif line == "QUIT":
                    send("231 HAPPY HACKING\r\n")
                    return
                elif line.startswith("SET self BOGUS"):
                    send("500 ERR UNKNOWN PARAMETER\r\n")
                else:
                    send("200 OK\r\n")
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            return

    def emit_end(self, msg_id: int) -> None:
        for w in self._writers:
            w.write(f"702-{msg_id}\r\n702-1\r\n702 END\r\n".encode())

    def emit_mark(self, msg_id: int, name: str) -> None:
        for w in self._writers:
            w.write(f"700-{msg_id}\r\n700-1\r\n700-{name}\r\n700 INDEX MARK\r\n".encode())


@pytest.fixture
async def server(tmp_path: Path) -> AsyncIterator[FakeSSIPServer]:
    srv = FakeSSIPServer(tmp_path / "speechd.sock")
    await srv.start()
    yield srv
    await srv.close()


def test_escape_data_dot_stuffing() -> None:
    assert escape_data("oi\n.ponto\r\nfim") == b"oi\r\n..ponto\r\nfim\r\n.\r\n"


def test_resolve_address() -> None:
    assert resolve_address({"SPEECHD_ADDRESS": "unix_socket:/tmp/x.sock"}).path == "/tmp/x.sock"
    inet = resolve_address({"SPEECHD_ADDRESS": "inet_socket:localhost:7000"})
    assert (inet.method, inet.host, inet.port) == ("inet_socket", "localhost", 7000)
    default = resolve_address({"XDG_RUNTIME_DIR": "/run/user/1000"})
    assert default.path == "/run/user/1000/speech-dispatcher/speechd.sock"


async def test_client_handshake_speak_events_and_cancel(server: FakeSSIPServer) -> None:
    events: list[SSIPEvent] = []
    client = SSIPClient(on_event=events.append)
    await client.connect(SSIPAddress("unix_socket", path=str(server.path)), autospawn=False)
    assert server.commands[:2] == [
        "SET self CLIENT_NAME user:nvda-linux:main",
        "SET self NOTIFICATION all on",
    ]
    msg_id = await client.speak("olá\n.mundo")
    assert msg_id == 100
    assert server.messages == ["olá\n.mundo"]
    await wait_for(lambda: any(e.code == EVENT_END for e in events))
    assert events[-1].msg_id == 100 and events[-1].kind == "end"
    client.cancel()
    await wait_for(lambda: "CANCEL self" in server.commands)
    voices = await client.list_voices()
    assert voices[0] == ("pt-br", "pt", "none")
    with pytest.raises(SSIPError):
        await client.command("SET self BOGUS 1")
    await client.close()
    assert not client.connected


async def test_cancel_during_data_phase_is_deferred(server: FakeSSIPServer) -> None:
    """CANCEL no meio de um SPEAK não pode virar texto: vai logo depois do '.'."""
    server.delay_230 = 0.05
    client = SSIPClient()
    await client.connect(SSIPAddress("unix_socket", path=str(server.path)), autospawn=False)
    task = asyncio.ensure_future(client.speak("texto"))
    await asyncio.sleep(0.01)  # SPEAK enviado, esperando o 230
    client.cancel()
    await task
    await wait_for(lambda: "CANCEL self" in server.commands)
    assert server.messages == ["texto"]
    idx_data = server.lines.index("DATA:texto")
    assert server.lines.index("CANCEL self") > idx_data
    await client.close()


async def test_connect_failure_without_autospawn(tmp_path: Path) -> None:
    client = SSIPClient()
    with pytest.raises(SSIPError):
        await client.connect(
            SSIPAddress("unix_socket", path=str(tmp_path / "nada.sock")), autospawn=False
        )


# ---------------------------------------------------------------- driver
def _utt(i: int, text: str) -> Utterance:
    return Utterance(i, (TextSegment(text),))


async def _native_driver(
    server: FakeSSIPServer, monkeypatch: pytest.MonkeyPatch
) -> tuple[SpeechDispatcherDriver, list[int]]:
    monkeypatch.setenv("SPEECHD_ADDRESS", f"unix_socket:{server.path}")
    driver = SpeechDispatcherDriver(transport="native", autospawn=False)
    done: list[int] = []
    driver.bind(asyncio.get_running_loop(), done.append)
    await driver.initialize()
    return driver, done


async def test_driver_native_speak_and_done(
    server: FakeSSIPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, done = await _native_driver(server, monkeypatch)
    assert driver.active_transport == "native"
    assert "SET self SSML_MODE on" in server.commands
    assert "SET self PRIORITY message" in server.commands
    driver.speak(_utt(7, "bom dia & boa noite"))
    await wait_for(lambda: done == [7])
    assert server.messages == ["<speak>bom dia &amp; boa noite</speak>"]
    await driver.terminate()


async def test_driver_native_index_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = FakeSSIPServer(tmp_path / "marks.sock", auto_end=False)
    await server.start()
    try:
        driver, done = await _native_driver(server, monkeypatch)
        marks: list[tuple[int, int]] = []
        driver.bind(asyncio.get_running_loop(), done.append, lambda u, i: marks.append((u, i)))
        assert driver.supports_index_marks
        driver.speak(Utterance(4, (TextSegment("um"), IndexSegment(1), TextSegment("dois"))))
        await wait_for(lambda: server.messages == ['<speak>um<mark name="1"/>dois</speak>'])
        await asyncio.sleep(0.05)  # resposta 225 do SPEAK registrada
        server.emit_mark(100, "1")
        server.emit_mark(100, "__spd_interno")  # marca do próprio speechd: ignorada
        server.emit_end(100)
        await wait_for(lambda: done == [4])
        assert marks == [(4, 1)]
        await driver.terminate()
    finally:
        await server.close()


def test_mark_to_index() -> None:
    assert mark_to_index("12") == 12
    assert mark_to_index(" 3 ") == 3
    assert mark_to_index("__spd_x") is None
    assert mark_to_index(None) is None


async def test_driver_cancel_before_send_drops_utterance(
    server: FakeSSIPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, done = await _native_driver(server, monkeypatch)
    driver.speak(_utt(1, "não deve sair"))
    driver.cancel()
    await wait_for(lambda: "CANCEL self" in server.commands)
    await asyncio.sleep(0.05)
    assert server.messages == []
    assert done == []
    await driver.terminate()


async def test_driver_settings_mapping(
    server: FakeSSIPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, _ = await _native_driver(server, monkeypatch)
    from nvda_linux.speech.driver import VoiceSettings

    driver.apply_settings(VoiceSettings(rate=75, pitch=50, volume=100, language="pt", voice="x"))
    await wait_for(lambda: "SET self SYNTHESIS_VOICE x" in server.commands)
    assert "SET self RATE 50" in server.commands
    assert "SET self PITCH 0" in server.commands
    assert "SET self VOLUME 100" in server.commands
    assert "SET self LANGUAGE pt" in server.commands
    voices = await driver.available_voices()
    assert [v.id for v in voices] == ["pt-br", "en"]
    assert nvda_to_ssip(0) == -100 and nvda_to_ssip(100) == 100
    await driver.terminate()


async def test_driver_reconnects_after_server_drop(
    server: FakeSSIPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, done = await _native_driver(server, monkeypatch)
    server.drop_clients()
    await asyncio.sleep(0.05)
    driver.speak(_utt(3, "de novo"))
    await wait_for(lambda: done == [3])
    assert server.messages[-1] == "<speak>de novo</speak>"
    await driver.terminate()


async def test_driver_falls_back_to_speechd_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem socket nativo, usa o módulo speechd (simulado) num thread próprio."""
    monkeypatch.setenv("SPEECHD_ADDRESS", f"unix_socket:{tmp_path / 'nada.sock'}")
    calls: list[tuple[str, Any]] = []

    class FakeClient:
        def __init__(self, name: str, component: str, autospawn: bool) -> None:
            calls.append(("init", name))

        def set_data_mode(self, mode: Any) -> None:
            calls.append(("mode", mode))

        def set_priority(self, prio: Any) -> None:
            calls.append(("prio", prio))

        def speak(self, text: str, callback: Any, event_types: Any) -> None:
            calls.append(("speak", text))
            callback("end")

        def cancel(self) -> None:
            calls.append(("cancel", None))

        def set_rate(self, v: int) -> None:
            calls.append(("rate", v))

        def set_pitch(self, v: int) -> None: ...

        def set_volume(self, v: int) -> None: ...

        def close(self) -> None:
            calls.append(("close", None))

    fake = SimpleNamespace(
        SSIPClient=FakeClient,
        DataMode=SimpleNamespace(SSML="ssml"),
        Priority=SimpleNamespace(MESSAGE="message"),
        CallbackType=SimpleNamespace(END="end", CANCEL="cancel"),
    )
    from nvda_linux.core import compat

    compat.inject_module("speechd", fake)
    try:
        driver = SpeechDispatcherDriver(transport="auto", autospawn=False)
        done: list[int] = []
        driver.bind(asyncio.get_running_loop(), done.append)
        await driver.initialize()
        assert driver.active_transport == "module"
        driver.speak(_utt(5, "oi"))
        await wait_for(lambda: done == [5])
        driver.cancel()
        await wait_for(lambda: ("cancel", None) in calls)
        assert ("mode", "ssml") in calls and ("speak", "<speak>oi</speak>") in calls
        await driver.terminate()
    finally:
        compat.reset_cache()
        with contextlib.suppress(Exception):
            compat.inject_module("speechd", None)
        compat.reset_cache()
