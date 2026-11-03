"""El simulador de reutilización de números de inodo (fixture reutilizar_inodos de conftest.py).

Estas pruebas no dependen de que el sistema de archivos repita números: cuando
necesitan que los números reales sean distintos, crean el archivo nuevo
mientras el anterior todavía existe. Que dos archivos que existen a la vez no
compartan número dentro de un mismo sistema de archivos (man 7 inode) se
afirma solo para sistemas de archivos locales; overlayfs, NFS y FUSE no están
probados.
"""

import os

from conftest import FSTAT_REAL, LSTAT_REAL, STAT_REAL

NOMBRE = "latido-velocidad.dat"


def _crear(ruta):
    with open(ruta, "xb") as archivo:
        archivo.write(b"x")


def test_con_la_fixture_stat_lstat_y_fstat_son_los_del_simulador(reutilizar_inodos):
    assert (os.stat, os.lstat, os.fstat) == (reutilizar_inodos.stat, reutilizar_inodos.lstat, reutilizar_inodos.fstat)


def test_no_repite_el_numero_mientras_el_original_esta_abierto(tmp_path, reutilizar_inodos):
    ruta = tmp_path / NOMBRE
    _crear(ruta)
    original = os.stat(ruta)
    descriptor = os.open(ruta, os.O_RDONLY)
    try:
        os.unlink(ruta)
        _crear(ruta)
        nuevo = os.stat(ruta)
        abierto = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    assert nuevo.st_ino != original.st_ino
    assert (abierto.st_dev, abierto.st_ino, abierto.st_nlink) == (original.st_dev, original.st_ino, 0)
    assert reutilizar_inodos.decisiones == [(NOMBRE, "anterior abierto")]


def test_repite_el_numero_cuando_el_original_ya_no_existe(tmp_path, reutilizar_inodos):
    ruta = tmp_path / NOMBRE
    _crear(ruta)
    original = os.stat(ruta)
    _crear(tmp_path / "nuevo.tmp")  # existe a la vez que el original: su número real es otro
    os.unlink(ruta)
    os.rename(tmp_path / "nuevo.tmp", ruta)
    assert LSTAT_REAL(ruta).st_ino != original.st_ino
    visto = os.lstat(ruta)
    assert (visto.st_dev, visto.st_ino) == (original.st_dev, original.st_ino)
    assert os.stat(str(ruta)).st_ino == original.st_ino
    carpeta = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert os.stat(NOMBRE, dir_fd=carpeta, follow_symlinks=False).st_ino == original.st_ino
    finally:
        os.close(carpeta)
    descriptor = os.open(ruta, os.O_RDONLY)
    try:
        assert os.fstat(descriptor).st_ino == original.st_ino
    finally:
        os.close(descriptor)
    assert reutilizar_inodos.decisiones == [(NOMBRE, "reutilizado")]


def test_no_repite_el_numero_si_el_anterior_sigue_con_otro_nombre(tmp_path, reutilizar_inodos):
    ruta = tmp_path / NOMBRE
    _crear(ruta)
    original = os.stat(ruta)
    os.rename(ruta, tmp_path / "guardado.dat")
    _crear(ruta)
    assert os.stat(ruta).st_ino != original.st_ino
    assert reutilizar_inodos.decisiones == [(NOMBRE, "anterior con nombre")]


def test_solo_afecta_a_los_nombres_indicados(tmp_path, reutilizar_inodos):
    ruta = tmp_path / "otro.dat"
    _crear(ruta)
    original = os.stat(ruta)
    _crear(tmp_path / "nuevo.tmp")
    os.unlink(ruta)
    os.rename(tmp_path / "nuevo.tmp", ruta)
    assert os.stat(ruta).st_ino != original.st_ino
    assert reutilizar_inodos.decisiones == []


def test_sin_la_fixture_no_hay_simulacion():
    """No es autouse y monkeypatch la deshace: aquí os.stat, os.lstat y os.fstat son los reales."""
    assert (os.stat, os.lstat, os.fstat) == (STAT_REAL, LSTAT_REAL, FSTAT_REAL)
