# nvda-linux — equipe SEMÂNTICA

Acessibilidade e comportamento do leitor: tudo que lê a árvore AT-SPI2,
decide o que falar e responde a gestos. A fala, os bipes, o braille, o
teclado e o loop são da PLATAFORMA e só são usados por `services.*()`.

## Mapa dos módulos

| Pacote | NVDA equivalente | O que faz |
|---|---|---|
| `NVDAObjects/_atspi.py` | (IAccessible/UIA) | Única camada que toca `gi.repository.Atspi`. Import protegido, `call()` que nunca levanta, normalização de enums, `Collection`, `EventBridge`. |
| `NVDAObjects/controlTypes.py` | `controlTypes` | `Role`, `State`, `OutputReason`, rótulos em pt-BR. |
| `NVDAObjects/roleMapping.py` | — | Mapeamento completo `Atspi.Role` / `Atspi.StateSet` → `Role` / `State`. |
| `NVDAObjects/base.py` | `NVDAObjects.NVDAObject` | `LinuxNVDAObject`: nome, papel, estados, valor, descrição, hierarquia, posição, atalho, `location`, `app_module`, `make_text_info`, ações. Cache leve + fábrica com classes overlay. |
| `NVDAObjects/textInfos.py` | `textInfos.offsets` | `OffsetsTextInfo` sobre `Atspi.Text` ou texto local (caractere, palavra, linha, parágrafo, seleção, cursor). |
| `NVDAObjects/behaviors.py` | `NVDAObjects.behaviors` | `EditableText` (setas falam char/palavra/linha esperando `text-caret-moved`; seleção) e `Terminal`. |
| `scripts/scriptHandler.py` | `scriptHandler`, `baseObject` | `@script`, `ScriptableObject`, normalização de gestos, `gestures.ini`. |
| `scripts/eventHandler.py` | `eventHandler` | Ouvintes AT-SPI2, coalescência, cadeia de eventos. |
| `scripts/chain.py` | `inputCore` (parte) | `ScriptChainSource` na ordem do NVDA, isolamento de exceções. |
| `scripts/globalCommands.py` | `globalCommands` | Comandos globais Desktop/Laptop. |
| `scripts/focus.py` | `api` + `doPreGainFocus` | `FocusTracker`: foco, primeiro plano, navegador, revisão, ancestrais. |
| `scripts/objectSpeech.py`, `ui.py` | `speech`, `ui` | Como objetos são falados; saída via serviços. |
| `scripts/bootstrap.py` | `core.main` (parte) | `start()` / `stop()` chamados pela PLATAFORMA. |
| `treeInterceptors/virtualBuffer.py` | `virtualBuffers` | Buffer plano do `DOCUMENT_WEB`, índices por tipo (bisect), tabelas, atualização incremental. |
| `treeInterceptors/browseMode.py` | `browseMode` | Browse/Focus Mode, teclas rápidas, tabelas, ler tudo, bipes. |
| `treeInterceptors/elementsList.py` | `ElementsListDialog` (dados) | Lista de elementos sem GUI. |
| `appModules/` | `appModules` | Base + `firefox`, `chromium`, `gnome_terminal`. |
| `globalPlugins/` | `globalPluginHandler` | Base dos plugins globais. |
| `addons/` | `addonHandler` | Carregador de add-ons (ver `ADDONS.md`). |
| `gui/` | `gui` | GTK 4 (import protegido): menu NVDA, configurações, Visualizador de Fala, Lista de Elementos, gerenciador de add-ons. |

## Fluxos principais

**Evento AT-SPI2.** O `EventBridge` recebe o evento no loop GLib e o
entrega ao `EventHandler`, que enfileira e processa em lote 20 ms depois:
invalida o cache dos objetos afetados, deduplica (mesmo tipo + objeto) e
mantém só o último foco e a última ativação de janela. Cada evento vira um
evento NVDA (`gainFocus`, `foreground`, `nameChange`, `stateChange`,
`valueChange`, `caret`, `textChange`, `descriptionChange`, `childrenChanged`,
`documentLoadComplete`) e percorre globalPlugins → appModule →
treeInterceptor → `NVDAObject.event_*`, cada manipulador com
`(obj, next_handler)`. Exceções de um elo vão ao log e a cadeia segue.

**Foco.** `gain_focus` ignora objetos mortos, eventos atrasados (sem
`FOCUSED`) e duplicados; cria o treeInterceptor do documento web se for o
caso; o `FocusManager` calcula os ancestrais recém-entrados (diálogo,
agrupamento com nome, ponto de referência...), move o navegador e troca o
perfil de configuração ao mudar de aplicativo (`profileTriggers.app.<app>`).

