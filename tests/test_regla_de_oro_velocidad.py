"""Regla de oro de la pestaña Velocidad.

fio escribe SOLO un archivo dentro de un directorio nuevo que crea Latido;
nunca en /dev, /proc o /sys, nunca en un archivo que ya existía, nunca a
través de un enlace simbólico ni de un shell. Ninguna prueba ejecuta el fio
real: se usa tests/fio_falso.py (y conftest.py hace fallar cualquier intento).
"""

import os
import subprocess
import tempfile
import threading
import time

import pytest

from conftest import StatvfsFalso, es_programa_prohibido
from latido.velocidad import ejecucion as ejecucion_mod
from latido.velocidad.carpeta import ErrorCarpeta, revisar_carpeta, validar_carpeta
from latido.velocidad.ejecucion import ENTORNO, Cancelado, Ejecucion, ErrorVelocidad
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import (
    ARCHIVO_PRUEBA,
    FIO,
    MIB,
    PREFIJO_DIRECTORIO,
    PRUEBAS,
    Configuracion,
    Direccion,
    Paso,
    RutaNoPermitida,
    comprobar_ruta_archivo,
    construir_comando,
)

ARCHIVO = "/media/datos/.latido-velocidad-abc12345/latido-velocidad.dat"
TAMANO = 1024**3


def _ejecucion(carpeta, fio_falso, configuracion=None, **opciones):
    def revisar(ruta, conf):
        return revisar_carpeta(ruta, conf, statvfs=lambda _ruta: StatvfsFalso(10**12))

    return Ejecucion(
        str(carpeta),
        configuracion or Configuracion(256 * MIB, 1),
        fio=str(fio_falso.ruta),
        comprobar=lambda fio: EstadoFio("fio-falso"),
        revisar=revisar,
        segundos_para_terminar=1,
        **opciones,
    )


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

def test_filename_dentro_del_directorio_nuevo(tmp_path, fio_falso):
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    ej = _ejecucion(carpeta, fio_falso)
    ej.ejecutar()
    invocaciones = fio_falso.invocaciones()
    assert len(invocaciones) == 1 + 8
    directorio = os.path.dirname(ej.archivo)
    assert os.path.dirname(directorio) == str(carpeta)
    assert os.path.basename(directorio).startswith(PREFIJO_DIRECTORIO)
    assert os.path.basename(ej.archivo) == ARCHIVO_PRUEBA
    for invocacion in invocaciones:
        nombres = [a for a in invocacion["argv"] if a.startswith("--filename=")]
        assert nombres == [f"--filename={ej.archivo}"]
        assert invocacion["cwd"] == directorio
    assert os.listdir(carpeta) == []


def test_nunca_shell_lista_ruta_absoluta_entorno_limpio_y_grupo_propio(tmp_path, fio_falso, monkeypatch):
    llamadas = []
    original = subprocess.Popen

    class PopenEspia(original):
        def __init__(self, args, *resto, **opciones):
            llamadas.append((args, opciones))
            super().__init__(args, *resto, **opciones)

    monkeypatch.setattr(ejecucion_mod.subprocess, "Popen", PopenEspia)
    ej = _ejecucion(tmp_path, fio_falso)
    ej.ejecutar()
    assert len(llamadas) == 9
    for args, opciones in llamadas:
        assert isinstance(args, list)
        assert args[0] == str(fio_falso.ruta) and os.path.isabs(args[0])
        assert not opciones.get("shell", False)
        assert opciones["env"] == ENTORNO == {"LC_ALL": "C"}
        assert opciones["start_new_session"] is True
        assert opciones["stdin"] is subprocess.DEVNULL
    for invocacion in fio_falso.invocaciones():
        assert invocacion["sid"] == invocacion["pid"] == invocacion["pgid"]  # sesión y grupo propios
        assert {k: v for k, v in invocacion["entorno"].items() if k != "LC_CTYPE"} == {"LC_ALL": "C"}


def test_nunca_usa_un_archivo_que_ya_existia(tmp_path, fio_falso, monkeypatch):
    """Si algo aparece en la ruta antes de crear el archivo, Latido no lo usa ni lo borra."""
    mkdtemp_real = tempfile.mkdtemp

    def mkdtemp_con_intruso(**opciones):
        directorio = mkdtemp_real(**opciones)
        with open(os.path.join(directorio, ARCHIVO_PRUEBA), "w", encoding="utf-8") as archivo:
            archivo.write("archivo que Latido no creó")
        return directorio

    monkeypatch.setattr(ejecucion_mod.tempfile, "mkdtemp", mkdtemp_con_intruso)
    ej = _ejecucion(tmp_path, fio_falso)
    with pytest.raises(ErrorVelocidad, match="no está vacía") as error:
        ej.ejecutar()
    assert fio_falso.invocaciones() == []
    intruso = os.path.join(os.path.dirname(ej.archivo), ARCHIVO_PRUEBA)
    with open(intruso, encoding="utf-8") as archivo:
        assert archivo.read() == "archivo que Latido no creó"
    assert not error.value.limpieza.completa
    assert any("no es el archivo de prueba de Latido" in p for p in error.value.limpieza.problemas)


