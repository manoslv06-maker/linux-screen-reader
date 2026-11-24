"""Nomes de caracteres para soletração e eco de teclado.

Equivale, de forma reduzida, ao ``characterDescriptions``/``symbols`` do
NVDA: espaço, pontuação e letras recebem um nome falável. As letras só são
convertidas em nome quando o sintetizador não sabe soletrar sozinho (Piper).
"""

from __future__ import annotations

from typing import Final

_SYMBOLS_PT: Final[dict[str, str]] = {
    " ": "espaço",
    "\t": "tab",
    "\n": "nova linha",
    "\r": "retorno",
    " ": "espaço não separável",
    "!": "exclamação",
    '"': "aspas",
    "#": "cerquilha",
    "$": "cifrão",
    "%": "por cento",
    "&": "e comercial",
    "'": "apóstrofo",
    "(": "abre parênteses",
    ")": "fecha parênteses",
    "*": "asterisco",
    "+": "mais",
    ",": "vírgula",
    "-": "hífen",
    ".": "ponto",
    "/": "barra",
    ":": "dois pontos",
    ";": "ponto e vírgula",
    "<": "menor",
    "=": "igual",
    ">": "maior",
    "?": "interrogação",
    "@": "arroba",
    "[": "abre colchetes",
    "\\": "barra invertida",
    "]": "fecha colchetes",
    "^": "circunflexo",
    "_": "sublinhado",
    "`": "crase",
    "{": "abre chaves",
    "|": "barra vertical",
    "}": "fecha chaves",
    "~": "til",
    "€": "euro",
    "°": "grau",
}

_SYMBOLS_EN: Final[dict[str, str]] = {
    " ": "space",
    "\t": "tab",
    "\n": "new line",
    "\r": "carriage return",
    " ": "no-break space",
    "!": "bang",
    '"': "quote",
    "#": "number",
    "$": "dollar",
    "%": "percent",
    "&": "and",
    "'": "tick",
    "(": "left paren",
    ")": "right paren",
    "*": "star",
    "+": "plus",
    ",": "comma",
    "-": "dash",
    ".": "dot",
    "/": "slash",
    ":": "colon",
    ";": "semi",
    "<": "less",
    "=": "equals",
    ">": "greater",
    "?": "question",
    "@": "at",
    "[": "left bracket",
    "\\": "backslash",
    "]": "right bracket",
    "^": "caret",
    "_": "line",
    "`": "graav",
    "{": "left brace",
    "|": "bar",
    "}": "right brace",
    "~": "tilda",
}

_LETTERS_PT: Final[dict[str, str]] = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        [
            "á",
            "bê",
            "cê",
            "dê",
            "é",
            "éfe",
            "gê",
            "agá",
            "í",
            "jota",
            "cá",
            "éle",
            "ême",
            "êne",
            "ó",
            "pê",
            "quê",
            "érre",
            "ésse",
            "tê",
            "ú",
            "vê",
            "dáblio",
            "xis",
            "ípsilon",
            "zê",
        ],
        strict=True,
    )
)
_LETTERS_PT.update({"ç": "cê cedilha"})

_LETTERS_EN: Final[dict[str, str]] = dict(
    zip(
        "abcdefghijklmnopqrstuvwxyz",
        [
            "ay",
            "bee",
            "see",
            "dee",
            "ee",
            "eff",
            "jee",
            "aitch",
            "eye",
            "jay",
            "kay",
            "el",
            "em",
            "en",
            "oh",
            "pee",
            "cue",
            "ar",
            "ess",
            "tee",
            "you",
            "vee",
            "double you",
            "ex",
            "why",
            "zed",
        ],
        strict=True,
    )
)

CAP_WORD: Final = {"pt": "maiúscula", "en": "cap"}


def _lang_key(language: str) -> str:
    return "pt" if language.lower().startswith("pt") else "en"


def symbol_name(char: str, language: str = "pt") -> str | None:
    """Nome falável de um símbolo/espaço, ou None se for letra/dígito comum."""
    table = _SYMBOLS_PT if _lang_key(language) == "pt" else _SYMBOLS_EN
    return table.get(char)


def letter_name(char: str, language: str = "pt") -> str | None:
    """Nome da letra (para motores que não soletram), ou None."""
    table = _LETTERS_PT if _lang_key(language) == "pt" else _LETTERS_EN
    return table.get(char.lower())


def cap_word(language: str = "pt") -> str:
    return CAP_WORD[_lang_key(language)]


def describe_character(char: str, language: str = "pt", *, spell_letters: bool = False) -> str:
    """Texto para falar um caractere isolado (eco de teclado, soletração)."""
    name = symbol_name(char, language)
    if name is not None:
        return name
    if spell_letters:
        letter = letter_name(char, language)
        if letter is not None:
            return letter
    if not char.isprintable():
        return f"U+{ord(char):04X}"
    return char
