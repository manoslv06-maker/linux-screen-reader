# linux-screen-reader

[English](README.md) · [Português](README.pt-BR.md) · [Español](README.es.md) · [中文](README.zh-CN.md) · [日本語](README.ja.md) · **Русский** · [हिन्दी](README.hi.md)

Экранный диктор для Linux с привычным управлением NVDA: клавиша NVDA (Insert или Caps Lock), раскладки Desktop и Laptop, режим просмотра и режим фокуса в вебе, помощь по вводу, `gestures.ini` и дополнения. Написан на Python 3 поверх AT-SPI2, evdev/uinput, Speech Dispatcher и BrlAPI.

Пакет и команда называются `nvda-linux`. Проект **не связан с NV Access** и официальным NVDA; он лишь повторяет способ работы — для тех, кто уже знаком с NVDA в Windows.

> ⚠️ **Экспериментальная версия (0.1.0.dev0).** Пока не подходит для повседневного использования. Он заработал в Fedora 45 с GNOME 51 в виртуальной машине, но ещё ни разу не использовался незрячим человеком в повседневной работе, а голос ещё не проверяли на машине со звуком.

## Что уже работает

Проверено на реальной системе (Fedora 45, GNOME 51, Firefox):

- речь через Speech Dispatcher, эхо при наборе («звёздочка» в полях пароля);
- захват клавиатуры через evdev/uinput, клавиша NVDA, NVDA+T (заголовок), объявление фокуса;
- режим просмотра в Firefox: чтение страницы при загрузке, H/B (следующий заголовок/кнопка), стрелки построчно.

Покрыто автотестами (279), но ещё не подтверждено на реальной машине: «читать всё» с курсором, следующим за речью, полная быстрая навигация (K, F, T, D, 1–6...), таблицы, список элементов, брайль, интерфейс на GTK 4, дополнения.

## Установка

Нужен PyGObject 3.50 или новее: **Debian 13, Ubuntu 25.04 или новее, Fedora 41+, openSUSE Tumbleweed или Arch**. Ubuntu 24.04 пока не подходит.

Проще всего воспользоваться единым установщиком со страницы [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases). Он определяет дистрибутив и использует apt, dnf, zypper или pacman:

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # установка (спросит, прежде чем менять группу input)
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

Как собрать установщик из исходников, см. [Сборка пакетов](#сборка-пакетов).

### Перед первым запуском

Диктор захватывает всю клавиатуру. Оставьте **запасной способ входа** (SSH или другую текстовую консоль) и запомните: **Ctrl+Alt+Shift+Esc** завершает диктор и возвращает клавиатуру.

```sh
sudo usermod -aG input $USER      # затем выйдите из сеанса и войдите снова
nvda-linux --check-permissions    # диагностика
nvda-linux --debug                # запуск в терминале с подробным журналом
systemctl --user enable --now nvda-linux.service   # запуск вместе с сеансом (необязательно)
```

Журнал находится в `~/.local/state/nvda-linux/nvda.log`.

## Разработка

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

Тесты используют поддельные объекты (им не нужны AT-SPI2, звук или клавиатура). Запускайте их в Linux: в Windows часть из них не работает.

Документация (на португальском):

- [docs/ROADMAP.md](docs/ROADMAP.md): запланированные этапы и версии;
- [docs/platform/README.md](docs/platform/README.md): цикл событий, речь, клавиатура, брайль и упаковка;
- [docs/semantics/README.md](docs/semantics/README.md): AT-SPI2, события, режим просмотра и интерфейс;
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md): дополнения;
- [CLAUDE.md](CLAUDE.md): текущее состояние и следующие шаги.

### Сборка пакетов

Каждый скрипт запускается в соответствующем дистрибутиве и записывает результат в `dist/`:

| Скрипт | Собирает |
|---|---|
| `packaging/build-packages.sh` | `.deb` и исходники `.tar.gz` (Debian/Ubuntu) |
| `packaging/build-rpm.sh` | `.rpm` (Fedora или openSUSE, в зависимости от машины) |
| `packaging/build-arch.sh` | `.pkg.tar.zst` (Arch, от обычного пользователя) |
| `packaging/build-installer.sh` | `nvda-linux-instalador-<версия>.run` со всем перечисленным |

## Лицензия

[GPL-2.0-or-later](LICENSE).
