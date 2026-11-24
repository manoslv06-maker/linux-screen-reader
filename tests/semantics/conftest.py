"""Fixtures da SEMÂNTICA: serviços falsos registrados e estado global limpo."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from nvda_linux import services
from nvda_linux.addons import compat
from nvda_linux.contracts import KeyboardLayout
from nvda_linux.gui import _gtk
from nvda_linux.NVDAObjects import _atspi
from nvda_linux.NVDAObjects import base as nvda_base
from nvda_linux.NVDAObjects.behaviors import EditableText
from nvda_linux.scripts import runtime as runtime_module
from nvda_linux.scripts import sayAll, speechHooks
from nvda_linux.scripts.runtime import Runtime
from tests.semantics.fakes import (
    FakeBraille,
    FakeConfig,
    FakeDispatcher,
    FakeSpeech,
    FakeTones,
)


@dataclass
class Platform:
    speech: FakeSpeech
    tones: FakeTones
    braille: FakeBraille
    config: FakeConfig
    dispatcher: FakeDispatcher


@pytest.fixture(autouse=True)
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[Platform]:
    """Registra fakes da PLATAFORMA e zera o estado global entre testes."""
    # A árvore falsa só entende SimpleMatchRule: mesmo com PyGObject instalado,
    # os testes não podem montar MatchRule/StateSet do AT-SPI2 real.
    monkeypatch.setattr(_atspi, "Atspi", None)
    # Idem para o GTK: com GTK 4 e um display (ex.: WSLg) os testes abririam
    # janelas de verdade em vez de cair no aviso falado.
    monkeypatch.setattr(_gtk, "Gtk", None)
    sayAll.stop()
    services.clear()
    runtime_module.set_current(None)
    nvda_base.clear_registry()
    speechHooks.clear()
    old_ttl = nvda_base.LinuxNVDAObject.cache_ttl
    old_timeout = EditableText.caret_timeout
    # TTL longo: os testes provam que a invalidação por evento funciona.
    nvda_base.LinuxNVDAObject.cache_ttl = 60.0
    EditableText.caret_timeout = 0.01
    fakes = Platform(FakeSpeech(), FakeTones(), FakeBraille(), FakeConfig(),
                     FakeDispatcher(KeyboardLayout.DESKTOP))
    services.register("speech", fakes.speech)
    services.register("tones", fakes.tones)
    services.register("braille", fakes.braille)
    services.register("config", fakes.config)
    services.register("dispatcher", fakes.dispatcher)
    yield fakes
    compat.uninstall()
    for name in [n for n in sys.modules if n == "nvdaAddons" or n.startswith("nvdaAddons.")]:
        del sys.modules[name]
    nvda_base.LinuxNVDAObject.cache_ttl = old_ttl
    EditableText.caret_timeout = old_timeout
    runtime_module.set_current(None)
    nvda_base.clear_registry()
    speechHooks.clear()
    sayAll.stop()
    services.clear()


@pytest.fixture
def rt() -> Runtime:
    """Runtime completo sem AT-SPI2 real (eventos são injetados à mão)."""
    return runtime_module.create(atspi_connected=False)
