# nvda-linux: equipe PLATAFORMA

Sistema, entrada e saída do leitor: loop principal, configuração, log,
watchdog, fala, bips, braille, teclado e empacotamento. A parte semântica
(AT-SPI2, NVDAObjects, Browse Mode, scripts, GUI) é da outra equipe e só
conversa com a plataforma por `contracts.py` e `services.py`.

## Arquitetura

```
                 ┌──────────────── core/app.py (Application) ────────────────┐
                 │ config → tones → speech → dispatcher → braille → teclado   │
                 │ → watchdog → nvda_linux.scripts.bootstrap.start()          │
                 └────────────────────────────────────────────────────────────┘

 teclado físico                                   serviços registrados
 ──────────────                                   ────────────────────
 evdev (grab) ─┐                                  "config"     TomlConfigStore
 KeyboardMon. ─┤→ RawKeyEvent → KeyboardInput-    "tones"      ToneGenerator
               │   Processor (tecla NVDA, duplo   "speech"     SpeechManager
               │   toque, Ctrl/Shift, emergência) "braille"    BrailleHandler
               │        │ InputGesture            "dispatcher" InputManager
               │        ▼                         "app"        Application
               │   InputManager: NVDA+1, NVDA+F2, ajuda de entrada,
               │   services.script_chain().chain() → script (sync/async)
               │        │ sem script → passthrough (uinput) + eco/interrupção
 linha braille ┘   BrailleHandler: rolagem local; demais teclas → InputManager
 (BrlAPI)
```

### Módulos

| Caminho | Papel |
|---|---|
| `core/loop.py` | asyncio sobre o GLib via `gi.events.GLibEventLoopPolicy` (PyGObject ≥ 3.50), usando `policy.get_event_loop()` (o MainContext padrão, onde AT-SPI2/GTK entregam eventos). Sem `gi`, cai para asyncio puro. SIGINT/SIGTERM/SIGHUP disparam o desligamento limpo. |
| `core/config.py` | `ConfigStore` em TOML (`~/.config/nvda-linux/nvda.toml`, perfis em `profiles/<nome>.toml`), chaves com ponto, nomes iguais aos do `nvda.ini`. Valores com tipo errado são ignorados com aviso. Extensão: `subscribe(prefixo, ouvinte)`. |
| `core/log.py` | Log em `~/.local/state/nvda-linux/nvda.log` (+ `nvda-old.log`), nível `IO` para fala e teclas, buffer circular para a GUI. |
| `core/watchdog.py` | Thread que detecta o loop travado (> 5 s), registra a pilha e **solta o grab do teclado**; regrab automático quando o loop volta. |
| `core/permissions.py` | `--check-permissions`: `/dev/input`, `/dev/uinput`, grupo `input`, D-Bus, speechd, variáveis de acessibilidade, módulos. |
| `core/instance.py` | Trava de instância única (`flock` em `$XDG_RUNTIME_DIR`). |
| `core/app.py` | Orquestração, ordem de partida/parada, bootstrap da SEMÂNTICA (tolerante a `ImportError`), saída de emergência. |
| `speech/driver.py` | `SynthDriver` abstrato, segmentos (texto/prosódia/pausa/soletração), SSML. |
| `speech/ssip.py` | Cliente SSIP próprio, assíncrono, no socket Unix do Speech Dispatcher. `CANCEL self` é uma escrita no socket, sem esperar resposta. |
| `speech/drivers/` | `speechd` (transporte nativo ou módulo `speechd`), `espeak` (subprocesso `espeak-ng -m`), `piper` (subprocesso + áudio em fluxo), `silence`. `auto`: speechd → espeak → piper → silêncio. |
| `speech/manager.py` | `SpeechOutput`: filas NOW/NEXT/NORMAL, comandos `pitch`/`rate`/`break`/`spell`/`beep`/`lang`, soletração com maiúsculas, eco de caracteres/palavras. |
| `speech/tones.py`, `speech/audio.py` | `ToneOutput`: senoide NumPy (ou Python puro) com rampa, estéreo; saída por `sounddevice`, `pw-play -a`, `pacat --raw` ou `aplay`. |
| `braille/` | `BrailleOutput` via BrlAPI (BRLTTY), liblouis opcional, janelas com quebra de palavra, mensagens temporárias, teclas → gestos `br(brltty):*`. |
| `inputCore/keys.py`, `gesture.py`, `layouts.py` | Nomes de teclas do NVDA, identificadores normalizados, layouts Desktop/Laptop. |
| `inputCore/gesture_map.py` | `gestures.ini` no formato do NVDA. |
| `inputCore/xkb.py` | Caractere digitado conforme o layout XKB real (libxkbcommon via ctypes); reserva US. |
| `inputCore/keyboard.py` | Máquina de estados do teclado. |
| `inputCore/dispatcher.py` | `GestureDispatcher` (`InputManager`). |
| `inputCore/evdev_backend.py` | Grab exclusivo + reemissão por uinput (KDE, Sway, Hyprland, X11, console). |
| `inputCore/keyboard_monitor.py` | `org.freedesktop.a11y.KeyboardMonitor` (GNOME 48+ Wayland, niri) via `dbus-next`. |
| `inputCore/factory.py` | Escolha automática do backend. |
| `packaging/` | systemd `--user`, udev, `environment.d`/perfil com as variáveis de acessibilidade, autostart, esboços AUR/RPM/deb, `install-user.sh`. |

