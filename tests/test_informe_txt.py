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


def _velocidad(disco="el de salud"):
    """La velocidad medida con los fixtures de fio, en el disco que se diga (por defecto, el de _disco())."""
    resultado = ResultadoVelocidad(1)
    for prueba in PRUEBAS:
        for direccion in Direccion:
            paso = Paso(prueba, direccion, 1)
            texto = (FIO / f"{paso.trabajo}.json").read_text(encoding="utf-8")
            resultado.agregar(paso, leer_salida_fio(texto, 0, "", paso.trabajo, direccion))
    return VelocidadMedida(resultado, Configuracion(256 * MIB, 1), "btrfs",
                           disco=_disco() if disco == "el de salud" else disco)


def _seccion_velocidad(texto):
    lineas = texto.splitlines()
    return lineas[lineas.index("VELOCIDAD") + 1:]


AVISO_OTRO_DISCO = "  ATENCIÓN: la velocidad se midió en otro disco que el de este informe."
USB = Disco(nombre="sdb", ruta="/dev/sdb", ruta_lectura=None, modelo="Disco USB", tamano=500107862016,
            transporte="usb", es_sistema=False, habilitado=False, aviso=None)


def test_velocidad_dice_en_que_disco_se_midio():
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), _velocidad(), fecha=FECHA)
    assert _seccion_velocidad(texto)[0] == f"  Medida en: {_disco().etiqueta_corta}"
    assert "ATENCIÓN" not in texto


def test_velocidad_en_otro_disco_avisa_en_la_primera_linea():
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), _velocidad(USB), fecha=FECHA)
    seccion = _seccion_velocidad(texto)
    assert seccion[0] == AVISO_OTRO_DISCO
    assert seccion[1] == f"  Medida en: {USB.etiqueta_corta}"
    assert texto.count("ATENCIÓN") == 1


def test_mismo_modelo_y_capacidad_pero_otro_disco_tambien_avisa():
    """Dos discos iguales: se distinguen por el dispositivo, no por la etiqueta."""
    gemelo = Disco(**{**_disco().__dict__, "nombre": "nvme1n1", "ruta": "/dev/nvme1n1", "ruta_lectura": "/dev/nvme1"})
    assert gemelo.etiqueta_corta == _disco().etiqueta_corta
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), _velocidad(gemelo), fecha=FECHA)
    assert _seccion_velocidad(texto)[0] == AVISO_OTRO_DISCO


def test_velocidad_sin_saber_el_disco():
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), _velocidad(None), fecha=FECHA)
    seccion = _seccion_velocidad(texto)
    assert seccion[0].startswith("  No se pudo saber en qué disco")
    assert "Medida en:" not in texto and "ATENCIÓN" not in texto


def test_sin_velocidad_no_dice_disco():
    texto = construir_texto(analizar(cargar("nvme_real.json")), _disco(), None, fecha=FECHA)
    assert _seccion_velocidad(texto) == ["  Sin una prueba de velocidad terminada en esta sesión."]


def test_contenido_de_referencia_con_el_fixture_real():
    texto = construir_texto(cargar_fixture(FIXTURES / "nvme_real.json"), _disco(), _velocidad(), fecha=FECHA)
    assert texto == REFERENCIA.read_text(encoding="utf-8")


def test_cifra_temperatura_en_txt_incluye_tiempo_en_umbral_critico():
    texto = construir_texto(analizar(cargar("sintetico_temp_critica.json")), _disco(), fecha=FECHA)
    assert "  Temperatura:          41 °C · Atención" in texto
    assert "Umbrales del disco: advertencia 80 °C · crítica 85 °C." in texto
    assert "Pasó 37 min por encima del umbral crítico" in texto



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


def test_escribir_informe_con_sustituto_suelto_lanza_unicode_error_sin_dejar_temporales(tmp_path):
    antes = sorted(os.listdir(tmp_path))
    with pytest.raises(UnicodeEncodeError):
        escribir_informe(tmp_path / "informe.txt", "modelo: DISCO\udcff\n")
    assert sorted(os.listdir(tmp_path)) == antes == []


def test_escribir_informe_con_sustituto_suelto_deja_intacto_el_destino_previo(tmp_path):
    destino = tmp_path / "informe.txt"
    contenido_previo = b"informe anterior intacto\n\x00\xff"
    destino.write_bytes(contenido_previo)
    antes = sorted(os.listdir(tmp_path))
    with pytest.raises(UnicodeEncodeError):
        escribir_informe(destino, "modelo: DISCO\udcff\n")
    assert sorted(os.listdir(tmp_path)) == antes == ["informe.txt"]
    assert destino.read_bytes() == contenido_previo


# --- en la ventana ---


def _ventana():
    from latido.ui.ventana import VentanaPrincipal

    return VentanaPrincipal([_disco()], lambda disco: None)


def _registrar_toasts(ventana, monkeypatch):
    toasts = []
    original = ventana.toasts.add_toast

    def capturar(toast):
        toasts.append(toast.get_title())
        return original(toast)

    monkeypatch.setattr(ventana.toasts, "add_toast", capturar)
    return toasts


class _ArchivoFalso:
    def __init__(self, ruta):
        self._ruta = ruta

    def get_path(self):
        return self._ruta


