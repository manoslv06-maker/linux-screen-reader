# Pedidos da equipe SEMÂNTICA

Pedidos ao coordenador (contratos, `pyproject.toml`) e à PLATAFORMA. Cada
item diz qual contorno está em uso enquanto isso.

## Ao coordenador (contratos)

### S1. `FocusTracker.focus_is_protected() -> bool`

O eco de digitação é da PLATAFORMA (`SpeechManager.on_typed_character`) e
hoje fala os caracteres reais também em campos de senha. Pedido: acrescentar
ao Protocol `FocusTracker`:

```python
def focus_is_protected(self) -> bool:
    """O foco é um campo de senha (eco deve dizer "asterisco" ou nada)."""
```

Contorno: `FocusManager.focus_is_protected()` já existe; a PLATAFORMA pode
chamar `getattr(services.focus(), "focus_is_protected", lambda: False)()`.

### S2. Marcadores de índice na fala (ler tudo)

Para o "ler tudo" do NVDA (cursor acompanha a leitura e para onde o usuário
interrompeu), é preciso saber até onde a fala chegou. Pedido:
`SpeechCommand("index", n)` aceito na sequência e um retorno opcional em
`SpeechOutput`, por exemplo `add_index_listener(fn: Callable[[int], None])`
ou `speak(..., on_index=fn)`.

Contorno: o Browse Mode e o NVDA+↓ enfileiram as linhas e levam o cursor à
última linha enfileirada.

### S3. `services.app()` e Protocol `AppControl`

Mesmo pedido que o P4 da PLATAFORMA. Contorno: NVDA+Q usa
`services._registry["app"].request_exit()` e, sem ele, `SIGTERM`.

### S4. Chaves de configuração da SEMÂNTICA nos padrões

O `TomlConfigStore` só valida tipos de chaves presentes em `DEFAULTS`.
Pedido: incluir (com estes padrões) para que apareçam documentadas no TOML:

```toml
[browseMode]
enableOnPageLoad = true
maxNodes = 20000
updateDelayMs = 150

[presentation]
reportKeyboardShortcuts = true
reportObjectPositionInformation = true
reportObjectDescriptions = true
reportDynamicContentChanges = true

[documentFormatting]
reportTableCellCoords = true

[reviewCursor]
followFocus = true
followCaret = true
simpleReviewMode = true

[general]
askToExit = true

[addons]
nvdaCompatAliases = true

[profileTriggers.app]   # appModule -> nome do perfil, ex.: firefox = "web"
```

Contorno: `scripts/configUtils.SEMANTIC_DEFAULTS` dá o padrão quando a
chave não existe; gravar chaves novas já funciona.

## À PLATAFORMA

### S5. Visualizador de Fala: manter `SpeechManager.add_listener`

O Visualizador de Fala usa `services.speech().add_listener(fn)` quando
existe (o P5 de vocês) e então desliga a notificação própria da SEMÂNTICA
para não duplicar. Se `add_listener` sair, a alternativa é chamar
`nvda_linux.scripts.speechHooks.notify(sequence, priority)` dentro de
`speak()` e `speechHooks.set_platform_notifies(True)` uma vez. Sem nenhum
dos dois, o visualizador só mostra a fala da SEMÂNTICA.

### S6. Eco em campos de senha

Até o S1 entrar no contrato: em `on_typed_character`, consultar
`getattr(services.focus(), "focus_is_protected", lambda: False)()` e falar
"asterisco" (ou nada) quando verdadeiro.

### S7. Loop GLib

Os eventos do `Atspi.EventListener` e as janelas GTK 4 só funcionam se o
loop iterar o contexto GLib principal (a SEMÂNTICA não chama
`Atspi.event_main()`, que bloquearia). Também é esse contexto que permite a
reentrância do libatspi quando o leitor inspeciona as próprias janelas GTK.
Favor confirmar que `core/loop.py` roda o asyncio sobre o `GLib.MainContext`
padrão. O `bootstrap.start()` usa `asyncio.get_running_loop()` para agendar
o processamento dos eventos (`call_soon_threadsafe`).

### S8. Dependências de empacotamento

Runtime da SEMÂNTICA: `gir1.2-atspi-2.0` (ou `typelib-1_0-Atspi-2_0`),
`at-spi2-core`, `gir1.2-gtk-4.0` (GUI, opcional). Nenhuma dependência Python
nova.

## Informativo (sem mudança)

- Seguimos os avisos da PLATAFORMA: NVDA+1, NVDA+F2 e Ctrl/Shift sozinhos são
  dela (os scripts daqui ficam como reserva); a descrição dos scripts é
  copiada para a docstring do script devolvido; `gesture.extra["bindings"]`,
  `gesture.extra["layout"]` e `gesture_map.is_unbound` são respeitados;
  `refresh_grabs()` é chamado ao trocar de foco, de modo navegação/foco e de
  navegação por letra única; o roteamento braille usa
  `extra["text_offset"]`; o eco da SEMÂNTICA a partir de `text-changed` só
  roda se a fala não tiver `on_typed_character`.
