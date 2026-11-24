"""Trava de instância única.

Duas instâncias com grab no teclado brigariam pelas teclas (e o autostart
pode coexistir com a unidade systemd). A trava usa ``flock`` num arquivo em
``$XDG_RUNTIME_DIR`` e é liberada pelo kernel se o processo morrer.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
from types import TracebackType
from typing import Self


def lock_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/nvda-linux-{os.getuid()}"
    return Path(runtime) / "nvda-linux.lock"


class AlreadyRunning(RuntimeError):
    """Outra instância já segura a trava."""

    def __init__(self, pid: str) -> None:
        super().__init__(f"nvda-linux já está em execução (pid {pid or '?'})")
        self.pid = pid


class InstanceLock:
    """``with InstanceLock(): ...`` — levanta :class:`AlreadyRunning` se ocupada."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or lock_path()
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pid = os.pread(fd, 32, 0).decode(errors="replace").strip()
            os.close(fd)
            raise AlreadyRunning(pid) from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
