"""Interfaz de la pestaña Velocidad, con Gdk.Display real (fixture gtk de conftest.py).

Sin pantalla se saltan con motivo; con REQUIRE_DISPLAY=1 fallan. Nunca se
ejecuta el fio real: los servicios usan tests/fio_falso.py y falsos.
"""

import os
import time

import pytest

from conftest import StatvfsFalso, esperar, vivo
from latido.velocidad.carpeta import InfoCarpeta, Revision, revisar_carpeta
from latido.velocidad.ejecucion import Ejecucion
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import GIB, TAMANOS, Direccion
from latido.velocidad.restos import guardar_ultima_carpeta


class Espia:
    def __init__(self):
        self.llamadas = []

    def __call__(self, nombre, funcion):
        def envoltura(*args, **kwargs):
            self.llamadas.append(nombre)
            return funcion(*args, **kwargs)
        return envoltura


def _revisar_con_espacio(ruta, configuracion):
    return revisar_carpeta(ruta, configuracion, statvfs=lambda _ruta: StatvfsFalso(500 * GIB))


def _servicios(fio_falso=None, estado_fio=None, revisar=_revisar_con_espacio, espia=None):
    from latido.ui.pagina_velocidad import ServiciosVelocidad

    espia = espia or Espia()
    estado_fio = estado_fio or EstadoFio("fio-3.40")

    def crear(carpeta, configuracion, al_progresar=None):
        return Ejecucion(
            carpeta, configuracion, al_progresar, fio=str(fio_falso.ruta),
            comprobar=lambda fio: estado_fio, revisar=revisar, segundos_para_terminar=1,
        )

    base = ServiciosVelocidad()
    return ServiciosVelocidad(
        comprobar_fio=espia("comprobar_fio", lambda: estado_fio),
        revisar_carpeta=espia("revisar_carpeta", revisar),
        crear_ejecucion=espia("crear_ejecucion", crear),
        leer_ultima_carpeta=espia("leer_ultima_carpeta", base.leer_ultima_carpeta),
        buscar_restos=espia("buscar_restos", base.buscar_restos),
        borrar_resto=espia("borrar_resto", base.borrar_resto),
    )


def _ventana(servicios):
    from latido.ui.ventana import VentanaPrincipal

    return VentanaPrincipal([], lambda disco: None, servicios_velocidad=servicios)


def _abrir_pestana(ventana):
    ventana.pila.set_visible_child(ventana.pagina_velocidad)
    return ventana.pagina_velocidad


@pytest.fixture
def carpeta(tmp_path):
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    return carpeta


def test_pestana_velocidad_junto_a_salud(gtk):
    from gi.repository import Gdk

    ventana = _ventana(_servicios())
    paginas = [ventana.pila.get_page(hijo) for hijo in (ventana.pagina_salud, ventana.pagina_velocidad)]
    assert [p.get_title() for p in paginas] == ["Salud", "Velocidad"]
    tema = gtk[1].IconTheme.get_for_display(Gdk.Display.get_default())
    for pagina in paginas:
        assert tema.has_icon(pagina.get_icon_name()), pagina.get_icon_name()
    assert ventana.pila.get_visible_child() is ventana.pagina_salud


def test_al_construir_no_ejecuta_nada(gtk):
    espia = Espia()
    _ventana(_servicios(espia=espia))
    assert espia.llamadas == []


def test_al_abrir_la_pestana_comprueba_fio_y_busca_restos(gtk):
    espia = Espia()
    pagina = _abrir_pestana(_ventana(_servicios(espia=espia)))
    assert espia.llamadas == ["comprobar_fio", "leer_ultima_carpeta"]
    assert pagina.fila_fio.get_subtitle() == "fio-3.40 con motor libaio"
    assert not pagina.banner.get_revealed()
    assert not pagina.boton.get_sensitive()  # falta la carpeta


def test_falta_fio_se_dice_y_no_deja_iniciar(gtk, carpeta):
    problema = "Falta fio (/usr/bin/fio). Instálalo con: sudo dnf install fio fio-engine-libaio"
    pagina = _abrir_pestana(_ventana(_servicios(estado_fio=EstadoFio(problemas=[problema]))))
    pagina.elegir_carpeta(str(carpeta))
    assert pagina.fila_fio.get_subtitle() == problema
    assert not pagina.boton.get_sensitive()


