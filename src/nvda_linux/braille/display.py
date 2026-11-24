"""Linhas braille: BRLTTY via BrlAPI, e a implementação nula.

O BRLTTY já conversa com praticamente todas as linhas braille (USB,
Bluetooth, serial). O leitor se conecta como cliente BrlAPI, entra no modo
"tty" do terminal gráfico atual e recebe os comandos das teclas da linha
(rolagem, roteamento...). O fd da conexão entra no loop com ``add_reader``.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nvda_linux.core.compat import optional_import
from nvda_linux.core.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DisplayKey:
    """Tecla da linha já traduzida: nome no estilo do driver brltty do NVDA."""

    name: str  # "routing", "fwinlt", "fwinrt", "lnup", "lndn"...
    argument: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


KeyCallback = Callable[[DisplayKey], None]


class BrailleDisplay(abc.ABC):
    """Uma linha braille física (ou nenhuma)."""

    name = "abstract"

    def __init__(self) -> None:
        self.on_key: KeyCallback | None = None

    @property
    @abc.abstractmethod
    def num_cells(self) -> int: ...

    @abc.abstractmethod
    def write_text(self, text: str, cursor: int | None) -> None:
        """Texto já cortado para a janela; o BRLTTY aplica a tabela de texto."""

    @abc.abstractmethod
    def write_dots(self, cells: bytes) -> None:
        """Células já em pontos (bit 0 = ponto 1 ... bit 7 = ponto 8)."""

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None


class NullDisplay(BrailleDisplay):
    """Sem linha braille: guarda o último conteúdo (útil em testes)."""

    name = "none"

    def __init__(self, cells: int = 0) -> None:
        super().__init__()
        self._cells = cells
        self.last_text: str | None = None
        self.last_cursor: int | None = None
        self.last_dots: bytes | None = None

    @property
    def num_cells(self) -> int:
        return self._cells

    def write_text(self, text: str, cursor: int | None) -> None:
        self.last_text, self.last_cursor, self.last_dots = text, cursor, None

    def write_dots(self, cells: bytes) -> None:
        self.last_dots, self.last_text = cells, None


def _command_names(brlapi: Any) -> dict[int, str]:
    names: dict[int, str] = {}
    for attr in dir(brlapi):
        if attr.startswith("KEY_CMD_") and attr not in ("KEY_CMD_BLK_MASK", "KEY_CMD_ARG_MASK"):
            value = getattr(brlapi, attr)
            if isinstance(value, int):
                names.setdefault(value, attr[len("KEY_CMD_") :].lower())
    if hasattr(brlapi, "KEY_CMD_ROUTE"):
        names[brlapi.KEY_CMD_ROUTE] = "routing"
    return names


class BrlapiDisplay(BrailleDisplay):
    """Cliente BrlAPI (``python3-brlapi``)."""

    name = "brltty"

    def __init__(self, brlapi: Any | None = None) -> None:
        super().__init__()
        self._brlapi = brlapi if brlapi is not None else optional_import("brlapi")
        self._conn: Any = None
        self._cells = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._names: dict[int, str] = {}

    @property
    def num_cells(self) -> int:
        return self._cells

    async def open(self) -> None:
        brlapi = self._brlapi
        if brlapi is None:
            raise OSError("python3-brlapi não instalado")
        try:
            conn = brlapi.Connection()
        except Exception as exc:  # brlapi.ConnectionError etc.
            raise OSError(f"BRLTTY indisponível: {exc}") from exc
        width, height = conn.displaySize
        if width * height <= 0:
            with contextlib.suppress(Exception):
                conn.closeConnection()
            raise OSError("BRLTTY conectado, mas sem linha braille")
        try:
            conn.enterTtyModeWithPath()
        except Exception:  # noqa: BLE001
            vt = int(os.environ.get("XDG_VTNR", "0") or 0)
            try:
                conn.enterTtyMode(vt or None)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.closeConnection()
                raise OSError(f"não foi possível entrar no modo tty do BRLTTY: {exc}") from exc
        with contextlib.suppress(Exception):
            conn.acceptKeys(brlapi.rangeType_all, [0])
        self._conn = conn
        self._cells = int(width * height)
        self._names = _command_names(brlapi)
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(conn.fileDescriptor, self._on_readable)
        log.info("Linha braille: %s com %d células", getattr(conn, "driverName", "?"), self._cells)

    def _on_readable(self) -> None:
        conn = self._conn
        if conn is None:
            return
        while True:
            try:
                code = conn.readKey(False)
            except Exception as exc:  # noqa: BLE001
                log.warning("BrlAPI perdeu a conexão: %s", exc)
                self._drop()
                return
            if code is None:
                return
            self._dispatch(code)

    def _dispatch(self, code: int) -> None:
        brlapi = self._brlapi
        try:
            info = dict(self._conn.expandKeyCode(code))
        except Exception:  # noqa: BLE001
            return
        if info.get("type") != getattr(brlapi, "KEY_TYPE_CMD", info.get("type")):
            return
        command = int(info.get("command", 0))
        name = self._names.get(command, f"cmd{command}")
        key = DisplayKey(name, int(info.get("argument", 0)), info)
        if self.on_key is not None:
            try:
                self.on_key(key)
            except Exception:
                log.exception("Tratamento de tecla braille falhou")

    def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None and self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(conn.fileDescriptor)
        self._cells = 0

    def write_text(self, text: str, cursor: int | None) -> None:
        if self._conn is None:
            return
        off = getattr(self._brlapi, "CURSOR_OFF", 0)
        try:
            # BrlAPI conta o cursor a partir de 1; 0 = sem cursor.
            self._conn.writeText(text, off if cursor is None else cursor + 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao escrever na linha braille: %s", exc)

    def write_dots(self, cells: bytes) -> None:
        if self._conn is None:
            return
        try:
            self._conn.writeDots(cells)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao escrever pontos na linha braille: %s", exc)

    async def close(self) -> None:
        conn = self._conn
        self._drop()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.leaveTtyMode()
            with contextlib.suppress(Exception):
                conn.closeConnection()
