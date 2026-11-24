#!/bin/sh
# Junta os pacotes de dist/ num instalador único e autoextraível:
#   dist/nvda-linux-instalador-<versão>.run
#
# Antes, gere os pacotes (cada um na sua distribuição):
#   build-packages.sh (.deb e .tar.gz), build-rpm.sh (Fedora e openSUSE), build-arch.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
OUT="$ROOT/dist/nvda-linux-instalador-$VERSION.run"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BUNDLE="$WORK/nvda-linux-instalador"
mkdir -p "$BUNDLE/packages"
cp "$ROOT/packaging/installer/install.sh" "$BUNDLE/install.sh"
chmod +x "$BUNDLE/install.sh"

# Código-fonte sempre novo (é dele que saem as reconstruções na máquina do usuário).
SRC="$WORK/nvda-linux-$VERSION"
mkdir "$SRC"
tar -C "$ROOT" \
    --exclude=./dist --exclude=./.git --exclude='*/__pycache__' \
    --exclude=./.pytest_cache --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude='*.egg-info' --exclude=./build --exclude=./.venv \
    -cf - . | tar -C "$SRC" -xf -
tar -C "$WORK" -czf "$BUNDLE/packages/nvda-linux-$VERSION.tar.gz" "nvda-linux-$VERSION"
cp "$BUNDLE/packages/nvda-linux-$VERSION.tar.gz" "$ROOT/dist/"
rm -rf "$SRC"

missing=""
for pattern in 'nvda-linux_*_all.deb' 'nvda-linux-*.fc*.noarch.rpm' \
               'nvda-linux-*.opensuse.noarch.rpm' 'nvda-linux-*.pkg.tar.zst'; do
    found=""
    for f in "$ROOT"/dist/$pattern; do
        [ -f "$f" ] && found="$f"
    done
    if [ -n "$found" ]; then
        cp "$found" "$BUNDLE/packages/"
    else
        missing="$missing $pattern"
    fi
done
[ -z "$missing" ] || echo "Aviso: faltam em dist/:$missing (essas distribuições cairão na reconstrução ou no erro)."

cat "$ROOT/packaging/installer/header.sh" > "$OUT"
tar -C "$WORK" -czf - nvda-linux-instalador >> "$OUT"
chmod +x "$OUT"

echo "Pronto: $OUT"
ls -l "$OUT"
