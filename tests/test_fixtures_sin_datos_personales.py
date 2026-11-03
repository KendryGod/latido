"""Ningún fixture puede traer datos que identifiquen una unidad concreta ni a su dueño."""

import getpass
import json
import socket
from pathlib import Path

import pytest

CARPETA_FIXTURES = Path(__file__).parent / "fixtures"

# Una clave es sospechosa si contiene alguno de estos textos
# (cubre serial_number, wwn, nguid, eui64 y sus variantes).
FRAGMENTOS_PROHIBIDOS = ("serial", "wwn", "nguid", "eui64")


def _vacio(valor):
    return valor is None or valor == "" or valor == [] or valor == {}


def buscar_identificadores(obj, ruta="$"):
    """Devuelve las rutas de claves de identificación con valor no vacío.

    Se ignora todo lo que esté dentro de una clave "argv": ahí "noserial"
    aparece legítimamente como argumento de smartctl.
    """
    hallados = []
    if isinstance(obj, dict):
        for clave, valor in obj.items():
            sub = f"{ruta}.{clave}"
            if clave == "argv":
                continue
            if any(f in clave.lower() for f in FRAGMENTOS_PROHIBIDOS) and not _vacio(valor):
                hallados.append(sub)
            hallados.extend(buscar_identificadores(valor, sub))
    elif isinstance(obj, list):
        for i, valor in enumerate(obj):
            hallados.extend(buscar_identificadores(valor, f"{ruta}[{i}]"))
    return hallados


ARCHIVOS = sorted(CARPETA_FIXTURES.rglob("*.json"))


def test_hay_fixtures():
    assert ARCHIVOS, "no se encontró ningún .json en tests/fixtures"


@pytest.mark.parametrize("archivo", ARCHIVOS, ids=lambda p: str(p.relative_to(CARPETA_FIXTURES)))
def test_fixture_sin_datos_personales(archivo):
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    assert buscar_identificadores(datos) == []


def test_detecta_identificadores_en_dict_sintetico():
    sintetico = {
        "smartctl": {"argv": ["smartctl", "-q", "noserial", "/dev/nvme0"]},
        "serial_number": "ABC123",
        "wwn": {"naa": 5, "oui": 1, "id": 2},
        "nvme_namespaces": [{"id": 1, "eui64": {"oui": 1, "ext_id": 2}, "nguid": "00ff"}],
        "farm": {"drive_serial_number": "XYZ"},
    }
    assert buscar_identificadores(sintetico) == [
        "$.serial_number",
        "$.wwn",
        "$.nvme_namespaces[0].eui64",
        "$.nvme_namespaces[0].nguid",
        "$.farm.drive_serial_number",
    ]


def test_ignora_valores_vacios_y_argv():
    limpio = {
        "smartctl": {"argv": ["smartctl", "-q", "noserial"]},
        "serial_number": "",
        "wwn": None,
        "nguid": {},
    }
    assert buscar_identificadores(limpio) == []


# --- Salidas de fio: rutas personales, usuario y nombre del equipo ---

CARPETA_FIO = CARPETA_FIXTURES / "fio"
RUTAS_PERSONALES = ("/home/", "/var/home/", "/root/", "/run/user/", "/tmp/", "/media/", "/mnt/", "/.cache/")
RUTA_REDACTADA = "/RUTA-REDACTADA/"


def datos_personales_en_texto(texto, usuario=None, equipo=None):
    hallados = [ruta for ruta in RUTAS_PERSONALES if ruta in texto]
    for nombre in (usuario, equipo):
        if nombre and len(nombre) >= 3 and nombre not in ("root", "localhost") and nombre in texto:
            hallados.append(nombre)
    return hallados


ARCHIVOS_FIO = sorted(p for p in CARPETA_FIO.iterdir() if p.is_file())


def test_hay_salidas_de_fio():
    assert len(ARCHIVOS_FIO) >= 9


@pytest.mark.parametrize("archivo", ARCHIVOS_FIO, ids=lambda p: p.name)
def test_salida_de_fio_sin_rutas_usuario_ni_equipo(archivo):
    texto = archivo.read_text(encoding="utf-8")
    assert datos_personales_en_texto(texto, getpass.getuser(), socket.gethostname()) == []


def test_filename_de_fio_redactado():
    reales = sorted(CARPETA_FIO.glob("latido-*.json"))
    assert len(reales) == 9
    for archivo in reales:
        for trabajo in json.loads(archivo.read_text(encoding="utf-8"))["jobs"]:
            assert trabajo["job options"]["filename"].startswith(RUTA_REDACTADA), archivo.name


def test_detecta_rutas_usuario_y_equipo():
    assert datos_personales_en_texto('{"filename": "/home/ana/x"}') == ["/home/"]
    assert datos_personales_en_texto("/var/home/ana/.cache/x") == ["/home/", "/var/home/", "/.cache/"]
    assert datos_personales_en_texto("hecho por ana en pc-de-ana", usuario="ana", equipo="pc-de-ana") == [
        "ana", "pc-de-ana"
    ]
    assert datos_personales_en_texto("root en localhost", usuario="root", equipo="localhost") == []
