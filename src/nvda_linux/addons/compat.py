"""Módulos de compatibilidade com a API de add-ons do NVDA.

Muitos add-ons do NVDA começam com::

    import addonHandler, globalPluginHandler, ui, api, controlTypes
    from scriptHandler import script
    addonHandler.initTranslation()

:func:`install` cria esses nomes em ``sys.modules`` (só se ainda não
existirem), apontando para a API do nvda-linux. Desligável com
``addons.nvdaCompatAliases = false``. A parte do add-on que usa APIs do
Windows continua sem funcionar, claro.
"""

from __future__ import annotations

import inspect
import logging
import sys
import types
from collections.abc import Callable, Sequence
from typing import Any

log = logging.getLogger(__name__)

_installed: list[str] = []


def _nvda_script(
    description: str = "",
    category: str | None = None,
    gesture: str | None = None,
    gestures: Sequence[str] | None = None,
    canPropagate: bool = False,
    bypassInputHelp: bool = False,
    allowInSleepMode: bool = False,
    resumeSayAllMode: int | None = None,
    speakOnDemand: bool = False,
) -> Callable[[Any], Any]:
    """``scriptHandler.script`` com os nomes de argumento do NVDA."""
    from nvda_linux.scripts.scriptHandler import script

    return script(
        description=description,
        category=category,
        gesture=gesture,
        gestures=tuple(gestures or ()),
        bypass_input_help=bypassInputHelp,
    )


def _init_translation() -> None:
    """``addonHandler.initTranslation``: define ``_`` (sem tradução) no chamador."""
    frame = inspect.currentframe()
    caller = frame.f_back if frame is not None else None
    if caller is not None:
        caller.f_globals.setdefault("_", lambda text: text)


def _build_modules() -> dict[str, types.ModuleType]:
    from nvda_linux.appModules.appModuleHandler import AppModule
    from nvda_linux.globalPlugins.globalPluginHandler import GlobalPlugin
    from nvda_linux.NVDAObjects import controlTypes as ct
    from nvda_linux.scripts import runtime, ui

    def get_focus_object() -> Any:
        rt = runtime.current()
        return rt.focus.focus if rt is not None else None

    def get_navigator_object() -> Any:
        rt = runtime.current()
        return (rt.focus.navigator or rt.focus.focus) if rt is not None else None

    def set_navigator_object(obj: Any) -> bool:
        rt = runtime.current()
        if rt is None or obj is None:
            return False
        rt.focus.set_navigator(obj)
        return True

    def get_foreground_object() -> Any:
        rt = runtime.current()
        return rt.focus.foreground if rt is not None else None

    def get_review_position() -> Any:
        rt = runtime.current()
        return rt.focus.review if rt is not None else None

    modules: dict[str, types.ModuleType] = {}

    def module(name: str, **attrs: Any) -> None:
        mod = types.ModuleType(name, f"Compatibilidade NVDA ({name}) do nvda-linux")
        for key, value in attrs.items():
            setattr(mod, key, value)
        modules[name] = mod

    module("globalPluginHandler", GlobalPlugin=GlobalPlugin)
    module("appModuleHandler", AppModule=AppModule)
    module("scriptHandler", script=_nvda_script)
    module("ui", message=lambda text, *a, **k: ui.message(str(text)))
    module(
        "api",
        getFocusObject=get_focus_object,
        getNavigatorObject=get_navigator_object,
        setNavigatorObject=set_navigator_object,
        getForegroundObject=get_foreground_object,
        getReviewPosition=get_review_position,
    )
    module("controlTypes", Role=ct.Role, State=ct.State, OutputReason=ct.OutputReason)
    module(
        "speech",
        speakMessage=lambda text, *a, **k: ui.speak_text(str(text)),
        speakText=lambda text, *a, **k: ui.speak_text(str(text)),
        speakSpelling=lambda text, *a, **k: ui.speak_spelling(str(text)),
        cancelSpeech=ui.cancel,
    )
    module("tones", beep=lambda hz, length, left=50, right=50: ui.beep(hz, length, left, right))
    module("addonHandler", initTranslation=_init_translation)
    module("logHandler", log=logging.getLogger("nvda_linux.addon"))
    return modules


def install() -> list[str]:
    """Cria os módulos de compatibilidade ausentes. Devolve os criados."""
    created: list[str] = []
    try:
        modules = _build_modules()
    except Exception:
        log.exception("Falha ao montar os módulos de compatibilidade")
        return created
    for name, mod in modules.items():
        if name in sys.modules:
            continue
        sys.modules[name] = mod
        _installed.append(name)
        created.append(name)
    return created


def uninstall() -> None:
    """Remove os módulos criados por :func:`install`."""
    for name in _installed:
        mod = sys.modules.get(name)
        if mod is not None and (mod.__doc__ or "").startswith("Compatibilidade NVDA"):
            del sys.modules[name]
    _installed.clear()
