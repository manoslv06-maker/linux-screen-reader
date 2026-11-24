"""Loop, watchdog, log, compat, permissões, trava de instância e __main__."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from pathlib import Path

import pytest

from nvda_linux import __main__ as entry
from nvda_linux.core import compat, loop, permissions
from nvda_linux.core.instance import AlreadyRunning, InstanceLock
from nvda_linux.core.log import IO, get_logger, ring_buffer, setup_logging
from nvda_linux.core.watchdog import Watchdog


# ------------------------------------------------------------------ compat
def test_optional_import_handles_missing_and_broken() -> None:
    compat.reset_cache()
    assert compat.optional_import("modulo_que_nao_existe_xyz") is None
    assert "ModuleNotFoundError" in (compat.import_failure("modulo_que_nao_existe_xyz") or "")
    assert compat.optional_import("json") is not None
    compat.inject_module("json", None)
    assert compat.optional_import("json") is None
    compat.reset_cache()


# ------------------------------------------------------------------ loop
def test_run_falls_back_to_asyncio_and_returns_value() -> None:
    async def main(shutdown: loop.ShutdownSignal) -> int:
        info = loop.current_loop_info()
        assert info is not None
        return 42 if info.kind in ("glib", "asyncio") else 0

    assert loop.run(main) == 42


def test_run_without_glib() -> None:
    async def main(shutdown: loop.ShutdownSignal) -> str:
        info = loop.current_loop_info()
        assert info is not None and info.kind == "asyncio"
        return "ok"

    assert loop.run(main, prefer_glib=False) == "ok"


def test_sigterm_triggers_shutdown() -> None:
    async def main(shutdown: loop.ShutdownSignal) -> int | None:
        asyncio.get_running_loop().call_later(0.05, os.kill, os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(shutdown.event.wait(), 2)
        return shutdown.received

    assert loop.run(main, prefer_glib=False) == signal.SIGTERM


# ------------------------------------------------------------------ watchdog
async def test_watchdog_detects_freeze_and_recovery() -> None:
    frozen = threading.Event()
    thread_names: list[str] = []
    recovered: list[bool] = []
    wd = Watchdog(freeze_timeout=0.15, heartbeat_interval=0.02, check_interval=0.02)

    def on_freeze() -> None:
        thread_names.append(threading.current_thread().name)
        frozen.set()

    wd.add_freeze_hook(on_freeze)
    wd.add_recover_hook(lambda: recovered.append(True))
    wd.start()
    await asyncio.sleep(0.05)
    time.sleep(0.4)  # noqa: ASYNC251 - trava o loop de propósito
    assert frozen.is_set()
    assert thread_names == ["nvda-watchdog"]
    await asyncio.sleep(0.1)
    assert recovered == [True]
    assert not wd.is_frozen
    await wd.stop()


async def test_watchdog_hook_errors_do_not_kill_thread() -> None:
    calls: list[int] = []
    wd = Watchdog(freeze_timeout=0.1, heartbeat_interval=0.02, check_interval=0.02)

    def boom() -> None:
        raise RuntimeError("x")

    wd.add_freeze_hook(boom)
    wd.add_freeze_hook(lambda: calls.append(1))
    wd.start()
    await asyncio.sleep(0.03)
    time.sleep(0.3)  # noqa: ASYNC251 - trava o loop de propósito
    await asyncio.sleep(0.05)
    assert calls == [1]
    await wd.stop()


# ------------------------------------------------------------------ log
def test_setup_logging_writes_file_and_ring(tmp_path: Path) -> None:
    log_file = tmp_path / "nvda.log"
    log_file.write_text("anterior", encoding="utf-8")
    setup_logging(logging.DEBUG, log_file, to_stderr=False)
    get_logger("teste").log(IO, "falando algo")
    assert (tmp_path / "nvda-old.log").read_text(encoding="utf-8") == "anterior"
    ring = ring_buffer()
    assert ring is not None and any("falando algo" in line for line in ring.lines())
    assert "falando algo" in log_file.read_text(encoding="utf-8")
    setup_logging(logging.WARNING, tmp_path / "outro.log", to_stderr=False)


# ------------------------------------------------------------------ permissões
def test_permission_checks_report() -> None:
    checks = permissions.run_checks({"XDG_SESSION_TYPE": "wayland"})
    names = {c.name for c in checks}
    assert {"/dev/input", "/dev/uinput", "Speech Dispatcher", "python: evdev"} <= names
    report = permissions.format_report(checks)
    assert "Diagnóstico do nvda-linux" in report


def test_a11y_env_check() -> None:
    ok = permissions.check_a11y_env(
        {"GTK_MODULES": "gail:atk-bridge", "QT_ACCESSIBILITY": "1", "ACCESSIBILITY_ENABLED": "1"}
    )
    assert ok.status is permissions.Status.OK
    missing = permissions.check_a11y_env({})
    assert missing.status is permissions.Status.WARN and "QT_ACCESSIBILITY" in missing.detail


def test_input_check_without_devices(tmp_path: Path) -> None:
    check = permissions.check_input_devices(str(tmp_path / "event*"))
    assert check.status is permissions.Status.FAIL


# ------------------------------------------------------------------ instância
def test_instance_lock(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    with InstanceLock(path):
        with pytest.raises(AlreadyRunning) as info:
            InstanceLock(path).acquire()
        assert info.value.pid == str(os.getpid())
    with InstanceLock(path):
        pass


# ------------------------------------------------------------------ __main__
def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        entry.main(["--version"])
    assert info.value.code == 0
    assert "nvda-linux" in capsys.readouterr().out


def test_main_check_permissions(capsys: pytest.CaptureFixture[str]) -> None:
    code = entry.main(["--check-permissions"])
    assert code in (0, 1)
    assert "Diagnóstico" in capsys.readouterr().out


def test_parser_layout() -> None:
    args = entry.build_parser().parse_args(["--layout", "laptop", "--debug"])
    assert args.layout == "laptop" and args.debug
    with pytest.raises(SystemExit):
        entry.build_parser().parse_args(["--layout", "outro"])


def test_glib_path_uses_policy_get_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Com um gi.events falso, o loop vem de policy.get_event_loop() (contexto padrão)."""
    import types

    created: list[asyncio.AbstractEventLoop] = []

    class FakePolicy(asyncio.DefaultEventLoopPolicy):
        def get_event_loop(self) -> asyncio.AbstractEventLoop:
            created.append(asyncio.new_event_loop())
            return created[-1]

    fake_events = types.SimpleNamespace(GLibEventLoopPolicy=FakePolicy)
    compat.inject_module("gi.events", fake_events)
    previous = asyncio.get_event_loop_policy()
    try:

        async def main(shutdown: loop.ShutdownSignal) -> str:
            info = loop.current_loop_info()
            assert info is not None and info.kind == "glib"
            asyncio.get_running_loop().create_task(asyncio.sleep(10))  # pendente: cancelada
            return "glib"

        assert loop.run(main) == "glib"
        assert len(created) == 1 and created[0].is_closed()
    finally:
        asyncio.set_event_loop_policy(previous)
        compat.reset_cache()
