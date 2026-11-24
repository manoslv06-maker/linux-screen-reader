# nvda-linux — instruções para o Claude Code

Leitor de tela para Linux em Python 3 que reproduz o NVDA do Windows: NVDAObjects, Browse/Focus Mode, tecla NVDA, layouts Desktop/Laptop, gestures.ini e add-ons. Roadmap completo em `docs/ROADMAP.md`.

## Regras do projeto

- Nunca use bibliotecas do Windows (win32api, win32con, ctypes.windll, comtypes, UIA, MSAA, IAccessible2).
- Stack: AT-SPI2 via `gi.repository.Atspi`; loop `gi.events.GLibEventLoopPolicy` (PyGObject ≥ 3.50, **não** usar gbulb); teclado via `org.freedesktop.a11y.KeyboardMonitor` (GNOME) ou evdev + uinput; fala via Speech Dispatcher (SSIP), eSpeak-NG ou Piper; braille via BrlAPI; GUI em GTK 4.
- Tipagem estrita (mypy --strict), docstrings, asyncio para E/S, tratamento de objetos mortos do AT-SPI2 e falhas de D-Bus.
- Imports de gi, speechd, brlapi, louis, sounddevice e dbus_next sempre protegidos (try/except com fallback).

## Arquitetura e divisão

- `src/nvda_linux/contracts.py` e `services.py`: contratos entre as duas metades. Mude com cuidado e atualize as duas.
- **Plataforma** (`core/`, `speech/`, `braille/`, `inputCore/`, `__main__.py`, `packaging/`, `tests/platform/`): loop, fala, bips, teclado, braille, empacotamento. Detalhes em `docs/platform/README.md`.
- **Semântica** (`NVDAObjects/`, `treeInterceptors/`, `scripts/`, `appModules/`, `globalPlugins/`, `addons/`, `gui/`, `tests/semantics/`): AT-SPI2, eventos, comandos, Browse Mode, add-ons, GUI. Detalhes em `docs/semantics/README.md` e `docs/semantics/ADDONS.md`.
- Divisão de arquivos: `docs/OWNERSHIP.md`. Pedidos entre as equipes: `docs/requests/`.

## Comandos

```bash
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
PYTHONPATH=src python -m nvda_linux --debug           # rodar
PYTHONPATH=src python -m nvda_linux --check-permissions
```

Dependências do sistema (Debian/Ubuntu): `python3-gi gir1.2-atspi-2.0 at-spi2-core gir1.2-gtk-4.0 speech-dispatcher python3-speechd espeak-ng brltty python3-brlapi liblouis-bin python3-louis`. O usuário precisa estar no grupo `input` ou ter a regra `packaging/udev/99-nvda-input.rules` para o backend evdev.

**Segurança no primeiro teste real:** deixe um acesso reserva (SSH ou outro TTY). Ctrl+Alt+Shift+Esc encerra o leitor e solta o teclado.

## Estado atual (23/11/2026)

- Fases 0 a 7 implementadas e testadas com fakes: 241 testes, mypy e ruff limpos. Nada foi validado ainda num Linux real com AT-SPI2, áudio e teclado.
- Browse Mode avisa quando a página passa de `browseMode.maxNodes` (ao carregar e no NVDA+F5); `VirtualBuffer.collection_failed` indica que o resto sumiu porque não houve `Atspi.Collection`. Os testes da Semântica desligam o AT-SPI2 e o GTK reais (`conftest.py`), então passam com ou sem PyGObject/GTK 4 e display instalados (verificado em Ubuntu 24.04, Fedora 45 e Arch).
- No Windows os testes rodam só em parte: `test_app`, `test_core`, `test_ssip` e os de evdev/braille/subprocessos dependem de recursos do Linux (SIGHUP, sockets Unix, `add_reader`, scripts sh). Rode a suíte completa no Linux ou WSL.
- Suíte inteira verde no Linux (270 testes), mypy --strict e ruff limpos. `add_index_listener` implementado (ver item 1 abaixo).

## Primeiro teste real (Fedora 45 / GNOME 51 no Hyper-V, 23/11/2026)

