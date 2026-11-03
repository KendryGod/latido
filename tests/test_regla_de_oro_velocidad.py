"""Regla de oro de la pestaña Velocidad.

fio escribe SOLO un archivo dentro de un directorio nuevo que crea Latido;
nunca en /dev, /proc o /sys, nunca a través de un enlace simbólico. Ninguna
prueba ejecuta el fio real (conftest.py hace fallar cualquier intento).
"""

import subprocess

import pytest

from conftest import es_programa_prohibido
from latido.velocidad.carpeta import ErrorCarpeta, validar_carpeta
from latido.velocidad.pruebas import (
    FIO,
    PRUEBAS,
    Direccion,
    Paso,
    RutaNoPermitida,
    comprobar_ruta_archivo,
    construir_comando,
)

ARCHIVO = "/media/datos/.latido-velocidad-abc12345/latido-velocidad.dat"
TAMANO = 1024**3


# --- el comando exacto ---

def test_ruta_absoluta_de_fio():
    assert FIO == "/usr/bin/fio"


def test_comando_exacto_preparacion():
    assert construir_comando(Paso(), ARCHIVO, TAMANO) == [
        "/usr/bin/fio", "--output-format=json", "--eta=never",
        "--name=latido-preparar", f"--filename={ARCHIVO}", "--ioengine=libaio", "--direct=1",
        "--rw=write", "--bs=1048576", "--iodepth=8", "--numjobs=1", "--size=1073741824",
    ]


ESPERADOS = {
    ("seq1m-q8t1", "read"): ("read", 1048576, 8),
    ("seq1m-q8t1", "write"): ("write", 1048576, 8),
    ("seq1m-q1t1", "read"): ("read", 1048576, 1),
    ("seq1m-q1t1", "write"): ("write", 1048576, 1),
    ("rnd4k-q32t1", "read"): ("randread", 4096, 32),
    ("rnd4k-q32t1", "write"): ("randwrite", 4096, 32),
    ("rnd4k-q1t1", "read"): ("randread", 4096, 1),
    ("rnd4k-q1t1", "write"): ("randwrite", 4096, 1),
}


@pytest.mark.parametrize("prueba", PRUEBAS, ids=lambda p: p.clave)
@pytest.mark.parametrize("direccion", list(Direccion), ids=lambda d: d.texto)
def test_comando_exacto_de_cada_medicion(prueba, direccion):
    rw, bloque, cola = ESPERADOS[(prueba.clave, direccion.value)]
    lectura = direccion is Direccion.LECTURA
    assert construir_comando(Paso(prueba, direccion, 1), ARCHIVO, TAMANO) == [
        "/usr/bin/fio", "--output-format=json", "--eta=never",
        *(["--readonly"] if lectura else []),
        f"--name=latido-{prueba.clave}-{direccion.texto}", f"--filename={ARCHIVO}",
        "--ioengine=libaio", "--direct=1", f"--rw={rw}", f"--bs={bloque}", f"--iodepth={cola}",
        "--numjobs=1", "--size=1073741824", "--runtime=5", "--allow_file_create=0",
    ]


def test_las_cuatro_pruebas_pedidas():
    assert [(p.nombre, p.bloque, p.cola, p.hilos, p.aleatoria) for p in PRUEBAS] == [
        ("SEQ1M Q8T1", 1048576, 8, 1, False),
        ("SEQ1M Q1T1", 1048576, 1, 1, False),
        ("RND4K Q32T1", 4096, 32, 1, True),
        ("RND4K Q1T1", 4096, 1, 1, True),
    ]


