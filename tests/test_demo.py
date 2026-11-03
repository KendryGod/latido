"""Modo demo (`python3 -m latido --demo ESTADO`): datos de ejemplo, sin leer ningún disco ni ejecutar nada."""

import subprocess

import pytest

from conftest import esperar
from latido import app, demo
from latido.informe_txt import MARCA_DEMO
from latido.salud import Estado


@pytest.mark.parametrize("argv, estado", [(["--demo", "sano"], "sano"), (["--demo=peligro"], "peligro"),
                                          (["--demo", "sin-datos"], "sin-datos")])
def test_argumentos_demo(argv, estado):
    assert app.interpretar_argumentos(argv) == (False, None, estado)


@pytest.mark.parametrize("argv", [["--demo"], ["--demo", "roto"], ["--demo", "sano", "--desde-fixture", "a.json"]])
def test_argumentos_demo_invalidos(argv):
    with pytest.raises(app.ErrorArgumentos):
        app.interpretar_argumentos(argv)


def test_los_mismos_estados_en_la_app_y_en_la_demo():
    assert app.ESTADOS_DEMO == demo.ESTADOS == ("sano", "precaucion", "peligro", "sin-datos")


@pytest.mark.parametrize("estado, esperado", [("sano", Estado.BUENO), ("precaucion", Estado.PRECAUCION),
                                              ("peligro", Estado.MALO), ("sin-datos", Estado.DESCONOCIDO)])
def test_cada_estado_de_la_demo(estado, esperado):
    assert demo.informe_demo(estado).estado is esperado


def test_los_datos_de_ejemplo_no_son_de_ningun_disco():
    for estado in demo.ESTADOS:
        datos = demo.datos_demo(estado)
        assert "serial_number" not in datos
        assert datos["model_name"] == "Disco de ejemplo NVMe"


@pytest.fixture
def sin_subprocesos(monkeypatch):
    """Cualquier intento de ejecutar algo (pkexec, smartctl, fio, lsblk) queda anotado y falla.

    Se anota porque un error dentro de un manejador de señal de GTK no llega a la prueba: PyGObject lo
    imprime y sigue.
    """
    intentos = []

    def prohibido(*args, **kwargs):
        intentos.append(args)
        raise AssertionError(f"el modo demo intentó ejecutar {args!r}")

    class PopenProhibido:
        def __init__(self, *args, **kwargs):
            prohibido(*args)

    for nombre in ("run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, nombre, prohibido)
    monkeypatch.setattr(subprocess, "Popen", PopenProhibido)
    return intentos


@pytest.mark.parametrize("estado", demo.ESTADOS)
def test_la_demo_funciona_sin_ejecutar_nada(gtk, sin_subprocesos, estado):
    GLib, _ = gtk
    from latido.ui.aplicacion import crear_ventana_demo

    ventana = crear_ventana_demo(estado)
    salud = ventana.pagina_salud
    assert not salud.mostrando_estado()
    assert salud.etiqueta_estado.get_text() == {"sano": "Bueno", "precaucion": "Precaución", "peligro": "Peligro",
                                                 "sin-datos": "Sin datos"}[estado]
    ventana.activate_action("win.actualizar", None)  # vuelve a «leer»: los datos de ejemplo
    esperar(GLib, lambda: not salud.leyendo)
    assert not salud.mostrando_estado()
    ventana.pila.set_visible_child(ventana.pagina_velocidad)
    velocidad = ventana.pagina_velocidad
    assert velocidad.vistas.get_visible_child_name() == "prueba"
    assert not velocidad.boton.get_sensitive() and not velocidad.boton_carpeta.get_sensitive()
    celda = velocidad.cuadros["seq1m-q8t1"].columnas[next(iter(velocidad.cuadros["seq1m-q8t1"].columnas))]
    assert celda.valor.get_text() != "—" and celda.latencia.get_text() != "—"
    texto = ventana.texto_del_informe()
    assert texto.splitlines()[1] == MARCA_DEMO and "ext4 (ejemplo)" in texto
    assert sin_subprocesos == []  # ni pkexec, ni smartctl, ni fio, ni nada


def test_la_demo_lleva_su_banner_permanente(gtk):
    from gi.repository import Adw

    from latido.ui.aplicacion import crear_ventana_demo

    vista = crear_ventana_demo("sano").get_content()
    banners = []
    hijo = vista.get_first_child()
    while hijo is not None:
        pila = [hijo]
        while pila:
            widget = pila.pop()
            if isinstance(widget, Adw.Banner):
                banners.append(widget)
            hijo_interno = widget.get_first_child()
            while hijo_interno is not None:
                pila.append(hijo_interno)
                hijo_interno = hijo_interno.get_next_sibling()
        hijo = hijo.get_next_sibling()
    visibles = [(b.get_title(), b.get_button_label()) for b in banners if b.get_revealed()]
    assert visibles == [("Datos de ejemplo, no son de tu disco", None)]  # sin botón: no se puede cerrar
