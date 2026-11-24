# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Gancho de "texto falado", consumido pelo Visualizador de Fala.

Toda fala da SEMÂNTICA passa por :func:`nvda_linux.scripts.ui.speak`, que
chama :func:`notify`. Para incluir também a fala da PLATAFORMA (mensagens do
despachante, eco de teclado), :func:`attach_platform_listener` usa o
``add_listener`` opcional do ``SpeechOutput`` dela; enquanto ele estiver
ligado, a SEMÂNTICA para de notificar por conta própria (sem duplicar
linhas). Ver ``docs/requests/semantics.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from nvda_linux import services
from nvda_linux.contracts import SpeechCommand, SpeechPriority

log = logging.getLogger(__name__)

SpeechHook = Callable[[Sequence[str | SpeechCommand], SpeechPriority], None]

_hooks: list[SpeechHook] = []
_platform_notifies = False
_platform_cancel: Callable[[], object] | None = None


def register(hook: SpeechHook) -> None:
    """Registra um ouvinte de fala (idempotente)."""
    if hook not in _hooks:
        _hooks.append(hook)


def unregister(hook: SpeechHook) -> None:
    if hook in _hooks:
        _hooks.remove(hook)


def set_platform_notifies(enabled: bool) -> None:
    """A PLATAFORMA declara que chama :func:`notify` para toda fala."""
    global _platform_notifies
    _platform_notifies = enabled


def platform_notifies() -> bool:
    return _platform_notifies


def notify(
    sequence: Sequence[str | SpeechCommand],
    priority: SpeechPriority = SpeechPriority.NORMAL,
) -> None:
    """Entrega a sequência aos ouvintes; erros de ouvintes nunca propagam."""
    for hook in _hooks:
        try:
            hook(sequence, priority)
        except Exception:
            log.exception("Gancho de fala falhou")


def attach_platform_listener() -> bool:
    """Assina ``services.speech().add_listener`` (se existir). ``True`` se ligado."""
    global _platform_cancel
    if _platform_cancel is not None:
        return True
    try:
        add_listener = getattr(services.speech(), "add_listener", None)
    except Exception:  # noqa: BLE001
        return False
    if not callable(add_listener):
        return False

    def on_text(text: str) -> None:
        notify([text], SpeechPriority.NORMAL)

    try:
        cancel = add_listener(on_text)
    except Exception:
        log.exception("add_listener da fala falhou")
        return False
    _platform_cancel = cancel if callable(cancel) else (lambda: None)
    set_platform_notifies(True)
    return True


def detach_platform_listener() -> None:
    global _platform_cancel
    if _platform_cancel is None:
        return
    try:
        _platform_cancel()
    except Exception:
        log.exception("Cancelar o ouvinte de fala falhou")
    _platform_cancel = None
    set_platform_notifies(False)


def text_of(sequence: Sequence[str | SpeechCommand]) -> str:
    """Só o texto da sequência, unido por espaços."""
    return "  ".join(s for s in sequence if isinstance(s, str) and s.strip())


def clear() -> None:
    """Remove todos os ouvintes (testes)."""
    global _platform_notifies, _platform_cancel
    _hooks.clear()
    _platform_notifies = False
    _platform_cancel = None
