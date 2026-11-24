"""Leitura do ``manifest.ini`` de add-ons (formato configobj do NVDA).

Exemplo::

    name = meuPlugin
    summary = "Meu complemento"
    description = \"\"\"Texto
    em várias linhas\"\"\"
    author = "Fulana <fulana@example.org>"
    version = 1.0
    url = https://example.org
    minimumNVDAVersion = 2024.1
    lastTestedNVDAVersion = 2025.1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_KEY_RE = re.compile(r"^\s*([A-Za-z_][\w.-]*)\s*=\s*(.*)$")
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class ManifestError(ValueError):
    """``manifest.ini`` ausente, ilegível ou sem nome válido."""


@dataclass(frozen=True, slots=True)
class AddonManifest:
    name: str
    summary: str = ""
    description: str = ""
    author: str = ""
    version: str = ""
    url: str = ""
    minimum_nvda_version: str = ""
    last_tested_nvda_version: str = ""
    raw: dict[str, str] = field(default_factory=dict)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_manifest_text(text: str) -> dict[str, str]:
    """Pares ``chave = valor`` com aspas simples, duplas e triplas."""
    result: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "[")):
            continue
        match = _KEY_RE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        for triple in ('"""', "'''"):
            if value.startswith(triple):
                body = value[3:]
                if triple in body:
                    value = body.split(triple, 1)[0]
                else:
                    parts = [body]
                    while i < len(lines):
                        nxt = lines[i]
                        i += 1
                        if triple in nxt:
                            parts.append(nxt.split(triple, 1)[0])
                            break
                        parts.append(nxt)
                    value = "\n".join(parts)
                break
        else:
            value = _unquote(value)
        result[key] = value
    return result


def read_manifest(path: Path, fallback_name: str | None = None) -> AddonManifest:
    """Lê ``path`` (o arquivo ``manifest.ini``)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"manifest ilegível: {exc}") from exc
    data = parse_manifest_text(text)
    name = data.get("name") or fallback_name or ""
    if not VALID_NAME_RE.match(name):
        raise ManifestError(f"nome de complemento inválido: {name!r}")
    return AddonManifest(
        name=name,
        summary=data.get("summary", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        version=data.get("version", ""),
        url=data.get("url", ""),
        minimum_nvda_version=data.get("minimumNVDAVersion", ""),
        last_tested_nvda_version=data.get("lastTestedNVDAVersion", ""),
        raw=data,
    )
