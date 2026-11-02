"""Ningún fixture puede traer datos que identifiquen una unidad concreta."""

import json
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
