"""Mapa de gestos no formato ``gestures.ini`` do NVDA.

Exemplo (o mesmo formato que o NVDA grava em ``%APPDATA%\\nvda\\gestures.ini``)::

    [globalCommands.GlobalCommands]
    reportCurrentFocus = kb:nvda+tab, kb(laptop):nvda+shift+tab
    None = kb:nvda+t

    [browseMode.BrowseModeTreeInterceptor]
    nextHeading = kb:h
    nextComma = "kb:nvda+,"

- seção = ``módulo.Classe`` dona do script; chave = nome do script (sem o
  prefixo ``script_``); valor = gestos separados por vírgula (use aspas
  para gestos que contêm vírgula);
- ``None = ...`` desfaz a associação padrão desses gestos naquela classe.

O despacho de scripts é da SEMÂNTICA: o mapa carregado fica em
``InputManager.gesture_map`` e as associações encontradas para cada gesto
vão em ``gesture.extra["bindings"]`` como lista de ``(seção, script)``.
"""

from __future__ import annotations

import configparser
from collections.abc import Iterable
from pathlib import Path

from nvda_linux.core.log import get_logger
from nvda_linux.inputCore.gesture import normalize_identifier

log = get_logger(__name__)

Binding = tuple[str, str]  # (seção "modulo.Classe", nome do script)


def split_gesture_list(value: str) -> list[str]:
    """Divide ``a, "b,c", d`` respeitando aspas."""
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for ch in value:
        if quote:
            if ch == quote:
                quote = None
            else:
                current.append(ch)
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    items.append("".join(current).strip())
    return [i for i in items if i]


def _quote(identifier: str) -> str:
    return f'"{identifier}"' if "," in identifier else identifier


class GestureMap:
    """Associações gesto -> script lidas de um ou mais ``gestures.ini``."""

    def __init__(self) -> None:
        self._by_gesture: dict[str, list[Binding]] = {}
        self._by_script: dict[Binding, list[str]] = {}
        self._unbound: dict[str, set[str]] = {}

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_script.values())

    # ------------------------------------------------------------ edição
    def add(self, section: str, script: str, identifier: str) -> None:
        gid = normalize_identifier(identifier)
        binding = (section, script)
        if binding not in self._by_gesture.setdefault(gid, []):
            self._by_gesture[gid].append(binding)
        if gid not in self._by_script.setdefault(binding, []):
            self._by_script[binding].append(gid)
        self._unbound.get(section, set()).discard(gid)

    def remove(self, section: str, script: str, identifier: str) -> None:
        gid = normalize_identifier(identifier)
        binding = (section, script)
        if binding in self._by_gesture.get(gid, []):
            self._by_gesture[gid].remove(binding)
        if gid in self._by_script.get(binding, []):
            self._by_script[binding].remove(gid)

    def unbind(self, section: str, identifier: str) -> None:
        """Marca ``identifier`` como desassociado em ``section`` (``None = ...``)."""
        gid = normalize_identifier(identifier)
        for binding in list(self._by_gesture.get(gid, [])):
            if binding[0] == section:
                self.remove(binding[0], binding[1], gid)
        self._unbound.setdefault(section, set()).add(gid)

    # ------------------------------------------------------------ consulta
    def bindings_for(self, identifiers: Iterable[str]) -> list[Binding]:
        """Associações para os identificadores, na ordem dada (específico primeiro)."""
        seen: list[Binding] = []
        for identifier in identifiers:
            try:
                gid = normalize_identifier(identifier)
            except ValueError:
                continue
            for binding in self._by_gesture.get(gid, []):
                if binding not in seen:
                    seen.append(binding)
        return seen

    def gestures_for(self, section: str, script: str) -> list[str]:
        return list(self._by_script.get((section, script), []))

    def is_unbound(self, section: str, identifier: str) -> bool:
        try:
            gid = normalize_identifier(identifier)
        except ValueError:
            return False
        return gid in self._unbound.get(section, set())

    def sections(self) -> list[str]:
        names = {s for s, _ in self._by_script} | set(self._unbound)
        return sorted(names)

    # ------------------------------------------------------------ E/S
    def loads(self, text: str, source: str = "<texto>") -> None:
        """Acrescenta as associações de um texto ``gestures.ini``."""
        parser = configparser.ConfigParser(
            interpolation=None, delimiters=("=",), comment_prefixes=("#", ";"), strict=False
        )
        parser.optionxform = str  # type: ignore[assignment,method-assign]
        try:
            parser.read_string(text, source=source)
        except configparser.Error as exc:
            log.error("gestures.ini inválido (%s): %s", source, exc)
            return
        for section in parser.sections():
            for script, value in parser.items(section):
                for identifier in split_gesture_list(value):
                    try:
                        if script == "None":
                            self.unbind(section, identifier)
                        else:
                            self.add(section, script, identifier)
                    except ValueError as exc:
                        log.warning("%s [%s] %s: %s", source, section, script, exc)

    def load(self, path: Path) -> bool:
        """Carrega ``path`` se existir. Devolve True se leu algo."""
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        except OSError as exc:
            log.error("Não foi possível ler %s: %s", path, exc)
            return False
        self.loads(text, str(path))
        log.info("Mapa de gestos carregado de %s (%d associações)", path, len(self))
        return True

    def to_ini(self) -> str:
        """Serializa no formato do NVDA."""
        lines: list[str] = []
        for section in self.sections():
            entries = [
                (script, gids)
                for (sec, script), gids in sorted(self._by_script.items())
                if sec == section and gids
            ]
            unbound = sorted(self._unbound.get(section, set()))
            if not entries and not unbound:
                continue
            if lines:
                lines.append("")
            lines.append(f"[{section}]")
            for script, gids in entries:
                lines.append(f"{script} = {', '.join(_quote(g) for g in gids)}")
            if unbound:
                lines.append(f"None = {', '.join(_quote(g) for g in unbound)}")
        return "\n".join(lines) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_ini(), encoding="utf-8")
