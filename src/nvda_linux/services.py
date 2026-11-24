"""Registro de serviços compartilhado. SOMENTE LEITURA para as duas equipes.

A PLATAFORMA registra speech, tones, braille, config e dispatcher no start.
A SEMÂNTICA registra script_chain e focus.
Cada lado só chama ``get_*`` do que o outro registrou.
"""

from __future__ import annotations

from typing import cast

from nvda_linux.contracts import (
    AppControl,
    BrailleOutput,
    ConfigStore,
    FocusTracker,
    GestureDispatcher,
    ScriptChainSource,
    SpeechOutput,
    ToneOutput,
)

_registry: dict[str, object] = {}


class ServiceMissing(RuntimeError):
    """Serviço pedido antes de ser registrado."""


def register(name: str, impl: object) -> None:
    _registry[name] = impl


def _get(name: str) -> object:
    try:
        return _registry[name]
    except KeyError as exc:
        raise ServiceMissing(name) from exc


def clear() -> None:
    """Usado só em testes."""
    _registry.clear()


def speech() -> SpeechOutput:
    return cast(SpeechOutput, _get("speech"))


def tones() -> ToneOutput:
    return cast(ToneOutput, _get("tones"))


def braille() -> BrailleOutput:
    return cast(BrailleOutput, _get("braille"))


def config() -> ConfigStore:
    return cast(ConfigStore, _get("config"))


def dispatcher() -> GestureDispatcher:
    return cast(GestureDispatcher, _get("dispatcher"))


def app() -> AppControl:
    """Registrado pela PLATAFORMA (core/app.py). [P4/S3]"""
    return cast(AppControl, _get("app"))


def script_chain() -> ScriptChainSource:
    return cast(ScriptChainSource, _get("script_chain"))


def focus() -> FocusTracker:
    return cast(FocusTracker, _get("focus"))


# Ganchos de ciclo de vida da SEMÂNTICA, chamados pela PLATAFORMA em core/app.py.
# A SEMÂNTICA expõe em nvda_linux/scripts/bootstrap.py:
#     async def start() -> None   # conecta AT-SPI2, registra script_chain e focus
#     async def stop() -> None
SEMANTICS_BOOTSTRAP_MODULE = "nvda_linux.scripts.bootstrap"
