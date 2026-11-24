"""Loop principal: asyncio rodando sobre o GLib MainLoop.

O AT-SPI2 (``gi.repository.Atspi``) e o GTK 4 entregam eventos pelo
``GLib.MainContext`` padrão. Desde o PyGObject 3.50 existe
``gi.events.GLibEventLoopPolicy``, um loop asyncio cujo motor é o próprio
GLib: corrotinas, ``add_reader`` (evdev, BrlAPI), subprocessos e sinais do
GLib passam a conviver no mesmo thread, sem ``gbulb`` (arquivado).

Se o ``gi`` não puder ser importado (ou for antigo), caímos para o loop
asyncio padrão: tudo que é da PLATAFORMA continua funcionando, só os eventos
GLib/AT-SPI2 ficam sem motor.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import warnings
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from nvda_linux.core.compat import import_failure, optional_import
from nvda_linux.core.log import get_logger

log = get_logger(__name__)

T = TypeVar("T")
LoopKind = Literal["glib", "asyncio"]


@dataclass(frozen=True, slots=True)
class LoopInfo:
    """Qual implementação de loop está em uso e por quê."""

    kind: LoopKind
    reason: str


def _glib_policy() -> tuple[Any | None, str]:
    events = optional_import("gi.events")
    if events is None:
        return None, f"gi.events indisponível ({import_failure('gi.events') or 'não importável'})"
    policy_cls = getattr(events, "GLibEventLoopPolicy", None)
    if policy_cls is None:
        return None, "PyGObject < 3.50 (sem GLibEventLoopPolicy)"
    try:
        return policy_cls(), "GLibEventLoopPolicy do PyGObject"
    except Exception as exc:  # noqa: BLE001
        return None, f"GLibEventLoopPolicy falhou: {exc}"


def make_loop_factory(
    prefer_glib: bool = True,
) -> tuple[Callable[[], asyncio.AbstractEventLoop], LoopInfo]:
    """Devolve uma fábrica de loops e a descrição do tipo escolhido.

    No caso GLib a fábrica é ``policy.get_event_loop()``: o loop do
    ``GLib.MainContext`` padrão, que é onde o AT-SPI2 e o GTK entregam
    eventos. (``new_event_loop()``/``asyncio.run()`` não servem: a
    documentação do PyGObject os declara incompatíveis.)
    """
    if prefer_glib:
        policy, reason = _glib_policy()
        if policy is not None:
            # A política precisa estar instalada para que get_event_loop() e
            # bibliotecas que chamam asyncio.get_event_loop_policy() vejam o GLib.
            setter = getattr(asyncio, "set_event_loop_policy", None)
            if setter is not None:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    setter(policy)
            factory: Callable[[], asyncio.AbstractEventLoop] = policy.get_event_loop
            return factory, LoopInfo("glib", reason)
        log.info("Usando asyncio puro: %s", reason)
        return asyncio.new_event_loop, LoopInfo("asyncio", reason)
    return asyncio.new_event_loop, LoopInfo("asyncio", "GLib desativado por opção")


def _run_on_loop(loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, T]) -> T:
    """``run_until_complete`` com limpeza (tarefas, geradores assíncronos)."""
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            with contextlib.suppress(Exception):
                loop.close()


class ShutdownSignal:
    """Evento de desligamento ligado a SIGINT/SIGTERM (e SIGHUP)."""

    SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.received: int | None = None
        self._installed: list[int] = []
        self._previous: dict[int, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        """Instala os handlers no loop (ou via ``signal.signal`` como reserva)."""
        self._loop = loop
        for sig in self.SIGNALS:
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
                self._installed.append(sig)
            except (NotImplementedError, RuntimeError, ValueError):
                try:
                    self._previous[sig] = signal.signal(sig, self._on_signal_threadsafe)
                except (ValueError, OSError):  # fora do thread principal
                    log.debug("Não foi possível instalar handler para %s", sig)

    def _on_signal(self, sig: int) -> None:
        if self.received is None:
            log.info("Sinal %s recebido; encerrando", signal.Signals(sig).name)
        self.received = sig
        self.event.set()

    def _on_signal_threadsafe(self, sig: int, _frame: object) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._on_signal, sig)

    def uninstall(self) -> None:
        if self._loop is not None:
            for sig in self._installed:
                with contextlib.suppress(Exception):
                    self._loop.remove_signal_handler(sig)
        for sig, previous in self._previous.items():
            with contextlib.suppress(Exception):
                signal.signal(sig, previous)
        self._installed.clear()
        self._previous.clear()


_current_info: LoopInfo | None = None


def current_loop_info() -> LoopInfo | None:
    """Informação do loop criado por :func:`run` (None se não estiver rodando)."""
    return _current_info


def run(
    main: Callable[[ShutdownSignal], Coroutine[Any, Any, T]],
    *,
    prefer_glib: bool = True,
    debug: bool = False,
) -> T:
    """Roda ``main(shutdown)`` até terminar, sobre o loop GLib quando possível.

    ``main`` recebe o :class:`ShutdownSignal` e deve retornar quando
    ``shutdown.event`` for disparado. Os handlers de sinal são removidos e as
    tarefas pendentes canceladas ao final.
    """
    global _current_info
    factory, info = make_loop_factory(prefer_glib)
    _current_info = info
    log.debug("Loop principal: %s (%s)", info.kind, info.reason)
    shutdown = ShutdownSignal()

    async def wrapper() -> T:
        shutdown.install(asyncio.get_running_loop())
        try:
            return await main(shutdown)
        finally:
            shutdown.uninstall()

    try:
        if info.kind == "glib":
            glib_loop = factory()
            glib_loop.set_debug(debug)
            return _run_on_loop(glib_loop, wrapper())
        with asyncio.Runner(loop_factory=factory, debug=debug) as runner:
            return runner.run(wrapper())
    finally:
        _current_info = None
