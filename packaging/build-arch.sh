#!/bin/sh
# Gera dist/nvda-linux-<versão>-<rel>-any.pkg.tar.zst (Arch Linux e derivadas).
#
# Uso (numa máquina Arch, como usuário comum; o makepkg não roda como root):
#   sudo pacman -S --needed base-devel python-build python-installer \
#                           python-setuptools python-wheel
#   ./packaging/build-arch.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
NAME="nvda-linux-$VERSION"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ROOT/dist"

# Tarball de código-fonte ao lado do PKGBUILD (source=("$pkgname-$pkgver.tar.gz")).
mkdir "$WORK/$NAME"
tar -C "$ROOT" \
    --exclude=./dist --exclude=./.git --exclude='*/__pycache__' \
    --exclude=./.pytest_cache --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude='*.egg-info' --exclude=./build --exclude=./.venv \
    -cf - . | tar -C "$WORK/$NAME" -xf -
tar -C "$WORK" -czf "$WORK/$NAME.tar.gz" "$NAME"
rm -rf "${WORK:?}/$NAME"
cp "$ROOT/packaging/arch/PKGBUILD" "$ROOT/packaging/arch/nvda-linux.install" "$WORK/"

(cd "$WORK" && PKGDEST="$WORK" makepkg -f --nodeps --noconfirm)
cp "$WORK"/nvda-linux-*.pkg.tar.zst "$ROOT/dist/"

echo
echo "Pronto:"
ls -l "$ROOT"/dist/*.pkg.tar.zst
