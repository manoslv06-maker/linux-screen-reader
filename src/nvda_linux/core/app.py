"""Orquestração do leitor (equivale ao ``core.main`` do NVDA).

Ordem de partida:

1. configuração (``services.register("config")``);
2. áudio e bips (``"tones"``);
3. sintetizador e gerenciador de fala (``"speech"``);
4. despachante de gestos (``"dispatcher"``) e mapa ``gestures.ini``;
5. braille (``"braille"``);
6. teclado: processador + backend automático (KeyboardMonitor ou evdev);
7. watchdog (solta o teclado se o loop travar);
8. SEMÂNTICA: ``nvda_linux.scripts.bootstrap.start()`` se o módulo existir.

A parada é na ordem inversa, e o teclado é sempre solto primeiro.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nvda_linux import services
from nvda_linux.braille.handler import BrailleHandler, create_braille
from nvda_linux.contracts import ConfigStore, KeyboardLayout, SpeechPriority
from nvda_linux.core.config import TomlConfigStore
from nvda_linux.core.log import ROOT_LOGGER_NAME, get_logger
from nvda_linux.core.loop import ShutdownSignal
from nvda_linux.core.permissions import keyboard_permission_message
from nvda_linux.core.watchdog import Watchdog
from nvda_linux.inputCore.backend import KeyboardBackend
from nvda_linux.inputCore.dispatcher import InputManager
from nvda_linux.inputCore.factory import BackendFactory, select_backend
from nvda_linux.inputCore.gesture_map import GestureMap
from nvda_linux.inputCore.keyboard import KeyboardInputProcessor
from nvda_linux.inputCore.xkb import create_keymap
from nvda_linux.speech.audio import AudioPlayer, create_player
from nvda_linux.speech.driver import SynthDriver
from nvda_linux.speech.drivers import select_driver
from nvda_linux.speech.drivers.espeak import language_from_locale
from nvda_linux.speech.manager import SpeechManager
from nvda_linux.speech.tones import ToneGenerator

log = get_logger(__name__)

SynthFactory = Callable[[str, Callable[[str, Any], Any]], Awaitable[SynthDriver]]
BrailleFactory = Callable[
    [ConfigStore, Callable[[], InputManager | None]], Awaitable[BrailleHandler]
]

START_TONES = ((440.0, 60), (660.0, 60))
EXIT_TONES = ((660.0, 60), (440.0, 60))
HARD_EXIT_SECONDS = 5.0
INPUT_ERROR_TONE = (220.0, 150)
INPUT_ERROR_MESSAGE = "Erro no teclado do NVDA. Os comandos voltam em instantes."
INPUT_GAVE_UP_MESSAGE = (
    "Erros repetidos no teclado. Comandos do NVDA desligados; reinicie o leitor."
)


@dataclass
class AppOptions:
    """Opções de linha de comando que afetam a partida."""

    debug: bool = False
    layout: KeyboardLayout | None = None
    config_dir: Path | None = None
    synth: str | None = None
    keyboard_backend: str | None = None
    load_semantics: bool = True
    play_sounds: bool | None = None
    watchdog_timeout: float = 5.0


@dataclass
class _Overrides:
    config: ConfigStore | None = None
    synth_factory: SynthFactory | None = None
    audio_player: AudioPlayer | None = None
    braille_factory: BrailleFactory | None = None
    backend_factories: dict[str, BackendFactory] = field(default_factory=dict)


class Application:
    """O leitor de tela em execução."""

    def __init__(
        self,
        options: AppOptions | None = None,
        *,
        config: ConfigStore | None = None,
        synth_factory: SynthFactory | None = None,
        audio_player: AudioPlayer | None = None,
        braille_factory: BrailleFactory | None = None,
        backend_factories: dict[str, BackendFactory] | None = None,
    ) -> None:
        self.options = options or AppOptions()
        self._over = _Overrides(
            config, synth_factory, audio_player, braille_factory, dict(backend_factories or {})
        )
        self.config: ConfigStore | None = None
        self.tones: ToneGenerator | None = None
        self.speech: SpeechManager | None = None
        self.dispatcher: InputManager | None = None
        self.braille: BrailleHandler | None = None
        self.processor: KeyboardInputProcessor | None = None
        self.backend: KeyboardBackend | None = None
        self.watchdog: Watchdog | None = None
        self.semantics: Any = None
        self.semantics_error: str | None = None
        self.keyboard_errors: list[str] = []
        self._exit = asyncio.Event()
        self._exit_code = 0
        self._started = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ utilidades
    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def _sounds_enabled(self) -> bool:
        if self.options.play_sounds is not None:
            return self.options.play_sounds
        return bool(self._cfg("general.playStartAndExitSounds", True))

    # ------------------------------------------------------------ partida
    async def start(self) -> None:
        """Cria e registra todos os serviços da PLATAFORMA e inicia a SEMÂNTICA."""
        self._loop = asyncio.get_running_loop()

        # 1. Configuração
        self.config = self._over.config or TomlConfigStore(self.options.config_dir)
        services.register("config", self.config)
        if not self.options.debug:
            level = logging.getLevelName(str(self._cfg("general.logLevel", "info")).upper())
            if isinstance(level, int):
                logging.getLogger(ROOT_LOGGER_NAME).setLevel(level)

        # 2. Bips
        player = self._over.audio_player or create_player(
            device=str(self._cfg("audio.outputDevice", ""))
        )
        self.tones = ToneGenerator(player, volume=int(self._cfg("audio.beepVolume", 50)))
        self.tones.bind(self._loop)
        services.register("tones", self.tones)

        # 3. Fala
        synth_name = self.options.synth or str(self._cfg("speech.synth", "auto"))
        factory = self._over.synth_factory or select_driver
        driver = await factory(synth_name, self._cfg)
        language = str(self._cfg("speech.language", "")) or language_from_locale()
        self.speech = SpeechManager(driver, config=self.config, tones=self.tones, language=language)
        self.speech.start(self._loop)
        services.register("speech", self.speech)

        # 4. Despachante + gestures.ini
        gesture_map = GestureMap()
        gestures_file = str(self._cfg("keyboard.gesturesFile", ""))
        config_dir = getattr(self.config, "directory", None)
        if gestures_file:
            gesture_map.load(Path(gestures_file).expanduser())
        elif isinstance(config_dir, Path):
            gesture_map.load(config_dir / "gestures.ini")
        self.dispatcher = InputManager(
            config=self.config,
            speech=self.speech,
            gesture_map=gesture_map,
            layout=self.options.layout,
        )
        services.register("dispatcher", self.dispatcher)

        # 5. Braille
        braille_factory = self._over.braille_factory or create_braille
        self.braille = await braille_factory(self.config, lambda: self.dispatcher)
        self.dispatcher.braille = self.braille
        services.register("braille", self.braille)

        # 6. Teclado
        keymap = create_keymap(
            str(self._cfg("keyboard.xkbLayout", "")), str(self._cfg("keyboard.xkbVariant", ""))
        )
        self.processor = KeyboardInputProcessor(
            self.dispatcher,
            config=self.config,
            keymap=keymap,
            on_emergency=self.emergency_exit,
            on_input_error=self._on_input_error,
        )
        backend_name = self.options.keyboard_backend or str(self._cfg("keyboard.backend", "auto"))
        choice = await select_backend(
            backend_name,
            self.processor,
            self.dispatcher,
            self.config,
            factories=self._over.backend_factories or None,
        )
        self.backend = choice.backend
        self.keyboard_errors = choice.errors
        if choice.backend.name == "none" and backend_name != "none":
            message = (
                keyboard_permission_message()
                if choice.permission_problem
                else ("Atenção: nenhum teclado disponível para o NVDA. Veja o log.")
            )
            log.error("%s Detalhes: %s", message, "; ".join(choice.errors))
            self.speech.speak_text(message, SpeechPriority.NEXT)

        # 7. Watchdog
        self.watchdog = Watchdog(freeze_timeout=self.options.watchdog_timeout)
        backend = self.backend
        self.watchdog.add_freeze_hook(backend.release_grab)
        self.watchdog.add_recover_hook(backend.regrab)
        self.watchdog.start()

        services.register("app", self)
        self._started = True
        if self._sounds_enabled():
            for i, (hz, ms) in enumerate(START_TONES):
                self._loop.call_later(i * ms / 1000.0, self.tones.beep, hz, ms)

        # 8. SEMÂNTICA
        if self.options.load_semantics:
            await self._start_semantics()
        log.info(
            "nvda-linux iniciado (fala=%s, teclado=%s, braille=%s, layout=%s)",
            driver.name,
            self.backend.name,
            self.braille.display.name,
            self.dispatcher.layout.value,
        )

    async def _start_semantics(self) -> None:
        name = services.SEMANTICS_BOOTSTRAP_MODULE
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            if getattr(exc, "name", None) == name:
                self.semantics_error = f"{name} ainda não existe"
                log.warning("Módulo semântico %s não encontrado; rodando só a plataforma", name)
            else:
                self.semantics_error = f"falha ao importar {name}: {exc}"
                log.exception("Falha ao importar %s", name)
            return
        except Exception as exc:
            self.semantics_error = f"erro em {name}: {exc}"
            log.exception("Erro ao importar %s", name)
            return
        self.semantics = module
        start = getattr(module, "start", None)
        if not callable(start):
            self.semantics_error = f"{name}.start() não existe"
            log.warning("%s não define start()", name)
            return
        try:
            result = start()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self.semantics_error = f"{name}.start() falhou: {exc}"
            log.exception("%s.start() falhou", name)

    # ------------------------------------------------------------ parada
    async def stop(self) -> None:
        """Encerra tudo, soltando o teclado antes de qualquer outra coisa."""
        if not self._started:
            return
        self._started = False
        if self.backend is not None:
            with contextlib.suppress(Exception):
                self.backend.release_grab()
        if self.semantics is not None:
            stop = getattr(self.semantics, "stop", None)
            if callable(stop):
                try:
                    result = stop()
                    if inspect.isawaitable(result):
                        await asyncio.wait_for(result, 3.0)
                except Exception:
                    log.exception("Falha ao parar a SEMÂNTICA")
        if self.backend is not None:
            try:
                await self.backend.stop()
            except Exception:
                log.exception("Falha ao parar o backend de teclado")
        if self.watchdog is not None:
            await self.watchdog.stop()
        if self.dispatcher is not None:
            await self.dispatcher.stop()
        if self.tones is not None and self._sounds_enabled():
            for hz, ms in EXIT_TONES:
                self.tones.beep(hz, ms)
                await asyncio.sleep(ms / 1000.0)
        if self.braille is not None:
            await self.braille.close()
        if self.speech is not None:
            await self.speech.stop()
        if self.tones is not None:
            await self.tones.close()
        if self.config is not None:
            try:
                self.config.save()
            except Exception:
                log.exception("Falha ao salvar a configuração")
        log.info("nvda-linux encerrado")

    def request_exit(self, code: int = 0) -> None:
        """Pede o encerramento limpo (usado por NVDA+Q da SEMÂNTICA via services)."""
        self._exit_code = code
        loop = self._loop
        if loop is None:
            self._exit.set()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._exit.set()
        else:
            loop.call_soon_threadsafe(self._exit.set)

    def _on_input_error(self, gave_up: bool) -> None:
        """Um erro no teclado soltou o grab: o usuário precisa saber."""
        message = INPUT_GAVE_UP_MESSAGE if gave_up else INPUT_ERROR_MESSAGE
        if self.tones is not None:
            self.tones.beep(*INPUT_ERROR_TONE)
        if self.speech is not None:
            self.speech.speak_text(message, SpeechPriority.NOW)

    def emergency_exit(self) -> None:
        """Combinação de emergência: teclado já foi solto; encerra mesmo se travar."""
        log.warning("Saída de emergência solicitada")
        timer = threading.Timer(HARD_EXIT_SECONDS, lambda: os._exit(3))
        timer.daemon = True
        timer.start()
        self.request_exit(3)

    async def run(self, shutdown: ShutdownSignal | None = None) -> int:
        """Inicia, espera o pedido de saída (ou sinal) e encerra."""
        try:
            await self.start()
        except Exception:
            log.exception("Falha fatal na partida")
            await self.stop()
            return 1
        waiters: list[asyncio.Task[Any]] = [asyncio.ensure_future(self._exit.wait())]
        if shutdown is not None:
            waiters.append(asyncio.ensure_future(shutdown.event.wait()))
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waiters:
                w.cancel()
            await self.stop()
        return self._exit_code
