"""Fixtures da PLATAFORMA: registro de serviços limpo e configuração isolada."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from nvda_linux import services
from nvda_linux.core.config import TomlConfigStore


@pytest.fixture(autouse=True)
def clean_services() -> Iterator[None]:
    services.clear()
    yield
    services.clear()


@pytest.fixture(autouse=True)
def isolated_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nada de testes escrevendo em ~/.config, ~/.local/state ou no runtime real."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()


@pytest.fixture
def config(tmp_path: Path) -> TomlConfigStore:
    return TomlConfigStore(tmp_path / "cfg")
