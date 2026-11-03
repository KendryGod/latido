"""Pruebas de la interfaz.

Se comprueba la pantalla con Gdk.Display.get_default() real, no con la
variable DISPLAY. Sin pantalla, se saltan con motivo; con REQUIRE_DISPLAY=1
fallan en vez de saltar. Las ventanas no se muestran (no se llama present).
"""

import os
import time

import pytest

from conftest import FIXTURES
from latido.salud import Estado
from latido.sistema.discos import AVISO_SD, Disco
from latido.sistema.lectura import ErrorLectura, TipoError, cargar_fixture


def _hay_pantalla():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk

    Gtk.init_check()
    return Gdk.Display.get_default() is not None


@pytest.fixture(scope="module")
def gtk():
    if not _hay_pantalla():
        motivo = "Sin pantalla: Gdk.Display.get_default() devolvió None"
        if os.environ.get("REQUIRE_DISPLAY") == "1":
            pytest.fail(motivo + " y REQUIRE_DISPLAY=1")
        pytest.skip(motivo)
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    Adw.init()
    return GLib, Gtk


def _disco(**cambios):
    datos = dict(
        nombre="nvme0n1", ruta="/dev/nvme0n1", ruta_lectura="/dev/nvme0", modelo="DISCO", tamano=10**12,
        transporte="nvme", es_sistema=False, habilitado=True, aviso=None,
    )
    datos.update(cambios)
    return Disco(**datos)


def _ventana(discos, lector):
    from latido.ui.ventana import VentanaPrincipal

    return VentanaPrincipal(discos, lector)


def _esperar(GLib, condicion, segundos=5):
    contexto = GLib.MainContext.default()
    limite = time.monotonic() + segundos
    while not condicion() and time.monotonic() < limite:
        contexto.iteration(False)
        time.sleep(0.01)
    while contexto.pending():
        contexto.iteration(False)


def test_al_abrir_no_lee_ni_pide_contrasena(gtk):
    llamadas = []
    ventana = _ventana([_disco()], lambda disco: llamadas.append(disco))
    pagina = ventana.pagina_salud
    assert llamadas == []
    assert pagina.etiqueta_estado.get_text() == "—"
    assert pagina.boton.get_label() == "Leer salud"
    assert pagina.boton.get_sensitive()
    assert not pagina.grupo_resumen.get_visible()


def test_pestana_salud(gtk):
    ventana = _ventana([_disco()], lambda disco: None)
    pagina = ventana.pila.get_page(ventana.pagina_salud)
    assert pagina.get_title() == "Salud"


CLASES_DE_ESTADO = {"latido-bueno", "latido-precaucion", "latido-malo", "latido-desconocido"}


@pytest.mark.parametrize("archivo, texto, clase, icono", [
    ("nvme_real.json", "BUENO", "latido-bueno", "object-select-symbolic"),
    ("sintetico_precaucion.json", "PRECAUCIÓN", "latido-precaucion", "dialog-warning-symbolic"),
    ("sintetico_malo.json", "MALO", "latido-malo", "dialog-error-symbolic"),
    ("sintetico_desconocido.json", "DESCONOCIDO", "latido-desconocido", "dialog-question-symbolic"),
    ("nvme_sin_root.json", "DESCONOCIDO", "latido-desconocido", "dialog-question-symbolic"),
])
def test_cada_estado_aplica_su_clase_icono_y_texto(gtk, archivo, texto, clase, icono):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / archivo))
    assert pagina.etiqueta_estado.get_text() == texto
    assert set(pagina.insignia.get_css_classes()) & CLASES_DE_ESTADO == {clase}
    assert pagina.icono_estado.get_visible()
    assert pagina.icono_estado.get_icon_name() == icono


