"""Sintetizadores disponíveis e escolha automática.

Ordem do modo ``auto``: Speech Dispatcher -> eSpeak-NG (subprocesso) ->
Piper (se houver modelo configurado) -> Silêncio.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nvda_linux.core.log import get_logger
from nvda_linux.speech.driver import SynthDriver, SynthDriverError

log = get_logger(__name__)

ConfigGetter = Callable[[str, Any], Any]


def driver_classes() -> dict[str, type[SynthDriver]]:
    """Nome -> classe de todos os drivers embutidos."""
    from nvda_linux.speech.drivers.espeak import EspeakDriver
    from nvda_linux.speech.drivers.piper import PiperDriver
    from nvda_linux.speech.drivers.silence import SilenceDriver
    from nvda_linux.speech.drivers.speechdispatcher import SpeechDispatcherDriver

    return {
        SpeechDispatcherDriver.name: SpeechDispatcherDriver,
        EspeakDriver.name: EspeakDriver,
        PiperDriver.name: PiperDriver,
        SilenceDriver.name: SilenceDriver,
    }


AUTO_ORDER = ("speechd", "espeak", "piper", "silence")


def _instantiate(cls: type[SynthDriver], get: ConfigGetter) -> SynthDriver:
    factory = getattr(cls, "from_config", None)
    if callable(factory):
        driver = factory(get)
        assert isinstance(driver, SynthDriver)
        return driver
    return cls()


async def select_driver(name: str, get: ConfigGetter) -> SynthDriver:
    """Cria e inicializa o driver ``name`` (ou o primeiro que funcionar em ``auto``).

    Nunca falha: no pior caso devolve o driver de silêncio, e o motivo fica
    no log.
    """
    classes = driver_classes()
    order = AUTO_ORDER if name in ("", "auto") else (name, *[n for n in AUTO_ORDER if n != name])
    for candidate in order:
        cls = classes.get(candidate)
        if cls is None:
            log.warning("Sintetizador desconhecido: %s", candidate)
            continue
        try:
            if not cls.check():
                log.debug("Sintetizador %s não disponível", candidate)
                continue
            driver = _instantiate(cls, get)
            await driver.initialize()
        except (SynthDriverError, OSError) as exc:
            log.warning("Sintetizador %s falhou ao iniciar: %s", candidate, exc)
            continue
        if candidate != name and name not in ("", "auto"):
            log.warning("Sintetizador %s indisponível; usando %s", name, candidate)
        log.info("Sintetizador ativo: %s", candidate)
        return driver
    from nvda_linux.speech.drivers.silence import SilenceDriver

    driver = SilenceDriver()
    await driver.initialize()
    return driver


__all__ = ["AUTO_ORDER", "SynthDriverError", "driver_classes", "select_driver"]
