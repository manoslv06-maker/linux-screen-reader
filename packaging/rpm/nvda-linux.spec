# Spec RPM do nvda-linux: Fedora 41+ e openSUSE Tumbleweed / Leap 16+.
# Build: ./packaging/build-rpm.sh (gera dist/*.noarch.rpm).
# Precisa de PyGObject >= 3.50 (gi.events) na distribuição.
Name:           nvda-linux
Version:        0.1.0~dev0
Release:        1%{?dist}
Summary:        Leitor de tela para Linux com a ergonomia do NVDA
License:        GPL-2.0-or-later
URL:            https://github.com/manoslv06-maker/linux-screen-reader
Source0:        %{name}-0.1.0.dev0.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
%if 0%{?suse_version}
BuildRequires:  python-rpm-macros
BuildRequires:  systemd-rpm-macros
%else
BuildRequires:  pyproject-rpm-macros
BuildRequires:  systemd-rpm-macros
%endif

# Módulos Python pelo nome padrão python3dist(): o Fedora chama de
# python3-gobject, o openSUSE de python313-gobject; os dois fornecem isto.
Requires:       python3dist(pygobject) >= 3.50
Requires:       python3dist(evdev) >= 1.7
Requires:       python3dist(dbus-next) >= 0.2.3
Requires:       python3dist(numpy) >= 1.26
Recommends:     python3dist(sounddevice)
Requires:       at-spi2-core
Requires:       espeak-ng
Requires:       speech-dispatcher
Recommends:     brltty

%if 0%{?suse_version}
Requires:       typelib-1_0-Atspi-2_0
Requires:       typelib-1_0-Gtk-4_0
Requires:       libxkbcommon0
Requires:       speech-dispatcher-module-espeak
Recommends:     %{primary_python}-speechd
Recommends:     python3-brlapi
Recommends:     python3-louis
Recommends:     pipewire-tools
%else
Requires:       gtk4
Requires:       libxkbcommon
Requires:       speech-dispatcher-espeak-ng
Recommends:     python3-speechd
Recommends:     python3-brlapi
Recommends:     python3-louis
Recommends:     pipewire-utils
%endif

%description
nvda-linux reproduz no Linux a ergonomia do NVDA: tecla NVDA, layouts
Desktop e Laptop, modos de navegação e foco, ajuda de entrada e add-ons,
sobre AT-SPI2, evdev/uinput, Speech Dispatcher e BrlAPI.

%prep
%autosetup -n %{name}-0.1.0.dev0

%build
%if 0%{?suse_version}
%python3_pyproject_wheel
%else
%pyproject_wheel
%endif

%install
%if 0%{?suse_version}
%python3_pyproject_install
%else
%pyproject_install
%endif
install -Dm644 packaging/systemd/nvda-linux.service %{buildroot}%{_userunitdir}/nvda-linux.service
install -Dm644 packaging/udev/99-nvda-input.rules %{buildroot}%{_udevrulesdir}/99-nvda-input.rules
install -Dm644 packaging/udev/nvda-linux-uinput.conf %{buildroot}%{_modulesloaddir}/nvda-linux-uinput.conf
install -Dm644 packaging/env/50-nvda-linux-a11y.conf %{buildroot}%{_prefix}/lib/environment.d/50-nvda-linux-a11y.conf
install -Dm755 packaging/env/nvda-linux-a11y-env.sh %{buildroot}%{_bindir}/nvda-linux-a11y-env
# Início automático opcional: copiar para ~/.config/autostart se quiser.
install -Dm644 packaging/autostart/nvda-linux.desktop %{buildroot}%{_datadir}/nvda-linux/autostart/nvda-linux.desktop
install -Dm644 docs/platform/README.md %{buildroot}%{_docdir}/%{name}/PLATFORM.md

%post
%systemd_user_post nvda-linux.service
udevadm control --reload-rules >/dev/null 2>&1 || :
udevadm trigger --subsystem-match=input --subsystem-match=misc >/dev/null 2>&1 || :
modprobe uinput >/dev/null 2>&1 || :
if [ $1 -eq 1 ]; then
    echo "nvda-linux instalado. Para usar:"
    echo "  1. sudo usermod -aG input \$USER   (e entre de novo na sessão)"
    echo "  2. nvda-linux --check-permissions"
    echo "  3. Teste com um acesso reserva (SSH ou outro TTY). Ctrl+Alt+Shift+Esc encerra."
    echo "  4. Para iniciar junto com a sessão: systemctl --user enable --now nvda-linux.service"
fi

%preun
%systemd_user_preun nvda-linux.service

%files
%{_bindir}/nvda-linux
%{_bindir}/nvda-linux-a11y-env
%{python3_sitelib}/nvda_linux/
%{python3_sitelib}/nvda_linux-*.dist-info/
%{_userunitdir}/nvda-linux.service
%{_udevrulesdir}/99-nvda-input.rules
%{_modulesloaddir}/nvda-linux-uinput.conf
%dir %{_prefix}/lib/environment.d
%{_prefix}/lib/environment.d/50-nvda-linux-a11y.conf
%dir %{_datadir}/nvda-linux
%dir %{_datadir}/nvda-linux/autostart
%{_datadir}/nvda-linux/autostart/nvda-linux.desktop
%doc %{_docdir}/%{name}/PLATFORM.md

%changelog
* Mon Nov 23 2026 manoslv06-maker <359591594+manoslv06-maker@users.noreply.github.com> - 0.1.0~dev0-1
- Primeiro RPM instalável (Fedora e openSUSE): depende de GTK 4 e do módulo
  eSpeak do Speech Dispatcher; nada inicia sozinho; aplica a regra udev.
- Esboço inicial
