"""Pruebas de la interfaz.

Se comprueba la pantalla con Gdk.Display.get_default() real, no con la
variable DISPLAY (fixture gtk en conftest.py). Sin pantalla, se saltan con
motivo; con REQUIRE_DISPLAY=1 fallan en vez de saltar. Las ventanas no se
muestran (no se llama present).
"""

import pytest

from conftest import FIXTURES, esperar
from latido.salud import Estado
from latido.sistema.discos import AVISO_SD, Disco
from latido.sistema.lectura import ErrorLectura, TipoError, cargar_fixture


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


def test_al_abrir_no_lee_ni_pide_contrasena(gtk):
    llamadas = []
    ventana = _ventana([_disco()], lambda disco: llamadas.append(disco))
    pagina = ventana.pagina_salud
    assert llamadas == []
    assert pagina.etiqueta_estado.get_text() == "—"
    assert pagina.boton.get_label() == "Leer salud"
    assert pagina.boton.get_sensitive()
    assert pagina.mostrando_estado()


def test_el_esquema_de_color_sigue_al_sistema(gtk):
    """Latido no fuerza claro ni oscuro: Adw.StyleManager queda en ColorScheme.DEFAULT."""
    from gi.repository import Adw

    _ventana([_disco()], lambda disco: None)
    assert Adw.StyleManager.get_default().get_color_scheme() == Adw.ColorScheme.DEFAULT


def test_pestana_salud(gtk):
    ventana = _ventana([_disco()], lambda disco: None)
    pagina = ventana.pila.get_page(ventana.pagina_salud)
    assert pagina.get_title() == "Salud"


CLASES_DE_ESTADO = {"latido-bueno", "latido-precaucion", "latido-malo", "latido-desconocido"}


