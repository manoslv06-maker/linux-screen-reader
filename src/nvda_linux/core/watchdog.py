"""Watchdog do núcleo (equivalente ao ``watchdog`` do NVDA).

Uma tarefa no loop marca um "batimento" periódico. Um thread separado
verifica se o batimento está atrasado. Se o loop ficar travado por mais de
``freeze_timeout`` segundos:

1. registra no log a pilha do thread principal (para depuração);
2. chama os ganchos ``on_freeze`` *no thread do watchdog*. O uso principal
   é soltar o grab exclusivo do teclado (evdev), para que o usuário nunca
   fique sem teclado porque o leitor travou. Esses ganchos precisam ser
   seguros para chamar de outro thread.

Quando o loop volta a responder, os ganchos ``on_recover`` rodam no loop.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import traceback
from collections.abc import Callable

from nvda_linux.core.log import get_logger

log = get_logger(__name__)

FreezeHook = Callable[[], None]


class Watchdog:
    """Detecta travamentos do loop asyncio e executa ganchos de segurança."""

    def __init__(
        self,
        freeze_timeout: float = 5.0,
        heartbeat_interval: float = 0.25,
        check_interval: float = 0.5,
    ) -> None:
        self.freeze_timeout = freeze_timeout
        self.heartbeat_interval = heartbeat_interval
        self.check_interval = check_interval
        self._last_beat = time.monotonic()
        self._frozen = False
        self._freeze_hooks: list[FreezeHook] = []
        self._recover_hooks: list[FreezeHook] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._main_thread_id = threading.main_thread().ident
        self._loop_thread_id: int | None = None
        self.freeze_count = 0

    def add_freeze_hook(self, hook: FreezeHook) -> None:
        """Gancho chamado no thread do watchdog quando o loop trava."""
        self._freeze_hooks.append(hook)

    def add_recover_hook(self, hook: FreezeHook) -> None:
        """Gancho chamado no loop quando ele volta a responder."""
        self._recover_hooks.append(hook)

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def start(self) -> None:
        """Inicia o batimento (no loop atual) e o thread de verificação."""
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._last_beat = time.monotonic()
        self._stop.clear()
        self._task = self._loop.create_task(self._heartbeat(), name="watchdog-heartbeat")
        self._thread = threading.Thread(target=self._watch, name="nvda-watchdog", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        """Para o batimento e o thread."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    async def _heartbeat(self) -> None:
        while True:
            self._last_beat = time.monotonic()
            if self._frozen:
                self._frozen = False
                log.warning("Núcleo voltou a responder")
                for hook in list(self._recover_hooks):
                    try:
                        hook()
                    except Exception:
                        log.exception("Gancho de recuperação do watchdog falhou")
            await asyncio.sleep(self.heartbeat_interval)

    def _watch(self) -> None:
        while not self._stop.wait(self.check_interval):
            lag = time.monotonic() - self._last_beat
            if lag > self.freeze_timeout and not self._frozen:
                self._frozen = True
                self.freeze_count += 1
                self._on_freeze(lag)

    def _on_freeze(self, lag: float) -> None:
        thread_id = self._loop_thread_id or self._main_thread_id
        frame = sys._current_frames().get(thread_id) if thread_id is not None else None
        stack = "".join(traceback.format_stack(frame)) if frame is not None else "(sem pilha)"
        log.error("Núcleo travado há %.1f s. Pilha do loop:\n%s", lag, stack)
        for hook in list(self._freeze_hooks):
            try:
                hook()
            except Exception:
                log.exception("Gancho de travamento do watchdog falhou")
