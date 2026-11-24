"""Saída para o usuário (o ``ui``/``speech`` do NVDA) sobre os serviços.

Nada aqui fala com speechd, tons ou BrlAPI diretamente: tudo passa por
``services.speech()``, ``services.tones()`` e ``services.braille()``. Se um
serviço não estiver registrado (início, testes, falha da PLATAFORMA), a
chamada vira um no-op com log, nunca uma exceção.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from nvda_linux import services
from nvda_linux.contracts import SpeechCommand, SpeechPriority
from nvda_linux.scripts import speechHooks

log = logging.getLogger(__name__)

#: Nomes falados de caracteres isolados (eco de digitação, revisão).
CHARACTER_NAMES: dict[str, str] = {
    " ": "espaço",
    "\n": "nova linha",
    "\r": "retorno de carro",
    "\t": "tab",
    " ": "espaço inseparável",
    ".": "ponto",
    ",": "vírgula",
    ";": "ponto e vírgula",
    ":": "dois pontos",
    "!": "exclamação",
    "?": "interrogação",
    "-": "hífen",
    "_": "sublinhado",
    "/": "barra",
    "\\": "barra invertida",
    "(": "abre parêntese",
    ")": "fecha parêntese",
    "[": "abre colchete",
    "]": "fecha colchete",
    "{": "abre chave",
    "}": "fecha chave",
    "@": "arroba",
    "#": "cerquilha",
    "$": "cifrão",
    "%": "por cento",
    "&": "e comercial",
    "*": "asterisco",
    "+": "mais",
    "=": "igual",
    "<": "menor",
    ">": "maior",
    "'": "apóstrofo",
    '"': "aspas",
    "`": "crase",
    "~": "til",
    "^": "circunflexo",
    "|": "barra vertical",
    "￼": "objeto",
}

BLANK = "em branco"

#: Recebe o deslocamento no texto mostrado na linha braille (``extra["text_offset"]``).
RoutingHandler = Callable[[int], None]
_routing_handler: RoutingHandler | None = None


def character_name(ch: str) -> str:
    """Nome falado de um caractere (``" "`` -> ``"espaço"``)."""
    if not ch:
        return BLANK
    return CHARACTER_NAMES.get(ch, ch)


def speak(
    sequence: Sequence[str | SpeechCommand],
    priority: SpeechPriority = SpeechPriority.NORMAL,
) -> None:
    """Fala uma sequência e a entrega ao gancho do Visualizador de Fala."""
    cleaned = [s for s in sequence if not isinstance(s, str) or s.strip()]
    if not cleaned:
        return
    if not speechHooks.platform_notifies():
        speechHooks.notify(cleaned, priority)
    try:
        services.speech().speak(cleaned, priority)
    except Exception as exc:  # noqa: BLE001
        log.debug("Fala indisponível: %s", exc)


def speak_text(text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
    speak([text], priority)


def message(text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
    """``ui.message`` do NVDA: fala e mostra na linha braille."""
    speak([text], priority)
    braille_message(text)


def speak_character(ch: str) -> None:
    speak([character_name(ch)])


def speak_spelling(text: str) -> None:
    if not text:
        speak([BLANK])
        return
    if not speechHooks.platform_notifies():
        speechHooks.notify([text], SpeechPriority.NORMAL)
    try:
        services.speech().speak_spelling(text)
    except Exception as exc:  # noqa: BLE001
        log.debug("Soletração indisponível: %s", exc)


def cancel() -> None:
    try:
        services.speech().cancel()
    except Exception as exc:  # noqa: BLE001
        log.debug("Cancelamento indisponível: %s", exc)


def pause(paused: bool) -> None:
    try:
        services.speech().pause(paused)
    except Exception as exc:  # noqa: BLE001
        log.debug("Pausa indisponível: %s", exc)


def beep(hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
    try:
        services.tones().beep(hz, duration_ms, left, right)
    except Exception as exc:  # noqa: BLE001
        log.debug("Bipe indisponível: %s", exc)


def braille_show(
    text: str, cursor: int | None = None, on_route: RoutingHandler | None = None
) -> None:
    """Mostra ``text``; ``on_route`` trata as teclas de roteamento sobre ele."""
    global _routing_handler
    _routing_handler = on_route
    try:
        display = services.braille()
        if display.available:
            display.show_text(text, cursor)
    except Exception as exc:  # noqa: BLE001
        log.debug("Braille indisponível: %s", exc)


def route_braille(text_offset: int) -> bool:
    """Tecla de roteamento sobre o texto mostrado por :func:`braille_show`."""
    handler = _routing_handler
    if handler is None:
        return False
    try:
        handler(text_offset)
    except Exception:
        log.exception("Roteamento braille falhou")
        return False
    return True


def braille_message(text: str) -> None:
    try:
        display = services.braille()
        if display.available:
            display.show_message(text)
    except Exception as exc:  # noqa: BLE001
        log.debug("Braille indisponível: %s", exc)
