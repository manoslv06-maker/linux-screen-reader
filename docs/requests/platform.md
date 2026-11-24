# Pedidos da equipe PLATAFORMA

Pedidos ao coordenador (contratos, `pyproject.toml`) e avisos para a
SEMÂNTICA. Cada item diz qual contorno está em uso enquanto isso.

## Ao coordenador

### P1. mypy: `python_version = "3.11"` quebra a análise dos stubs do NumPy

O NumPy 2.x usa `type X = ...` (PEP 695) nos `.pyi`; com
`[tool.mypy] python_version = "3.11"` o mypy aborta com *"Type statement is
only supported in Python 3.12 and greater"* em qualquer módulo que importe
`numpy`.

Pedido (qualquer um):

```toml
[tool.mypy]
python_version = "3.12"
```

ou

```toml
[[tool.mypy.overrides]]
module = ["numpy", "numpy.*"]
follow_imports = "skip"
```

Contorno: `speech/tones.py` importa o NumPy via
`core.compat.optional_import("numpy")` (tipado como `Any`) e tem um gerador
de senoide em Python puro como reserva. Os testes de tipos de
`tests/platform` só passam com `--python-version 3.12` pelo mesmo motivo.

### P2. `GestureDispatcher`: expor o que a plataforma já oferece

O `InputManager` tem, além do contrato:

- `process_gesture(gesture, *, suppressed=None) -> bool` — usado pelo braille
  e útil para a SEMÂNTICA emular gestos;
- `gesture_map: GestureMap` — o `gestures.ini` do usuário (a SEMÂNTICA já lê
  via `getattr`);
- `refresh_grabs()` — ver P3;
- `pass_next: bool`.

Pedido: acrescentar `process_gesture` e `gesture_map` ao Protocol. Contorno:
`getattr(services.dispatcher(), ...)`.

### P3. Aviso de troca de modo para os grabs do KeyboardMonitor

No GNOME/Wayland o compositor decide antes da tecla se ela é engolida. Para
teclas sem NVDA (H, K, B... no modo de navegação), a plataforma sonda a
cadeia a cada 300 ms e logo após cada script. Uma troca de modo
navegação/foco que *não* venha de um script (foco mudou sozinho, carga de
página) pode levar até 300 ms para valer.

Pedido: incluir `refresh_grabs()` no Protocol `GestureDispatcher`; a
SEMÂNTICA chama ao trocar de modo/treeInterceptor. Contorno: já existe em
`InputManager.refresh_grabs()` (use `getattr(services.dispatcher(),
"refresh_grabs", None)`), mais o polling de 300 ms como rede de segurança.

### P4. Serviço `"app"` e `ConfigStore.subscribe`

- A plataforma registra `services.register("app", Application)` com
  `request_exit(code=0)`. Não há getter em `services.py`; a SEMÂNTICA lê
  `services._registry["app"]`. Pedido: `services.app()` + Protocol
  `AppControl` com `request_exit`.
- `TomlConfigStore.subscribe(prefixo, ouvinte) -> cancelar` avisa mudanças
  (inclusive troca de perfil). Pedido: incluir no Protocol `ConfigStore`
  (útil para a GUI).

### P5. `SpeechOutput.add_listener` para o Visualizador de Fala

`SpeechManager.add_listener(fn) -> cancelar` recebe o texto de cada fala.
Pedido: incluir no Protocol (opcional). Contorno: `getattr`.

## Para a SEMÂNTICA (sem mudança de contrato)

1. **NVDA+1 e NVDA+F2 são embutidos** no despachante e tratados antes da
   cadeia. `set_input_help()` é silencioso (quem chama anuncia); o NVDA+1
   embutido anuncia "Ajuda de entrada ativada/desativada". Na ajuda de
   entrada a plataforma só *consulta* `get_script` e fala
   `"<gesto>: <1ª linha da docstring>"`, sem executar.
2. **Layout Laptop**: ligue os comandos de `inputCore/layouts.py`
   (`CORE_COMMANDS`) pelo gesto **Desktop**; no Laptop o despachante tenta
   primeiro o equivalente Desktop (`gesture.extra["laptop_identifier"]`
   guarda o original). Gestos só do Laptop podem continuar com
   `kb(laptop):...` via `extra["normalized_identifiers"]`.
3. **Eco de teclado**: a plataforma já ecoa caracteres/palavras digitados e
   interrompe a fala nas teclas repassadas (`keyboard.speakTyped*`,
   `keyboard.speechInterruptFor*`). Não ecoe de novo a partir de
   `text-changed` do AT-SPI2. Ctrl sozinho cala a fala; toque em Shift pausa.
4. **Interrupção ao executar script**: padrão é cancelar a fala antes do
   script. Para não cancelar (ex.: comandos de leitura contínua), defina no
   script `speechEffectWhenExecuted = None`.
5. **Braille**: rolagem (`fwinlt`/`fwinrt`) é tratada pela plataforma.
   `br(brltty):routing` chega com `extra["routing_index"]` (célula) e
   `extra["text_offset"]` (índice no texto passado a `show_text`, já
   considerando a janela; `None` se for mensagem).
6. **SpeechCommand** aceitos: `pitch`/`rate` (deslocamento em %, 0 volta ao
   normal), `break` (ms), `spell` (texto), `beep` (`hz` ou `"hz,ms"`), o
   extra `lang`/`language` (código de idioma) e `index` (inteiro, avisado por
   `speech().add_index_listener(fn)` quando a fala chega nele; nunca depois
   de `cancel()`).
7. **Saída**: `services._registry["app"].request_exit()` (ou SIGTERM) encerra
   limpo.
