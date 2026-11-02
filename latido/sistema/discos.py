"""Detección de discos con lsblk, sin root."""

import json
import os
import re
import subprocess
from dataclasses import dataclass

from latido.salud import formato
from latido.sistema.rutas import LSBLK

AVISO_SD = "SATA y USB llegan en una próxima fase"

_NAMESPACE_NVME = re.compile(r"nvme[0-9]+n[0-9]+")
_CONTROLADOR_NVME = re.compile(r"nvme[0-9]+")
_DISCO_SD = re.compile(r"sd[a-z]+")


class ErrorDeteccion(Exception):
    pass


@dataclass
class Disco:
    nombre: str  # nvme0n1, sda...
    ruta: str  # /dev/nvme0n1
    ruta_lectura: str | None  # lo que recibe el ayudante; None si no se puede leer
    modelo: str | None
    tamano: int | None  # bytes
    transporte: str | None  # nvme, usb, sata...
    es_sistema: bool
    habilitado: bool
    aviso: str | None

    @property
    def etiqueta(self):
        partes = [self.modelo or self.nombre, formato.capacidad(self.tamano), self.ruta]
        texto = " · ".join(partes)
        if self.es_sistema:
            texto += " · disco del sistema"
        return texto


def ruta_controlador_nvme(nombre, sys_block="/sys/block"):
    """Para nvme0n1 devuelve /dev/nvme0 (el controlador), como en los fixtures.

    Se obtiene de /sys/block/<nombre>/device. Si no se puede, se usa el
    namespace (/dev/nvme0n1), que el ayudante también acepta.
    """
    destino = os.path.basename(os.path.realpath(os.path.join(sys_block, nombre, "device")))
    if _CONTROLADOR_NVME.fullmatch(destino):
        return f"/dev/{destino}"
    return f"/dev/{nombre}"


def _montajes(dispositivo):
    montajes = [m for m in dispositivo.get("mountpoints") or [] if m]
    for hijo in dispositivo.get("children") or []:
        montajes.extend(_montajes(hijo))
    return montajes


def discos_desde_lsblk(salida, sys_block="/sys/block"):
    """Convierte el JSON de lsblk en una lista de Disco (NVMe y sd*)."""
    discos = []
    for dispositivo in salida.get("blockdevices") or []:
        nombre = dispositivo.get("name") or ""
        if dispositivo.get("type") != "disk" or nombre.startswith(("loop", "zram")):
            continue  # fuera loop, rom y zram
        es_nvme = _NAMESPACE_NVME.fullmatch(nombre) is not None
        if not es_nvme and _DISCO_SD.fullmatch(nombre) is None:
            continue
        tamano = dispositivo.get("size")
        discos.append(
            Disco(
                nombre=nombre,
                ruta=dispositivo.get("path") or f"/dev/{nombre}",
                ruta_lectura=ruta_controlador_nvme(nombre, sys_block) if es_nvme else None,
                modelo=(dispositivo.get("model") or "").strip() or None,
                tamano=tamano if isinstance(tamano, int) else None,
                transporte=dispositivo.get("tran"),
                es_sistema="/" in _montajes(dispositivo),
                habilitado=es_nvme,
                aviso=None if es_nvme else AVISO_SD,
            )
        )
    return discos


def listar_discos(ejecutar=None):
    ejecutar = ejecutar or subprocess.run
    comando = [LSBLK, "--json", "--bytes", "--output", "NAME,PATH,TYPE,TRAN,MODEL,SIZE,MOUNTPOINTS"]
    try:
        proceso = ejecutar(comando, capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired as error:
        raise ErrorDeteccion("lsblk no respondió a tiempo.") from error
    except OSError as error:
        raise ErrorDeteccion(f"No se pudo ejecutar {LSBLK}.") from error
    if proceso.returncode != 0:
        raise ErrorDeteccion(f"lsblk terminó con el código {proceso.returncode}.")
    try:
        salida = json.loads(proceso.stdout)
    except ValueError as error:
        raise ErrorDeteccion("La salida de lsblk no es JSON válido.") from error
    if not isinstance(salida, dict):
        raise ErrorDeteccion("La salida de lsblk no tiene el formato esperado.")
    return discos_desde_lsblk(salida)
