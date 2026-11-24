#!/bin/sh
# Gera os arquivos de instalação em dist/:
#   - nvda-linux_<versão>_all.deb      (Debian 13+, Ubuntu 25.04+)
#   - nvda-linux-<versão>.tar.gz       (fonte para o PKGBUILD e o spec RPM)
#
# Uso (numa máquina Debian/Ubuntu):
#   sudo apt install build-essential debhelper dh-python pybuild-plugin-pyproject \
#                    python3-all python3-setuptools
#   ./packaging/build-packages.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
NAME="nvda-linux-$VERSION"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ROOT/dist"

# Cópia limpa do código (sem caches, dist/ nem ambientes virtuais).
mkdir "$WORK/$NAME"
tar -C "$ROOT" \
    --exclude=./dist --exclude=./.git --exclude='*/__pycache__' \
    --exclude=./.pytest_cache --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude='*.egg-info' --exclude=./build --exclude=./.venv \
    -cf - . | tar -C "$WORK/$NAME" -xf -

# 1. Tarball de código-fonte.
tar -C "$WORK" -czf "$ROOT/dist/$NAME.tar.gz" "$NAME"

# 2. Pacote .deb (binário, sem assinatura).
cp -r "$WORK/$NAME/packaging/debian" "$WORK/$NAME/debian"
chmod +x "$WORK/$NAME/debian/rules"
(cd "$WORK/$NAME" && dpkg-buildpackage -b -us -uc)
cp "$WORK"/nvda-linux_*_all.deb "$ROOT/dist/"

echo
echo "Pronto:"
ls -l "$ROOT/dist"
