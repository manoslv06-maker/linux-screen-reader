# linux-screen-reader

[English](README.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · **中文** · [日本語](README.ja.md) · [Русский](README.ru.md) · [हिन्दी](README.hi.md)

一款操作方式与 NVDA 一致的 Linux 屏幕阅读器：NVDA 键（Insert 或 Caps Lock）、台式机和笔记本两种键盘布局、网页的浏览模式和焦点模式、输入帮助、`gestures.ini` 以及插件。使用 Python 3 编写，基于 AT-SPI2、evdev/uinput、Speech Dispatcher 和 BrlAPI。

软件包和命令名为 `nvda-linux`。本项目**与 NV Access 及官方 NVDA 无关**，只是为已经在 Windows 上熟悉 NVDA 的用户重现相同的使用方式。

> ⚠️ **实验版本（0.1.0.dev0）。** 尚不适合日常使用。它已在虚拟机中的 Fedora 45 + GNOME 51 上运行，但还从未被视障人士在日常工作中使用过，也还没有在有声卡的机器上实际听过语音。

## 已可用的功能

已在真实系统上测试（Fedora 45、GNOME 51、Firefox）：

- 通过 Speech Dispatcher 朗读，支持输入回显（密码框中读作“星号”）；
- 通过 evdev/uinput 捕获键盘，NVDA 键，NVDA+T（读标题），焦点播报；
- Firefox 中的浏览模式：页面加载时自动朗读、H/B（下一个标题/按钮）、方向键逐行浏览。

已有自动化测试覆盖（279 个），但尚未在真实机器上确认：光标跟随语音的“全文朗读”、完整的快速导航（K、F、T、D、1–6……）、表格、元素列表、盲文、GTK 4 图形界面、插件。

## 安装

需要 PyGObject 3.50 或更新版本：**Debian 13、Ubuntu 25.04 或更新版本、Fedora 41+、openSUSE Tumbleweed 或 Arch**。Ubuntu 24.04 暂不支持。

最简单的方式是使用 [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases) 页面上的一体化安装程序。它会自动识别发行版，并使用 apt、dnf、zypper 或 pacman：

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # 安装（修改 input 用户组前会先询问）
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

如需从源代码生成安装程序，请参阅[构建软件包](#构建软件包)。

### 首次测试之前

阅读器会捕获整个键盘。请保留**一个备用的登录方式**（SSH 或另一个文本控制台），并记住：**Ctrl+Alt+Shift+Esc** 会退出阅读器并归还键盘。

```sh
sudo usermod -aG input $USER      # 然后注销并重新登录
nvda-linux --check-permissions    # 诊断
nvda-linux --debug                # 在终端中运行，输出详细日志
systemctl --user enable --now nvda-linux.service   # 随会话启动（可选）
```

日志位于 `~/.local/state/nvda-linux/nvda.log`。

## 开发

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

测试使用模拟对象（不需要 AT-SPI2、音频或键盘）。请在 Linux 上运行：在 Windows 上部分测试无法运行。

文档（葡萄牙语）：

- [docs/ROADMAP.md](docs/ROADMAP.md)：计划中的阶段和版本；
- [docs/platform/README.md](docs/platform/README.md)：事件循环、语音、键盘、盲文和打包；
- [docs/semantics/README.md](docs/semantics/README.md)：AT-SPI2、事件、浏览模式和图形界面；
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md)：插件；
- [CLAUDE.md](CLAUDE.md)：当前状态和后续步骤。

### 构建软件包

每个脚本在对应的发行版上运行，并输出到 `dist/`：

| 脚本 | 生成 |
|---|---|
| `packaging/build-packages.sh` | `.deb` 和 `.tar.gz` 源代码包（Debian/Ubuntu） |
| `packaging/build-rpm.sh` | `.rpm`（Fedora 或 openSUSE，取决于所在机器） |
| `packaging/build-arch.sh` | `.pkg.tar.zst`（Arch，以普通用户身份运行） |
| `packaging/build-installer.sh` | 包含以上全部内容的 `nvda-linux-instalador-<版本>.run` |

## 许可证

[GPL-2.0-or-later](LICENSE)。
