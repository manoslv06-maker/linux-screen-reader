"""Diagnóstico de permissões e dependências (``nvda-linux --check-permissions``).

Verifica o que o leitor precisa para funcionar e explica como corrigir:
acesso a ``/dev/input`` e ``/dev/uinput``, grupo ``input``, D-Bus de sessão,
Speech Dispatcher, BRLTTY, variáveis de acessibilidade e módulos Python.
"""

from __future__ import annotations

import glob
import grp
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from nvda_linux.core.compat import import_failure, optional_import


class Status(Enum):
    OK = "ok"
    WARN = "aviso"
    FAIL = "falha"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str
    hint: str = ""


A11Y_ENV: dict[str, str] = {
    "GTK_MODULES": "gail:atk-bridge",
    "QT_ACCESSIBILITY": "1",
    "ACCESSIBILITY_ENABLED": "1",
}

INPUT_HINT = (
    "sudo usermod -aG input $USER  (e entre de novo na sessão), ou instale "
    "packaging/udev/99-nvda-input.rules em /etc/udev/rules.d/"
)


def _in_group(name: str) -> bool | None:
    try:
        group = grp.getgrnam(name)
    except KeyError:
        return None
    if group.gr_gid in os.getgroups():
        return True
    user = os.environ.get("USER", "")
    return bool(user and user in group.gr_mem)


def check_input_devices(pattern: str = "/dev/input/event*") -> Check:
    nodes = sorted(glob.glob(pattern))
    readable = [n for n in nodes if os.access(n, os.R_OK)]
    if not nodes:
        return Check("/dev/input", Status.FAIL, "nenhum nó de evento encontrado", INPUT_HINT)
    if not readable:
        return Check(
            "/dev/input", Status.FAIL, f"0 de {len(nodes)} dispositivos legíveis", INPUT_HINT
        )
    status = Status.OK if len(readable) == len(nodes) else Status.WARN
    return Check("/dev/input", status, f"{len(readable)} de {len(nodes)} dispositivos legíveis")


def check_uinput(path: str = "/dev/uinput") -> Check:
    if not os.path.exists(path):
        return Check(
            "/dev/uinput", Status.FAIL, "não existe", "sudo modprobe uinput (e regra udev)"
        )
    if os.access(path, os.W_OK):
        return Check("/dev/uinput", Status.OK, "gravável")
    return Check("/dev/uinput", Status.FAIL, "sem permissão de escrita", INPUT_HINT)


def check_group() -> Check:
    member = _in_group("input")
    if member is None:
        return Check("grupo input", Status.WARN, "o grupo 'input' não existe nesta distribuição")
    if member:
        return Check("grupo input", Status.OK, "usuário pertence ao grupo")
    return Check("grupo input", Status.WARN, "usuário fora do grupo 'input'", INPUT_HINT)


def check_session(environ: Mapping[str, str]) -> list[Check]:
    checks: list[Check] = []
    session = environ.get("XDG_SESSION_TYPE", "desconhecida")
    desktop = environ.get("XDG_CURRENT_DESKTOP", "desconhecido")
    checks.append(Check("sessão", Status.OK, f"{session} / {desktop}"))
    if environ.get("DBUS_SESSION_BUS_ADDRESS") or os.path.exists(
        os.path.join(environ.get("XDG_RUNTIME_DIR", "/nonexistent"), "bus")
    ):
        checks.append(Check("D-Bus de sessão", Status.OK, "disponível"))
    else:
        checks.append(
            Check(
                "D-Bus de sessão",
                Status.FAIL,
                "DBUS_SESSION_BUS_ADDRESS ausente",
                "rode dentro de uma sessão gráfica (ou via systemd --user)",
            )
        )
    return checks


def check_speech(environ: Mapping[str, str]) -> list[Check]:
    from nvda_linux.speech.ssip import resolve_address

    checks: list[Check] = []
    address = resolve_address(dict(environ))
    has_socket = address.method == "inet_socket" or os.path.exists(address.path)
    has_binary = shutil.which("speech-dispatcher") is not None
    if has_socket:
        checks.append(Check("Speech Dispatcher", Status.OK, f"socket {address.describe()}"))
    elif has_binary:
        checks.append(Check("Speech Dispatcher", Status.OK, "instalado (autospawn)"))
    else:
        checks.append(
            Check(
                "Speech Dispatcher",
                Status.WARN,
                "não encontrado",
                "instale speech-dispatcher e speech-dispatcher-espeak-ng",
            )
        )
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    checks.append(
        Check(
            "eSpeak-NG",
            Status.OK if espeak else Status.WARN,
            espeak or "não encontrado (driver de reserva indisponível)",
        )
    )
    return checks


def check_modules() -> list[Check]:
    checks: list[Check] = []
    for module, purpose, required in (
        ("gi", "AT-SPI2/GTK (PyGObject)", True),
        ("evdev", "teclado via /dev/input", True),
        ("dbus_next", "KeyboardMonitor do GNOME", False),
        ("numpy", "bips", True),
        ("sounddevice", "áudio em processo", False),
        ("speechd", "transporte alternativo do Speech Dispatcher", False),
        ("brlapi", "linha braille (BRLTTY)", False),
        ("louis", "tabelas braille liblouis", False),
    ):
        mod = optional_import(module)
        if mod is not None:
            checks.append(Check(f"python: {module}", Status.OK, purpose))
        else:
            reason = import_failure(module) or "ausente"
            status = Status.FAIL if required else Status.WARN
            checks.append(Check(f"python: {module}", status, f"{purpose}: {reason}"))
    if optional_import("gi") is not None:
        events = optional_import("gi.events")
        checks.append(
            Check(
                "gi.events",
                Status.OK if events is not None else Status.WARN,
                "GLibEventLoopPolicy" if events is not None else "PyGObject < 3.50",
            )
        )
    return checks


def check_a11y_env(environ: Mapping[str, str]) -> Check:
    missing = [k for k, v in A11Y_ENV.items() if v not in environ.get(k, "")]
    if not missing:
        return Check("variáveis de acessibilidade", Status.OK, "exportadas")
    return Check(
        "variáveis de acessibilidade",
        Status.WARN,
        f"faltando: {', '.join(missing)}",
        "use packaging/env/nvda-linux-a11y-env.sh (ou o perfil instalado)",
    )


def run_checks(environ: Mapping[str, str] | None = None) -> list[Check]:
    env = os.environ if environ is None else environ
    checks = [check_input_devices(), check_uinput(), check_group()]
    checks += check_session(env)
    checks += check_speech(env)
    checks.append(check_a11y_env(env))
    checks += check_modules()
    return checks


def format_report(checks: list[Check]) -> str:
    marks = {Status.OK: "[ ok ]", Status.WARN: "[aviso]", Status.FAIL: "[FALHA]"}
    lines = ["Diagnóstico do nvda-linux", ""]
    for c in checks:
        lines.append(f"{marks[c.status]} {c.name}: {c.detail}")
        if c.hint and c.status is not Status.OK:
            lines.append(f"        -> {c.hint}")
    fails = sum(c.status is Status.FAIL for c in checks)
    warns = sum(c.status is Status.WARN for c in checks)
    lines += ["", f"{fails} falha(s), {warns} aviso(s)."]
    return "\n".join(lines)


def keyboard_permission_message() -> str:
    """Mensagem falada quando o teclado não pode ser lido."""
    return (
        "Atenção: o NVDA não tem permissão para ler o teclado. "
        "Adicione seu usuário ao grupo input e entre de novo na sessão. "
        "Os atalhos do NVDA não vão funcionar até lá."
    )
