#!/bin/sh
# Variáveis que fazem GTK, Qt, Chromium/Electron e Java exporem a árvore
# AT-SPI2 pelo D-Bus.
#
# Uso 1 (perfil):  sudo install -m 644 nvda-linux-a11y-env.sh /etc/profile.d/
# Uso 2 (wrapper): nvda-linux-a11y-env.sh firefox
#                  (exporta e executa o comando)

case ":${GTK_MODULES:-}:" in
    *:gail:atk-bridge:*) ;;
    *:atk-bridge:*) ;;
    ::) GTK_MODULES="gail:atk-bridge" ;;
    *) GTK_MODULES="${GTK_MODULES}:gail:atk-bridge" ;;
esac
export GTK_MODULES
export QT_ACCESSIBILITY=1
export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1
export ACCESSIBILITY_ENABLED=1
# Java (java-atk-wrapper)
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }-Djavax.accessibility.assistive_technologies=org.GNOME.Accessibility.AtkWrapper"

if [ "$#" -gt 0 ]; then
    exec "$@"
fi