**Gesto.** A PLATAFORMA chama `services.script_chain().chain()` e executa o
primeiro script. A cadeia é globalPlugins → appModule → treeInterceptor →
foco → globalCommands. Cada provedor está num `SafeProvider` que isola
exceções e copia a descrição do script para a docstring (a ajuda de entrada
da PLATAFORMA lê a docstring). `gesture.extra["bindings"]` (do
`gestures.ini`, seção `módulo.Classe` como no NVDA) tem precedência; o
layout vem de `gesture.extra["layout"]` ou de `services.dispatcher().layout`.

**Browse Mode.** Ao focar um `DOCUMENT_WEB`/`DOCUMENT_FRAME`, o
`TreeInterceptorManager` cria um `BrowseModeTreeInterceptor` para o
documento mais externo. O `VirtualBuffer` renderiza o documento: objetos com
`Atspi.Text` contribuem com o texto e cada `U+FFFC` é substituído pelo filho
embutido; blocos ficam em linhas próprias, controles viram folhas. Páginas
acima de `browseMode.maxNodes` são cortadas e os elementos navegáveis
restantes vêm em uma chamada `Atspi.Collection`. `children-changed` e
`text-changed` agendam `update_subtree` (150 ms, coalescido) que
re-renderiza só a subárvore e desloca o resto; se não der, reconstrói.

## Comandos

Desktop (teclado numérico) e Laptop seguem o Guia do Usuário do NVDA e a
tabela `inputCore/layouts.py` da PLATAFORMA.

| Comando | Desktop | Laptop |
|---|---|---|
| Objeto atual / pai / anterior / próximo / primeiro filho | NVDA+5/8/4/6/2 (num.) | NVDA+Shift+O / ↑ / ← / → / ↓ |
| Navegador ao foco; foco ao navegador; ativar | NVDA+num−; NVDA+Shift+num−; NVDA+numEnter | NVDA+Backspace; NVDA+Shift+Backspace; NVDA+Enter |
| Revisão linha ant./atual/próx. | num 7/8/9 | NVDA+↑ / NVDA+Shift+. / NVDA+↓ |
| Revisão palavra ant./atual/próx. | num 4/5/6 | NVDA+Ctrl+← / NVDA+Ctrl+. / NVDA+Ctrl+→ |
| Revisão caractere ant./atual/próx. (2×: soletra; 3×: código) | num 1/2/3 | NVDA+← / NVDA+. / NVDA+→ |
| Revisão topo / fim / início e fim da linha / ler tudo | Shift+num7/num9/num1/num3, num+ | NVDA+Ctrl+Home/End, NVDA+Home/End, NVDA+Shift+A |
| Ler tudo | NVDA+↓ | NVDA+A |
| Linha atual (2×: soletra) | NVDA+↑ | NVDA+L |
| Seleção | NVDA+Shift+↑ | NVDA+Shift+S |
| Barra de status | NVDA+End | NVDA+Shift+End |
| Título (2×: soletra), foco, janela, hora/data, formatação | NVDA+T, NVDA+Tab, NVDA+B, NVDA+F12, NVDA+F | iguais |
| Ajuda de entrada, passar tecla, modo dormir | NVDA+1, NVDA+F2, NVDA+Shift+Z | iguais |
| Menu NVDA, sair | NVDA+N, NVDA+Q | iguais |
| Browse/Focus, lista de elementos, recarregar, letra única | NVDA+Espaço, NVDA+F7, NVDA+F5, NVDA+Shift+Espaço | iguais |
| Teclas rápidas (Shift volta) | H, 1–6, K, U, V, F, T, B, E, L, I, G, D, C, X, R, Q, S, M, O | iguais |
| Tabelas | Ctrl+Alt+setas | iguais |
| Braille | roteamento `br(brltty):routing` move o cursor / ativa | igual |

NVDA+1, NVDA+F2 e Ctrl/Shift sozinhos são tratados primeiro pelo
despachante da PLATAFORMA; os scripts equivalentes daqui ficam como reserva.

## Configuração lida

Chaves da PLATAFORMA (`core/config.py`): `keyboard.keyboardLayout`,
`keyboard.speakTyped*`, `browseMode.*` (`maxLineLength`, `linesPerPage`,
`autoPassThroughOnFocusChange`, `autoPassThroughOnCaretMove`,
`passThroughAudioIndication`, `trapNonCommandGestures`,
`autoSayAllOnPageLoad`, `autoFocusFocusableElements`), `speech.*`,
`braille.*`. Chaves só da SEMÂNTICA, com padrão em
`scripts/configUtils.SEMANTIC_DEFAULTS`: `browseMode.enableOnPageLoad`,
`browseMode.maxNodes`, `browseMode.updateDelayMs`,
`presentation.report{KeyboardShortcuts,ObjectPositionInformation,ObjectDescriptions,DynamicContentChanges}`,
`reviewCursor.{followFocus,followCaret,simpleReviewMode}`,
`documentFormatting.reportTableCellCoords`, `general.askToExit`,
`addons.nvdaCompatAliases`, `profileTriggers.app.<appModule>`.

