from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from nvda_linux.contracts import ConfigStore
from nvda_linux.core.config import DEFAULTS, TomlConfigStore, config_dir, dumps_toml


def test_implements_contract(config: TomlConfigStore) -> None:
    assert isinstance(config, ConfigStore)


def test_defaults_and_fallback(config: TomlConfigStore) -> None:
    assert config.get("speech.rate") == 50
    assert config.get("keyboard.keyboardLayout") == "desktop"
    assert config.get("browseMode.autoFocusMode") is True
    assert config.get("braille.messageTimeout") == 4
    assert config.get("nao.existe", "x") == "x"
    assert config.get("speech.rate.sub", 7) == 7


def test_table_get_returns_merged_copy(config: TomlConfigStore) -> None:
    config.set("speech.rate", 70)
    speech = config.get("speech")
    assert speech["rate"] == 70 and speech["pitch"] == 50
    speech["rate"] = 1  # cópia: não altera a configuração
    assert config.get("speech.rate") == 70


def test_set_save_reload(tmp_path: Path) -> None:
    store = TomlConfigStore(tmp_path)
    store.set("speech.rate", 80)
    store.set("keyboard.useCapsLockAsNVDAModifierKey", True)
    store.set("addons.meuPlugin.opcao", 'valor com "aspas"\n')
    store.save()
    data = tomllib.loads((tmp_path / "nvda.toml").read_text(encoding="utf-8"))
    assert data["speech"]["rate"] == 80
    again = TomlConfigStore(tmp_path)
    assert again.get("speech.rate") == 80
    assert again.get("keyboard.useCapsLockAsNVDAModifierKey") is True
    assert again.get("addons.meuPlugin.opcao") == 'valor com "aspas"\n'


def test_type_validation(config: TomlConfigStore) -> None:
    with pytest.raises(TypeError):
        config.set("speech.rate", "rápido")
    with pytest.raises(TypeError):
        config.set("browseMode.autoFocusMode", 1)
    config.set("speech.rate", 10)  # int ok


def test_invalid_file_values_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "nvda.toml").write_text('[speech]\nrate = "x"\npitch = 60\n', encoding="utf-8")
    store = TomlConfigStore(tmp_path)
    assert store.get("speech.rate") == 50
    assert store.get("speech.pitch") == 60


def test_corrupt_file_uses_defaults(tmp_path: Path) -> None:
    (tmp_path / "nvda.toml").write_text("isto não é [toml", encoding="utf-8")
    store = TomlConfigStore(tmp_path)
    assert store.get("speech.rate") == 50


def test_profiles(tmp_path: Path) -> None:
    store = TomlConfigStore(tmp_path)
    store.set("speech.rate", 40)
    store.activate_profile("firefox")
    assert store.active_profile == "firefox"
    assert store.get("speech.rate") == 40  # herda da base
    store.set("speech.rate", 90)  # grava no perfil
    assert store.get("speech.rate") == 90
    store.save()
    store.activate_profile(None)
    assert store.get("speech.rate") == 40
    assert (tmp_path / "profiles" / "firefox.toml").exists()
    assert store.list_profiles() == ["firefox"]
    store.activate_profile("firefox")
    assert store.get("speech.rate") == 90


def test_subscribe_and_profile_change_notifies(config: TomlConfigStore) -> None:
    seen: list[tuple[str, Any]] = []
    unsubscribe = config.subscribe("speech", lambda k, v: seen.append((k, v)))
    config.set("speech.rate", 60)
    config.set("keyboard.speakTypedWords", True)  # fora do prefixo
    assert seen == [("speech.rate", 60)]
    config.activate_profile("p")
    config.set("speech.pitch", 70)
    seen.clear()
    config.activate_profile(None)
    assert ("speech.pitch", 50) in seen
    unsubscribe()
    config.set("speech.rate", 1)
    assert ("speech.rate", 1) not in seen


def test_set_same_value_is_noop(config: TomlConfigStore) -> None:
    seen: list[str] = []
    config.subscribe("", lambda k, v: seen.append(k))
    config.set("speech.rate", 50)
    assert seen == []


def test_dumps_toml_roundtrip() -> None:
    data: dict[str, Any] = {
        "a": 1,
        "b": {"c": [1, 2, 3], "d": {"e": True, "f": 1.5}, "g": "x\ty"},
        "chave com espaço": "ok",
        "vazio": {},
    }
    assert tomllib.loads(dumps_toml(data)) == data
    assert tomllib.loads(dumps_toml(DEFAULTS)) == DEFAULTS


def test_config_dir_uses_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_dir() == tmp_path / "nvda-linux"
