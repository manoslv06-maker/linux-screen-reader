#!/bin/sh
# Instalação local (sem pacote) para testar numa máquina real.
#   ./packaging/install-user.sh          # instala para o usuário atual
#   ./packaging/install-user.sh --system # também mostra os comandos sudo
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}

install -Dm644 "$HERE/systemd/nvda-linux.service" "$CONFIG/systemd/user/nvda-linux.service"
# A unidade aponta para /usr/bin/nvda-linux; ajusta para o executável deste usuário.
BIN=$(command -v nvda-linux || echo "$HOME/.local/bin/nvda-linux")
sed -i "s#^ExecStart=.*#ExecStart=$BIN#" "$CONFIG/systemd/user/nvda-linux.service"
install -Dm644 "$HERE/env/50-nvda-linux-a11y.conf" "$CONFIG/environment.d/50-nvda-linux-a11y.conf"
systemctl --user daemon-reload 2>/dev/null || true

echo "Instalado em $CONFIG (unidade systemd --user e environment.d)."
echo "Ativar:   systemctl --user enable --now nvda-linux.service"
if [ "${1:-}" = "--system" ]; then
    echo
    echo "Permissões de teclado (uma vez, como root):"
    echo "  sudo install -m 644 $HERE/udev/99-nvda-input.rules /etc/udev/rules.d/"
    echo "  sudo install -m 644 $HERE/udev/nvda-linux-uinput.conf /etc/modules-load.d/"
    echo "  sudo modprobe uinput && sudo udevadm control --reload && sudo udevadm trigger"
    echo "  sudo usermod -aG input \$USER   # e entre de novo na sessão"
fi