Ferramentas do teste ficaram fora do repositório (máquina virtual local: guest.sh, hv-tools.ps1, step.ps1). Corrigido e coberto por testes:
- ciclo de eventos `state-changed:defunct` do gnome-shell (CPU 27%, 17 mil linhas de log/s);
- conflito de nomes do PyGObject: `Atspi.Accessible.get_text()` escondia `Atspi.Text.get_text` (texto vazio em todo o Browse Mode) → `_atspi.InterfaceProxy`;
- papel `BUTTON` (at-spi2-core novo) e `make_match_rule` tolerante a papéis ausentes.
Funcionou: fala (speechd nativo), evdev com grab, eco, NVDA+T, foco no GNOME, Browse Mode no Firefox (leitura ao carregar, H, B, setas).
Também corrigido: rótulo igual ao nome do campo era falado duas vezes ("Nome Nome caixa de edição"). Pacotes e `.run` em `dist/` regerados com todas essas correções (conferido dentro de cada pacote).
Pendente: "ler tudo" para após o 1º índice (o speechd da VM travou uma vez; reconfirmar com speechd limpo e sem alt+tab no meio); KeyboardMonitor do GNOME 51 recusa (AccessDenied) → cai no evdev; ouvir a voz de verdade (Hyper-V não tem placa de som).

## Próximo trabalho (rodada 2, interrompida antes de começar)

Plataforma:
1. ~~Marcadores de índice~~ feito: `SpeechCommand("index", n)` + `SpeechManager.add_index_listener()`. Drivers com `supports_index_marks` (Speech Dispatcher, nos dois transportes) recebem `IndexSegment` → `<mark name="n"/>` e avisam por `notify_index`; marcas não avisadas saem no fim do enunciado. Os demais (eSpeak, Piper, Silence) têm o enunciado cortado em cada índice, que dispara quando o trecho anterior termina. `cancel()` não dispara índices pendentes.
2. ~~Eco em senha~~ feito: `SpeechManager.on_typed_character` fala "asterisco" e não guarda a palavra quando `focus_is_protected()`; se a consulta falhar, trata como senha.
2b. Feito: erro no processamento de tecla solta o grab, avisa (bip + fala) e pega o teclado de novo após 1 s (`KeyboardInputProcessor._recover_after_error`). Mais de 3 erros em 30 s: desiste e avisa para reiniciar.
3. Incluir em `core/config.py` DEFAULTS as chaves do pedido S4 (`docs/requests/semantics.md`).
4. ~~Dependências GTK 4 nos pacotes~~ feito. `packaging/build-packages.sh` gera `dist/nvda-linux_<versão>_all.deb` e `dist/nvda-linux-<versão>.tar.gz` (fonte do PKGBUILD/spec). O .deb exige python3-gi >= 3.50 (Debian 13, Ubuntu 25.04+), não ativa a unidade systemd de ninguém (`--no-enable`) e não instala autostart global (o .desktop fica em `/usr/share/nvda-linux/autostart/`). `packaging/build-rpm.sh` gera o RPM na distribuição em que rodar (um spec para Fedora e openSUSE; módulos Python como `python3dist(...)`); o RPM fica preso ao `python(abi)` da distro, então gere um por versão. `packaging/build-arch.sh` gera o `.pkg.tar.zst` do Arch (como usuário comum; o makepkg não roda como root). Instalação com dependências reais testada no WSL em Ubuntu 26.04, Fedora 45, openSUSE Tumbleweed e Arch Linux.
   - Instalador único: `packaging/build-installer.sh` junta os pacotes de `dist/` (e um código-fonte sempre novo) em `dist/nvda-linux-instalador-<versão>.run`, autoextraível. O `packaging/installer/install.sh` lê `/etc/os-release` (inclui derivadas por `ID_LIKE`), usa apt/dnf/zypper/pacman, recusa com explicação sistemas com PyGObject < 3.50 (ex.: Ubuntu 24.04), reconstrói o RPM/pacote do Arch se o Python da máquina for outro (`NVDA_INSTALLER_FORCE_BUILD=1` força, para testes), pergunta antes de pôr o usuário no grupo `input` e tem `--yes`, `--dry-run` e `--uninstall`.

Semântica:
1. ~~"Ler tudo" com índices~~ feito em `scripts/sayAll.py`: lotes de 10 linhas, cada uma com `SpeechCommand("index", n)`; o cursor vai para a linha que a fala alcançou e o próximo lote entra na fila ao chegar na última linha do lote. Browse Mode move o cursor virtual; NVDA+seta baixo e "ler tudo" da revisão movem o cursor de revisão (não o do sistema, para não gerar eventos de cursor no meio da leitura). Sem `add_index_listener`, lê tudo de uma vez como antes. O "ler tudo" ao carregar a página não cancela mais o título.
2. Trocar contornos `getattr`/`services._registry` por `services.app()`, `dispatcher().refresh_grabs()/process_gesture/gesture_map`, `speech().add_listener`, `config().subscribe`.
3. Seleção no Browse Mode: Shift+setas, Shift+Ctrl+setas, Ctrl+Shift+Home/End, NVDA+Shift+F9/F10, Ctrl+C para a área de transferência.

Depois: validação num Linux real seguindo os roteiros em `docs/platform/README.md` e `docs/semantics/README.md`.
