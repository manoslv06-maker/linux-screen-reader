#!/bin/sh
# Instalador do nvda-linux: identifica a distribuição e instala o pacote certo.
#
#   ./install.sh               instala (pergunta antes de mudar o grupo do usuário)
#   ./install.sh --yes         instala sem perguntas (inclui o grupo input)
#   ./install.sh --uninstall   remove o nvda-linux
#   ./install.sh --dry-run     só mostra o que faria
#
# Pacotes esperados em ./packages: .deb (Debian/Ubuntu), .fc*.noarch.rpm
# (Fedora), .opensuse.noarch.rpm (openSUSE), .pkg.tar.zst (Arch) e o código-fonte
# nvda-linux-*.tar.gz (usado para reconstruir o RPM ou o pacote do Arch quando a
# versão do Python da máquina for outra).
#
# NVDA_INSTALLER_FORCE_BUILD=1 força a reconstrução no Fedora/openSUSE/Arch
# (usado nos testes do caminho de reconstrução).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
PKGS="$HERE/packages"
YES=0
DRY=0
ACTION=install
MIN_GI=3.50

# Nome mostrado ao usuário: o .run autoextraível passa o próprio nome.
PROG=${NVDA_INSTALLER_NAME:-$0}

usage() {
    cat <<EOF
Instalador do nvda-linux: identifica a distribuição e instala o pacote certo.

  sh $PROG               instala (pergunta antes de mudar o grupo do usuário)
  sh $PROG --yes         instala sem perguntas (inclui o grupo input)
  sh $PROG --uninstall   remove o nvda-linux
  sh $PROG --dry-run     só mostra o que faria

Funciona em Debian/Ubuntu (apt), Fedora (dnf), openSUSE (zypper) e Arch (pacman),
inclusive derivadas como Linux Mint, Pop!_OS, Manjaro e EndeavourOS.
EOF
}

for arg in "$@"; do
    case "$arg" in
        -y|--yes) YES=1 ;;
        --dry-run) DRY=1 ;;
        --uninstall|--remove) ACTION=uninstall ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Opção desconhecida: $arg (use --help)" >&2; exit 2 ;;
    esac
done

# ------------------------------------------------------------------ utilidades
say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    command -v sudo >/dev/null 2>&1 || die "rode como root ou instale o sudo."
    SUDO="sudo"
fi
TARGET_USER=${SUDO_USER:-$(id -un)}

run_root() {
    say "  \$ $*"
    if [ "$DRY" -eq 0 ]; then
        $SUDO "$@"
    fi
}

as_user() { # roda como $TARGET_USER (o makepkg não aceita root)
    if [ "$(id -u)" -eq 0 ]; then
        su "$TARGET_USER" -s /bin/sh -c "$*"
    else
        "$@"
    fi
}

ask() { # ask "pergunta" padrão(s/n)
    if [ "$YES" -eq 1 ]; then return 0; fi
    if [ ! -t 0 ]; then [ "$2" = s ]; return; fi
    if [ "$2" = s ]; then hint="[S/n]"; else hint="[s/N]"; fi
    printf '%s %s ' "$1" "$hint"
    read -r answer || answer=""
    case "${answer:-$2}" in s|S|sim|Sim|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

find_pkg() { # primeiro arquivo em $PKGS que casa com o padrão
    for f in "$PKGS"/$1; do
        if [ -f "$f" ]; then echo "$f"; return 0; fi
    done
    return 1
}

python_version() {
    python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true
}

# ------------------------------------------------------------------ detecção
detect() {
    [ -r /etc/os-release ] || die "não encontrei /etc/os-release: distribuição desconhecida."
    # shellcheck disable=SC1091
    . /etc/os-release
    NAME_PRETTY=${PRETTY_NAME:-${NAME:-Linux}}
    ids=" ${ID:-} ${ID_LIKE:-} "
    case "$ids" in
        *" arch "*|*" manjaro "*|*" endeavouros "*|*" cachyos "*) FAMILY=arch ;;
        *suse*|*" sles "*) FAMILY=suse ;;
        *" fedora "*|*" rhel "*|*" centos "*) FAMILY=fedora ;;
        *" debian "*|*" ubuntu "*) FAMILY=debian ;;
        *) FAMILY=unknown ;;
    esac
}

too_old() {
    die "$NAME_PRETTY traz o PyGObject $1, e o nvda-linux precisa da versão $MIN_GI ou mais nova.
Sistemas que já servem: Debian 13, Ubuntu 25.04 ou mais novo, Fedora 41+,
openSUSE Tumbleweed e Arch. Atualize o sistema e rode o instalador de novo."
}

