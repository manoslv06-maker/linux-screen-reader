# Add-ons do nvda-linux

Os add-ons seguem a organização dos add-ons do NVDA: `globalPlugins` valem
em qualquer aplicativo, `appModules` só no aplicativo de mesmo nome.

## Onde ficam

```
~/.config/nvda-linux/addons/          ($XDG_CONFIG_HOME/nvda-linux/addons)
  meu_plugin/
    manifest.ini
    globalPlugins/
      __init__.py        # opcional; pode definir GlobalPlugin
      atalhos.py         # class GlobalPlugin(...)
    appModules/
      firefox.py         # class AppModule(...) para o Firefox
  addonsState.json       # add-ons desativados (gerado)
```

Cada add-on é importado como o pacote `nvdaAddons.<nome>`; importações
relativas entre os módulos do add-on funcionam.

## manifest.ini

Formato configobj do NVDA (aspas simples, duplas ou triplas):

```ini
name = meu_plugin
summary = "Meu complemento"
description = """Faz coisas úteis.
Em várias linhas."""
author = "Fulana <fulana@example.org>"
version = 1.0
url = https://example.org/meu_plugin
minimumNVDAVersion = 2024.1
lastTestedNVDAVersion = 2025.1
```

`name` aceita letras, números, `_`, `.` e `-` (até 100 caracteres).

## Nome do appModule

O nome do aplicativo no AT-SPI2 é normalizado: minúsculas, caracteres fora
de `[a-z0-9]` viram `_`, e há apelidos: `google_chrome`, `chrome`,
`chromium_browser`, `brave_browser`, `microsoft_edge` → `chromium`;
`firefox_esr` → `firefox`; `gnome_terminal_server` → `gnome_terminal`.
`appModules/gedit.py` vale para o gedit. Um appModule de add-on substitui o
embutido de mesmo nome (pode herdar dele).

## API pública

### Classes base

```python
from nvda_linux.globalPlugins import GlobalPlugin
from nvda_linux.appModules import AppModule
from nvda_linux.scripts.scriptHandler import script
```

- `GlobalPlugin()` — construído sem argumentos. Métodos opcionais:
  `terminate()`, `choose_overlay_classes(obj, cls_list)`.
- `AppModule(process_id, app_name, module_name)` — atributos `process_id`,
  `app_name`, `name`, `sleep_mode`. Métodos opcionais: `terminate()`,
  `should_use_browse_mode(doc) -> bool`, `choose_overlay_classes(obj, cls_list)`,
  `config_profile() -> str | None`.

### Scripts e gestos

```python
@script(description="Fala a versão", category="Meu plugin",
        gesture="kb:nvda+shift+v",          # vale nos dois layouts
        gestures=("kb:nvda+control+v",),
        desktop_gestures=("kb:nvda+numpad9",),  # só no layout Desktop
        laptop_gestures=("kb:nvda+shift+9",),   # só no layout Laptop
        bypass_input_help=False)
def script_version(self, gesture): ...
```

Também valem os mapas de classe `gesture_map = {"kb:nvda+x": "nomeDoScript"}`
e o `__gestures` do NVDA. Em instâncias: `bind_gesture(id, nome)`,
`remove_gesture(id)`. Identificadores seguem o contrato: `kb:` + modificadores
em ordem alfabética (`alt`, `control`, `nvda`, `shift`, `windows`) + tecla
(`downarrow`, `numpad8`, `f12`, `space`, `.`...). Scripts podem ser `async`.
O `gesture` recebido é um `contracts.InputGesture` (`identifier`,
`repeat_count`, `character`, `extra`). A descrição aparece na ajuda de
entrada (NVDA+1). O usuário pode remapear com o `gestures.ini` usando a
seção `<módulo>.<Classe>` (ex.: `[atalhos.GlobalPlugin]`).

Ordem da cadeia: globalPlugins → appModule → treeInterceptor (Browse Mode) →
objeto em foco → globalCommands. O primeiro script encontrado ganha.

### Eventos

Assinatura do NVDA: `event_<nome>(self, obj, next_handler)`. Chame
`next_handler()` para seguir com o comportamento padrão (por exemplo, falar
o foco); não chamar suprime o evento. Eventos com dados extras os recebem
como argumentos nomeados se o método aceitar (`**kwargs` ou os nomes):

| Evento | Quando | Extras |
|---|---|---|
| `gainFocus` | foco mudou | — |
| `foreground` | janela ativada | — |
| `nameChange`, `descriptionChange`, `valueChange` | propriedade mudou | — |
| `stateChange` | `object:state-changed:*` | `state_name`, `enabled` |
| `caret` | cursor de texto moveu | — |
| `textChange` | texto inserido/removido | `inserted`, `deleted` |
| `childrenChanged` | filhos mudaram | — |
| `documentLoadComplete` | página carregou | — |

### Objetos (`LinuxNVDAObject`)

