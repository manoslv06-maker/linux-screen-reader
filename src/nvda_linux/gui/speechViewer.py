# ruff: noqa: N999  (nome de módulo no estilo do NVDA)
"""Visualizador de Fala (``speechViewer`` do NVDA).

:class:`SpeechViewerModel` (sem GTK) assina :mod:`nvda_linux.scripts.speechHooks`
e guarda as últimas falas. :class:`SpeechViewerWindow` mostra o modelo numa
janela GTK 4 somente leitura.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from nvda_linux.contracts import SpeechCommand, SpeechPriority
from nvda_linux.gui import _gtk
from nvda_linux.scripts import speechHooks

log = logging.getLogger(__name__)

LineListener = Callable[[str], None]


class SpeechViewerModel:
    """Histórico de fala alimentado pelo gancho de fala."""

    def __init__(self, max_lines: int = 2000) -> None:
        self.lines: deque[str] = deque(maxlen=max_lines)
        self._listeners: list[LineListener] = []
        self.active = False

    def start(self) -> None:
        if not self.active:
            speechHooks.register(self.on_speech)
            speechHooks.attach_platform_listener()
            self.active = True

    def stop(self) -> None:
        if self.active:
            speechHooks.unregister(self.on_speech)
            speechHooks.detach_platform_listener()
            self.active = False

    def add_listener(self, listener: LineListener) -> None:
        self._listeners.append(listener)

    def remove_listener(self, listener: LineListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def on_speech(
        self, sequence: Sequence[str | SpeechCommand], priority: SpeechPriority
    ) -> None:
        text = speechHooks.text_of(sequence)
        if not text:
            return
        self.lines.append(text)
        for listener in list(self._listeners):
            try:
                listener(text)
            except Exception:
                log.exception("Ouvinte do visualizador falhou")

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class SpeechViewerWindow:
    """Janela GTK 4 com o texto falado (não rouba o foco ao atualizar)."""

    def __init__(self, model: SpeechViewerModel) -> None:
        Gtk = _gtk.Gtk
        self.model = model
        self.window: Any = Gtk.Window(title="Visualizador de Fala - NVDA")
        self.window.set_default_size(600, 400)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        self.view: Any = Gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(True)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        _gtk.set_accessible_label(self.view, "Texto falado")
        scrolled.set_child(self.view)
        self.window.set_child(scrolled)
        self.view.get_buffer().set_text(model.text)
        model.add_listener(self._append)
        self.window.connect("close-request", self._on_close)
        _gtk.close_on_escape(self.window)

    def _append(self, line: str) -> None:
        buffer = self.view.get_buffer()
        prefix = "\n" if buffer.get_char_count() else ""
        buffer.insert(buffer.get_end_iter(), prefix + line)

    def _on_close(self, *_args: Any) -> bool:
        self.model.remove_listener(self._append)
        global _window
        _window = None
        return False

    def present(self) -> None:
        self.window.present()


_model = SpeechViewerModel()
_window: SpeechViewerWindow | None = None


def model() -> SpeechViewerModel:
    """Modelo global (começa a gravar ao abrir o visualizador pela primeira vez)."""
    return _model


def show() -> bool:
    """Abre (ou traz à frente) o Visualizador de Fala."""
    global _window
    _model.start()
    if not _gtk.available():
        return False
    if _window is None:
        try:
            _window = SpeechViewerWindow(_model)
        except Exception:
            log.exception("Falha ao abrir o Visualizador de Fala")
            return False
    _window.present()
    return True


def close() -> None:
    global _window
    if _window is not None:
        try:
            _window.window.close()
        except Exception:  # noqa: BLE001
            log.debug("Falha ao fechar o visualizador")
        _window = None
    _model.stop()