# ------------------------------------------------------------------ Debian/Ubuntu
install_debian() {
    deb=$(find_pkg 'nvda-linux_*_all.deb') || die "pacote .deb não encontrado em $PKGS."
    step "Atualizando a lista de pacotes"
    run_root apt-get update
    candidate=$(apt-cache policy python3-gi 2>/dev/null | awk '/Candidate:/ {print $2}')
    if [ -z "$candidate" ] || [ "$candidate" = "(none)" ]; then
        [ "$DRY" -eq 1 ] || too_old "(nenhum)"
    elif ! dpkg --compare-versions "$candidate" ge "$MIN_GI"; then
        too_old "$candidate"
    fi
    step "Instalando $(basename "$deb")"
    if [ "$YES" -eq 1 ]; then
        run_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$deb"
    else
        run_root apt-get install "$deb"
    fi
}

# ------------------------------------------------------------------ Fedora/openSUSE
build_rpm() { # reconstrói o RPM para o Python desta máquina; devolve o caminho
    src=$(find_pkg 'nvda-linux-*.tar.gz') || die "código-fonte não encontrado em $PKGS."
    step "Preparando as ferramentas de build do RPM" >&2
    if [ "$FAMILY" = suse ]; then
        run_root zypper --non-interactive install rpm-build python-rpm-macros systemd-rpm-macros \
            python3-devel python3-pip python3-setuptools python3-wheel tar gzip >&2
    else
        run_root dnf install -y rpm-build pyproject-rpm-macros systemd-rpm-macros python3-devel \
            python3-setuptools python3-wheel python3-pip >&2
    fi
    [ "$DRY" -eq 0 ] || { echo "$PKGS/(reconstruído).rpm"; return 0; }
    work=$(mktemp -d)
    tar -xzf "$src" -C "$work"
    script=$(ls "$work"/nvda-linux-*/packaging/build-rpm.sh 2>/dev/null | head -1)
    [ -n "$script" ] || die "o código-fonte não tem packaging/build-rpm.sh."
    step "Construindo o RPM para o Python $(python_version)" >&2
    sh "$script" >&2
    find_rpm=$(ls "$work"/nvda-linux-*/dist/*.noarch.rpm | head -1)
    cp "$find_rpm" "$work/"
    echo "$work/$(basename "$find_rpm")"
}

install_rpm() {
    if [ "$FAMILY" = suse ]; then pattern='nvda-linux-*.opensuse.noarch.rpm'; else pattern='nvda-linux-*.fc*.noarch.rpm'; fi
    rpm_file=$(find_pkg "$pattern" || true)
    mine=$(python_version)
    wanted=""
    if [ -n "$rpm_file" ]; then
        wanted=$(rpm -qp --requires "$rpm_file" 2>/dev/null | sed -n 's/^python(abi) = //p')
    fi
    if [ -n "${NVDA_INSTALLER_FORCE_BUILD:-}" ] || [ -z "$rpm_file" ] || [ -z "$mine" ] \
            || [ "$wanted" != "$mine" ]; then
        say "O pacote pronto é para o Python ${wanted:-?}; esta máquina tem o ${mine:-?}. Vou reconstruir."
        rpm_file=$(build_rpm)
    fi
    step "Instalando $(basename "$rpm_file")"
    if [ "$FAMILY" = suse ]; then
        if [ "$YES" -eq 1 ]; then
            run_root zypper --non-interactive install --allow-unsigned-rpm "$rpm_file"
        else
            run_root zypper install --allow-unsigned-rpm "$rpm_file"
        fi
    else
        if [ "$YES" -eq 1 ]; then
            run_root dnf install -y "$rpm_file"
        else
            run_root dnf install "$rpm_file"
        fi
    fi
}

# ------------------------------------------------------------------ Arch
install_arch() {
    pkg=$(find_pkg 'nvda-linux-*.pkg.tar.zst' || true)
    mine=$(python_version)
    wanted=""
    if [ -n "$pkg" ]; then
        wanted=$(bsdtar -tf "$pkg" 2>/dev/null | sed -n 's#^usr/lib/python\([0-9.]*\)/.*#\1#p' | head -1)
    fi
    if [ -n "${NVDA_INSTALLER_FORCE_BUILD:-}" ] || [ -z "$pkg" ] || [ -z "$mine" ] \
            || [ "$wanted" != "$mine" ]; then
        say "O pacote pronto é para o Python ${wanted:-?}; esta máquina tem o ${mine:-?}. Vou reconstruir."
        [ "$TARGET_USER" != root ] || die "para reconstruir no Arch, rode o instalador como usuário comum (com sudo)."
        src=$(find_pkg 'nvda-linux-*.tar.gz') || die "código-fonte não encontrado em $PKGS."
        step "Preparando as ferramentas de build"
        run_root pacman -S --needed --noconfirm base-devel python-build python-installer \
            python-setuptools python-wheel
        if [ "$DRY" -eq 0 ]; then
            work=$(mktemp -d)
            tar -xzf "$src" -C "$work"
            chown -R "$TARGET_USER" "$work"
            script=$(ls "$work"/nvda-linux-*/packaging/build-arch.sh 2>/dev/null | head -1)
            [ -n "$script" ] || die "o código-fonte não tem packaging/build-arch.sh."
            step "Construindo o pacote como $TARGET_USER"
            as_user sh "$script"
            pkg=$(ls "$work"/nvda-linux-*/dist/*.pkg.tar.zst | head -1)
        fi
    fi
    step "Instalando $(basename "${pkg:-nvda-linux.pkg.tar.zst}")"
    if [ "$YES" -eq 1 ]; then
        run_root pacman -U --noconfirm "$pkg"
    else
        run_root pacman -U "$pkg"
    fi
}

# ------------------------------------------------------------------ depois de instalar
after_install() {
    step "Permissões de teclado"
    if [ "$TARGET_USER" = root ]; then
        say "Rodando como root sem sudo: adicione o seu usuário ao grupo input depois:"
        say "  sudo usermod -aG input SEU_USUARIO"
    elif id -nG "$TARGET_USER" 2>/dev/null | tr ' ' '\n' | grep -qx input; then
        say "$TARGET_USER já está no grupo input."
    elif ask "Adicionar $TARGET_USER ao grupo input (necessário para o leitor usar o teclado)?" s; then
        run_root usermod -aG input "$TARGET_USER"
        [ "$DRY" -eq 1 ] || say "Feito. Saia e entre de novo na sessão para valer."
    else
        say "Pulado. Depois: sudo usermod -aG input $TARGET_USER"
    fi

    if [ "$DRY" -eq 1 ]; then
        say ""
        say "Simulação concluída: nada foi instalado nem alterado."
        return 0
    fi

    step "Diagnóstico (como $TARGET_USER)"
    if command -v nvda-linux >/dev/null 2>&1; then
        as_user nvda-linux --check-permissions || true
        say "(O grupo input só vale depois de sair e entrar de novo na sessão.)"
    fi

    cat <<EOF

nvda-linux instalado.
  - Primeiro teste: deixe um acesso reserva (SSH ou outro TTY) e rode: nvda-linux
    Ctrl+Alt+Shift+Esc encerra o leitor e solta o teclado.
  - Para iniciar junto com a sessão: systemctl --user enable --now nvda-linux.service
  - Para remover: sh $PROG --uninstall
EOF
}

is_installed() {
    case "$FAMILY" in
        debian) dpkg -s nvda-linux >/dev/null 2>&1 && dpkg -s nvda-linux | grep -q '^Status: install ok' ;;
        fedora|suse) rpm -q nvda-linux >/dev/null 2>&1 ;;
        arch) pacman -Q nvda-linux >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

uninstall() {
    if ! is_installed; then
        say "O nvda-linux não está instalado neste sistema."
        return 0
    fi
    step "Removendo o nvda-linux"
    case "$FAMILY" in
        debian) run_root apt-get remove -y nvda-linux ;;
        fedora) run_root dnf remove -y nvda-linux ;;
        suse) run_root zypper --non-interactive remove nvda-linux ;;
        arch) run_root pacman -R --noconfirm nvda-linux ;;
    esac
    say "Removido. O grupo input do seu usuário não foi alterado."
}

# ------------------------------------------------------------------ principal
detect
say "Sistema identificado: $NAME_PRETTY (família: $FAMILY)"
[ "$DRY" -eq 0 ] || say "(simulação: nada será alterado)"

if [ "$FAMILY" = unknown ]; then
    die "ainda não há pacote para esta distribuição.
Instale pelo código-fonte (packages/nvda-linux-*.tar.gz) seguindo docs/platform/README.md."
fi

if [ "$ACTION" = uninstall ]; then
    uninstall
    exit 0
fi

case "$FAMILY" in
    debian) install_debian ;;
    fedora|suse) install_rpm ;;
    arch) install_arch ;;
esac
after_install
