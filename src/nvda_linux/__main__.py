"""Ponto de entrada: ``nvda-linux`` / ``python -m nvda_linux``.

Opções principais::

    nvda-linux                       # inicia o leitor
    nvda-linux --layout laptop       # força o layout Laptop nesta sessão
    nvda-linux --debug               # log em nível DEBUG
    nvda-linux --check-permissions   # diagnóstico e sai
    nvda-linux --version
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path

from nvda_linux.contracts import KeyboardLayout

FALLBACK_VERSION = "0.1.0.dev0"


def version() -> str:
    """Versão instalada (ou a de desenvolvimento)."""
    try:
        return metadata.version("nvda-linux")
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nvda-linux",
        description="Leitor de tela para Linux com a ergonomia do NVDA.",
    )
    parser.add_argument("--version", action="version", version=f"nvda-linux {version()}")
    parser.add_argument("--debug", action="store_true", help="log detalhado (nível DEBUG)")
    parser.add_argument(
        "--layout",
        choices=[layout.value for layout in KeyboardLayout],
        help="layout de teclado do NVDA nesta sessão (desktop ou laptop)",
    )
    parser.add_argument(
        "--check-permissions",
        action="store_true",
        help="verifica permissões e dependências e sai (código 1 se houver falhas)",
    )
    parser.add_argument("--config-dir", type=Path, help="diretório de configuração alternativo")
    parser.add_argument("--log-file", type=Path, help="arquivo de log alternativo")
    parser.add_argument(
        "--synth", help="sintetizador nesta sessão (speechd, espeak, piper, silence)"
    )
    parser.add_argument(
        "--keyboard-backend",
        choices=["auto", "keyboardMonitor", "evdev", "none"],
        help="backend de teclado nesta sessão",
    )
    parser.add_argument("--no-glib", action="store_true", help="usa asyncio puro (sem GLib)")
    parser.add_argument(
        "--no-semantics", action="store_true", help="não carrega nvda_linux.scripts.bootstrap"
    )
    return parser


def check_permissions() -> int:
    from nvda_linux.core.permissions import Status, format_report, run_checks

    checks = run_checks()
    print(format_report(checks))
    return 1 if any(c.status is Status.FAIL for c in checks) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Interpreta a linha de comando e roda o leitor. Devolve o código de saída."""
    args = build_parser().parse_args(argv)
    if args.check_permissions:
        return check_permissions()

    from nvda_linux.core import loop as core_loop
    from nvda_linux.core.app import Application, AppOptions
    from nvda_linux.core.instance import AlreadyRunning, InstanceLock
    from nvda_linux.core.log import setup_logging

    setup_logging(logging.DEBUG if args.debug else logging.INFO, args.log_file)
    options = AppOptions(
        debug=args.debug,
        layout=KeyboardLayout(args.layout) if args.layout else None,
        config_dir=args.config_dir,
        synth=args.synth,
        keyboard_backend=args.keyboard_backend,
        load_semantics=not args.no_semantics,
    )
    app = Application(options)
    try:
        with InstanceLock():
            return core_loop.run(app.run, prefer_glib=not args.no_glib, debug=args.debug)
    except AlreadyRunning as exc:
        print(f"nvda-linux: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
