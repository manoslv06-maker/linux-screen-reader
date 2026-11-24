# Roadmap — NVDA para Linux

Atualizado em 23/11/2026. Fonte original: doc "Roadmap — NVDA para Linux".

O nvda-linux chega à versão 1.0 em agosto de 2027, em 8 fases e cerca de 35 semanas, com um leitor de tela em Python 3 que reproduz a ergonomia do NVDA no Linux. Estimativas para 1 a 2 desenvolvedores em tempo integral.

## Princípios

- **Zero Windows:** nada de win32api, comtypes, ctypes.windll, UIA, MSAA ou IAccessible2.
- **Paridade com o NVDA:** core, speech, braille, NVDAObjects, treeInterceptors, inputCore, addons e gui.
- **Wayland primeiro, X11 compatível:** nada de XRecord ou XGrabKey.
- **Resiliência:** toda chamada AT-SPI2/D-Bus trata objetos mortos e erros de conexão.
- **Latência:** fala interrompida em menos de 30 ms.
- **Código:** mypy --strict, asyncio para E/S, docstrings.

## Ajustes técnicos à especificação original

| Ponto | Situação | Decisão |
| --- | --- | --- |
| Loop com gbulb | gbulb arquivado; PyGObject 3.50+ integra asyncio | `gi.events.GLibEventLoopPolicy`, PyGObject ≥ 3.50 |
| Teclado só via evdev | at-spi2-core 2.55.90 + mutter têm `org.freedesktop.a11y.KeyboardMonitor` | KeyboardMonitor no GNOME; evdev + uinput nos demais |
| Flatpak | Sandbox dificulta `/dev/input` e o barramento de acessibilidade | Pacotes deb, rpm, AUR e pipx primeiro; Flatpak depois da 1.0 |

## Linha do tempo

| Fase | Período | Conteúdo |
| --- | --- | --- |
| 0 | 1 dez – 14 dez 2026 | Fundação: repositório, CI, config, log |
| 1 | 15 dez – 11 jan | Núcleo, loop e voz |
| 2 | 12 jan – 8 fev | Entrada e gestos |
| 3 | 9 fev – 22 mar | Objetos, foco e texto |
| 4 | 23 mar – 17 mai | Browse Mode na web |
| 5 | 18 mai – 7 jun | Braille |
| 6 | 8 jun – 12 jul | GUI, configurações e add-ons |
| 7 | 13 jul – 2 ago 2027 | Empacotamento e lançamento |

## Critérios de pronto por fase

- **Fase 0:** CI verde e `python -m nvda_linux --version` roda em GNOME, KDE e X11.
- **Fase 1:** fala "NVDA iniciado", toca um bip e cancela fala em menos de 30 ms.
- **Fase 2:** NVDA+T fala o título de teste, CapsLock duplo alterna maiúsculas, nenhuma tecla trava no GNOME e no KDE.
- **Fase 3:** dá para usar Configurações do GNOME, editor de texto, gerenciador de arquivos e terminal só com o leitor.
- **Fase 4:** página de 5.000 nós abre em Browse Mode em menos de 2 s; teclas rápidas funcionam no Firefox e no Chromium.
- **Fase 5:** foco, texto editável e Browse Mode corretos numa linha braille real ou no simulador do BRLTTY.
- **Fase 6:** add-on de exemplo instala, carrega, responde a um gesto e desinstala sem reiniciar.
- **Fase 7:** instalação limpa em Ubuntu, Fedora e Arch sem ajuda visual.

## Versões

| Versão | Depois da fase | O que o usuário consegue fazer | Para quem |
| --- | --- | --- | --- |
| 0.1 "Fala" | 2 | Ouvir teclas e atalhos NVDA | Desenvolvedores |
| 0.2 "Desktop" | 3 | Usar apps GTK e Qt, navegar por objetos, editar texto | Testadores técnicos |
| 0.3 "Web" | 4 | Navegar na web com Browse Mode | Testadores cegos convidados |
| 0.5 Beta | 6 | Braille, configurações, perfis e add-ons | Beta público |
| 1.0 | 7 | Instalar por pacote e usar no dia a dia | Todos |

## Riscos

| Risco | Mitigação |
| --- | --- |
| Compositor sem API de teclado para leitores de tela | Backend evdev + uinput como reserva; testes em GNOME, KDE e Sway |
| Grab do evdev travar o teclado | Soltar grab em exceção, watchdog, Ctrl+Alt+Shift+Esc encerra |
| Árvore AT-SPI2 lenta em páginas grandes | `Atspi.Collection`, cache, buffer incremental |
| Apps com pouca acessibilidade (Electron, Java, Qt) | AppModules específicos, `--force-renderer-accessibility` |
| asyncio do PyGObject experimental | Loop isolado em `core/loop.py`, versão mínima fixada |
| Sem testadores cegos cedo | Convidar usuários de NVDA a partir da 0.2 |
