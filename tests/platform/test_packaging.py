"""Sanidade dos arquivos de packaging/."""

from __future__ import annotations

import configparser
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packaging"


def test_systemd_unit() -> None:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(PKG / "systemd" / "nvda-linux.service", encoding="utf-8")
    assert parser["Service"]["ExecStart"].endswith("nvda-linux")
    assert parser["Install"]["WantedBy"] == "graphical-session.target"
    text = (PKG / "systemd" / "nvda-linux.service").read_text(encoding="utf-8")
    for var in ("GTK_MODULES=gail:atk-bridge", "QT_ACCESSIBILITY=1", "ACCESSIBILITY_ENABLED=1"):
        assert f"Environment={var}" in text


def test_udev_rule_covers_input_and_uinput() -> None:
    lines = [
        line
        for line in (PKG / "udev" / "99-nvda-input.rules").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert any('KERNEL=="event*"' in line and 'GROUP="input"' in line for line in lines)
    assert any('KERNEL=="uinput"' in line and 'MODE="0660"' in line for line in lines)


def test_env_script_exports_variables() -> None:
    script = PKG / "env" / "nvda-linux-a11y-env.sh"
    env = {"PATH": os.environ["PATH"], "GTK_MODULES": "canberra-gtk-module"}
    out = subprocess.run(
        [str(script), "env"], capture_output=True, text=True, env=env, check=True
    ).stdout
    values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    assert values["GTK_MODULES"] == "canberra-gtk-module:gail:atk-bridge"
    assert values["QT_ACCESSIBILITY"] == "1"
    assert values["ACCESSIBILITY_ENABLED"] == "1"
    again = subprocess.run(
        ["sh", "-c", f". {script}; . {script}; echo $GTK_MODULES"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
        check=True,
    ).stdout.strip()
    assert again == "gail:atk-bridge"


def test_desktop_entry() -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(PKG / "autostart" / "nvda-linux.desktop", encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application" and entry["Exec"] == "nvda-linux"


def test_distribution_sketches_exist() -> None:
    for rel in ("arch/PKGBUILD", "rpm/nvda-linux.spec", "debian/control", "debian/rules"):
        assert (PKG / rel).is_file(), rel
    assert "python3-evdev" in (PKG / "debian" / "control").read_text(encoding="utf-8")
