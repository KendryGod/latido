"""Pestaña Velocidad: configuración (tamaño y pasadas), orden de los pasos y formato de tamaños."""

import pytest

from latido.velocidad import formato
from latido.velocidad.pruebas import GIB, MIB, Configuracion, Direccion, ErrorConfiguracion


def test_formato_de_tamanos():
    assert [formato.tamano(t) for t in (256 * MIB, 512 * MIB, GIB, 13 * GIB, int(120.5 * GIB), 1536 * MIB)] == [
        "256 MiB", "512 MiB", "1 GiB", "13 GiB", "120.5 GiB", "1.5 GiB",
    ]
    assert formato.tamano(4096) == "4,096 bytes"
    assert formato.tamano(MIB + MIB // 2) == "1.5 MiB"
    assert formato.gigabytes(13 * GIB) == "13.96 GB"


def test_configuracion_por_defecto():
    configuracion = Configuracion()
    assert (configuracion.tamano, configuracion.pasadas) == (GIB, 3)
    assert configuracion.escritura_maxima == 13 * GIB  # 1 GiB de preparación + 4 pruebas x 3 pasadas x 1 GiB


@pytest.mark.parametrize("tamano, pasadas", [
    (255 * MIB, 3), (32 * GIB + MIB, 3), (256 * MIB + 1, 3), (GIB, 0), (GIB, 10), (True, 3), (GIB, 2.0),
])
def test_configuracion_fuera_de_rango(tamano, pasadas):
    with pytest.raises(ErrorConfiguracion):
        Configuracion(tamano, pasadas)


def test_limites_validos():
    Configuracion(256 * MIB, 1)
    Configuracion(32 * GIB, 9)


def test_orden_de_los_pasos():
    pasos = Configuracion(256 * MIB, 2).pasos()
    assert len(pasos) == 1 + 4 * 2 * 2
    assert pasos[0].es_preparacion
    assert [(p.prueba.clave, p.direccion, p.pasada) for p in pasos[1:5]] == [
        ("seq1m-q8t1", Direccion.LECTURA, 1), ("seq1m-q8t1", Direccion.LECTURA, 2),
        ("seq1m-q8t1", Direccion.ESCRITURA, 1), ("seq1m-q8t1", Direccion.ESCRITURA, 2),
    ]
    assert pasos[-1].trabajo == "latido-rnd4k-q1t1-escritura"


def test_formato_de_velocidades():
    assert formato.BYTES_POR_MB == 1_000_000  # MB/s = 1 000 000 bytes por segundo
    assert formato.mb_s(1369568653) == "1,369.57"
    assert formato.mb_s(54827503) == "54.83"
    assert formato.iops(138847.457627) == "138,847"
