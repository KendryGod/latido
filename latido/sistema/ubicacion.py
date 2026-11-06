"""En qué disco físico está una carpeta, para ligar la prueba de velocidad a su disco. Sin GTK.

Solo lee: os.stat, /sys y /proc/self/mountinfo. Nada aquí escribe. Si no se puede afirmar un único
disco (LVM, dm-crypt, RAID, btrfs de varios discos, overlayfs, tmpfs, red…), lo dice y no adivina.

- st_dev con mayor distinto de 0: /sys/dev/block/<mayor>:<menor> es el dispositivo de bloques; si es una
  partición, su disco es la carpeta de arriba en /sys/devices.
- st_dev con mayor 0 (dispositivo anónimo): btrfs da uno así a cada subvolumen. Solo en btrfs se sigue:
  el montaje de la carpeta dice su dispositivo y /sys/fs/btrfs/<uuid>/devices tiene que tener uno solo.
"""

import os
import re
from dataclasses import dataclass

from latido.velocidad.carpeta import MOUNTINFO, leer_mountinfo as interpretar_mountinfo, montaje_de

NO_SE_PUDO = "No se pudo saber en qué disco está esta carpeta"
SYS = "/sys"
_VIRTUAL = re.compile(r"(dm|md)-?[0-9]+(p[0-9]+)?")  # device-mapper (LVM, dm-crypt) y RAID por software


@dataclass(frozen=True)
class DiscoDeCarpeta:
    disco: object  # Disco de latido.sistema.discos, o None si no se pudo saber
    motivo: str | None = None  # por qué no se pudo saber

    @property
    def texto_antes(self):
        """Lo que dice la pestaña Velocidad antes de iniciar."""
        return f"Se medirá: {self.disco.etiqueta_corta}" if self.disco is not None else NO_SE_PUDO


def mismo_disco(a, b):
    """True solo si los dos son el mismo dispositivo. Dos discos iguales (modelo y capacidad) no lo son."""
    return a is not None and b is not None and a.ruta == b.ruta


def _leer_mountinfo():
    with open(MOUNTINFO, encoding="utf-8", errors="surrogateescape") as archivo:
        return archivo.read()


class _NoSePuede(Exception):
    pass


def _disco_base(nombre, raiz_sys):
    """De un dispositivo de bloques (nvme0n1p5, sdb, dm-0…) a su disco, o _NoSePuede."""
    base = os.path.join(raiz_sys, "class", "block", nombre)
    if not nombre or not os.path.isdir(base):
        raise _NoSePuede(f"El kernel no dice a qué disco pertenece {nombre or 'la carpeta'}.")
    if os.path.exists(os.path.join(base, "partition")):
        disco = os.path.basename(os.path.dirname(os.path.realpath(base)))
        _comprobar_que_no_es_virtual(disco, raiz_sys)
        _comprobar_que_no_es_virtual(nombre, raiz_sys)
        return disco
    _comprobar_que_no_es_virtual(nombre, raiz_sys)
    return nombre


def _comprobar_que_no_es_virtual(nombre, raiz_sys):
    try:
        debajo = os.listdir(os.path.join(raiz_sys, "class", "block", nombre, "slaves"))
    except FileNotFoundError:
        debajo = []
    except OSError:
        raise _NoSePuede(f"No se pudo leer qué hay debajo de {nombre}.") from None
    if debajo or _VIRTUAL.fullmatch(nombre):
        raise _NoSePuede(f"La carpeta está sobre {nombre} (LVM, dm-crypt o RAID): puede abarcar más de un disco.")


def _dispositivo_btrfs(ruta, leer_mountinfo, raiz_sys, realpath):
    """Para un st_dev anónimo: el único dispositivo de su btrfs, o _NoSePuede."""
    try:
        montaje = montaje_de(realpath(ruta), interpretar_mountinfo(leer_mountinfo()))
    except OSError:
        montaje = None
    if montaje is None:
        raise _NoSePuede("No se encontró el montaje de la carpeta.")
    if montaje.tipo != "btrfs":
        raise _NoSePuede(f"La carpeta está en {montaje.tipo}, que no está sobre un único disco.")
    if not montaje.fuente.startswith("/dev/"):
        raise _NoSePuede("No se pudo saber el dispositivo del btrfs de la carpeta.")
    dispositivo = os.path.basename(realpath(montaje.fuente))
    carpeta_btrfs = os.path.join(raiz_sys, "fs", "btrfs")
    try:
        sistemas = sorted(os.listdir(carpeta_btrfs))
    except OSError:
        sistemas = []
    miembros_de = []
    for uuid in sistemas:
        try:
            miembros = sorted(os.listdir(os.path.join(carpeta_btrfs, uuid, "devices")))
        except OSError:
            continue
        if dispositivo in miembros:
            miembros_de.append(miembros)
    if len(miembros_de) != 1:
        raise _NoSePuede("No se pudo saber qué discos forman el btrfs de la carpeta.")
    if len(miembros_de[0]) != 1:
        raise _NoSePuede(f"La carpeta está en un btrfs con varios discos ({', '.join(miembros_de[0])}).")
    return miembros_de[0][0]


def disco_de_carpeta(ruta, discos, stat=os.stat, raiz_sys=SYS, leer_mountinfo=_leer_mountinfo,
                     realpath=os.path.realpath):
    """El disco de la lista (latido.sistema.discos) donde está la carpeta, o el motivo por el que no se sabe."""
    try:
        try:
            dispositivo = stat(ruta).st_dev
        except OSError:
            raise _NoSePuede("No se pudo leer la carpeta.") from None
        mayor, menor = os.major(dispositivo), os.minor(dispositivo)
        if mayor == 0:
            nombre = _dispositivo_btrfs(ruta, leer_mountinfo, raiz_sys, realpath)
        else:
            enlace = os.path.join(raiz_sys, "dev", "block", f"{mayor}:{menor}")
            if not os.path.exists(enlace):
                raise _NoSePuede(f"El kernel no dice qué dispositivo es {mayor}:{menor}.")
            nombre = os.path.basename(os.path.realpath(enlace))
        base = _disco_base(nombre, raiz_sys)
        encontrados = [disco for disco in discos if disco.nombre == base]
        if len(encontrados) != 1:
            raise _NoSePuede(f"La carpeta está en {base}, que no es un disco de la lista de Latido.")
        return DiscoDeCarpeta(encontrados[0])
    except _NoSePuede as error:
        return DiscoDeCarpeta(None, str(error))