## Testes nesta máquina (sem AT-SPI2)

```sh
PYTHONPATH=src python3 -m pytest tests/semantics -q
PYTHONPATH=src python3 -m mypy --strict src/nvda_linux/{NVDAObjects,treeInterceptors,scripts,appModules,globalPlugins,addons,gui}
python3 -m ruff check src/nvda_linux/{NVDAObjects,treeInterceptors,scripts,appModules,globalPlugins,addons,gui} tests/semantics
```

`tests/semantics/fake_atspi.py` imita a API do `Atspi.Accessible` (Text,
Action, Component, Value, Table, Collection; `kill()` simula objeto morto) e
`pages.py` monta uma página web (landmark, lista de links, cabeçalhos,
parágrafo com link embutido, formulário, tabela, imagem, citação), um
diálogo GTK e um terminal. `fakes.py` tem os serviços da PLATAFORMA.

## Testar num Linux real

1. Pacotes (Debian/Ubuntu): `python3-gi gir1.2-atspi-2.0 at-spi2-core
   gir1.2-gtk-4.0 speech-dispatcher brltty`. Fedora: `python3-gobject
   at-spi2-core gtk4`.
2. Acessibilidade ligada na sessão: `gsettings set
   org.gnome.desktop.interface toolkit-accessibility true`; o pacote da
   PLATAFORMA exporta `GTK_MODULES=gail:atk-bridge`, `QT_ACCESSIBILITY=1`,
   `ACCESSIBILITY_ENABLED=1`. O `bootstrap` liga
   `org.a11y.Status.ScreenReaderEnabled` (necessário para Chromium/Electron).
3. Rode `nvda-linux` (ou `python3 -m nvda_linux --debug`) e feche o Orca.
4. Roteiro manual:
   - **Firefox**: abra uma página com cabeçalhos; ao carregar, o título e o
     conteúdo devem ser lidos. Teste H/Shift+H, K, F, T, B, D, 1–6; setas
     linha a linha; Tab até um campo (bipe agudo = modo de foco) e Tab até
     um botão (bipe grave); NVDA+Espaço; NVDA+F7; Ctrl+Alt+setas numa
     tabela; Enter num link.
   - **Chromium/Chrome**: o mesmo; se a árvore vier vazia, inicie com
     `--force-renderer-accessibility`.
   - **gedit / GNOME Text Editor / diálogos GTK**: setas falam caractere,
     palavra e linha; Shift+setas falam a seleção; Tab anuncia agrupamentos
     e botões ("OK botão Alt+O"); NVDA+numpad8/2/4/6 navegam por objetos.
   - **GNOME Terminal**: a saída nova é falada; setas para cima falam a
     linha do histórico.
   - **Visualizador de Fala**: NVDA+N → Visualizador de Fala.
5. Para inspecionar a árvore AT-SPI2 use o `accerciser`.

## Limitações conhecidas

- O AT-SPI2 real, o Firefox, o Chromium e o GTK 4 não existem nesta máquina:
  tudo foi exercitado com fakes. A ordem exata de eventos de cada navegador
  (ex.: foco no quadro antes do documento) pode exigir ajustes nos
  appModules.
- Ler tudo não acompanha o índice da fala: o contrato não tem marcadores de
  índice, então o cursor vai para a última linha enfileirada e o Ctrl não
  devolve o cursor ao ponto interrompido (pedido em `docs/requests/semantics.md`).
- Seleção de texto no modo de navegação (Shift+setas) e cópia não estão
  implementadas.
- O buffer usa a ordem dos filhos para casar `U+FFFC` com objetos embutidos
  (como fazem Firefox e Chromium); um toolkit que não siga isso precisaria
  da interface `Hypertext`.
- Tabelas de leiaute são detectadas só pelo atributo `layout-guess` do
  Firefox.
- A GUI roda no mesmo processo; inspecionar as próprias janelas depende da
  reentrância do libatspi no contexto GLib principal (o mesmo esquema do
  Orca). Se travar, a alternativa é a GUI em subprocesso.
- No Wayland, comandos sem a tecla NVDA no Browse Mode dependem dos "grabs"
  da PLATAFORMA (`refresh_grabs`, chamado ao trocar de modo/foco).
- O eco de digitação é da PLATAFORMA; num campo de senha ela precisa
  consultar `services.focus().focus_is_protected()` (pedido aberto).
