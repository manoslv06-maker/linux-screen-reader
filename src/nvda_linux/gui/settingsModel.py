# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Modelo do diálogo de configurações (sem GTK; testável).

Cada :class:`SettingSpec` descreve uma chave de ``services.config()`` com
rótulo, tipo e limites. As chaves seguem o ``core/config.py`` da PLATAFORMA.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nvda_linux.scripts import configUtils


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    label: str  # com mnemônico GTK ("_Velocidade")
    kind: str  # "bool" | "int" | "choice" | "text"
    default: Any
    minimum: int = 0
    maximum: int = 100
    choices: tuple[tuple[str, str], ...] = ()  # (valor, rótulo)


@dataclass(frozen=True, slots=True)
class SettingsCategory:
    name: str
    settings: tuple[SettingSpec, ...] = field(default_factory=tuple)


CATEGORIES: tuple[SettingsCategory, ...] = (
    SettingsCategory(
        "Voz",
        (
            SettingSpec("speech.synth", "_Sintetizador", "choice", "auto",
                        choices=(("auto", "Automático"), ("speechd", "Speech Dispatcher"),
                                 ("espeak", "eSpeak NG"), ("piper", "Piper"),
                                 ("silence", "Sem fala"))),
            SettingSpec("speech.voice", "V_oz", "text", ""),
            SettingSpec("speech.rate", "_Velocidade", "int", 50),
            SettingSpec("speech.pitch", "_Tom", "int", 50),
            SettingSpec("speech.volume", "V_olume", "int", 100),
            SettingSpec("speech.inflection", "_Inflexão", "int", 80),
            SettingSpec("speech.capPitchChange", "Mudança de tom para _maiúsculas", "int", 30,
                        minimum=-100, maximum=100),
            SettingSpec("speech.sayCapForCapitals", "Dizer \"maiúscula\" antes de maiúsculas",
                        "bool", False),
            SettingSpec("speech.beepForCapitals", "_Bipe para maiúsculas", "bool", False),
        ),
    ),
    SettingsCategory(
        "Teclado",
        (
            SettingSpec("keyboard.keyboardLayout", "_Layout do teclado", "choice", "desktop",
                        choices=(("desktop", "Desktop"), ("laptop", "Laptop"))),
            SettingSpec("keyboard.useCapsLockAsNVDAModifierKey", "Usar _Caps Lock como tecla NVDA",
                        "bool", False),
            SettingSpec("keyboard.useNumpadInsertAsNVDAModifierKey",
                        "Usar Insert do teclado _numérico como tecla NVDA", "bool", True),
            SettingSpec("keyboard.useExtendedInsertAsNVDAModifierKey",
                        "Usar _Insert estendido como tecla NVDA", "bool", True),
            SettingSpec("keyboard.speakTypedCharacters", "Falar _caracteres digitados", "bool",
                        True),
            SettingSpec("keyboard.speakTypedWords", "Falar _palavras digitadas", "bool", False),
            SettingSpec("keyboard.speechInterruptForCharacters",
                        "Interromper a fala ao digitar _caracteres", "bool", True),
            SettingSpec("keyboard.speechInterruptForEnter", "Interromper a fala com _Enter",
                        "bool", True),
        ),
    ),
    SettingsCategory(
        "Modo de navegação",
        (
            SettingSpec("browseMode.maxLineLength", "_Máximo de caracteres por linha", "int", 100,
                        minimum=10, maximum=250),
            SettingSpec("browseMode.linesPerPage", "_Linhas por página", "int", 25,
                        minimum=5, maximum=150),
            SettingSpec("browseMode.enableOnPageLoad", "_Ativar modo de navegação ao carregar",
                        "bool", True),
            SettingSpec("browseMode.autoSayAllOnPageLoad", "_Ler tudo ao carregar a página",
                        "bool", True),
            SettingSpec("browseMode.autoPassThroughOnFocusChange",
                        "Modo de foco automático ao mudar o _foco", "bool", True),
            SettingSpec("browseMode.autoPassThroughOnCaretMove",
                        "Modo de foco automático ao mover o _cursor", "bool", False),
            SettingSpec("browseMode.passThroughAudioIndication",
                        "Indicação _sonora dos modos de foco e navegação", "bool", True),
            SettingSpec("browseMode.trapNonCommandGestures",
                        "_Bloquear teclas que não são comandos", "bool", True),
            SettingSpec("browseMode.autoFocusFocusableElements",
                        "Focar _automaticamente elementos focáveis", "bool", False),
        ),
    ),
    SettingsCategory(
        "Braille",
        (
            SettingSpec("braille.display", "_Linha braille", "choice", "auto",
                        choices=(("auto", "Automático"), ("brltty", "BRLTTY"),
                                 ("none", "Nenhuma"))),
            SettingSpec("braille.translationTable", "_Tabela de tradução", "text", ""),
            SettingSpec("braille.messageTimeout", "_Tempo das mensagens (segundos)", "int", 4,
                        minimum=0, maximum=20),
            SettingSpec("braille.wordWrap", "_Evitar dividir palavras", "bool", True),
            SettingSpec("braille.tetherTo", "_Braille segue", "choice", "focus",
                        choices=(("focus", "Foco"), ("review", "Revisão"),
                                 ("auto", "Automático"))),
        ),
    ),
)


def coerce(spec: SettingSpec, value: Any) -> Any:
    """Converte e limita um valor ao tipo da configuração."""
    if spec.kind == "bool":
        return bool(value)
    if spec.kind == "int":
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = int(spec.default)
        return max(spec.minimum, min(spec.maximum, number))
    if spec.kind == "choice":
        valid = [v for v, _label in spec.choices]
        return value if value in valid else spec.default
    return "" if value is None else str(value)


def load_values(getter: Callable[[str, Any], Any] | None = None) -> dict[str, Any]:
    """Valores atuais de todas as configurações."""
    get = getter or configUtils.get
    return {
        spec.key: coerce(spec, get(spec.key, spec.default))
        for category in CATEGORIES
        for spec in category.settings
    }


def apply_values(values: dict[str, Any], save: bool = True) -> list[str]:
    """Grava os valores alterados. Devolve as chaves que falharam."""
    current = load_values()
    failed: list[str] = []
    specs = {s.key: s for c in CATEGORIES for s in c.settings}
    for key, value in values.items():
        spec = specs.get(key)
        if spec is None:
            continue
        new = coerce(spec, value)
        if current.get(key) == new:
            continue
        if not configUtils.set_value(key, new):
            failed.append(key)
    if save:
        configUtils.save()
    return failed
