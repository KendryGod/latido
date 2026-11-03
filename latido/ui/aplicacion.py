"""Aplicación Adw: arma la ventana en modo normal o desde un fixture."""

import os

from gi.repository import Adw, Gio

from latido.sistema.discos import Disco, ErrorDeteccion, listar_discos
from latido.sistema.lectura import cargar_fixture, leer_salud
from latido.ui.ventana import ATAJOS, VentanaPrincipal

ID_APLICACION = "io.github.kendrygod.latido"


def disco_de_fixture(ruta):
    nombre = os.path.basename(ruta)
    return Disco(
        nombre=nombre,
        ruta=nombre,  # solo para mostrar: la ruta completa ensancharía el selector
        ruta_lectura=ruta,
        modelo="Archivo de prueba",
        tamano=None,
        transporte=None,
        es_sistema=False,
        habilitado=True,
        aviso=None,
    )


def crear_ventana_demo(estado, aplicacion=None):
    """Modo demo: datos de ejemplo, banner permanente, sin leer ningún disco ni ejecutar nada."""
    from latido import demo

    disco = demo.disco_demo()
    ventana = VentanaPrincipal(
        [disco],
        lambda _disco: demo.informe_demo(estado),
        aviso_desarrollo=demo.AVISO,
        servicios_velocidad=demo.servicios_velocidad_demo(),
        velocidad_demo=demo.velocidad_demo(),
        demo=True,
        application=aplicacion,
    )
    ventana.pagina_salud.mostrar_informe(demo.informe_demo(estado), disco)
    return ventana


def crear_ventana(aplicacion=None, ruta_fixture=None, estado_demo=None):
    if estado_demo:
        return crear_ventana_demo(estado_demo, aplicacion)
    if ruta_fixture:
        return VentanaPrincipal(
            [disco_de_fixture(ruta_fixture)],
            lambda disco: cargar_fixture(disco.ruta_lectura),
            aviso_desarrollo="Modo desarrollo: datos de un archivo, no de un disco real",
            application=aplicacion,
        )
    try:
        discos = listar_discos()
        error = None
    except ErrorDeteccion as fallo:
        discos, error = [], f"No se pudieron detectar los discos. {fallo}"
    return VentanaPrincipal(
        discos,
        lambda disco: leer_salud(disco.ruta_lectura),
        error_deteccion=error,
        detectar=listar_discos,
        application=aplicacion,
    )


class Aplicacion(Adw.Application):
    def __init__(self, ruta_fixture=None, demo=None):
        aparte = ruta_fixture or demo
        flags = Gio.ApplicationFlags.NON_UNIQUE if aparte else Gio.ApplicationFlags.DEFAULT_FLAGS
        super().__init__(application_id=ID_APLICACION, flags=flags)
        self.ruta_fixture = ruta_fixture
        self.demo = demo

    def do_startup(self):
        Adw.Application.do_startup(self)
        salir = Gio.SimpleAction(name="salir")
        salir.connect("activate", lambda _accion, _parametro: self.salir())
        self.add_action(salir)
        for accion, teclas in ATAJOS.items():
            self.set_accels_for_action(accion, teclas)

    def salir(self):
        """Ctrl+Q o «Salir»: cierra cada ventana. Con una prueba en marcha, la ventana pide confirmación."""
        for ventana in list(self.get_windows()):
            ventana.close()

    def do_activate(self):
        ventana = self.get_active_window() or crear_ventana(self, self.ruta_fixture, self.demo)
        ventana.present()

    def do_shutdown(self):
        # Si la app se cierra con una prueba de velocidad en marcha (por ejemplo,
        # Ctrl+C en la terminal), se detiene fio y se limpia antes de salir.
        for ventana in self.get_windows():
            pagina = getattr(ventana, "pagina_velocidad", None)
            if pagina is not None:
                pagina.detener_y_esperar()
        Adw.Application.do_shutdown(self)
