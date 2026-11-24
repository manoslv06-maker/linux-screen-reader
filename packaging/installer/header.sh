#!/bin/sh
# Instalador do nvda-linux (arquivo único, autoextraível).
#   sh nvda-linux-instalador.run            instala
#   sh nvda-linux-instalador.run --yes      instala sem perguntas
#   sh nvda-linux-instalador.run --uninstall
#   sh nvda-linux-instalador.run --help
# Descobre a distribuição sozinho e usa apt, dnf, zypper ou pacman.
set -eu
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM
LINE=$(awk '/^__NVDA_LINUX_PAYLOAD__$/ { print NR + 1; exit }' "$0")
tail -n +"$LINE" "$0" | tar -xzf - -C "$TMP"
NVDA_INSTALLER_NAME=$(basename "$0") sh "$TMP/nvda-linux-instalador/install.sh" "$@"
exit $?
__NVDA_LINUX_PAYLOAD__
