#!/bin/sh
# Gera dist/nvda-linux-<versão>-1.<dist>.noarch.rpm na distribuição em que rodar.
# O RPM fica preso à versão do Python da distribuição (python(abi)), então
# gere um por versão: Fedora 45 -> .fc45; openSUSE Tumbleweed -> .opensuse.
#
# Fedora:
#   sudo dnf install rpm-build pyproject-rpm-macros systemd-rpm-macros python3-devel \
#                    python3-setuptools python3-wheel python3-pip
# openSUSE:
#   sudo zypper install rpm-build python-rpm-macros systemd-rpm-macros python3-devel \
#                       python3-pip python3-setuptools python3-wheel
# Depois:
#   ./packaging/build-rpm.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
NAME="nvda-linux-$VERSION"
TOP=$(mktemp -d)
trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP/SOURCES" "$ROOT/dist"

# Tarball de código-fonte (mesmo conteúdo do build-packages.sh).
mkdir "$TOP/$NAME"
tar -C "$ROOT" \
    --exclude=./dist --exclude=./.git --exclude='*/__pycache__' \
    --exclude=./.pytest_cache --exclude=./.mypy_cache --exclude=./.ruff_cache \
    --exclude='*.egg-info' --exclude=./build --exclude=./.venv \
    -cf - . | tar -C "$TOP/$NAME" -xf -
tar -C "$TOP" -czf "$TOP/SOURCES/$NAME.tar.gz" "$NAME"

# O openSUSE não põe a distribuição no nome do pacote; marcamos para não
# confundir com o do Fedora (.fc45).
if grep -qi suse /etc/os-release 2>/dev/null; then
    rpmbuild --define "_topdir $TOP" --define "dist .opensuse" -bb "$ROOT/packaging/rpm/nvda-linux.spec"
else
    rpmbuild --define "_topdir $TOP" -bb "$ROOT/packaging/rpm/nvda-linux.spec"
fi
cp "$TOP"/RPMS/noarch/*.rpm "$ROOT/dist/"

echo
echo "Pronto:"
ls -l "$ROOT"/dist/*.rpm
