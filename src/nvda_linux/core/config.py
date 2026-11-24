"""Configuração com perfis (implementa ``contracts.ConfigStore``).

Arquivos (seguindo o XDG):

- ``~/.config/nvda-linux/nvda.toml``: configuração base;
- ``~/.config/nvda-linux/profiles/<nome>.toml``: perfis (só as diferenças).

As chaves usam ponto (``"speech.rate"``) e, sempre que possível, os mesmos
nomes do ``nvda.ini`` do NVDA (``keyboard.useCapsLockAsNVDAModifierKey``,
``speech.capPitchChange`` ...). A leitura procura, em ordem: perfil ativo,
configuração base, valores padrão e, por último, o ``default`` passado.
Como no NVDA, ``set`` grava no perfil ativo quando há um.
"""

from __future__ import annotations

import copy
import math
import os
import re
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from nvda_linux.core.log import get_logger

log = get_logger(__name__)

ConfigListener = Callable[[str, Any], None]

DEFAULTS: Final[dict[str, Any]] = {
    "general": {
        "language": "",  # vazio = idioma do sistema (LANG)
        "logLevel": "info",
        "playStartAndExitSounds": True,
    },
    "speech": {
        "synth": "auto",  # auto | speechd | espeak | piper | silence
        "voice": "",
        "language": "",
        "variant": "",
        "rate": 50,  # 0..100, como no NVDA
        "pitch": 50,
        "volume": 100,
        "inflection": 80,
        "capPitchChange": 30,  # porcentagem
        "sayCapForCapitals": False,
        "beepForCapitals": False,
        "useSpellingFunctionality": True,
        "autoLanguageSwitching": True,
        "speechd": {
            "transport": "auto",  # auto | native | module
            "outputModule": "",
            "priority": "message",
            "autospawn": True,
        },
        "espeak": {"executable": "espeak-ng"},
        "piper": {"executable": "piper", "model": "", "sampleRate": 0},
    },
    "keyboard": {
        "keyboardLayout": "desktop",  # desktop | laptop
        "backend": "auto",  # auto | keyboardMonitor | evdev | none
        "useCapsLockAsNVDAModifierKey": False,
        "useNumpadInsertAsNVDAModifierKey": True,
        "useExtendedInsertAsNVDAModifierKey": True,
        "doubleTapTimeoutMs": 350,
        "repeatTimeoutMs": 500,
        "speakTypedCharacters": True,
        "speakTypedWords": False,
        "speechInterruptForCharacters": True,
        "speechInterruptForEnter": True,
        "xkbLayout": "",  # vazio = detectar
        "xkbVariant": "",
        "gesturesFile": "",  # vazio = ~/.config/nvda-linux/gestures.ini
    },
    "browseMode": {
        "autoFocusMode": True,
        "maxLineLength": 100,
        "linesPerPage": 25,
        "useScreenLayout": True,
        "autoPassThroughOnFocusChange": True,
        "autoPassThroughOnCaretMove": False,
        "passThroughAudioIndication": True,
        "trapNonCommandGestures": True,
        "autoSayAllOnPageLoad": True,
        "autoFocusFocusableElements": False,
    },
    "braille": {
        "display": "auto",  # auto | brltty | none
        "translationTable": "",  # vazio = tabela de texto do BRLTTY
        "messageTimeout": 4,  # segundos (0 = sem mensagens)
        "wordWrap": True,
        "tetherTo": "focus",
    },
    "audio": {
        "beepVolume": 50,  # 0..100
        "outputDevice": "",
    },
}

_BARE_KEY: Final = re.compile(r"^[A-Za-z0-9_-]+$")


