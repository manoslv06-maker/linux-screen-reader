# linux-screen-reader

**English** · [Português](README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md) · [Русский](README.ru.md) · [हिन्दी](README.hi.md)

A screen reader for Linux with the ergonomics of NVDA: NVDA key (Insert or Caps Lock), Desktop and Laptop layouts, browse mode and focus mode on the web, input help, `gestures.ini` and add-ons. Written in Python 3, on top of AT-SPI2, evdev/uinput, Speech Dispatcher and BrlAPI.

The package and the command are called `nvda-linux`. This project is **not affiliated with NV Access** or the official NVDA; it only reproduces the way NVDA is used, for people who already know it on Windows.

> ⚠️ **Experimental (0.1.0.dev0).** Not ready for daily use yet. It worked on Fedora 45 with GNOME 51 in a virtual machine, but it has never been used day to day by a blind person, and the voice has not yet been heard on a machine with sound.

## What already works

Tested for real (Fedora 45, GNOME 51, Firefox):

- speech through Speech Dispatcher, with typing echo ("asterisk" in password fields);
- keyboard capture through evdev/uinput, NVDA key, NVDA+T (title), focus announcement;
- browse mode in Firefox: reading the page on load, H/B (next heading/button), line-by-line arrows.

Covered by automated tests (279), not yet confirmed on a real machine: "say all" with the cursor following the speech, full quick navigation (K, F, T, D, 1–6...), tables, elements list, braille, GTK 4 GUI, add-ons.

## Install

Requires PyGObject 3.50 or newer: **Debian 13, Ubuntu 25.04 or newer, Fedora 41+, openSUSE Tumbleweed or Arch**. Ubuntu 24.04 does not work yet.

The easiest way is the single installer from the [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases) page. It detects the distribution and uses apt, dnf, zypper or pacman:

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # installs (asks before changing the input group)
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

To build the installer from source, see [Building the packages](#building-the-packages).

### Before the first test

The reader captures the whole keyboard. Keep **a backup way in** (SSH or another text console) and remember: **Ctrl+Alt+Shift+Esc** quits the reader and gives the keyboard back.

```sh
sudo usermod -aG input $USER      # then log out and back in
nvda-linux --check-permissions    # diagnostics
nvda-linux --debug                # runs in the terminal, with a detailed log
systemctl --user enable --now nvda-linux.service   # start with the session (optional)
```

The log is at `~/.local/state/nvda-linux/nvda.log`.

## Development

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

The tests use fake objects (they need no AT-SPI2, audio or keyboard). Run them on Linux: on Windows part of them does not work.

Documentation (in Portuguese):

- [docs/ROADMAP.md](docs/ROADMAP.md): planned phases and versions;
- [docs/platform/README.md](docs/platform/README.md): loop, speech, keyboard, braille and packaging;
- [docs/semantics/README.md](docs/semantics/README.md): AT-SPI2, events, browse mode and GUI;
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md): add-ons;
- [CLAUDE.md](CLAUDE.md): current status and next steps.

### Building the packages

Each script runs on the matching distribution and writes to `dist/`:

| Script | Builds |
|---|---|
| `packaging/build-packages.sh` | `.deb` and the `.tar.gz` source (Debian/Ubuntu) |
| `packaging/build-rpm.sh` | `.rpm` (Fedora or openSUSE, depending on the machine) |
| `packaging/build-arch.sh` | `.pkg.tar.zst` (Arch, as a regular user) |
| `packaging/build-installer.sh` | `nvda-linux-instalador-<version>.run` with all of the above |

## License

[GPL-2.0-or-later](LICENSE).
