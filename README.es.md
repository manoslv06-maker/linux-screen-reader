# linux-screen-reader

[English](README.md) · [Português](README.pt-BR.md) · **Español** · [中文](README.zh-CN.md) · [日本語](README.ja.md) · [Русский](README.ru.md) · [हिन्दी](README.hi.md)

Lector de pantalla para Linux con la ergonomía de NVDA: tecla NVDA (Insert o Bloq Mayús), distribuciones de teclado Desktop y Laptop, modo exploración y modo foco en la web, ayuda de entrada, `gestures.ini` y complementos. Escrito en Python 3, sobre AT-SPI2, evdev/uinput, Speech Dispatcher y BrlAPI.

El paquete y el comando se llaman `nvda-linux`. Este proyecto **no está afiliado a NV Access** ni al NVDA oficial; solo reproduce la forma de uso, para quien ya conoce NVDA en Windows.

> ⚠️ **Experimental (0.1.0.dev0).** Todavía no sirve para el uso diario. Funcionó en Fedora 45 con GNOME 51 en una máquina virtual, pero nunca lo ha usado a diario una persona ciega, y la voz aún no se ha escuchado en una máquina con sonido.

## Qué funciona ya

Probado de verdad (Fedora 45, GNOME 51, Firefox):

- voz a través de Speech Dispatcher, con eco de escritura ("asterisco" en campos de contraseña);
- captura del teclado por evdev/uinput, tecla NVDA, NVDA+T (título), anuncio del foco;
- modo exploración en Firefox: lectura de la página al cargar, H/B (siguiente encabezado/botón), flechas línea por línea.

Cubierto por pruebas automáticas (279), aún sin confirmar en una máquina real: "leer todo" con el cursor siguiendo la voz, navegación rápida completa (K, F, T, D, 1–6...), tablas, lista de elementos, braille, interfaz gráfica en GTK 4, complementos.

## Instalar

Requiere PyGObject 3.50 o más reciente: **Debian 13, Ubuntu 25.04 o más reciente, Fedora 41+, openSUSE Tumbleweed o Arch**. Ubuntu 24.04 todavía no sirve.

La forma más sencilla es el instalador único de la página [Releases](https://github.com/manoslv06-maker/linux-screen-reader/releases). Detecta la distribución y usa apt, dnf, zypper o pacman:

```sh
sh nvda-linux-instalador-0.1.0.dev0.run          # instala (pregunta antes de cambiar el grupo input)
sh nvda-linux-instalador-0.1.0.dev0.run --help
sh nvda-linux-instalador-0.1.0.dev0.run --uninstall
```

Para generar el instalador desde el código fuente, consulta [Generar los paquetes](#generar-los-paquetes).

### Antes de la primera prueba

El lector captura todo el teclado. Deja **un acceso de reserva** (SSH u otra consola de texto) y recuerda: **Ctrl+Alt+Mayús+Esc** cierra el lector y devuelve el teclado.

```sh
sudo usermod -aG input $USER      # después cierra la sesión y vuelve a entrar
nvda-linux --check-permissions    # diagnóstico
nvda-linux --debug                # se ejecuta en la terminal, con registro detallado
systemctl --user enable --now nvda-linux.service   # iniciar con la sesión (opcional)
```

El registro está en `~/.local/state/nvda-linux/nvda.log`.

## Desarrollo

```sh
pip install -e ".[dev,audio]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m mypy --strict src/nvda_linux
ruff check src tests
```

Las pruebas usan objetos falsos (no necesitan AT-SPI2, audio ni teclado). Ejecútalas en Linux: en Windows parte de ellas no funciona.

Documentación (en portugués):

- [docs/ROADMAP.md](docs/ROADMAP.md): fases y versiones previstas;
- [docs/platform/README.md](docs/platform/README.md): bucle, voz, teclado, braille y empaquetado;
- [docs/semantics/README.md](docs/semantics/README.md): AT-SPI2, eventos, modo exploración e interfaz gráfica;
- [docs/semantics/ADDONS.md](docs/semantics/ADDONS.md): complementos;
- [CLAUDE.md](CLAUDE.md): estado actual y próximos pasos.

### Generar los paquetes

Cada script se ejecuta en la distribución correspondiente y escribe en `dist/`:

| Script | Genera |
|---|---|
| `packaging/build-packages.sh` | `.deb` y el código fuente `.tar.gz` (Debian/Ubuntu) |
| `packaging/build-rpm.sh` | `.rpm` (Fedora u openSUSE, según la máquina) |
| `packaging/build-arch.sh` | `.pkg.tar.zst` (Arch, como usuario normal) |
| `packaging/build-installer.sh` | `nvda-linux-instalador-<versión>.run` con todo lo anterior |

## Licencia

[GPL-2.0-or-later](LICENSE).