@pytest.mark.parametrize("archivo", [
    "/dev/sda",
    "/dev/nvme0n1",
    "/dev/.latido-velocidad-x/latido-velocidad.dat",
    "/proc/.latido-velocidad-x/latido-velocidad.dat",
    "/sys/.latido-velocidad-x/latido-velocidad.dat",
    "relativo/.latido-velocidad-x/latido-velocidad.dat",
    "/media/a/../.latido-velocidad-x/latido-velocidad.dat",
    "/media/a:b/.latido-velocidad-x/latido-velocidad.dat",
    "/media/$ncpus/.latido-velocidad-x/latido-velocidad.dat",
    "/media/a\\b/.latido-velocidad-x/latido-velocidad.dat",
    "/media/a\nb/.latido-velocidad-x/latido-velocidad.dat",
    "/media/datos/latido-velocidad.dat",  # sin el directorio de Latido
    "/media/datos/.latido-velocidad-x/otro.dat",  # otro nombre de archivo
    "/media/datos/.latido-velocidad-x",
    "-",  # stdin/stdout para fio
])
def test_construir_comando_rechaza_rutas_peligrosas(archivo):
    with pytest.raises(RutaNoPermitida):
        construir_comando(Paso(), archivo, TAMANO)


def test_acepta_solo_el_archivo_de_prueba():
    assert comprobar_ruta_archivo(ARCHIVO) == ARCHIVO


# --- la carpeta elegida ---

@pytest.mark.parametrize("ruta", ["/dev", "/dev/shm", "/proc", "/proc/self", "/sys", "/sys/class/block"])
def test_rechaza_dev_proc_sys(ruta):
    with pytest.raises(ErrorCarpeta, match="no hace pruebas dentro de"):
        validar_carpeta(ruta)


def test_rechaza_enlace_simbolico_que_lleva_a_dev(tmp_path):
    enlace = tmp_path / "parece_normal"
    enlace.symlink_to("/dev")
    with pytest.raises(ErrorCarpeta, match="dentro de /dev"):
        validar_carpeta(str(enlace))


def test_rechaza_enlace_simbolico_y_dice_la_ruta_real(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    enlace = tmp_path / "enlace"
    enlace.symlink_to(real)
    with pytest.raises(ErrorCarpeta, match="enlace simbólico") as error:
        validar_carpeta(str(enlace))
    assert str(real) in str(error.value)


def test_rechaza_lo_que_no_existe_o_no_es_carpeta(tmp_path):
    with pytest.raises(ErrorCarpeta, match="no existe"):
        validar_carpeta(str(tmp_path / "no-existe"))
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("x", encoding="utf-8")
    with pytest.raises(ErrorCarpeta, match="no es una carpeta"):
        validar_carpeta(str(archivo))


def test_rechaza_carpeta_sin_permiso_de_escritura(tmp_path, monkeypatch):
    # Se simula con os.access: en la CI las pruebas corren como root y chmod no bastaría.
    monkeypatch.setattr("latido.velocidad.carpeta.os.access", lambda ruta, modo: False)
    with pytest.raises(ErrorCarpeta, match="permiso para escribir"):
        validar_carpeta(str(tmp_path))


@pytest.mark.parametrize("nombre", ["a:b", "precio$ncpus", "barra\\invertida", "salto\nde_linea"])
def test_rechaza_caracteres_que_fio_interpreta(tmp_path, nombre):
    carpeta = tmp_path / nombre
    carpeta.mkdir()
    with pytest.raises(ErrorCarpeta, match="fio interpreta|caracteres de control"):
        validar_carpeta(str(carpeta))


def test_rechaza_ruta_relativa_o_vacia():
    for ruta in ("", "relativa/carpeta", None):
        with pytest.raises(ErrorCarpeta):
            validar_carpeta(ruta)


def test_acepta_carpeta_normal(tmp_path):
    assert validar_carpeta(str(tmp_path)) == str(tmp_path)


# --- lo que de verdad recibe fio (con el fio falso) ---


# --- herramientas y carpeta ANTES de crear nada ---


def test_la_guardia_de_las_pruebas_detecta_fio_y_git_reales():
    assert es_programa_prohibido(["/usr/bin/fio", "--version"])
    assert es_programa_prohibido(["fio"])
    assert es_programa_prohibido(["git", "status"])
    assert es_programa_prohibido("/usr/bin/git")
    assert not es_programa_prohibido(["/tmp/x/fio_falso"])
    with pytest.raises(AssertionError, match="prohibidos"):
        subprocess.run(["/usr/bin/fio", "--version"], check=False)
