#!/bin/sh
# Instala el ayudante de root y la política polkit de Latido (desarrollo).
#
# Uso, desde la carpeta del repositorio:
#     sudo sh tools/instalar-helper-dev.sh
#
# Copia (no enlaza) los archivos: el ayudante de root nunca se ejecuta
# desde la carpeta personal.

set -eu

DESTINO_HELPER=/usr/libexec/latido/latido-helper
DESTINO_POLITICA=/usr/share/polkit-1/actions/io.github.kendrygod.latido.policy

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script necesita root. Ejecuta: sudo sh tools/instalar-helper-dev.sh" >&2
    exit 1
fi

RAIZ=$(cd "$(dirname "$0")/.." && pwd)
ORIGEN_HELPER="$RAIZ/helper/latido-helper"
ORIGEN_POLITICA="$RAIZ/data/io.github.kendrygod.latido.policy"

# Comprobar todo antes de tocar nada.
faltan=0
for archivo in "$ORIGEN_HELPER" "$ORIGEN_POLITICA"; do
    if [ ! -f "$archivo" ]; then
        echo "No se encontró $archivo" >&2
        faltan=1
    fi
done
for herramienta in /usr/bin/python3 /usr/bin/smartctl /usr/bin/pkexec; do
    if [ ! -x "$herramienta" ]; then
        echo "Falta $herramienta (instala el paquete que lo provee)" >&2
        faltan=1
    fi
done
if [ ! -d /usr/share/polkit-1/actions ]; then
    echo "No existe /usr/share/polkit-1/actions (¿está instalado polkit?)" >&2
    faltan=1
fi
if [ "$faltan" -ne 0 ]; then
    echo "No se instaló nada." >&2
    exit 1
fi

install -d -o root -g root -m 0755 /usr/libexec/latido
install -o root -g root -m 0755 "$ORIGEN_HELPER" "$DESTINO_HELPER"
install -o root -g root -m 0644 "$ORIGEN_POLITICA" "$DESTINO_POLITICA"

# Etiquetas SELinux por defecto para los archivos nuevos.
if command -v restorecon >/dev/null 2>&1; then
    restorecon -v /usr/libexec/latido "$DESTINO_HELPER" "$DESTINO_POLITICA"
fi

echo "Instalado:"
ls -l "$DESTINO_HELPER" "$DESTINO_POLITICA"
