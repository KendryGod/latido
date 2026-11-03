"""Comprueba fio y su motor libaio antes de medir.

En Fedora 44 el motor libaio es un paquete aparte: /usr/lib64/fio/fio-libaio.so
pertenece a fio-engine-libaio (comprobado con rpm -qf).

`fio --enghelp=libaio` (HOWTO.rst, --enghelp) carga de verdad el motor (con
LD_DEBUG=files se ve el dlopen de fio-libaio.so) y sale con 0 mostrando sus
opciones. Con un motor que no se puede cargar sale con 1 y dice
"engine ... not loadable" (probado con fio 3.40 y un nombre inexistente).
"""

import os
import subprocess
from dataclasses import dataclass, field

from latido.velocidad.pruebas import FIO

ENTORNO = {"LC_ALL": "C"}
SEGUNDOS_MAXIMOS = 15
INSTALAR_FIO = "sudo dnf install fio fio-engine-libaio"
INSTALAR_LIBAIO = "sudo dnf install fio-engine-libaio"


@dataclass
class EstadoFio:
    version: str | None = None
    problemas: list = field(default_factory=list)

    @property
    def listo(self):
        return not self.problemas


def _ejecutable(ruta):
    return os.path.isfile(ruta) and os.access(ruta, os.X_OK)


def _texto(datos):
    return datos.decode("utf-8", errors="replace") if isinstance(datos, bytes) else (datos or "")


def _consultar(ejecutar, comando):
    proceso = ejecutar(
        comando,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=ENTORNO,
        timeout=SEGUNDOS_MAXIMOS,
        check=False,
    )
    return proceso.returncode, _texto(proceso.stdout), _texto(proceso.stderr)


def comprobar_fio(fio=FIO, ejecutar=None, ejecutable=_ejecutable):
    """Devuelve EstadoFio; sus problemas dicen exactamente qué falta y cómo instalarlo."""
    ejecutar = ejecutar or subprocess.run
    estado = EstadoFio()
    if not ejecutable(fio):
        estado.problemas.append(f"Falta fio ({fio}). Instálalo con: {INSTALAR_FIO}")
        return estado
    try:
        codigo, salida, error = _consultar(ejecutar, [fio, "--version"])
        if codigo != 0:
            estado.problemas.append(f"fio --version terminó con el código {codigo}. {error.strip()}".strip())
            return estado
        estado.version = salida.strip() or None
        codigo, salida, error = _consultar(ejecutar, [fio, "--enghelp=libaio"])
    except subprocess.TimeoutExpired:
        estado.problemas.append(f"fio no respondió en {SEGUNDOS_MAXIMOS} s al consultarle su versión y sus motores.")
        return estado
    except OSError as fallo:
        estado.problemas.append(f"No se pudo ejecutar {fio}: {fallo.strerror}.")
        return estado
    if codigo != 0:
        mensaje = "\n".join(linea for linea in (salida + "\n" + error).splitlines() if linea.strip())
        estado.problemas.append(
            f"fio no pudo cargar el motor libaio. Instálalo con: {INSTALAR_LIBAIO}"
            + (f"\nMensaje de fio:\n{mensaje}" if mensaje else "")
        )
    return estado
