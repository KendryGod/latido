"""Comprueba, antes de pedir permisos, que todo lo necesario esté instalado."""

import os

from latido.sistema.rutas import HELPER, PKEXEC, POLITICA, SMARTCTL


def _ejecutable(ruta):
    return os.path.isfile(ruta) and os.access(ruta, os.X_OK)


def comprobar_herramientas(ejecutable=_ejecutable, existe=os.path.isfile):
    """Devuelve un mensaje por cada pieza que falte. Lista vacía = todo listo."""
    faltan = []
    if not ejecutable(SMARTCTL):
        faltan.append(f"Falta smartctl ({SMARTCTL}). Instálalo con: sudo dnf install smartmontools")
    if not ejecutable(PKEXEC):
        faltan.append(f"Falta pkexec ({PKEXEC}). Instálalo con: sudo dnf install polkit")
    if not ejecutable(HELPER):
        faltan.append(
            f"Falta el ayudante de Latido ({HELPER}). "
            "Instálalo desde la carpeta del proyecto con: sudo sh tools/instalar-helper-dev.sh"
        )
    if not existe(POLITICA):
        faltan.append(
            f"Falta la política de permisos de Latido ({POLITICA}). "
            "Instálala desde la carpeta del proyecto con: sudo sh tools/instalar-helper-dev.sh"
        )
    return faltan