@pytest.mark.parametrize("archivo, texto, clase, icono", [
    ("nvme_real.json", "Bueno", "latido-bueno", "object-select-symbolic"),
    ("sintetico_precaucion.json", "Precaución", "latido-precaucion", "dialog-warning-symbolic"),
    ("sintetico_malo.json", "Peligro", "latido-malo", "dialog-error-symbolic"),
    ("sintetico_desconocido.json", "Sin datos", "latido-desconocido", "dialog-question-symbolic"),
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


def test_cifras_clave_y_registro_del_fixture_real(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"))
    vistas = {clave: (t.titulo.get_text(), t.valor.get_text(), t.unidad.get_text(), t.palabra.get_text(),
                      t.detalle.get_text()) for clave, t in pagina.cifras.items()}
    assert vistas == {
        # Espacio no separable entre número y unidad: con el tema del usuario, a 720 px «°C» quedaba solo abajo.
        "temperatura": ("Temperatura", "46", "°C", "Normal",
                        "Umbrales del disco: advertencia 83\u00a0°C · crítica 90\u00a0°C"),
        "vida": ("Vida usada", "1", "%", "Normal", "Estimación del propio disco. Queda 99\u00a0%."),
        "reserva": ("Repuesto disponible", "100", "%", "Normal", "Umbral del disco: 10\u00a0%"),
        "horas": ("Horas encendido", "4,921", "h", "Informativo", "934 ciclos de encendido"),
        "escritos": ("Datos escritos", "13.08", "TB", "Informativo", "Leídos: 16.60 TB"),
        "errores": ("Errores de medio", "0", "", "Normal", "Datos que el disco no pudo corregir"),
    }
    assert all("numeric" in t.valor.get_css_classes() for t in pagina.cifras.values())
    assert pagina.grid_cifras.get_visible()
    assert len(pagina._filas_registro) == 18
    assert pagina.grupo_registro.get_visible()


def test_la_autenticidad_va_despues_de_las_cifras(gtk):
    """La salud va junta (tarjeta, «Por qué» y cifras); la autenticidad, aparte y después."""
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    hijos, hijo = [], pagina.contenido.get_first_child()
    while hijo is not None:
        hijos.append(hijo)
        hijo = hijo.get_next_sibling()
    orden = [hijos.index(w) for w in (pagina.grupo_motivos, pagina.grid_cifras, pagina.grupo_autenticidad,
                                      pagina.expansor)]
    assert orden == sorted(orden)


def test_grupo_disco_con_fixture_real(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco())
    valores = {clave: etiqueta.get_text() for clave, etiqueta in pagina.filas_disco.items()}
    assert valores == {
        "modelo": "KINGSTON SNV2S1000G",
        "serie": "No disponible",  # el fixture va sin serial
        "firmware": "SBI02105",
        "capacidad": "1.00 TB",
        "interfaz": "NVMe",
    }
    assert pagina.grupo_disco.get_visible()
    # Los textos cortos no se parten; los largos sí, con ancho mínimo.
    assert not pagina.filas_disco["interfaz"].get_wrap()
    assert pagina.filas_disco["modelo"].get_wrap()
    assert pagina.filas_disco["modelo"].get_width_chars() == 16


def test_numero_serie_en_pantalla_y_seleccionable(gtk):
    from conftest import cargar
    from latido.salud import analizar

    datos = cargar("nvme_real.json")
    datos["serial_number"] = "SINTETICO-0003-QWE"  # solo en memoria
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(analizar(datos), _disco())
    etiqueta = pagina.filas_disco["serie"]
    assert etiqueta.get_text() == "SINTETICO-0003-QWE"
    assert etiqueta.get_selectable()
    pagina.mostrar_error(ErrorLectura(TipoError.CANCELADO, "Cerraste la ventana de contraseña."))
    assert etiqueta.get_text() == ""
    assert not pagina.grupo_disco.get_visible()


def test_interfaz_con_otra_conexion(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco(transporte="usb"))
    assert pagina.filas_disco["interfaz"].get_text() == "NVMe (conexión USB)"


def test_tamano_por_defecto_y_minimo(gtk):
    from latido.ui.ventana import ALTO, ALTO_MINIMO, ANCHO, ANCHO_MINIMO

    ventana = _ventana([_disco()], lambda disco: None)
    assert ventana.get_default_size() == (ANCHO, ALTO) == (900, 700)  # cabe en 1366x768
    assert ventana.get_size_request() == (ANCHO_MINIMO, ALTO_MINIMO) == (400, 500)


def test_registro_dentro_de_area_con_scroll(gtk):
    _, Gtk = gtk
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"))
    assert isinstance(pagina, Gtk.ScrolledWindow)
    assert pagina.get_policy()[1] != Gtk.PolicyType.NEVER
    pagina.expansor.set_expanded(True)  # plegado, GTK saca al hijo del árbol de widgets
    assert pagina.grupo_registro.is_ancestor(pagina)
    assert pagina.grupo_registro.get_visible() and len(pagina._filas_registro) == 18


def test_lo_que_falta_dice_no_disponible(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_desconocido.json"))  # sin percentage_used
    assert pagina.cifras["vida"].valor.get_text() == "—"
    assert pagina.cifras["vida"].palabra.get_text() == "Sin dato"
    assert pagina.filas_disco["serie"].get_text() == "No disponible"


def test_disco_sin_datos_smart_muestra_una_pagina_de_estado(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_sin_root.json"))
    assert pagina.mostrando_estado()
    assert pagina.pagina_estado.get_title() == "El disco no entregó datos SMART"
    assert pagina.boton.get_label() == "Reintentar" and pagina.boton.get_visible()
    assert pagina.informe is None


def test_lectura_en_hilo_y_resultado_con_idle_add(gtk):
    GLib, _ = gtk
    pagina = _ventana([_disco()], lambda disco: cargar_fixture(FIXTURES / "nvme_real.json")).pagina_salud
    pagina.boton.emit("clicked")
    assert pagina.leyendo
    assert not pagina.boton.get_sensitive()
    esperar(GLib, lambda: not pagina.leyendo)
    assert not pagina.leyendo
    assert pagina.etiqueta_estado.get_text() == "Bueno"
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
        esperar(GLib, lambda: not pagina.leyendo)
    assert pagina.mostrando_estado()
    assert pagina.pagina_estado.get_title() == "No se leyó el disco"
    assert not pagina.grupo_registro.get_visible()
    assert pagina._filas_registro == [] and pagina._filas_motivos == [] and pagina._filas_ata == []
    assert pagina.informe is None


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
    assert pagina.mostrando_estado()
    assert pagina.pagina_estado.get_title() == "No se encontró ningún disco"
    assert not pagina.boton.get_visible()  # sin forma de volver a buscar, no hay «Reintentar»


def test_estado_inicial_de_informe_es_desconocido():
    # No necesita pantalla: el panel nunca arranca en BUENO.
    from latido.salud import InformeSalud

    assert InformeSalud().estado is Estado.DESCONOCIDO


# --- B2: ventana y estados ---


def test_selector_en_la_cabecera_con_modelo_y_capacidad_sin_serie(gtk):
    ventana = _ventana([_disco(modelo="DISCO A", tamano=10**12), _disco(nombre="nvme1n1", modelo="DISCO A",
                        tamano=10**12), _disco(nombre="sda", modelo="OTRO", tamano=5 * 10**11)], lambda disco: None)
    assert ventana.selector.is_ancestor(ventana.cabecera)
    modelo = ventana.selector.get_model()
    textos = [modelo.get_string(i) for i in range(modelo.get_n_items())]
    assert textos == ["DISCO A · 1.00 TB · nvme0n1", "DISCO A · 1.00 TB · nvme1n1", "OTRO · 500.0 GB"]
    assert "/dev/" not in " ".join(textos)


def test_el_selector_solo_se_ve_en_salud(gtk):
    ventana = _ventana([_disco()], lambda disco: None)
    assert ventana.selector.get_visible()
    ventana.pila.set_visible_child(ventana.pagina_velocidad)
    assert not ventana.selector.get_visible()


def test_acciones_atajos_y_menu(gtk):
    from latido.ui.ventana import ATAJOS

    ventana = _ventana([_disco()], lambda disco: None)
    for nombre in ("actualizar", "exportar", "acerca"):
        assert ventana.lookup_action(nombre) is not None, nombre
    assert ATAJOS == {"win.actualizar": ["<Control>r"], "win.exportar": ["<Control>e"], "app.salir": ["<Control>q"]}
    menu = ventana.boton_menu.get_menu_model()
    etiquetas = [menu.get_item_attribute_value(i, "label").get_string() for i in range(menu.get_n_items())]
    acciones = [menu.get_item_attribute_value(i, "action").get_string() for i in range(menu.get_n_items())]
    assert etiquetas == ["Exportar informe…", "Acerca de Latido", "Salir"]
    assert acciones == ["win.exportar", "win.acerca", "app.salir"]
    assert ventana.boton_actualizar.get_action_name() == "win.actualizar"


def test_ctrl_r_lee_el_disco_en_salud(gtk):
    GLib, _ = gtk
    llamadas = []

    def lector(disco):
        llamadas.append(disco.nombre)
        return cargar_fixture(FIXTURES / "nvme_real.json")

    ventana = _ventana([_disco()], lector)
    ventana.activate_action("win.actualizar", None)
    esperar(GLib, lambda: not ventana.pagina_salud.leyendo)
    assert llamadas == ["nvme0n1"]
    assert not ventana.pagina_salud.mostrando_estado()


def test_punto_de_corte_baja_las_pestanas(gtk):
    from latido.ui.ventana import ANCHO_ANGOSTO

    ventana = _ventana([_disco()], lambda disco: None)
    assert ANCHO_ANGOSTO == "560sp"
    assert ventana.angosto.get_condition().to_string() == "max-width: 560sp"
    assert ventana.barra_inferior.get_stack() is ventana.pila


@pytest.mark.parametrize("tipo, titulo, icono", [
    (TipoError.CANCELADO, "No se leyó el disco", "dialog-password-symbolic"),
    (TipoError.NO_AUTORIZADO, "No se obtuvo permiso", "dialog-password-symbolic"),
    (TipoError.HERRAMIENTAS, "Falta smartctl", "system-software-install-symbolic"),
    (TipoError.AYUDANTE, "No se pudo leer el disco", "dialog-warning-symbolic"),
])
def test_errores_en_una_pagina_de_estado_con_reintentar(gtk, tipo, titulo, icono):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    mensaje = "Falta smartctl (/usr/bin/smartctl). Instálalo con: sudo dnf install smartmontools"
    pagina.mostrar_error(ErrorLectura(tipo, mensaje))
    assert pagina.mostrando_estado()
    assert pagina.pagina_estado.get_title() == titulo
    assert pagina.pagina_estado.get_icon_name() == icono
    assert pagina.boton.get_label() == "Reintentar" and pagina.boton.get_visible()
    assert "dialog-error-symbolic" != pagina.pagina_estado.get_icon_name()  # nunca el ícono rojo


def test_cancelar_la_contrasena_es_un_mensaje_amable(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_error(ErrorLectura(TipoError.CANCELADO, "Cerraste la ventana de contraseña."))
    assert pagina.pagina_estado.get_description() == (
        "Cerraste la ventana de contraseña, así que Latido no leyó nada. Cuando quieras, vuelve a intentarlo."
    )
    assert not set(pagina.pagina_estado.get_css_classes()) & {"error", "latido-malo"}


def test_reintentar_vuelve_a_leer(gtk):
    GLib, _ = gtk
    respuestas = [ErrorLectura(TipoError.CANCELADO, "x"), cargar_fixture(FIXTURES / "nvme_real.json")]

    def lector(disco):
        respuesta = respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    pagina = _ventana([_disco()], lector).pagina_salud
    pagina.boton.emit("clicked")
    esperar(GLib, lambda: not pagina.leyendo)
    assert pagina.boton.get_label() == "Reintentar"
    pagina.boton.emit("clicked")
    esperar(GLib, lambda: not pagina.leyendo)
    assert not pagina.mostrando_estado() and respuestas == []


def test_sin_discos_reintentar_vuelve_a_buscarlos(gtk):
    GLib, _ = gtk
    pagina = _ventana([], lambda disco: None).pagina_salud
    pagina._detectar = lambda: [_disco()]
    pagina._al_cambiar_disco()
    assert pagina.boton.get_label() == "Reintentar" and pagina.boton.get_sensitive()
    pagina.boton.emit("clicked")
    esperar(GLib, lambda: not pagina.detectando)
    assert pagina.disco_seleccionado().nombre == "nvme0n1"
    assert pagina.pagina_estado.get_title() == "Leer la salud del disco"
    assert pagina.boton.get_label() == "Leer salud"


def test_acerca_de(gtk):
    from latido import __version__

    dialogo = _ventana([_disco()], lambda disco: None).crear_acerca_de()
    assert dialogo.get_application_name() == "Latido"
    assert dialogo.get_version() == __version__
    assert dialogo.get_license_type() == gtk[1].License.GPL_3_0


# --- B3: la vista de Salud ---


def test_tarjeta_del_veredicto_con_icono_grande_y_title_1(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_malo.json"), _disco())
    assert pagina.icono_estado.get_pixel_size() == 48
    assert "title-1" in pagina.etiqueta_estado.get_css_classes()
    assert pagina.etiqueta_frase.get_text() == "El disco reporta fallas: no le confíes datos importantes."
    assert pagina.etiqueta_disco.get_text() == _disco().etiqueta


def test_por_que_una_fila_por_regla_con_su_icono(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    informe = cargar_fixture(FIXTURES / "sintetico_precaucion.json")
    pagina.mostrar_informe(informe)
    assert pagina.grupo_motivos.get_title() == "Por qué"
    assert [f.get_title() for f in pagina._filas_motivos] == informe.motivos
    iconos = [f.get_first_child().get_first_child().get_first_child().get_icon_name() for f in pagina._filas_motivos]
    assert iconos == ["dialog-warning-symbolic"] * len(informe.motivos)


def test_cada_cifra_toma_el_estado_de_su_regla(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_precaucion.json"))
    palabras = {clave: t.palabra.get_text() for clave, t in pagina.cifras.items()}
    assert palabras == {"temperatura": "Normal", "vida": "Atención", "reserva": "Normal", "horas": "Informativo",
                        "escritos": "Informativo", "errores": "Atención"}
    assert "latido-precaucion" in pagina.cifras["vida"].chip.get_css_classes()
    assert pagina.cifras["vida"].icono.get_icon_name() == "dialog-warning-symbolic"


def test_todos_los_datos_esta_plegado_al_abrir(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"))
    assert not pagina.expansor.get_expanded()
    datos = pagina.expansor.get_child()
    assert pagina.grupo_registro.is_ancestor(datos) and pagina.grupo_disco.is_ancestor(datos)


def test_la_vista_pinta_la_tabla_ata(gtk):
    """sintetico_ata.json: datos inventados, NO medidos en hardware. La vista los pinta; no promete SATA."""
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_ata.json"))
    assert not pagina.mostrando_estado()
    assert pagina.etiqueta_estado.get_text() == "Sin datos"
    assert pagina.grupo_ata.get_visible() and len(pagina._filas_ata) == 7
    primera, temperatura = pagina._filas_ata[0], pagina._filas_ata[3]
    assert primera.get_title() == "5 · Reallocated_Sector_Ct"
    assert primera.get_subtitle() == "Valor 100 · Peor 100 · Umbral 10"
    assert temperatura.get_title() == "194 · Temperature_Celsius"
    assert "todavía no la analiza" in pagina.grupo_ata.get_description()
    assert [f.get_title() for f in pagina._filas_motivos] == [
        "Latido todavía no analiza discos de tipo ATA. No se puede saber el estado."
    ]
    assert not pagina.grid_cifras.get_visible()  # las seis cifras son de NVMe



# --- B4: veredicto honesto ---


def test_por_que_dice_la_fuente_o_que_es_criterio_de_latido(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_malo.json"))
    assert pagina._filas_motivos[0].get_subtitle() == "Fuente: NVMe Base Specification 2.0c, figura 207, byte 00, bit 2"
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "sintetico_precaucion.json"))
    assert "Criterio de Latido (sin fuente)" in [f.get_subtitle() for f in pagina._filas_motivos]


def test_autenticidad_aparte_del_color_de_salud(gtk):
    pagina = _ventana([_disco()], lambda disco: None).pagina_salud
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco(tamano=1000204886016))
    assert pagina.grupo_autenticidad.get_visible()
    assert pagina.fila_autenticidad.get_title() == "No concluyente"
    assert "Latido aún no verifica la capacidad real." in pagina.fila_autenticidad.get_subtitle()
    assert pagina.icono_autenticidad.get_icon_name() == "dialog-question-symbolic"
    assert not set(pagina.fila_autenticidad.get_css_classes()) & CLASES_DE_ESTADO
    pagina.mostrar_informe(cargar_fixture(FIXTURES / "nvme_real.json"), _disco(tamano=2 * 10**12))
    assert pagina.fila_autenticidad.get_title() == "Falso o manipulado"
    assert pagina.etiqueta_estado.get_text() == "Bueno"  # el color de salud no cambia
