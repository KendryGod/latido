#!/bin/sh
# Quita el ayudante de root y la política polkit de Latido (desarrollo).
#
# Uso:
#     sudo sh tools/desinstalar-helper-dev.sh
#
# Solo borra estos dos archivos y la carpeta /usr/libexec/latido si queda vacía.

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script necesita root. Ejecuta: sudo sh tools/desinstalar-helper-dev.sh" >&2
    exit 1
fi

rm -fv /usr/libexec/latido/latido-helper
rm -fv /usr/share/polkit-1/actions/io.github.kendrygod.latido.policy
if [ -d /usr/libexec/latido ]; then
    rmdir --ignore-fail-on-non-empty /usr/libexec/latido
fi

echo "Listo."