### Teclado: regras de comportamento

- **Tecla NVDA**: Insert, Insert numérico (com NumLock desligado) e Caps Lock,
  conforme `keyboard.useExtendedInsertAsNVDAModifierKey`,
  `keyboard.useNumpadInsertAsNVDAModifierKey` e
  `keyboard.useCapsLockAsNVDAModifierKey`. Nunca chega ao aplicativo. Dois
  toques em menos de `keyboard.doubleTapTimeoutMs` (350 ms) repassam a tecla
  original (no KeyboardMonitor, quem repassa é o compositor).
- **Identificadores**: `kb:` + modificadores em ordem alfabética (`alt`,
  `control`, `nvda`, `shift`, `windows`) + tecla, tudo minúsculo:
  `kb:control+nvda+shift+t`, `kb:numpad8`, `kb:numlocknumpad8`.
- **`gesture.extra`** (teclado): `layout`, `normalized_identifiers`
  (`kb(laptop):…` antes de `kb:…`), `modifiers`, `keycode`, `autorepeat`,
  `bindings` (do `gestures.ini`), e no Laptop `desktop_equivalent` /
  `laptop_identifier`. Braille: `command`, `argument`, `routing_index`
  (célula), `text_offset` (posição no texto mostrado).
- **Layout Laptop**: o despachante tenta primeiro o gesto Desktop
  equivalente (tabela `layouts.CORE_COMMANDS`, do Guia do Usuário do NVDA) e
  depois o original. Assim a SEMÂNTICA pode ligar os comandos de revisão e
  navegação só pelo gesto Desktop.
- **Embutidos**: `NVDA+1` (ajuda de entrada) e `NVDA+F2` (passar a próxima
  tecla) são tratados antes da cadeia. Ctrl sozinho interrompe a fala;
  um toque em Shift sozinho pausa/retoma.
- **Sem script**: gestos com NVDA são engolidos; os demais seguem ao
  aplicativo, com interrupção da fala (`keyboard.speechInterruptForCharacters`,
  `…ForEnter`) e eco (`keyboard.speakTypedCharacters`, `…Words`).
- **Script**: antes de rodar, a fala é interrompida, a menos que o script
  tenha `speechEffectWhenExecuted = None`. Scripts síncronos rodam no
  próximo giro do loop; `async` viram tarefas. Exceções vão para o log.
- **Segurança**: qualquer exceção no processamento solta o grab;
  **Ctrl+Alt+Shift+Esc** solta o teclado e encerra o leitor (com
  `os._exit` após 5 s se o encerramento travar); o watchdog solta o grab se
  o loop travar; o kernel solta o grab se o processo morrer.

## Como testar aqui (sem hardware)

```sh
PYTHONPATH=src python3 -m pytest tests/platform -q
PYTHONPATH=src python3 -m mypy --strict src/nvda_linux/core src/nvda_linux/speech \
    src/nvda_linux/inputCore src/nvda_linux/braille src/nvda_linux/__main__.py
python3 -m ruff check src/nvda_linux/core src/nvda_linux/speech src/nvda_linux/inputCore \
    src/nvda_linux/braille src/nvda_linux/__main__.py tests/platform
PYTHONPATH=src python3 -m pytest tests/platform/test_latency.py -q -s   # mostra as latências
```

Os testes usam fakes: teclados evdev com fd real (pipe) no `add_reader`,
uinput, conexão D-Bus do KeyboardMonitor, BrlAPI, liblouis, módulo
`speechd`, e um **servidor SSIP falso num socket Unix real** (o cliente SSIP
é exercitado de verdade). `test_latency.py` mede tecla → `cancel()` em três
níveis e falha acima de 30 ms; nesta máquina: ~0,03 ms (síncrono), ~0,1 ms
(evdev → driver) e ~0,3 ms (evdev → `CANCEL self` recebido pelo servidor).

## Como testar numa máquina Linux real

1. Dependências (exemplo Debian/Ubuntu; Fedora/Arch: ver `packaging/`):
   ```sh
   sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core python3-evdev \
       python3-dbus-next python3-numpy speech-dispatcher speech-dispatcher-espeak-ng \
       espeak-ng libxkbcommon0 brltty python3-brlapi python3-louis pipewire-bin
   ```
   PyGObject precisa ser ≥ 3.50 para o loop GLib (senão roda em asyncio puro,
   e a SEMÂNTICA fica sem eventos AT-SPI2).