def test_cambiar_de_estado_no_acumula_clases(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_malo.json"))
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"))
    assert set(pagina.insignia.get_css_classes()) & CLASES_DE_ESTADO == {"latido-bueno"}


def test_sin_leer_la_insignia_es_neutra(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    assert not set(pagina.insignia.get_css_classes()) & CLASES_DE_ESTADO
    assert not pagina.icono_estado.get_visible()


def test_iconos_existen_en_el_tema(gtk):
    from gi.repository import Gdk

    from latido.ui.pagina_salud import APARIENCIA

    tema = gtk[1].IconTheme.get_for_display(Gdk.Display.get_default())
    for _, _, icono, _ in APARIENCIA.values():
        assert tema.has_icon(icono), icono


def test_css_sin_errores_y_con_colores_de_libadwaita(gtk):
    from gi.repository import Gio

    from latido.ui import estilo

    hoja = Gio.resources_lookup_data("/org/gnome/Adwaita/styles/gtk.css", 0).get_data().decode()
    assert estilo.COLORES_USADOS == ["blue_3", "dark_1", "dark_4", "light_1", "red_3", "yellow_5"]
    for nombre in estilo.COLORES_USADOS:
        assert f"@define-color {nombre} " in hoja, nombre
    estilo._pantallas_con_estilo.clear()
    assert estilo.cargar_estilo() == []


def test_un_css_roto_si_se_detecta(gtk):
    proveedor = gtk[1].CssProvider()
    errores = []
    proveedor.connect("parsing-error", lambda _p, _s, error: errores.append(error.message))
    proveedor.load_from_string(".x { color: ; }")
    assert errores


def test_resumen_y_registro_del_fixture_real(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"))
    valores = {clave: etiqueta.get_text() for clave, (_, etiqueta) in pagina.filas_resumen.items()}
    assert valores == {
        "vida": "99 %",
        "temperatura": "46 °C",
        "horas": "4,921",
        "ciclos": "934",
        "tb_escritos": "13.08 TB",
        "tb_leidos": "16.60 TB",
    }
    assert len(pagina._filas_registro) == 18
    assert pagina.grupo_registro.get_visible()


def test_lo_que_falta_dice_no_disponible(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_sin_root.json"))
    for _, etiqueta in pagina.filas_resumen.values():
        assert etiqueta.get_text() == "No disponible"


def test_lectura_en_hilo_y_resultado_con_idle_add(gtk):
    GLib, _ = gtk
    pagina = _ventana([_disco()], lambda disco: cargar_fixture(FIXTURES / "nvme_real.json")).pagina_salud
    pagina.boton.emit("clicked")
    assert pagina.leyendo
    assert not pagina.boton.get_sensitive()
    _esperar(GLib, lambda: not pagina.leyendo)
    assert not pagina.leyendo
    assert pagina.etiqueta_estado.get_text() == "BUENO"
    assert pagina.boton.get_sensitive()


def test_error_no_deja_datos_viejos(gtk):
    GLib, _ = gtk
    respuestas = [
        cargar_fixture(FIXTURES / "nvme_real.json"),
        ErrorLectura(TipoError.CANCELADO, "Cerraste la ventana de contraseña. No se leyó nada del disco."),
    ]

    def lector(disco):
        respuesta = respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    pagina = _ventana([_disco()], lector).pagina_salud
    for _ in range(2):
        pagina.boton.emit("clicked")
        _esperar(GLib, lambda: not pagina.leyendo)
    assert pagina.etiqueta_estado.get_text() == "DESCONOCIDO"
    assert "latido-desconocido" in pagina.insignia.get_css_classes()
    assert not pagina.grupo_resumen.get_visible()
    assert not pagina.grupo_registro.get_visible()
    assert pagina._filas_registro == []
    assert [f.get_title() for f in pagina._filas_motivos] == [
        "Cerraste la ventana de contraseña. No se leyó nada del disco."
    ]


def test_disco_sd_deshabilitado_con_aviso(gtk):
    llamadas = []
    sda = _disco(nombre="sda", ruta="/dev/sda", ruta_lectura=None, habilitado=False, aviso=AVISO_SD)
    pagina = _ventana([sda], lambda disco: llamadas.append(disco)).pagina_salud
    assert not pagina.boton.get_sensitive()
    assert pagina.aviso.get_visible()
    assert pagina.aviso.get_text() == "SATA y USB llegan en una próxima fase"
    pagina.boton.emit("clicked")
    assert llamadas == []


def test_sin_discos(gtk):
    pagina = _ventana([], lambda disco: None).pagina_salud
    assert not pagina.boton.get_sensitive()
    assert "No se encontró ningún disco" in pagina.etiqueta_frase.get_text()


def test_estado_inicial_de_informe_es_desconocido():
    # No necesita pantalla: el panel nunca arranca en BUENO.
    from latido.salud import InformeSalud

    assert InformeSalud().estado is Estado.DESCONOCIDO