Propriedades: `name`, `role` (`controlTypes.Role`), `states`
(`frozenset[State]`), `value`, `description`, `keyboard_shortcut`,
`position_info`, `heading_level`, `landmark`, `parent`, `children`,
`child_count`, `next`, `previous`, `first_child`, `last_child`, `location`,
`app_name`, `process_id`, `app_module`, `tree_interceptor`, `is_dead`,
`is_focusable`, `attributes`, `raw` (o `Atspi.Accessible`). Métodos:
`make_text_info(position)`, `set_focus()`, `do_action(i)`,
`find_descendants(roles=("PUSH_BUTTON",), states=(), count=0)`,
`invalidate_cache(*nomes)`. Os nomes camelCase do NVDA (`firstChild`,
`appModule`, `makeTextInfo`, `setFocus`...) também existem. Nada disso
levanta exceção com objeto morto.

`TextInfo`: `expand(TextUnit.LINE)`, `collapse()`, `move(unit, n)`, `text`,
`update_caret()`, `update_selection()`, `copy()`.

### Saída e estado

```python
from nvda_linux.scripts import ui, runtime
ui.message("texto")           # fala + braille
ui.speak(["a", "b"]); ui.speak_spelling("abc"); ui.beep(440, 50); ui.cancel()
rt = runtime.current()        # rt.focus.focus, rt.focus.navigator, rt.focus.review,
                              # rt.focus.foreground, rt.tree_interceptors, rt.addons
```

Para falar e bipar sempre use `ui` (ou `services.speech()`/`services.tones()`);
nunca speechd, evdev ou BrlAPI diretamente.

### Classes overlay

```python
from nvda_linux.NVDAObjects.base import LinuxNVDAObject
from nvda_linux.NVDAObjects.controlTypes import Role

class BotaoEspecial(LinuxNVDAObject):
    def event_gainFocus(self):
        ui.message("botão especial")

class AppModule(AppModule):
    def choose_overlay_classes(self, obj, cls_list):
        if obj.role == Role.BUTTON and obj.name == "Enviar":
            cls_list.insert(0, BotaoEspecial)
```

### Compatibilidade com add-ons do NVDA

Com `addons.nvdaCompatAliases = true` (padrão) existem os módulos
`globalPluginHandler`, `appModuleHandler`, `scriptHandler` (com os nomes de
argumento do NVDA, ex.: `bypassInputHelp`), `ui`, `api` (`getFocusObject`,
`getNavigatorObject`, `setNavigatorObject`, `getForegroundObject`,
`getReviewPosition`), `controlTypes`, `speech`, `tones`, `addonHandler`
(`initTranslation()` define `_` sem tradução) e `logHandler`. Código que usa
APIs do Windows continua sem funcionar.

## Ciclo de vida

- Ativar/desativar/remover/instalar sem reiniciar, pelo gerenciador (NVDA+N
  → Gerenciador de complementos) ou por código
  (`rt.addons.enable/disable/remove/install(caminho)`).
- Desativar chama `terminate()` dos plugins, retira os appModules do add-on
  (o aplicativo volta ao appModule embutido no próximo foco) e descarrega os
  módulos de `sys.modules`.
- `install()` aceita uma pasta ou um pacote `.nvda-addon` (zip). Caminhos
  absolutos, `..`, links simbólicos e pacotes acima de 200 MiB são recusados.
- Erros de importação, de construtor, de scripts e de eventos vão ao log e a
  `Addon.errors`; o leitor e os demais add-ons continuam.

## Exemplo completo

`~/.config/nvda-linux/addons/relogio/manifest.ini`:

```ini
name = relogio
summary = "Relógio falado"
version = 1.0
author = "Fulana"
```

`~/.config/nvda-linux/addons/relogio/globalPlugins/relogio.py`:

```python
import datetime

from nvda_linux.globalPlugins import GlobalPlugin as BaseGlobalPlugin
from nvda_linux.scripts import ui
from nvda_linux.scripts.scriptHandler import script


class GlobalPlugin(BaseGlobalPlugin):
    def __init__(self):
        super().__init__()
        self.focos = 0

    @script(description="Fala os segundos atuais", category="Relógio",
            gesture="kb:nvda+shift+f12")
    def script_segundos(self, gesture):
        ui.message(f"{datetime.datetime.now().second} segundos")

    def event_gainFocus(self, obj, next_handler):
        self.focos += 1
        next_handler()

    def terminate(self):
        ui.message(f"Relógio encerrado depois de {self.focos} focos")
```

`~/.config/nvda-linux/addons/relogio/appModules/firefox.py`:

```python
from nvda_linux.appModules.firefox import AppModule as FirefoxAppModule
from nvda_linux.scripts import ui


class AppModule(FirefoxAppModule):
    gesture_map = {"kb:nvda+shift+u": "url"}

    def script_url(self, gesture):
        ui.message("comando só do Firefox")
```

Para empacotar: `cd relogio && zip -r ../relogio.nvda-addon .`.
