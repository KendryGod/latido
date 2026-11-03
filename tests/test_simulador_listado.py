"""El simulador del listado de carpetas de btrfs (fixture listar_como_btrfs de conftest.py).

Cada caso repite algo medido en btrfs con el kernel 7.2.14: un descriptor de
carpeta no ve lo que se creó después de abrirlo hasta la siguiente llamada a
os.listdir o un os.lseek, y un descriptor abierto después lo ve todo. Estas
pruebas no dependen del sistema de archivos real: el simulador abre la carpeta
otra vez para saber qué hay de verdad.
"""

import os

from conftest import CLOSE_REAL, LISTDIR_REAL, LSEEK_REAL, OPEN_REAL

ABRIR_CARPETA = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC


def _crear(carpeta, nombre):
    with open(carpeta / nombre, "xb") as archivo:
        archivo.write(b"x")


def _abrir(carpeta):
    return os.open(carpeta, ABRIR_CARPETA)


def test_oculta_lo_creado_despues_de_abrir(tmp_path, listar_como_btrfs):
    descriptor = _abrir(tmp_path)
    try:
        _crear(tmp_path, "nuevo.txt")
        assert os.listdir(descriptor) == []
        assert LISTDIR_REAL(tmp_path) == ["nuevo.txt"]  # existe de verdad
    finally:
        os.close(descriptor)


def test_lo_muestra_en_la_llamada_siguiente(tmp_path, listar_como_btrfs):
    descriptor = _abrir(tmp_path)
    try:
        _crear(tmp_path, "nuevo.txt")
        assert os.listdir(descriptor) == []
        assert os.listdir(descriptor) == ["nuevo.txt"]
    finally:
        os.close(descriptor)


def test_lo_muestra_tras_lseek_al_principio(tmp_path, listar_como_btrfs):
    descriptor = _abrir(tmp_path)
    try:
        _crear(tmp_path, "nuevo.txt")
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.listdir(descriptor) == ["nuevo.txt"]
    finally:
        os.close(descriptor)


def test_lo_muestra_un_descriptor_abierto_despues_de_crearlo(tmp_path, listar_como_btrfs):
    _crear(tmp_path, "nuevo.txt")
    descriptor = _abrir(tmp_path)
    try:
        assert os.listdir(descriptor) == ["nuevo.txt"]
    finally:
        os.close(descriptor)


def test_no_lo_muestra_un_descriptor_abierto_antes_de_crearlo(tmp_path, listar_como_btrfs):
    antes = _abrir(tmp_path)
    try:
        _crear(tmp_path, "nuevo.txt")
        despues = _abrir(tmp_path)
        try:
            assert os.listdir(antes) == []
            assert os.listdir(despues) == ["nuevo.txt"]
        finally:
            os.close(despues)
    finally:
        os.close(antes)


def test_lo_borrado_desaparece_enseguida(tmp_path, listar_como_btrfs):
    _crear(tmp_path, "viejo.txt")
    descriptor = _abrir(tmp_path)
    try:
        assert os.listdir(descriptor) == ["viejo.txt"]
        os.unlink(tmp_path / "viejo.txt")
        assert os.listdir(descriptor) == []
    finally:
        os.close(descriptor)


def test_lo_vuelto_a_crear_o_renombrado_no_aparece_hasta_la_llamada_siguiente(tmp_path, listar_como_btrfs):
    _crear(tmp_path, "nuevo.txt")
    _crear(tmp_path, "otro.txt")
    descriptor = _abrir(tmp_path)
    try:
        assert sorted(os.listdir(descriptor)) == ["nuevo.txt", "otro.txt"]
        # El viejo sigue abierto mientras se crea el nuevo: así no pueden compartir número.
        viejo = os.open(tmp_path / "nuevo.txt", os.O_RDONLY | os.O_CLOEXEC)
        try:
            os.unlink(tmp_path / "nuevo.txt")
            _crear(tmp_path, "nuevo.txt")
            assert os.listdir(descriptor) == ["otro.txt"]
        finally:
            os.close(viejo)
        assert sorted(os.listdir(descriptor)) == ["nuevo.txt", "otro.txt"]
        os.rename(tmp_path / "otro.txt", tmp_path / "renombrado.txt")
        assert os.listdir(descriptor) == ["nuevo.txt"]
        assert sorted(os.listdir(descriptor)) == ["nuevo.txt", "renombrado.txt"]
    finally:
        os.close(descriptor)


def test_con_una_ruta_la_lista_esta_al_dia(tmp_path, listar_como_btrfs):
    descriptor = _abrir(tmp_path)
    try:
        _crear(tmp_path, "nuevo.txt")
        assert os.listdir(tmp_path) == ["nuevo.txt"]
    finally:
        os.close(descriptor)


def test_sin_la_fixture_no_hay_simulacion():
    assert (os.open, os.listdir, os.lseek, os.close) == (OPEN_REAL, LISTDIR_REAL, LSEEK_REAL, CLOSE_REAL)
