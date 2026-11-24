"""Importação protegida de dependências opcionais do sistema.

Várias bibliotecas usadas pela PLATAFORMA vêm dos pacotes da distribuição
(``python3-speechd``, ``python3-brlapi``, ``python3-louis``, PyGObject) ou
dependem de bibliotecas nativas (PortAudio para ``sounddevice``). Em máquinas
sem elas, o leitor precisa continuar funcionando com um substituto. Este
módulo centraliza o ``try/except`` e devolve ``None`` quando a importação
falha por qualquer motivo (``ImportError``, ``OSError`` de biblioteca nativa
ausente, ou o erro de importação circular do ``gi`` quebrado).
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

log = logging.getLogger(__name__)

_cache: dict[str, Any] = {}
_failures: dict[str, str] = {}


def optional_import(name: str) -> Any | None:
    """Importa ``name`` ou devolve ``None`` se não for possível.

    O resultado (inclusive a falha) fica em cache, de modo que o custo e o
    aviso no log acontecem uma única vez por processo.
    """
    if name in _cache:
        return _cache[name]
    if name in _failures:
        return None
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # qualquer falha vira "ausente"  # noqa: BLE001
        _failures[name] = f"{type(exc).__name__}: {exc}"
        log.debug("Dependência opcional %s indisponível: %s", name, _failures[name])
        return None
    _cache[name] = module
    return module


def import_failure(name: str) -> str | None:
    """Motivo da falha da última tentativa de importar ``name`` (ou None)."""
    return _failures.get(name)


def reset_cache() -> None:
    """Esquece importações anteriores. Usado só em testes."""
    _cache.clear()
    _failures.clear()


def inject_module(name: str, module: Any | None) -> None:
    """Força o resultado de :func:`optional_import` (testes e fakes)."""
    _failures.pop(name, None)
    if module is None:
        _cache.pop(name, None)
        _failures[name] = "injetado como ausente"
    else:
        _cache[name] = module