def test_nunca_sigue_un_enlace_simbolico_en_la_ruta_del_archivo(tmp_path, fio_falso, monkeypatch):
    fuera = tmp_path / "fuera.txt"
    fuera.write_text("no tocar", encoding="utf-8")
    mkdtemp_real = tempfile.mkdtemp

    def mkdtemp_con_enlace(**opciones):
        directorio = mkdtemp_real(**opciones)
        os.symlink(fuera, os.path.join(directorio, ARCHIVO_PRUEBA))
        return directorio

    monkeypatch.setattr(ejecucion_mod.tempfile, "mkdtemp", mkdtemp_con_enlace)
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    with pytest.raises(ErrorVelocidad):
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert fio_falso.invocaciones() == []
    assert fuera.read_text(encoding="utf-8") == "no tocar"


def test_archivo_reemplazado_entre_pasos_detiene_la_prueba(tmp_path, fio_falso):
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    fio_falso.configurar(["ok", "reemplaza", "ok"])
    ej = _ejecucion(carpeta, fio_falso)
    with pytest.raises(ErrorVelocidad, match="cambió o desapareció") as error:
        ej.ejecutar()
    assert len(fio_falso.invocaciones()) == 2  # no se volvió a ejecutar fio
    # El archivo nuevo no es el que creó fio en la preparación: no se borra a ciegas.
    assert any("no es el archivo de prueba de Latido" in p for p in error.value.limpieza.problemas)


def test_enlace_simbolico_puesto_entre_pasos_no_se_sigue(tmp_path, fio_falso):
    fuera = tmp_path / "fuera.txt"
    fuera.write_text("no tocar", encoding="utf-8")
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    fio_falso.configurar(["ok", "enlaza", "ok"], enlace=str(fuera))
    with pytest.raises(ErrorVelocidad, match="cambió o desapareció"):
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert len(fio_falso.invocaciones()) == 2
    assert fuera.read_text(encoding="utf-8") == "no tocar"


# --- herramientas y carpeta ANTES de crear nada ---

def test_sin_fio_no_crea_nada(tmp_path, fio_falso):
    ej = Ejecucion(
        str(tmp_path), Configuracion(256 * MIB, 1), fio=str(fio_falso.ruta),
        comprobar=lambda fio: EstadoFio(problemas=["Falta fio (/usr/bin/fio). Instálalo con: sudo dnf install fio fio-engine-libaio"]),
    )
    with pytest.raises(ErrorVelocidad, match="sudo dnf install fio fio-engine-libaio") as error:
        ej.ejecutar()
    assert fio_falso.invocaciones() == []
    assert [n for n in os.listdir(tmp_path) if n.startswith(PREFIJO_DIRECTORIO)] == []
    assert error.value.limpieza.texto() == "No se llegó a crear ningún archivo."


def test_sin_espacio_no_crea_nada(tmp_path, fio_falso):
    def revisar(ruta, conf):
        return revisar_carpeta(ruta, conf, statvfs=lambda _ruta: StatvfsFalso(100 * MIB))

    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    ej = Ejecucion(
        str(carpeta), Configuracion(256 * MIB, 1), fio=str(fio_falso.ruta),
        comprobar=lambda fio: EstadoFio("fio-falso"), revisar=revisar,
    )
    with pytest.raises(ErrorVelocidad, match="No hay espacio suficiente"):
        ej.ejecutar()
    assert fio_falso.invocaciones() == []
    assert os.listdir(carpeta) == []


def test_carpeta_en_dev_no_crea_nada(fio_falso):
    ej = Ejecucion(
        "/dev/shm", Configuracion(256 * MIB, 1), fio=str(fio_falso.ruta),
        comprobar=lambda fio: EstadoFio("fio-falso"),
    )
    with pytest.raises(ErrorVelocidad, match="dentro de /dev"):
        ej.ejecutar()
    assert fio_falso.invocaciones() == []


def test_una_sola_prueba_a_la_vez(tmp_path, fio_falso):
    fio_falso.configurar(["duerme"])
    primera = _ejecucion(tmp_path, fio_falso)
    errores = []
    hilo = threading.Thread(target=lambda: errores.append(pytest.raises(Cancelado, primera.ejecutar)))
    hilo.start()
    limite = time.monotonic() + 10
    while not fio_falso.hijos() and time.monotonic() < limite:
        time.sleep(0.02)
    try:
        segunda = _ejecucion(tmp_path, fio_falso)
        with pytest.raises(ErrorVelocidad, match="Ya hay una prueba de velocidad en marcha"):
            segunda.ejecutar()
    finally:
        primera.cancelar()
        hilo.join(15)
    assert len(errores) == 1  # la primera terminó en Cancelado
    assert len(fio_falso.invocaciones()) == 1


def test_la_guardia_de_las_pruebas_detecta_fio_y_git_reales():
    assert es_programa_prohibido(["/usr/bin/fio", "--version"])
    assert es_programa_prohibido(["fio"])
    assert es_programa_prohibido(["git", "status"])
    assert es_programa_prohibido("/usr/bin/git")
    assert not es_programa_prohibido(["/tmp/x/fio_falso"])
    with pytest.raises(AssertionError, match="prohibidos"):
        subprocess.run(["/usr/bin/fio", "--version"], check=False)