def test_resumen_antes_de_iniciar(gtk, carpeta):
    def revisar(ruta, configuracion):
        info = InfoCarpeta(ruta=ruta, tipo="btrfs", punto_montaje="/home", fuente="/dev/nvme0n1p5",
                           libre=int(366.5 * GIB), disco_sistema=True, discos=frozenset({"nvme0n1"}))
        return Revision(info=info, avisos=["aviso de desgaste", "aviso del disco del sistema"])

    pagina = _abrir_pestana(_ventana(_servicios(revisar=revisar)))
    pagina.elegir_carpeta(str(carpeta))
    assert pagina.fila_carpeta.get_subtitle() == str(carpeta)
    assert pagina.fila_libre.get_subtitle() == "366.5 GiB libres · hacen falta 2 GiB (1 GiB + 1 GiB de margen)"
    assert pagina.fila_sistema.get_subtitle() == "btrfs · /dev/nvme0n1p5 montado en /home"
    assert pagina.fila_escritura.get_subtitle() == "13 GiB (13.96 GB) como máximo"
    assert [f.get_title() for f in pagina._filas_avisos] == ["aviso de desgaste", "aviso del disco del sistema"]
    assert pagina.boton.get_sensitive() and pagina.boton.get_label() == "Iniciar"


def test_tamano_y_pasadas_por_defecto_y_al_cambiarlos(gtk, carpeta):
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert TAMANOS[pagina.fila_tamano.get_selected()] == GIB
    assert pagina.fila_pasadas.get_value() == 3
    pagina.fila_tamano.set_selected(TAMANOS.index(2 * GIB))
    pagina.fila_pasadas.set_value(1)
    assert pagina.configuracion().tamano == 2 * GIB and pagina.configuracion().pasadas == 1
    assert pagina.fila_escritura.get_subtitle() == "10 GiB (10.74 GB) como máximo"


def test_carpeta_invalida_muestra_el_error_y_no_deja_iniciar(gtk):
    pagina = _abrir_pestana(_ventana(_servicios()))
    pagina.elegir_carpeta("/dev/shm")
    assert [f.get_title() for f in pagina._filas_avisos] == [
        "Latido no hace pruebas dentro de /dev (la carpeta está en «/dev/shm»)."
    ]
    assert not pagina.boton.get_sensitive()


def test_unidades_explicadas_en_pantalla(gtk):
    pagina = _ventana(_servicios()).pagina_velocidad
    assert "MB/s = 1,000,000 bytes por segundo" in pagina.nota.get_text()
    assert "no se guardan" in pagina.nota.get_text()
    assert [c.prueba.nombre for c in pagina.cuadros.values()] == ["SEQ1M Q8T1", "SEQ1M Q1T1", "RND4K Q32T1", "RND4K Q1T1"]


