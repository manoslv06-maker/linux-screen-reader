"""Contratos congelados entre as duas equipes do nvda-linux.

ESTE ARQUIVO É SOMENTE LEITURA PARA OS DOIS DESENVOLVEDORES.
Qualquer mudança aqui precisa ser pedida ao coordenador (ver docs/OWNERSHIP.md).

- Equipe PLATAFORMA implementa: SpeechOutput, ToneOutput, BrailleOutput,
  ConfigStore e o despacho de gestos (GestureDispatcher).
- Equipe SEMÂNTICA implementa: ScriptProvider (cadeia de scripts),
  FocusTracker e tudo que lê a árvore AT-SPI2.

As duas equipes só se falam por meio destes Protocols e do registro em
``nvda_linux.services``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Protocol, runtime_checkable


# --------------------------------------------------------------------------
# Fala
# --------------------------------------------------------------------------
class SpeechPriority(IntEnum):
    """Prioridades da fila de fala, iguais às do NVDA (speech.priorities)."""

    NORMAL = 0
    NEXT = 1
    NOW = 2


@dataclass(frozen=True, slots=True)
class SpeechCommand:
    """Comando embutido numa sequência de fala (mudança de tom, pausa etc.)."""

    kind: str  # "pitch" | "rate" | "break" | "spell" | "beep" | "lang" | "index"
    value: float | int | str | None = None


SpeechSequence = Sequence[str | SpeechCommand]


@runtime_checkable
class SpeechOutput(Protocol):
    """Saída de fala. Implementada pela PLATAFORMA (speech/)."""

    def speak(
        self, sequence: SpeechSequence, priority: SpeechPriority = SpeechPriority.NORMAL
    ) -> None:
        """Enfileira a sequência. Nunca bloqueia o loop."""

    def speak_text(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
        """Atalho para ``speak([text])``."""

    def speak_spelling(self, text: str) -> None:
        """Soletra caractere a caractere."""

    def cancel(self) -> None:
        """Interrompe a fala atual e esvazia a fila em menos de 30 ms."""

    def pause(self, paused: bool) -> None:
        """Pausa ou retoma a fala."""

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Recebe o texto de cada fala (Visualizador de Fala). Devolve o cancelador. [P5]"""

    def add_index_listener(self, listener: Callable[[int], None]) -> Callable[[], None]:
        """Avisa quando a fala alcança um ``SpeechCommand("index", n)``. Devolve o
        cancelador. Usado pelo "ler tudo" para o cursor acompanhar a leitura. [S2]"""


@runtime_checkable
class ToneOutput(Protocol):
    """Bips senoidais. Implementada pela PLATAFORMA (speech/tones.py)."""

    def beep(self, hz: float, duration_ms: int, left: int = 50, right: int = 50) -> None:
        """Toca um bip sem bloquear o loop."""


@runtime_checkable
class BrailleOutput(Protocol):
    """Linha braille. Implementada pela PLATAFORMA (braille/)."""

    def show_text(self, text: str, cursor: int | None = None) -> None: ...

    def show_message(self, text: str, timeout_ms: int = 4000) -> None: ...

    @property
    def available(self) -> bool: ...


# Tons padrão usados pela SEMÂNTICA ao alternar modos (NVDA usa estes valores).
BROWSE_MODE_TONE = (440.0, 30)
FOCUS_MODE_TONE = (880.0, 30)


# --------------------------------------------------------------------------
# Entrada e gestos
# --------------------------------------------------------------------------
class KeyboardLayout(Enum):
    DESKTOP = "desktop"
    LAPTOP = "laptop"


@dataclass(frozen=True, slots=True)
class InputGesture:
    """Gesto normalizado.

    ``identifier`` segue o formato do NVDA, sempre em minúsculas e com
    modificadores em ordem alfabética: ``"kb:nvda+shift+downarrow"``,
    ``"kb:h"``, ``"kb:shift+h"``, ``"kb:numpad8"``, ``"br(brltty):routing"``.
    Modificadores válidos: alt, control, nvda, shift, windows.
    """

    identifier: str
    is_modifier_only: bool = False
    repeat_count: int = 0  # 0 = primeiro toque, 1 = segundo toque rápido...
    character: str | None = None  # caractere digitado, se houver
    extra: dict[str, Any] = field(default_factory=dict)  # ex.: {"routing_index": 12}


Script = Callable[[InputGesture], None | Awaitable[None]]


@runtime_checkable
class ScriptProvider(Protocol):
    """Qualquer coisa que responde a gestos (appModule, treeInterceptor,
    NVDAObject, globalPlugin, globalCommands). Implementado pela SEMÂNTICA."""

    def get_script(self, gesture: InputGesture) -> Script | None:
        """Retorna o script ligado ao gesto, ou None para seguir a cadeia."""


@runtime_checkable
class ScriptChainSource(Protocol):
    """Fonte da cadeia de scripts, na ordem do NVDA:
    globalPlugins -> appModule -> treeInterceptor -> foco -> globalCommands.
    Implementado pela SEMÂNTICA (scripts/chain.py)."""

    def chain(self) -> Sequence[ScriptProvider]: ...


@runtime_checkable
class GestureDispatcher(Protocol):
    """Recebe gestos do hardware e decide: script ou passthrough.
    Implementado pela PLATAFORMA (inputCore/)."""

    def set_input_help(self, enabled: bool) -> None: ...

    @property
    def input_help(self) -> bool: ...

    @property
    def layout(self) -> KeyboardLayout: ...

    def send_through(self, gesture: InputGesture) -> None:
        """Reenvia o gesto ao aplicativo (ex.: NVDA+F2 / tecla passthrough)."""

    def process_gesture(self, gesture: InputGesture, *, suppressed: bool | None = None) -> bool:
        """Executa o gesto pela cadeia como se viesse do hardware. True = tratado. [P2]"""

    def refresh_grabs(self) -> None:
        """Recalcula as teclas capturadas. A SEMÂNTICA chama ao trocar de modo
        navegação/foco ou de treeInterceptor. [P3]"""

    # Mapa de gestos do usuário (inputCore.gesture_map.GestureMap). [P2]
    gesture_map: Any


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
@runtime_checkable
class ConfigStore(Protocol):
    """Configuração com perfis. Implementada pela PLATAFORMA (core/config.py).
    Chaves com ponto: "speech.rate", "browseMode.autoFocusMode"."""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...

    def save(self) -> None: ...

    def activate_profile(self, name: str | None) -> None:
        """None = perfil padrão. Usado pela SEMÂNTICA ao trocar de app."""

    def subscribe(
        self, prefix: str, listener: Callable[[str, Any], None]
    ) -> Callable[[], None]:
        """Avisa mudanças em chaves que começam com ``prefix`` (inclusive troca de
        perfil). Devolve o cancelador. [P4]"""


@runtime_checkable
class AppControl(Protocol):
    """Ciclo de vida do leitor. Implementado pela PLATAFORMA (core/app.py). [P4/S3]"""

    def request_exit(self, code: int = 0) -> None: ...


# --------------------------------------------------------------------------
# Foco (lido pela PLATAFORMA para, por exemplo, braille e cancelamento)
# --------------------------------------------------------------------------
@runtime_checkable
class FocusTracker(Protocol):
    """Implementado pela SEMÂNTICA."""

    def focus_description(self) -> str:
        """Texto curto do objeto em foco (para braille e depuração)."""

    def focus_is_protected(self) -> bool:
        """O foco é um campo de senha: o eco de digitação não fala o caractere. [S1]"""
