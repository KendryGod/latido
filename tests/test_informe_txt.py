"""Informe TXT (menú «Exportar informe»): contenido, privacidad y escritura segura."""

import getpass
import os
import socket
import stat
from datetime import datetime
from pathlib import Path

import pytest

from conftest import FIXTURES, cargar, esperar
from latido.informe_txt import (
    MARCA_DEMO,
    ErrorExportar,
    VelocidadMedida,
    construir_texto,
    destino_permitido,
    escribir_informe,
    nombre_por_defecto,
)
from latido.salud import analizar
from latido.sistema.discos import Disco
from latido.sistema.lectura import cargar_fixture
from latido.velocidad.pruebas import MIB, PRUEBAS, Configuracion, Direccion, Paso
from latido.velocidad.resultado import ResultadoVelocidad, leer_salida_fio

REFERENCIA = Path(__file__).parent / "fixtures" / "informe" / "nvme_real.txt"
FIO = Path(__file__).parent / "fixtures" / "fio"
FECHA = datetime(2026, 11, 3, 14, 30)
SERIE = "SINTETICO-0003-QWE"


def _disco():
    return Disco(nombre="nvme0n1", ruta="/dev/nvme0n1", ruta_lectura="/dev/nvme0", modelo="KINGSTON SNV2S1000G",
                 tamano=1000204886016, transporte="nvme", es_sistema=True, habilitado=True, aviso=None)


def _velocidad():
    resultado = ResultadoVelocidad(1)
    for prueba in PRUEBAS:
        for direccion in Direccion:
            paso = Paso(prueba, direccion, 1)
            texto = (FIO / f"{paso.trabajo}.json").read_text(encoding="utf-8")
            resultado.agregar(paso, leer_salida_fio(texto, 0, "", paso.trabajo, direccion))
    return VelocidadMedida(resultado, Configuracion(256 * MIB, 1), "btrfs")


def test_contenido_de_referencia_con_el_fixture_real():
    texto = construir_texto(cargar_fixture(FIXTURES / "nvme_real.json"), _disco(), _velocidad(), fecha=FECHA)
    assert texto == REFERENCIA.read_text(encoding="utf-8")


def test_nunca_lleva_datos_personales(tmp_path):
    datos = cargar("nvme_real.json")
    datos["serial_number"] = SERIE  # solo en memoria
    texto = construir_texto(analizar(datos), _disco(), _velocidad(), fecha=FECHA)
    prohibidos = [SERIE, getpass.getuser(), socket.gethostname(), str(Path.home()), str(tmp_path), "io.github."]
    for prohibido in prohibidos:
        if prohibido and prohibido != "fedora":  # «fedora» es el nombre genérico del equipo y no se escribe
            assert prohibido not in texto, prohibido
    assert "Número de serie" not in texto and "serie" not in texto.lower()


@pytest.mark.parametrize("archivo", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_lineas_de_80_columnas_como_maximo(archivo):
    texto = construir_texto(analizar(cargar(archivo)), _disco(), _velocidad(), fecha=FECHA, demo=True)
    assert max(len(linea) for linea in texto.splitlines()) <= 80


def test_dice_que_es_una_lectura_puntual_y_la_version():
    from latido import __version__

    texto = construir_texto(analizar(cargar("nvme_real.json")), fecha=FECHA)
    assert f"Versión de Latido: {__version__}" in texto
    assert "Fecha: 2026-11-03 14:30" in texto
    assert "Es una lectura puntual" in texto
    assert "Sin una prueba de velocidad terminada en esta sesión." in texto


def test_modo_demo_lleva_la_marca_arriba_y_abajo():
    lineas = construir_texto(analizar(cargar("nvme_real.json")), fecha=FECHA, demo=True).splitlines()
    assert lineas[1] == MARCA_DEMO == "DATOS DE EJEMPLO, NO SON DE TU DISCO"
    assert lineas[-1] == MARCA_DEMO


def test_secciones_en_el_orden_de_la_pantalla():
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), fecha=FECHA)
    secciones = [linea.split(":")[0] for linea in texto.splitlines() if linea[:1].isupper() and
                 linea.split(":")[0].isupper()]
    assert secciones == ["DISCO", "SALUD", "CIFRAS CLAVE", "AUTENTICIDAD", "TODOS LOS DATOS", "VELOCIDAD"]


def test_nombre_por_defecto():
    assert nombre_por_defecto(FECHA) == "latido-informe-2026-11-03.txt"


# --- escritura ---


@pytest.mark.parametrize("ruta", ["/dev/latido.txt", "/proc/latido.txt", "/sys/latido.txt", "/dev/shm/latido.txt"])
def test_destinos_prohibidos(ruta):
    assert not destino_permitido(ruta)
    with pytest.raises(ErrorExportar, match="/dev, /proc ni /sys"):
        escribir_informe(ruta, "x")


def test_tampoco_a_traves_de_un_enlace_simbolico(tmp_path):
    (tmp_path / "atajo").symlink_to("/proc")
    with pytest.raises(ErrorExportar):
        escribir_informe(tmp_path / "atajo" / "latido.txt", "x")


def test_escribe_con_modo_0600_sin_dejar_temporales(tmp_path):
    destino = tmp_path / "latido-informe.txt"
    destino.write_text("viejo", encoding="utf-8")
    escribir_informe(destino, "nuevo\n")
    assert destino.read_text(encoding="utf-8") == "nuevo\n"
    assert stat.S_IMODE(os.stat(destino).st_mode) == 0o600
    assert sorted(os.listdir(tmp_path)) == ["latido-informe.txt"]


def test_si_falla_no_deja_el_temporal(tmp_path):
    (tmp_path / "carpeta").mkdir()
    with pytest.raises(OSError):
        escribir_informe(tmp_path / "carpeta", "x")  # el destino es una carpeta: os.replace falla
    assert sorted(os.listdir(tmp_path)) == ["carpeta"]


# --- en la ventana ---


def _ventana():
    from latido.ui.ventana import VentanaPrincipal

    return VentanaPrincipal([_disco()], lambda disco: None)


def test_exportar_solo_con_un_informe_en_pantalla(gtk):
    from latido.sistema.lectura import ErrorLectura, TipoError

    ventana = _ventana()
    assert not ventana.lookup_action("exportar").get_enabled()
    ventana.pagina_salud.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco())
    assert ventana.lookup_action("exportar").get_enabled()
    ventana.pagina_salud.mostrar_error(ErrorLectura(TipoError.CANCELADO, "x"))
    assert not ventana.lookup_action("exportar").get_enabled()


def test_guardar_desde_la_ventana_con_la_velocidad_medida(gtk, tmp_path):
    GLib, _ = gtk
    ventana = _ventana()
    ventana.pagina_salud.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco())
    ventana.pagina_velocidad.velocidad_medida = _velocidad()
    texto = ventana.texto_del_informe(FECHA)
    assert texto == REFERENCIA.read_text(encoding="utf-8")
    assert ventana.guardar_informe(tmp_path / "informe.txt", texto)
    assert (tmp_path / "informe.txt").read_text(encoding="utf-8") == texto
    assert not ventana.guardar_informe("/proc/informe.txt", texto)
    esperar(GLib, lambda: False, 0.1)