def test_prueba_completa_con_fio_falso(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    assert pagina.en_marcha and pagina.boton.get_label() == "Cancelar"
    assert not pagina.boton_carpeta.get_sensitive()
    esperar(GLib, lambda: not pagina.en_marcha, 30)
    assert not pagina.en_marcha
    lectura = pagina.cuadros["seq1m-q8t1"].columnas[Direccion.LECTURA]
    assert lectura.valor.get_text() == "200.00"  # promedio de 100, 200 y 300 MB/s
    assert lectura.iops.get_text() == "191 IOPS"
    assert lectura.extremos.get_text() == "Mejor 300.00 MB/s\nPeor 100.00 MB/s"
    aleatoria = pagina.cuadros["rnd4k-q32t1"].columnas[Direccion.ESCRITURA]
    assert aleatoria.iops.get_text() == "48,828 IOPS"  # 200 MB/s en bloques de 4 KiB
    assert pagina.mensaje.get_text() == "Prueba terminada. Se borraron el archivo de prueba y su carpeta temporal."
    assert pagina.boton.get_label() == "Iniciar" and pagina.boton.get_sensitive()
    assert os.listdir(carpeta) == []


def _esperar_que_duerma(GLib, fio_falso):
    esperar(GLib, lambda: bool(fio_falso.hijos()), 10)
    assert fio_falso.hijos()
    return fio_falso.invocaciones()[-1]["pid"], fio_falso.hijos()[-1]


def test_cancelar_desde_la_interfaz_detiene_fio_y_limpia(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["ok", "duerme"])
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    principal, hijo = _esperar_que_duerma(GLib, fio_falso)
    pagina.boton.emit("clicked")  # Cancelar
    esperar(GLib, lambda: not pagina.en_marcha, 20)
    assert pagina.mensaje.get_text() == "Prueba cancelada. Se borraron el archivo de prueba y su carpeta temporal."
    assert pagina.cuadros["seq1m-q8t1"].columnas[Direccion.LECTURA].estado.get_text() == "Sin resultado"
    assert not vivo(principal) and not vivo(hijo)
    assert os.listdir(carpeta) == []


def test_error_de_fio_se_muestra_tal_cual(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["falla"])
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    esperar(GLib, lambda: not pagina.en_marcha, 20)
    assert pagina.mensaje.get_text() == (
        "fio falló en «Preparando el archivo de prueba».\n"
        "fio terminó con el código 1. Mensaje de fio:\n"
        "fio: error inventado por el fio falso (err=22/Invalid argument)\n"
        "Se borró la carpeta temporal; el archivo de prueba no llegó a crearse."  # el falso falla antes de crearlo
    )
    assert os.listdir(carpeta) == []


def test_cerrar_la_ventana_en_plena_prueba_pide_confirmacion_y_limpia(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["ok", "duerme"])
    ventana = _ventana(_servicios(fio_falso))
    ventana.realize()  # Gtk.Window.close() no hace nada en una ventana sin realizar
    pagina = _abrir_pestana(ventana)
    cierres = []
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    principal, hijo = _esperar_que_duerma(GLib, fio_falso)

    ventana.close()  # emite close-request: se bloquea y pregunta
    assert ventana.dialogo_cerrar is not None
    assert pagina.en_marcha and vivo(principal)
    ventana.responder_cierre(ventana.dialogo_cerrar, "seguir")
    assert pagina.en_marcha and vivo(principal)  # "Seguir midiendo" no toca nada

    ventana.connect("close-request", lambda _v: cierres.append(time.monotonic()) or False)
    ventana.close()
    ventana.responder_cierre(ventana.dialogo_cerrar, "cerrar")
    esperar(GLib, lambda: bool(cierres), 20)
    assert cierres, "la ventana no se cerró después de limpiar"
    assert not pagina.en_marcha
    assert not vivo(principal) and not vivo(hijo)
    assert os.listdir(carpeta) == []


def test_cerrar_sin_prueba_no_pregunta(gtk):
    ventana = _ventana(_servicios())
    ventana.realize()
    cierres = []
    ventana.connect("close-request", lambda _v: cierres.append(1) or False)
    ventana.close()
    assert cierres == [1] and ventana.dialogo_cerrar is None


def _resto(carpeta, nombre=".latido-velocidad-abcd1234"):
    resto = carpeta / nombre
    resto.mkdir()
    (resto / "latido-velocidad.dat").write_bytes(b"\0" * 4096)
    return resto


def test_restos_de_la_ultima_carpeta_se_avisan_y_solo_se_borran_al_confirmar(gtk, carpeta):
    resto = _resto(carpeta)
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert pagina.banner.get_revealed()
    assert str(carpeta) in pagina.banner.get_title()
    assert resto.exists()  # avisar no borra

    pagina.banner.emit("button-clicked")
    assert pagina.dialogo_restos is not None
    pagina.responder_restos(pagina.dialogo_restos, "cancelar")
    assert resto.exists()

    pagina.banner.emit("button-clicked")
    pagina.responder_restos(pagina.dialogo_restos, "borrar")
    assert not resto.exists()
    assert os.listdir(carpeta) == []
    assert pagina.mensaje.get_text() == f"Se borró {resto}."
    assert not pagina.banner.get_revealed()


def test_restos_ajenos_no_se_ofrecen_para_borrar(gtk, carpeta):
    resto = _resto(carpeta)
    (resto / "mio.txt").write_text("del usuario", encoding="utf-8")
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert pagina.banner.get_revealed()
    pagina.banner.emit("button-clicked")
    assert not pagina.dialogo_restos.get_response_enabled("borrar")
    pagina.responder_restos(pagina.dialogo_restos, "borrar")
    assert sorted(os.listdir(resto)) == ["latido-velocidad.dat", "mio.txt"]


def test_solo_revisa_la_ultima_carpeta_usada(gtk, tmp_path, carpeta):
    otra = tmp_path / "otra"
    otra.mkdir()
    _resto(otra)
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert not pagina.banner.get_revealed()
