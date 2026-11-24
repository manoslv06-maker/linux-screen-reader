"""Registro de eventos (equivalente ao ``logHandler`` do NVDA).

- Arquivo em ``$XDG_STATE_HOME/nvda-linux/nvda.log`` (padrão
  ``~/.local/state/nvda-linux/nvda.log``), com o anterior preservado como
  ``nvda-old.log``, igual ao ``nvda.log``/``nvda-old.log`` do NVDA.
- Nível ``IO`` (12), como no NVDA, para registrar o que é falado e as teclas.
- Um buffer circular em memória, para o visualizador de log da GUI.
"""

from __future__ import annotations

import collections
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Final

IO: Final = 12
DEBUGWARNING: Final = 15
logging.addLevelName(IO, "IO")
logging.addLevelName(DEBUGWARNING, "DEBUGWARNING")

ROOT_LOGGER_NAME: Final = "nvda_linux"
_FORMAT: Final = "%(levelname)s - %(name)s (%(asctime)s.%(msecs)03d) - %(threadName)s:\n%(message)s"
_DATEFMT: Final = "%H:%M:%S"


def state_dir() -> Path:
    """Diretório de estado do usuário (XDG_STATE_HOME)."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "nvda-linux"


class RingBufferHandler(logging.Handler):
    """Guarda as últimas ``capacity`` linhas formatadas em memória."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._lines: collections.deque[str] = collections.deque(maxlen=capacity)
        self._lock_rb = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
        except Exception:  # noqa: BLE001
            self.handleError(record)
            return
        with self._lock_rb:
            self._lines.append(text)

    def lines(self) -> list[str]:
        """Cópia das linhas guardadas, da mais antiga para a mais nova."""
        with self._lock_rb:
            return list(self._lines)


_ring: RingBufferHandler | None = None


def ring_buffer() -> RingBufferHandler | None:
    """Buffer em memória instalado por :func:`setup_logging`, se houver."""
    return _ring


def _rotate(path: Path) -> None:
    if path.exists():
        old = path.with_name("nvda-old.log")
        try:
            path.replace(old)
        except OSError:
            pass


def setup_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
    *,
    to_stderr: bool = True,
) -> logging.Logger:
    """Configura o logger raiz do projeto e devolve-o.

    Pode ser chamado mais de uma vez (os handlers anteriores são trocados).
    Falhas ao abrir o arquivo de log não são fatais: o leitor de tela não
    pode deixar de falar porque o disco está cheio.
    """
    global _ring
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(_FORMAT, _DATEFMT)

    if log_file is None:
        log_file = state_dir() / "nvda.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _rotate(log_file)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        print(f"nvda-linux: não foi possível abrir o log {log_file}: {exc}", file=sys.stderr)

    if to_stderr:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        stream.setLevel(max(level, logging.INFO) if level > logging.DEBUG else level)
        root.addHandler(stream)

    _ring = RingBufferHandler()
    _ring.setFormatter(formatter)
    root.addHandler(_ring)
    root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    """Logger filho de ``nvda_linux`` (aceita ``__name__`` dos módulos)."""
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
