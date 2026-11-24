# Divisão de trabalho do nvda-linux

Dois desenvolvedores trabalham em paralelo na mesma pasta. **Cada um só cria e edita arquivos da sua área.** Ler qualquer arquivo é permitido; escrever fora da sua área não é.

## Arquivos do coordenador (ninguém edita)

- `src/nvda_linux/contracts.py`, `src/nvda_linux/services.py`, `src/nvda_linux/__init__.py`
- `pyproject.toml`, `docs/OWNERSHIP.md`
- Precisa mudar um contrato ou adicionar dependência? Escreva o pedido em `docs/requests/<equipe>.md` (sua área) e siga com um contorno local.

## Equipe PLATAFORMA (Dev A): sistema, entrada e saída

- `src/nvda_linux/__main__.py`
- `src/nvda_linux/core/` (loop, app, config, log, watchdog)
- `src/nvda_linux/speech/` (SynthDriver, SpeechDispatcherDriver, espeak/piper, manager, tones)
- `src/nvda_linux/braille/` (BrlAPI, liblouis)
- `src/nvda_linux/inputCore/` (backends KeyboardMonitor e evdev/uinput, gestos, dispatcher, layouts, gestures.ini)
- `packaging/` (systemd --user, udev, env de acessibilidade, deb/rpm/AUR)
- `tests/platform/`, `docs/platform/`, `docs/requests/platform.md`

## Equipe SEMÂNTICA (Dev B): acessibilidade e comportamento do leitor

- `src/nvda_linux/NVDAObjects/` (LinuxNVDAObject, roles, states, texto)
- `src/nvda_linux/treeInterceptors/` (VirtualBuffer, Browse/Focus Mode, quick nav, lista de elementos, tabelas)
- `src/nvda_linux/scripts/` (bootstrap, chain, globalCommands, eventHandler, foco, revisão, navegação por objetos)
- `src/nvda_linux/appModules/`, `src/nvda_linux/globalPlugins/`, `src/nvda_linux/addons/` (carregador de add-ons)
- `src/nvda_linux/gui/` (GTK 4: menu NVDA, configurações, Visualizador de Fala)
- `tests/semantics/`, `docs/semantics/`, `docs/requests/semantics.md`

## Pontos de encontro

- Tudo passa por `contracts.py` + `services.py`.
- A PLATAFORMA chama `nvda_linux.scripts.bootstrap.start()/stop()` em `core/app.py`.
- A PLATAFORMA, a cada gesto, percorre `services.script_chain().chain()` e chama o primeiro script encontrado; se nenhum, faz passthrough.
- A SEMÂNTICA nunca acessa evdev, speechd ou brlapi direto: usa `services.speech()`, `services.tones()`, `services.braille()`, `services.config()`, `services.dispatcher()`.
- Testes de cada equipe usam fakes próprios dos contratos, dentro da sua pasta de testes.
- `git`: não faça commit; o coordenador integra.
