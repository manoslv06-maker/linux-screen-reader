# linux-screen-reader

Leitor de tela para Linux com a ergonomia do NVDA: tecla NVDA (Insert ou Caps Lock), layouts Desktop e Laptop, modo de navegação e modo de foco na web, ajuda de entrada, `gestures.ini` e complementos. Escrito em Python 3, sobre AT-SPI2, evdev/uinput, Speech Dispatcher e BrlAPI.

O pacote e o comando se chamam `nvda-linux`. Este projeto **não é afiliado à NV Access** nem ao NVDA oficial; ele só reproduz a forma de uso, para quem já conhece o NVDA no Windows.

> ⚠️ **Experimental (0.1.0.dev0).** Ainda não serve para uso diário. Funcionou num Fedora 45 com GNOME 51 numa máquina virtual, mas nunca foi usado por uma pessoa cega no dia a dia, e a voz ainda não foi ouvida numa máquina com som.

## O que já funciona

Testado de verdade (Fedora 45, GNOME 51, Firefox):

- fala pelo Speech Dispatcher, com eco de digitação (e "asterisco" em campos de senha);
- captura do teclado por evdev/uinput, tecla NVDA, NVDA+T (título), anúncio do foco;
- modo de navegação no Firefox: leitura da página ao carregar, H/B (próximo título/botão), setas linha a linha.

Coberto por testes automáticos (279), ainda sem confirmação em máquina real: "ler tudo" com o cursor acompanhando a fala, navegação rápida completa (K, F, T, D, 1–6...), tabelas, lista de elementos, braille, GUI em GTK 4, complementos.

## Instalar

Precisa de PyGObject 3.50 ou mais novo: **Debian 13, Ubuntu 25.04 ou mais novo, Fedora 41+, openSUSE Tumbleweed ou Arch**. O Ubuntu 24.04 ainda não serve.

O jeito mais simples é o instalador único, que identifica a distribuição e usa apt, dnf, zypper ou pacman:

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # instala (pergunta antes de mexer no grupo input)
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

Para gerar o instalador a partir do código, veja [Gerar os pacotes](#gerar-os-pacotes).

### Antes do primeiro teste

O leitor captura o teclado inteiro. Deixe **um acesso reserva** (SSH ou outro terminal de texto) e lembre: **Ctrl+Alt+Shift+Esc** encerra o leitor e devolve o teclado.

```sh
sudo usermod -aG input $USER      # depois saia e entre de novo na sessão
nvda-linux --check-permissions    # diagnóstico
nvda-linux --debug                # roda no terminal, com log detalhado
systemctl --user enable --now nvda-linux.service   # iniciar junto com a sessão (opcional)
```

O log fica em `~/.local/state/nvda-linux/nvda.log`.

## Desenvolvimento

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

Os testes usam objetos falsos (não precisam de AT-SPI2, áudio nem teclado). Rode no Linux: no Windows parte deles não funciona.

Documentação:

- [docs/ROADMAP.md](docs/ROADMAP.md): fases e versões planejadas;
- [docs/platform/README.md](docs/platform/README.md): loop, fala, teclado, braille e empacotamento;
- [docs/semantics/README.md](docs/semantics/README.md): AT-SPI2, eventos, modo de navegação e GUI;
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md): complementos;
- [CLAUDE.md](CLAUDE.md): estado atual e próximos passos.

### Gerar os pacotes

Cada script roda na distribuição correspondente e grava em `dist/`:

| Script | Gera |
|---|---|
| `packaging/build-packages.sh` | `.deb` e o código-fonte `.tar.gz` (Debian/Ubuntu) |
| `packaging/build-rpm.sh` | `.rpm` (Fedora ou openSUSE, conforme a máquina) |
| `packaging/build-arch.sh` | `.pkg.tar.zst` (Arch, como usuário comum) |
| `packaging/build-installer.sh` | `nvda-linux-instalador-<versão>.run` com tudo acima |

## Licença

[GPL-2.0-or-later](LICENSE).