class _DialogoFalso:
    def __init__(self, archivo=None, error=None):
        self._archivo = archivo
        self._error = error

    def save_finish(self, _resultado):
        if self._error is not None:
            raise self._error
        return self._archivo


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


def test_callback_con_sustituto_suelto_muestra_un_solo_toast_sin_excepcion(gtk, tmp_path, monkeypatch):
    from latido.ui import ventana as mod_ventana

    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)
    destino = tmp_path / "informe.txt"
    destino.write_bytes(b"intacto")
    dialogo = _DialogoFalso(_ArchivoFalso(str(destino)))

    ventana._destino_elegido(dialogo, None, "texto con \udcff")

    esperado = getattr(
        mod_ventana,
        "AVISO_TEXTO_INVALIDO",
        "No se pudo guardar el informe: hay caracteres que no se pueden escribir en texto.",
    )
    assert hasattr(mod_ventana, "AVISO_TEXTO_INVALIDO")
    assert toasts == [esperado]
    for prohibido in (str(destino), str(tmp_path), "codec", "surrogate", "utf-8", "\udcff", "&", "<"):
        assert prohibido not in toasts[0].lower()
    assert destino.read_bytes() == b"intacto"
    assert sorted(os.listdir(tmp_path)) == ["informe.txt"]


def test_callback_con_byte_nulo_en_la_ruta_muestra_toast_de_ruta_invalida(gtk, tmp_path, monkeypatch):
    from latido.ui import ventana as mod_ventana

    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)
    ruta_nula = str(tmp_path / "x\0y.txt")
    dialogo = _DialogoFalso(_ArchivoFalso(ruta_nula))

    ventana._destino_elegido(dialogo, None, "hola\n")

    esperado = getattr(mod_ventana, "AVISO_RUTA_INVALIDA", "Elige una carpeta de un disco local.")
    assert hasattr(mod_ventana, "AVISO_RUTA_INVALIDA")
    assert toasts == [esperado]
    assert os.listdir(tmp_path) == []


def test_callback_con_get_path_none_muestra_toast_de_ruta_invalida_sin_escribir(gtk, tmp_path, monkeypatch):
    from latido.ui import ventana as mod_ventana

    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)
    dialogo = _DialogoFalso(_ArchivoFalso(None))

    ventana._destino_elegido(dialogo, None, "hola\n")
    assert not ventana.guardar_informe(None, "hola\n")

    esperado = getattr(mod_ventana, "AVISO_RUTA_INVALIDA", "Elige una carpeta de un disco local.")
    assert hasattr(mod_ventana, "AVISO_RUTA_INVALIDA")
    assert toasts == [esperado, esperado]
    assert os.listdir(tmp_path) == []


def test_callback_no_traga_excepciones_no_previstas(gtk, tmp_path, monkeypatch):
    from latido.ui import ventana as mod_ventana

    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)

    def fallar(_ruta, _texto):
        raise RuntimeError("fallo interno inesperado")

    monkeypatch.setattr(mod_ventana, "escribir_informe", fallar)
    with pytest.raises(RuntimeError, match="fallo interno inesperado"):
        ventana.guardar_informe(tmp_path / "informe.txt", "hola\n")
    assert toasts == []


def test_callback_oserror_y_destino_prohibido_conservan_sus_toasts(gtk, tmp_path, monkeypatch):
    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)

    assert not ventana.guardar_informe(tmp_path / "no-existe" / "informe.txt", "hola\n")
    assert len(toasts) == 1 and toasts[0].startswith("No se pudo guardar el informe:")

    assert not ventana.guardar_informe("/proc/latido.txt", "hola\n")
    assert len(toasts) == 2 and "/dev, /proc ni /sys" in toasts[1]


def test_callback_cancelar_el_dialogo_no_muestra_ningun_toast(gtk, monkeypatch):
    GLib, Gtk = gtk
    ventana = _ventana()
    toasts = _registrar_toasts(ventana, monkeypatch)
    error_cancelado = GLib.Error.new_literal(Gtk.DialogError.quark(), "Dismissed", int(Gtk.DialogError.DISMISSED))
    dialogo = _DialogoFalso(error=error_cancelado)

    ventana._destino_elegido(dialogo, None, "hola\n")
    assert toasts == []


def test_tras_fallo_exportar_sigue_habilitado_y_permite_guardar(gtk, tmp_path, monkeypatch):
    from latido.ui import ventana as mod_ventana

    ventana = _ventana()
    ventana.pagina_salud.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco())
    assert ventana.lookup_action("exportar").get_enabled()
    toasts = _registrar_toasts(ventana, monkeypatch)

    assert not ventana.guardar_informe(tmp_path / "informe.txt", "malo \udcff\n")
    assert ventana.lookup_action("exportar").get_enabled()

    destino = tmp_path / "informe.txt"
    texto = ventana.texto_del_informe(FECHA)
    assert ventana.guardar_informe(destino, texto)
    assert ventana.lookup_action("exportar").get_enabled()
    esperado_exito = getattr(mod_ventana, "AVISO_INFORME_GUARDADO", "Informe guardado.")
    assert hasattr(mod_ventana, "AVISO_INFORME_GUARDADO")
    assert toasts[-1] == esperado_exito
    assert destino.read_text(encoding="utf-8") == texto
    assert stat.S_IMODE(os.stat(destino).st_mode) == 0o600