def config_dir() -> Path:
    """Diretório de configuração do usuário (``$XDG_CONFIG_HOME/nvda-linux``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "nvda-linux"


# --------------------------------------------------------------------------
# Escrita de TOML (tomllib só lê; evitamos depender de tomli-w)
# --------------------------------------------------------------------------
def _toml_key(key: str) -> str:
    return key if _BARE_KEY.match(key) else _toml_str(key)


def _toml_str(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, Mapping):
        inner = ", ".join(f"{_toml_key(str(k))} = {_toml_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    raise TypeError(f"Tipo não suportado em TOML: {type(value).__name__}")


def dumps_toml(data: Mapping[str, Any]) -> str:
    """Serializa um dicionário aninhado como TOML (tabelas para dicionários)."""
    lines: list[str] = []

    def emit_table(prefix: list[str], table: Mapping[str, Any]) -> None:
        scalars = [(k, v) for k, v in table.items() if not isinstance(v, Mapping)]
        tables = [(k, v) for k, v in table.items() if isinstance(v, Mapping)]
        if prefix and (scalars or not tables):
            if lines:
                lines.append("")
            lines.append("[" + ".".join(_toml_key(p) for p in prefix) + "]")
        for key, value in scalars:
            lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")
        for key, value in tables:
            emit_table([*prefix, str(key)], value)

    emit_table([], data)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Acesso por chave com ponto
# --------------------------------------------------------------------------
_MISSING: Final = object()


def _lookup(tree: Mapping[str, Any], parts: list[str]) -> Any:
    node: Any = tree
    for part in parts:
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _assign(tree: dict[str, Any], parts: list[str], value: Any) -> None:
    node = tree
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in over.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _compatible(default: Any, value: Any) -> bool:
    """Diz se ``value`` tem tipo aceitável para uma chave cujo padrão é ``default``."""
    if default is _MISSING or default is None:
        return True
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, Mapping):
        return isinstance(value, Mapping)
    return isinstance(value, type(default))


def _sanitize(
    tree: Mapping[str, Any], defaults: Mapping[str, Any], path: str = ""
) -> dict[str, Any]:
    """Remove valores com tipo incompatível com o padrão (com aviso no log)."""
    clean: dict[str, Any] = {}
    for key, value in tree.items():
        full = f"{path}{key}"
        default = defaults.get(key, _MISSING) if isinstance(defaults, Mapping) else _MISSING
        if isinstance(value, Mapping):
            sub_defaults = default if isinstance(default, Mapping) else {}
            if default is not _MISSING and not isinstance(default, Mapping):
                log.warning("Configuração %s deveria ser um valor simples; ignorada", full)
                continue
            clean[key] = _sanitize(value, sub_defaults, full + ".")
        elif _compatible(default, value):
            if isinstance(default, float) and isinstance(value, int):
                value = float(value)
            clean[key] = value
        else:
            log.warning(
                "Configuração %s=%r tem tipo inválido (esperado %s); usando o padrão",
                full,
                value,
                type(default).__name__,
            )
    return clean


class TomlConfigStore:
    """Implementação de :class:`nvda_linux.contracts.ConfigStore` sobre TOML."""

    def __init__(
        self,
        directory: Path | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self._dir = directory or config_dir()
        self._defaults: dict[str, Any] = copy.deepcopy(dict(defaults or DEFAULTS))
        self._base: dict[str, Any] = {}
        self._profile: dict[str, Any] | None = None
        self._profile_name: str | None = None
        self._dirty_base = False
        self._dirty_profile = False
        self._listeners: list[tuple[str, ConfigListener]] = []
        self._base = self._read(self.base_path)

    # ------------------------------------------------------------- caminhos
    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def base_path(self) -> Path:
        return self._dir / "nvda.toml"

    def profile_path(self, name: str) -> Path:
        safe = re.sub(r"[^\w.-]", "_", name)
        return self._dir / "profiles" / f"{safe}.toml"

    @property
    def active_profile(self) -> str | None:
        return self._profile_name

    def list_profiles(self) -> list[str]:
        """Nomes dos perfis existentes em disco."""
        pdir = self._dir / "profiles"
        if not pdir.is_dir():
            return []
        return sorted(p.stem for p in pdir.glob("*.toml"))

    # ------------------------------------------------------------- leitura
    def _read(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError:
            return {}
        except (OSError, tomllib.TOMLDecodeError) as exc:
            log.error("Configuração %s ilegível (%s); usando valores padrão", path, exc)
            return {}
        return _sanitize(data, self._defaults)

    def get(self, key: str, default: Any = None) -> Any:
        """Valor de ``key`` (chave com ponto). Tabelas voltam como dict mesclado."""
        parts = key.split(".")
        layers: list[Mapping[str, Any]] = [self._defaults, self._base]
        if self._profile is not None:
            layers.append(self._profile)
        found: Any = _MISSING
        merged: dict[str, Any] | None = None
        for layer in layers:
            value = _lookup(layer, parts)
            if value is _MISSING:
                continue
            if isinstance(value, Mapping):
                merged = _deep_merge(merged if merged is not None else {}, value)
                found = merged
            else:
                merged = None
                found = value
        if found is _MISSING:
            return default
        return copy.deepcopy(found) if isinstance(found, (dict, list)) else found

    # ------------------------------------------------------------- escrita
    def set(self, key: str, value: Any) -> None:
        """Grava ``value`` no perfil ativo (ou na base) e avisa os ouvintes."""
        parts = key.split(".")
        default = _lookup(self._defaults, parts)
        if not _compatible(default, value):
            raise TypeError(
                f"Valor inválido para {key}: {value!r} (esperado {type(default).__name__})"
            )
        if self.get(key, _MISSING) == value:
            return
        if self._profile is not None:
            _assign(self._profile, parts, copy.deepcopy(value))
            self._dirty_profile = True
        else:
            _assign(self._base, parts, copy.deepcopy(value))
            self._dirty_base = True
        self._notify(key, value)

    def save(self) -> None:
        """Grava em disco (escrita atômica: arquivo temporário + rename)."""
        if self._dirty_base or not self.base_path.exists():
            self._write(self.base_path, self._base)
            self._dirty_base = False
        if self._profile is not None and self._profile_name is not None and self._dirty_profile:
            self._write(self.profile_path(self._profile_name), self._profile)
            self._dirty_profile = False

    def _write(self, path: Path, data: Mapping[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(dumps_toml(data), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.error("Não foi possível salvar a configuração em %s: %s", path, exc)

    # ------------------------------------------------------------- perfis
    def activate_profile(self, name: str | None) -> None:
        """Troca o perfil ativo. ``None`` volta à configuração base."""
        if name == self._profile_name:
            return
        before = self._snapshot()
        if self._dirty_profile:
            self.save()
        if name is None:
            self._profile = None
            self._profile_name = None
        else:
            self._profile = self._read(self.profile_path(name))
            self._profile_name = name
        self._dirty_profile = False
        log.debug("Perfil de configuração ativo: %s", name or "(padrão)")
        after = self._snapshot()
        for key in sorted(set(before) | set(after)):
            if before.get(key, _MISSING) != after.get(key, _MISSING):
                self._notify(key, after.get(key))

    def _snapshot(self) -> dict[str, Any]:
        flat: dict[str, Any] = {}

        def walk(prefix: str, node: Mapping[str, Any]) -> None:
            for k, v in node.items():
                if isinstance(v, Mapping):
                    walk(f"{prefix}{k}.", v)
                else:
                    flat[f"{prefix}{k}"] = v

        merged = _deep_merge(copy.deepcopy(self._defaults), self._base)
        if self._profile is not None:
            _deep_merge(merged, self._profile)
        walk("", merged)
        return flat

    # ------------------------------------------------------------- ouvintes
    def subscribe(self, prefix: str, listener: ConfigListener) -> Callable[[], None]:
        """Chama ``listener(key, value)`` quando uma chave sob ``prefix`` muda.

        Devolve uma função que cancela a inscrição. (Extensão local; não faz
        parte do contrato congelado.)
        """
        entry = (prefix, listener)
        self._listeners.append(entry)

        def unsubscribe() -> None:
            if entry in self._listeners:
                self._listeners.remove(entry)

        return unsubscribe

    def _notify(self, key: str, value: Any) -> None:
        for prefix, listener in list(self._listeners):
            if key == prefix or key.startswith(prefix.rstrip(".") + ".") or not prefix:
                try:
                    listener(key, value)
                except Exception:
                    log.exception("Ouvinte de configuração falhou para %s", key)