2. Permissões de teclado (backend evdev):
   ```sh
   sudo install -m 644 packaging/udev/99-nvda-input.rules /etc/udev/rules.d/
   sudo install -m 644 packaging/udev/nvda-linux-uinput.conf /etc/modules-load.d/
   sudo modprobe uinput && sudo udevadm control --reload && sudo udevadm trigger
   sudo usermod -aG input $USER     # e entre de novo na sessão
   ```
3. Variáveis de acessibilidade para a sessão:
   `cp packaging/env/50-nvda-linux-a11y.conf ~/.config/environment.d/` e, no
   GNOME, `gsettings set org.gnome.desktop.interface toolkit-accessibility true`.
4. Diagnóstico: `PYTHONPATH=src python3 -m nvda_linux --check-permissions`.
5. **Antes do primeiro teste com grab**, tenha um segundo meio de acesso (SSH,
   outro TTY) e decore **Ctrl+Alt+Shift+Esc**. Rode num terminal:
   `PYTHONPATH=src python3 -m nvda_linux --debug --no-semantics` e verifique:
   - bips de partida; `Insert+T` engolido (nada chega ao aplicativo);
   - duplo toque em Insert (ou Caps Lock com
     `keyboard.useCapsLockAsNVDAModifierKey = true`) repassa a tecla;
   - digitação normal funciona e ecoa caracteres (ABNT2: "ç" correto);
   - `Insert+1` liga a ajuda de entrada; `Insert+F2` + uma tecla a repassa;
   - Ctrl interrompe a fala; Ctrl+Alt+Shift+Esc encerra e devolve o teclado;
   - `kill -9 <pid>`: o teclado volta na hora (o kernel solta o grab).
   O watchdog é um thread do mesmo processo: ele age quando o *loop* trava
   (coberto por `test_core.py`), não quando o processo inteiro é parado
   com SIGSTOP.
6. GNOME 48+ no Wayland: confira no log `Backend de teclado: keyboardMonitor`.
   Force o outro com `--keyboard-backend evdev` para comparar.
7. Fala: com o speech-dispatcher ativo, confira `Speech Dispatcher conectado
   (transporte native)`. Sem ele, `--synth espeak`. Piper:
   `speech.piper.model = "/caminho/voz.onnx"` em `nvda.toml`.
8. Braille: com o BRLTTY rodando e uma linha conectada, confira
   `Linha braille: <driver> com N células`; teste rolagem e roteamento.
9. Serviço: `./packaging/install-user.sh --system` e
   `systemctl --user enable --now nvda-linux.service`.

## Limitações conhecidas

- **Validado só com fakes aqui**: `gi` está quebrado nesta máquina e não há
  speech-dispatcher, áudio, D-Bus de sessão, `/dev/input` nem BRLTTY. O
  caminho GLib do loop foi testado com uma política falsa; o comportamento
  real do `GLibEventLoopPolicy` (sinais, `add_reader`) precisa de máquina real.
- **KeyboardMonitor**: implementado pela especificação do XML do mutter/niri,
  sem teste real. Pontos a confirmar: (a) se o mutter restringe quais clientes
  podem chamar a interface (se recusar, o backend cai para o evdev); (b) se o
  par `(keysym, máscara)` de Shift+letra casa com a letra minúscula ou
  maiúscula (registramos as duas); (c) os grabs de teclas sem NVDA (H, K, B
  no modo de navegação) são recalculados a cada 300 ms e logo após cada
  script; uma troca de modo feita fora de um script pode levar até 300 ms
  para valer. Sem `/dev/uinput`, `send_through` não funciona nesse backend.
  Se o loop travar, o watchdog não consegue soltar esses grabs (a chamada
  D-Bus depende do loop).
- **evdev**: o caractere digitado usa o layout XKB detectado na partida
  (`keyboard.xkbLayout` para forçar); troca de layout em tempo real (vários
  grupos) e teclas mortas/compose não são acompanhadas. Outro programa com
  grab exclusivo (keyd, kmonad, ydotoold) impede o grab; o leitor avisa e
  segue em modo monitor.
- **Fala**: `NOW` retoma o enunciado interrompido desde o início (o NVDA
  retoma do último índice). O driver Piper carrega o modelo a cada
  enunciado (latência maior); prefira o Piper como módulo do speechd.
  `sounddevice` não foi exercitado (sem PortAudio aqui).
- **Shift**: o NVDA pausa a fala ao *pressionar* Shift; aqui a pausa é no
  *toque* (pressionar e soltar sem outra tecla), para não pausar a fala a
  cada letra maiúscula digitada.
- **Braille**: sem tabela liblouis configurada, o texto vai cru e o BRLTTY
  aplica a tabela de texto dele; não há cursor piscante nem
  "amarrar à revisão" (é papel da SEMÂNTICA decidir o que mostrar).
- **mypy**: o `pyproject.toml` fixa `python_version = "3.11"`, e os stubs do
  NumPy 2.x usam sintaxe 3.12; por isso o NumPy é importado via
  `optional_import` (há também um gerador de senoide em Python puro). Ver
  `docs/requests/platform.md`.
