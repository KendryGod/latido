"""Pestaña "Velocidad": lectura y escritura con fio, en una carpeta que elige el usuario."""

import re
import threading
import traceback
from dataclasses import dataclass
from typing import Callable

from gi.repository import Adw, Gio, GLib, GObject, Graphene, Gtk

from latido.informe_txt import VelocidadMedida
from latido.sistema.ubicacion import NO_SE_PUDO, disco_de_carpeta
from latido.velocidad import formato
from latido.velocidad.carpeta import espacio_necesario, margen, revisar_carpeta
from latido.velocidad.ejecucion import Cancelado, Ejecucion, ErrorVelocidad
from latido.velocidad.herramientas import comprobar_fio
from latido.velocidad.pruebas import (
    PASADAS_MAXIMO,
    PASADAS_MINIMO,
    PASADAS_POR_DEFECTO,
    PRUEBAS,
    SEGUNDOS_POR_MEDICION,
    TAMANO_POR_DEFECTO,
    TAMANOS,
    Configuracion,
    Direccion,
)
from latido.velocidad.restos import ErrorResto, borrar_resto, buscar_restos, leer_ultima_carpeta
from latido.velocidad.resultado import ResultadoVelocidad

NOTA = (
    "MB/s = 1,000,000 bytes por segundo. IOPS = operaciones por segundo. Latencia: tiempo medio de cada "
    "operación, desde que fio la crea hasta que termina. El número grande es el promedio de las pasadas; debajo "
    "van la mejor y la peor. La barra compara cada resultado con el más alto de la tabla. "
    f"Cada medición dura como máximo {SEGUNDOS_POR_MEDICION} s. Los resultados solo se muestran aquí: no se guardan."
)
SIN_CARPETA = "Elige dónde crear el archivo de prueba"
ORDEN_DIRECCIONES = (Direccion.LECTURA, Direccion.ESCRITURA)  # el de Configuracion.pasos()
MEDICIONES = len(PRUEBAS) * len(ORDEN_DIRECCIONES)  # 8: cada prueba, en lectura y en escritura
ICONO_BIEN = "object-select-symbolic"
ICONO_INFO = "dialog-information-symbolic"
ICONO_AVISO = "dialog-warning-symbolic"
ICONO_DISCO = "drive-harddisk-symbolic"


@dataclass
class ServiciosVelocidad:
    """Lo que la pestaña usa del sistema. Las pruebas lo reemplazan por falsos."""

    comprobar_fio: Callable = comprobar_fio
    revisar_carpeta: Callable = revisar_carpeta
    crear_ejecucion: Callable = Ejecucion  # (carpeta, configuracion, al_progresar=...) -> Ejecucion
    leer_ultima_carpeta: Callable = leer_ultima_carpeta
    buscar_restos: Callable = buscar_restos
    borrar_resto: Callable = borrar_resto
    ubicar_carpeta: Callable = disco_de_carpeta


def _fila(titulo, subtitulo=None, icono=None):
    fila = Adw.ActionRow(title=titulo, use_markup=False, title_lines=0, subtitle_lines=0)
    if subtitulo:
        fila.set_subtitle(subtitulo)
    if icono:
        fila.add_prefix(Gtk.Image(icon_name=icono))
    return fila


def numero_de_medicion(paso):
    """De 1 a 8: qué prueba y en qué dirección, en el orden de Configuracion.pasos()."""
    return PRUEBAS.index(paso.prueba) * len(ORDEN_DIRECCIONES) + ORDEN_DIRECCIONES.index(paso.direccion) + 1


def texto_del_paso(paso, configuracion):
    """«Paso n de 8: …» en las mediciones; la preparación va aparte y dice cuánto escribe."""
    if paso.es_preparacion:
        return f"{paso.descripcion()} (escribe {formato.tamano(configuracion.tamano)})"
    return f"Paso {numero_de_medicion(paso)} de {MEDICIONES}: {paso.descripcion(configuracion.pasadas)}"


def sin_cortes(texto):
    """Espacio no separable entre número y unidad («4 KiB», «1 hilo») y en «cola 32»: no se parten en dos líneas."""
    texto = re.sub(r"(\d) (?=MiB|KiB|hilo)", "\\1\u00a0", texto)
    return re.sub(r"\bcola (?=\d)", "cola\u00a0", texto)


def _caption(etiqueta, *clases):
    for clase in ("caption", "dimmed", *clases):
        etiqueta.add_css_class(clase)
    return etiqueta


class CeldaResultado(Gtk.Box):
    """Lectura o escritura de una prueba: MB/s grande, barra relativa, IOPS y latencia, mejor y peor."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        numero = Adw.WrapBox(child_spacing=6)  # si no cabe, la unidad pasa abajo: nunca se corta
        self.valor = Gtk.Label(xalign=0, valign=Gtk.Align.BASELINE_FILL)
        self.valor.add_css_class("title-1")
        self.valor.add_css_class("numeric")
        self.unidad = Gtk.Label(label="MB/s", xalign=0, valign=Gtk.Align.BASELINE_FILL)
        self.unidad.add_css_class("title-4")
        self.unidad.add_css_class("dimmed")
        numero.append(self.valor)
        numero.append(self.unidad)
        # Barra relativa al resultado más alto de la tabla. Sin los umbrales de GTK («low», «high», «full»):
        # con ellos libadwaita pinta una barra corta con el color de advertencia y una llena de verde, y aquí
        # no hay estados, solo magnitudes.
        self.barra = Gtk.LevelBar(min_value=0, max_value=1, value=0)
        for nombre in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.barra.remove_offset_value(nombre)
        self.secundario = Adw.WrapBox(child_spacing=6)
        self.iops = _caption(Gtk.Label(xalign=0), "numeric")
        self.separador = _caption(Gtk.Label(label="·"))
        self.latencia = _caption(Gtk.Label(xalign=0), "numeric")
        for etiqueta in (self.iops, self.separador, self.latencia):
            self.secundario.append(etiqueta)
        self.extremos = _caption(Gtk.Label(xalign=0, wrap=True), "numeric")
        self.estado = Gtk.Label(xalign=0, wrap=True)
        self.estado.add_css_class("caption")
        for hijo in (numero, self.barra, self.secundario, self.extremos, self.estado):
            self.append(hijo)
        self.promedio = None
        self.limpiar()

    @staticmethod
    def _poner(etiqueta, texto):
        etiqueta.set_text(texto)
        etiqueta.set_visible(bool(texto))

    def limpiar(self):
        self.promedio = None
        self.valor.set_text("—")
        self.unidad.set_visible(False)  # «—» solo
        self.barra.set_value(0)
        self.iops.set_text("")
        self.latencia.set_text("—")
        self.secundario.set_visible(False)
        self._poner(self.extremos, "")
        self._poner(self.estado, "")

    def midiendo(self, pasada, pasadas):
        self._poner(self.estado, f"Midiendo… pasada {pasada} de {pasadas}")

    def mostrar(self, resumen, pasadas):
        self.promedio = resumen.promedio
        self.valor.set_text(formato.mb_s(resumen.promedio))
        self.unidad.set_visible(True)
        self.iops.set_text(f"{formato.iops(resumen.iops_promedio)} IOPS")
        self.latencia.set_text(formato.latencia(resumen.latencia_promedio))
        con_latencia = resumen.latencia_promedio is not None
        self.separador.set_visible(con_latencia)
        self.latencia.set_visible(con_latencia)
        self.secundario.set_visible(True)
        self._poner(self.extremos, f"Mejor {formato.mb_s(resumen.mejor)} · peor {formato.mb_s(resumen.peor)}"
                    if resumen.pasadas > 1 else "")
        self._poner(self.estado, "" if resumen.pasadas == pasadas else f"{resumen.pasadas} de {pasadas} pasadas")

    def relativa(self, maximo):
        self.barra.set_value(self.promedio / maximo if self.promedio and maximo else 0)

    def sin_terminar(self):
        self._poner(self.estado, "Sin resultado" if self.promedio is None else self.estado.get_text())


class FilaPrueba:
    """Una prueba en la rejilla: nombre y descripción a la izquierda; lectura y escritura a la derecha."""

    def __init__(self, prueba):
        self.prueba = prueba
        self.cabecera = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.START)
        titulo = Gtk.Label(label=prueba.nombre, xalign=0)
        titulo.add_css_class("heading")
        self.descripcion = _caption(Gtk.Label(label=sin_cortes(prueba.descripcion), xalign=0, wrap=True,
                                              max_width_chars=16))
        self.cabecera.append(titulo)
        self.cabecera.append(self.descripcion)
        self.columnas = {direccion: CeldaResultado() for direccion in ORDEN_DIRECCIONES}
        self.celdas = Gtk.Box(spacing=18, homogeneous=True, hexpand=True)
        for celda in self.columnas.values():
            self.celdas.append(celda)


class PaginaVelocidad(Gtk.Box):
    def __init__(self, servicios=None, demo=None, obtener_discos=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.servicios = servicios or ServiciosVelocidad()
        self._obtener_discos = obtener_discos or (lambda: [])
        self.modo_demo = demo is not None  # demo: VelocidadMedida de ejemplo; nunca se ejecuta fio
        self.carpeta = None
        self.revision = None
        self.ubicacion = None
        self.estado_fio = None
        self.ejecucion = None
        self.en_marcha = False
        self.restos = []
        self.dialogo_restos = None
        self._hilo = None
        self._al_terminar = []
        self._parcial = None
        self._configuracion_en_marcha = None
        self._disco_en_marcha = None
        self.velocidad_medida = demo if self.modo_demo else None  # la última prueba terminada, para el informe TXT

        self.banner = Adw.Banner(revealed=False, button_label="Revisar…")
        self.banner.connect("button-clicked", self._al_pulsar_revisar_restos)
        self.append(self.banner)

        desplazable = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.desplazable = desplazable
        # Sin fio no hay prueba posible: Adw.StatusPage con «Reintentar».
        self.boton_reintentar = Gtk.Button(label="Reintentar", halign=Gtk.Align.CENTER)
        self.boton_reintentar.add_css_class("pill")
        self.boton_reintentar.connect("clicked", lambda _boton: self.actualizar())
        self.pagina_sin_fio = Adw.StatusPage(
            icon_name="system-software-install-symbolic", title="Falta fio", child=self.boton_reintentar,
            vexpand=True,
        )
        self.vistas = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.vistas.add_named(desplazable, "prueba")
        self.vistas.add_named(self.pagina_sin_fio, "sin_fio")
        self.append(self.vistas)
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for lado in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{lado}")(18)
        self._contenido = Adw.Clamp(maximum_size=760, child=caja)  # docs/diseno.md
        desplazable.set_child(self._contenido)

        # Configuración.
        grupo = Adw.PreferencesGroup(
            title="Prueba",
            description="fio escribe un archivo temporal en una carpeta nueva dentro de la que elijas, "
            "y Latido lo borra al terminar.",
        )
        self.fila_carpeta = _fila("Carpeta", SIN_CARPETA)
        self.boton_carpeta = Gtk.Button(label="Elegir…", valign=Gtk.Align.CENTER)
        self.boton_carpeta.connect("clicked", self._al_pulsar_elegir)
        self.fila_carpeta.add_suffix(self.boton_carpeta)
        self.fila_tamano = Adw.ComboRow(
            title="Tamaño del archivo de prueba",
            model=Gtk.StringList.new([formato.tamano(t) for t in TAMANOS]),
        )
        self.fila_tamano.set_selected(TAMANOS.index(TAMANO_POR_DEFECTO))
        self.fila_tamano.connect("notify::selected", self._al_cambiar_configuracion)
        self.fila_pasadas = Adw.SpinRow.new_with_range(PASADAS_MINIMO, PASADAS_MAXIMO, 1)
        self.fila_pasadas.set_title("Pasadas")
        self.fila_pasadas.set_subtitle("Cuántas veces se repite cada medición")
        self.fila_pasadas.set_value(PASADAS_POR_DEFECTO)
        self.fila_pasadas.connect("notify::value", self._al_cambiar_configuracion)
        for fila in (self.fila_carpeta, self.fila_tamano, self.fila_pasadas):
            grupo.add(fila)
        caja.append(grupo)

        # Antes de empezar.
        self.grupo_resumen = Adw.PreferencesGroup(title="Antes de empezar")
        self.fila_disco = _fila(NO_SE_PUDO)
        self.icono_disco = Gtk.Image(icon_name=ICONO_DISCO)
        self.fila_disco.add_prefix(self.icono_disco)
        self.fila_fio = _fila("fio", "Se comprueba al abrir esta pestaña")
        self.fila_libre = _fila("Espacio libre", "—")
        self.fila_sistema = _fila("Sistema de archivos", "—")
        self.fila_escritura = _fila("Escritura máxima", "—")
        for fila in (self.fila_disco, self.fila_fio, self.fila_libre, self.fila_sistema, self.fila_escritura):
            self.grupo_resumen.add(fila)
        self._filas_avisos = []
        caja.append(self.grupo_resumen)

        # Un solo botón: Iniciar o Cancelar.
        self.boton = Gtk.Button(label="Iniciar", halign=Gtk.Align.CENTER)
        self.boton.add_css_class("suggested-action")
        self.boton.add_css_class("pill")
        self.boton.connect("clicked", self._al_pulsar_boton)
        caja.append(self.boton)

        # Progreso: «Paso n de 8» en una etiqueta que se ajusta (nunca se corta) y la barra.
        self.zona_progreso = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, visible=False)
        self.etiqueta_paso = Gtk.Label(xalign=0, wrap=True)
        self.etiqueta_paso.add_css_class("heading")
        self.progreso = Gtk.ProgressBar(show_text=False)
        self.zona_progreso.append(self.etiqueta_paso)
        self.zona_progreso.append(self.progreso)
        caja.append(self.zona_progreso)

        # Mensaje del final (también el de la limpieza): ícono y texto, entre el botón y los resultados.
        self.caja_mensaje = Gtk.Box(visible=False)
        self.caja_mensaje.add_css_class("card")
        interior_mensaje = Gtk.Box(spacing=12, margin_top=12, margin_bottom=12, margin_start=18, margin_end=18,
                                   hexpand=True)
        self.icono_mensaje = Gtk.Image(icon_name=ICONO_INFO, valign=Gtk.Align.START)
        self.mensaje = Gtk.Label(xalign=0, wrap=True, selectable=True, hexpand=True)
        interior_mensaje.append(self.icono_mensaje)
        interior_mensaje.append(self.mensaje)
        self.caja_mensaje.append(interior_mensaje)
        caja.append(self.caja_mensaje)

        # Resultados: una rejilla, una fila por prueba y Lectura | Escritura.
        self.resultados = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        titulo_resultados = Gtk.Label(label="Resultados", xalign=0)
        titulo_resultados.add_css_class("heading")
        self.tarjeta_resultados = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tarjeta_resultados.add_css_class("card")
        self.rejilla = Gtk.Grid(column_spacing=18, row_spacing=12, margin_top=18, margin_bottom=18,
                                margin_start=18, margin_end=18)
        encabezado = Gtk.Box(spacing=18, homogeneous=True, hexpand=True)
        self.encabezados = [Gtk.Label(label=direccion.texto.capitalize(), xalign=0) for direccion in ORDEN_DIRECCIONES]
        for etiqueta in self.encabezados:
            etiqueta.add_css_class("heading")
            encabezado.append(etiqueta)
        self.rejilla.attach(encabezado, 1, 0, 1, 1)
        self.cuadros = {}
        for numero, prueba in enumerate(PRUEBAS):
            fila = FilaPrueba(prueba)
            self.cuadros[prueba.clave] = fila
            self.rejilla.attach(Gtk.Separator(), 0, 2 * numero + 1, 2, 1)
            self.rejilla.attach(fila.cabecera, 0, 2 * numero + 2, 1, 1)
            self.rejilla.attach(fila.celdas, 1, 2 * numero + 2, 1, 1)
        self.tarjeta_resultados.append(self.rejilla)
        self.resultados.append(titulo_resultados)
        self.resultados.append(self.tarjeta_resultados)
        caja.append(self.resultados)

        nota = Gtk.Label(label=NOTA, wrap=True, xalign=0)
        nota.add_css_class("caption")
        nota.add_css_class("dimmed")
        self.nota = nota
        caja.append(nota)

        self._actualizar_resumen()
        if self.modo_demo:
            self.fila_carpeta.set_subtitle("Modo demo: no se mide nada")
            self.mostrar_resultado(demo.resultado)
            self._mostrar_mensaje("Resultados de ejemplo. En el modo demo no se ejecuta fio.", ICONO_INFO)
            self._actualizar_boton()

    # --- al abrir la pestaña ---

    def al_mostrar(self):
        """Se llama cada vez que se abre la pestaña: comprueba fio y busca restos."""
        if self.estado_fio is None:
            self.estado_fio = self.servicios.comprobar_fio()
        if not self.en_marcha:
            self.revisar_restos()
        self._actualizar_resumen()

    def actualizar(self):
        """Ctrl+R o «Reintentar»: vuelve a comprobar fio y a buscar restos (nunca con una prueba en marcha)."""
        if self.en_marcha:
            return
        self.estado_fio = None
        self.al_mostrar()

    def revisar_restos(self):
        carpeta = self.servicios.leer_ultima_carpeta()
        self.restos = self.servicios.buscar_restos(carpeta) if carpeta else []
        if self.restos:
            self.banner.set_title(
                f"Quedó una prueba anterior sin limpiar en «{carpeta}». Latido no la borra sin tu confirmación."
            )
        self.banner.set_revealed(bool(self.restos))

    def _al_pulsar_revisar_restos(self, _banner):
        if not self.restos:
            return
        alguno = any(r.se_puede_borrar for r in self.restos)
        cuerpo = "\n".join(r.descripcion() for r in self.restos)
        if alguno:
            cuerpo += "\n\nSi aceptas, Latido borra solo su archivo de prueba (por su nombre exacto) y la carpeta vacía."
        dialogo = Adw.AlertDialog(heading="Restos de una prueba anterior", body=cuerpo)
        dialogo.add_response("cancelar", "No borrar")
        dialogo.add_response("borrar", "Borrar")
        dialogo.set_response_appearance("borrar", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_response_enabled("borrar", alguno)
        dialogo.set_default_response("cancelar")
        dialogo.set_close_response("cancelar")
        dialogo.connect("response", self.responder_restos)
        self.dialogo_restos = dialogo
        dialogo.present(self.get_root())

    def responder_restos(self, _dialogo, respuesta):
        self.dialogo_restos = None
        if respuesta != "borrar" or self.en_marcha:
            return
        mensajes, icono = [], ICONO_BIEN
        for resto in self.restos:
            if not resto.se_puede_borrar:
                continue
            try:
                mensajes.append(self.servicios.borrar_resto(resto))
            except ErrorResto as error:
                mensajes.append(str(error))
                icono = ICONO_AVISO
        self._mostrar_mensaje("\n".join(mensajes), icono)
        self.revisar_restos()

    # --- configuración y resumen previo ---

    def configuracion(self):
        return Configuracion(TAMANOS[self.fila_tamano.get_selected()], int(self.fila_pasadas.get_value()))

    def _al_cambiar_configuracion(self, *_):
        if not self.en_marcha:
            self._actualizar_resumen()

    def _al_pulsar_elegir(self, _boton):
        dialogo = Gtk.FileDialog(title="Carpeta para la prueba de velocidad", modal=True)
        if self.carpeta:
            dialogo.set_initial_folder(Gio.File.new_for_path(self.carpeta))
        dialogo.select_folder(self.get_root(), None, self._carpeta_elegida)

    def _carpeta_elegida(self, dialogo, resultado):
        try:
            archivo = dialogo.select_folder_finish(resultado)
        except GLib.Error as error:
            if not error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                self._mostrar_mensaje(f"No se pudo usar el selector de carpetas: {error.message}", ICONO_AVISO)
            return
        ruta = archivo.get_path() if archivo else None
        if not ruta:
            self._mostrar_mensaje("La carpeta elegida no tiene una ruta local; elige una carpeta de un disco.",
                                  ICONO_AVISO)
            return
        self.elegir_carpeta(ruta)

    def elegir_carpeta(self, ruta):
        self.carpeta = ruta
        self.fila_carpeta.set_subtitle(ruta)
        self._actualizar_resumen()

    def _actualizar_resumen(self):
        configuracion = self.configuracion()
        maximo = configuracion.escritura_maxima
        self.fila_escritura.set_subtitle(f"{formato.tamano(maximo)} ({formato.gigabytes(maximo)}) como máximo")
        if self.modo_demo:
            self.fila_fio.set_subtitle("En el modo demo no se ejecuta fio")
        elif self.estado_fio is not None:
            if self.estado_fio.problemas:
                self.fila_fio.set_subtitle("\n".join(self.estado_fio.problemas))
            else:
                self.fila_fio.set_subtitle(f"{self.estado_fio.version or 'fio'} con motor libaio")
        sin_fio = self.estado_fio is not None and bool(self.estado_fio.problemas) and not self.en_marcha
        if sin_fio:
            problemas = "\n".join(self.estado_fio.problemas)
            self.pagina_sin_fio.set_title("Falta fio" if "Falta fio" in problemas else "fio no está listo")
            self.pagina_sin_fio.set_description(GLib.markup_escape_text(problemas))
        self.vistas.set_visible_child_name("sin_fio" if sin_fio else "prueba")
        for fila in self._filas_avisos:
            self.grupo_resumen.remove(fila)
        self._filas_avisos = []

        self.revision = None
        if self.carpeta is not None:
            self.revision = self.servicios.revisar_carpeta(self.carpeta, configuracion)
        info = self.revision.info if self.revision else None
        if self.modo_demo and self.velocidad_medida.disco is not None:
            self.fila_disco.set_title(f"Medida en: {self.velocidad_medida.disco.etiqueta_corta} (ejemplo)")
            self.fila_disco.set_subtitle("En el modo demo no se mide ningún disco real.")
            self.icono_disco.set_from_icon_name(ICONO_DISCO)
            self.fila_disco.set_visible(True)
        elif info is None:
            self.ubicacion = None
            self.fila_disco.set_visible(False)
        else:
            self.ubicacion = self.servicios.ubicar_carpeta(info.ruta, list(self._obtener_discos()))
            self.fila_disco.set_title(self.ubicacion.texto_antes)
            self.fila_disco.set_subtitle(self.ubicacion.motivo or "")
            self.icono_disco.set_from_icon_name(ICONO_DISCO if self.ubicacion.disco is not None else ICONO_AVISO)
            self.fila_disco.set_visible(True)
        if info is None or info.libre is None:
            self.fila_libre.set_subtitle("—")
        else:
            necesario = espacio_necesario(configuracion.tamano)
            self.fila_libre.set_subtitle(
                f"{formato.tamano(info.libre)} libres · hacen falta {formato.tamano(necesario)} "
                f"({formato.tamano(configuracion.tamano)} + {formato.tamano(margen(configuracion.tamano))} de margen)"
            )
        if info is None:
            self.fila_sistema.set_subtitle("—")
        elif info.tipo is None:
            self.fila_sistema.set_subtitle("No se pudo saber")
        else:
            self.fila_sistema.set_subtitle(f"{info.tipo} · {info.fuente} montado en {info.punto_montaje}")

        if self.revision is not None:
            for error in self.revision.errores:
                self._agregar_aviso(error, "dialog-error-symbolic")
            for aviso in self.revision.avisos:
                self._agregar_aviso(aviso, "dialog-warning-symbolic")
        self._actualizar_boton()

    def _agregar_aviso(self, texto, icono):
        fila = _fila(texto, icono=icono)
        self.grupo_resumen.add(fila)
        self._filas_avisos.append(fila)

    def puede_empezar(self):
        return (
            not self.modo_demo
            and not self.en_marcha
            and self.estado_fio is not None
            and self.estado_fio.listo
            and self.revision is not None
            and self.revision.puede_empezar
        )

    def _actualizar_boton(self):
        if self.en_marcha:
            cancelando = self.ejecucion is not None and self.ejecucion.cancelada
            self.boton.set_label("Cancelando…" if cancelando else "Cancelar")
            self.boton.remove_css_class("suggested-action")
            self.boton.add_css_class("destructive-action")
            self.boton.set_sensitive(self.ejecucion is not None and not cancelando)
        else:
            self.boton.set_label("Iniciar")
            self.boton.remove_css_class("destructive-action")
            self.boton.add_css_class("suggested-action")
            self.boton.set_sensitive(self.puede_empezar())
        for control in (self.boton_carpeta, self.fila_tamano, self.fila_pasadas):
            control.set_sensitive(not self.en_marcha and not self.modo_demo)

    def _mostrar_mensaje(self, texto, icono=ICONO_INFO):
        """El ícono acompaña al texto, nunca va solo."""
        self.mensaje.set_text(texto)
        self.icono_mensaje.set_from_icon_name(icono)
        self.caja_mensaje.set_visible(bool(texto))

    # --- ejecución en un hilo ---

    def _al_pulsar_boton(self, _boton):
        if self.en_marcha:
            self.cancelar()
        else:
            self.iniciar()

    def iniciar(self):
        if not self.puede_empezar():
            return False
        configuracion = self.configuracion()
        self.en_marcha = True
        self.banner.set_revealed(False)
        self._configuracion_en_marcha = configuracion
        self._disco_en_marcha = self.ubicacion.disco if self.ubicacion else None
        self._parcial = ResultadoVelocidad(configuracion.pasadas)
        for celda in self._celdas():
            celda.limpiar()
        self._mostrar_mensaje("")
        self.progreso.set_fraction(0)
        self.etiqueta_paso.set_text("Comprobando fio y la carpeta…")
        self.zona_progreso.set_visible(True)
        self.ejecucion = self.servicios.crear_ejecucion(
            self.carpeta, configuracion, al_progresar=lambda progreso: GLib.idle_add(self._mostrar_progreso, progreso)
        )
        self._actualizar_boton()
        self._hilo = threading.Thread(target=self._ejecutar_en_hilo, args=(self.ejecucion,), daemon=True)
        self._hilo.start()
        GLib.idle_add(self._desplazar_a_resultados)
        return True

    def _desplazar_a_resultados(self):
        """Lleva la vista al botón, el progreso o el mensaje, y los resultados."""
        ok, punto = self.boton.compute_point(self._contenido, Graphene.Point().init(0, 0))
        if ok:
            ajuste = self.desplazable.get_vadjustment()
            ajuste.set_value(min(max(punto.y - 12, 0), ajuste.get_upper() - ajuste.get_page_size()))
        return GLib.SOURCE_REMOVE

    def _ejecutar_en_hilo(self, ejecucion):
        try:
            resultado = ejecucion.ejecutar()
        except (Cancelado, ErrorVelocidad) as error:
            resultado = error
        except Exception:
            traceback.print_exc()
            resultado = ErrorVelocidad("Ocurrió un error inesperado en Latido durante la prueba.")
        GLib.idle_add(self._terminar, resultado)

    def _mostrar_progreso(self, progreso):
        configuracion = self._configuracion_en_marcha
        paso = progreso.paso
        if not progreso.terminado:
            if not paso.es_preparacion:
                self.cuadros[paso.prueba.clave].columnas[paso.direccion].midiendo(paso.pasada, configuracion.pasadas)
            self.etiqueta_paso.set_text(texto_del_paso(paso, configuracion))
            self.progreso.set_fraction(progreso.indice / progreso.total)
        else:
            self.progreso.set_fraction((progreso.indice + 1) / progreso.total)
            if progreso.medicion is not None:
                self._parcial.agregar(paso, progreso.medicion)
                celda = self.cuadros[paso.prueba.clave].columnas[paso.direccion]
                celda.mostrar(self._parcial.resumen(paso.prueba, paso.direccion), configuracion.pasadas)
                self._actualizar_barras()
        return GLib.SOURCE_REMOVE

    def _terminar(self, resultado):
        self.en_marcha = False
        self.ejecucion = None
        self.zona_progreso.set_visible(False)
        if isinstance(resultado, ErrorVelocidad):
            texto = resultado.mensaje
            if resultado.limpieza is not None:
                texto += "\n" + resultado.limpieza.texto()
            self._mostrar_mensaje(texto, ICONO_AVISO)
            self._marcar_sin_terminar()
        elif isinstance(resultado, Cancelado):
            self._mostrar_mensaje("Prueba cancelada. " + resultado.limpieza.texto(),
                                  ICONO_INFO if resultado.limpieza.completa else ICONO_AVISO)
            self._marcar_sin_terminar()
        else:
            self.mostrar_resultado(resultado)
            info = self.revision.info if self.revision else None
            self.velocidad_medida = VelocidadMedida(
                resultado, self._configuracion_en_marcha, info.tipo if info else None, disco=self._disco_en_marcha,
            )
            limpieza = resultado.limpieza
            partes = ["Prueba terminada.", limpieza.texto() if limpieza else ""]
            if resultado.avisos or (limpieza is not None and not limpieza.completa):
                icono = ICONO_AVISO
            else:
                icono = ICONO_INFO if limpieza is None else ICONO_BIEN
            self._mostrar_mensaje(" ".join(p for p in partes if p) + "".join("\n" + a for a in resultado.avisos),
                                  icono)
        self._actualizar_resumen()
        GLib.idle_add(self._desplazar_a_resultados)  # que se vea el mensaje de la limpieza
        pendientes, self._al_terminar = self._al_terminar, []
        for funcion in pendientes:
            funcion()
        return GLib.SOURCE_REMOVE

    def mostrar_resultado(self, resultado):
        for prueba in PRUEBAS:
            for direccion in Direccion:
                resumen = resultado.resumen(prueba, direccion)
                if resumen is not None:
                    self.cuadros[prueba.clave].columnas[direccion].mostrar(resumen, resultado.pasadas)
        self._actualizar_barras()

    def _celdas(self):
        return [celda for fila in self.cuadros.values() for celda in fila.columnas.values()]

    def _actualizar_barras(self):
        """Cada barra, relativa al resultado más alto que hay en la tabla."""
        maximo = max((celda.promedio for celda in self._celdas() if celda.promedio), default=0)
        for celda in self._celdas():
            celda.relativa(maximo)

    def ajustes_angosto(self):
        """Para el Adw.Breakpoint de la ventana (< 560sp): números un poco más chicos, para que quepan.

        El valor va como GObject.Value de tipo GStrv: con una lista de Python, libadwaita 1.9 aborta el
        proceso («Unable to add setter … from value of type 'PyObject'»).
        """
        clases = GObject.Value(GObject.TYPE_STRV, ["title-2", "numeric"])
        return [(celda.valor, "css-classes", clases) for celda in self._celdas()]

    def _marcar_sin_terminar(self):
        for celda in self._celdas():
            celda.sin_terminar()

    def cancelar(self, al_terminar=None):
        """Pide a fio que se detenga; la limpieza la hace el hilo de la prueba."""
        if al_terminar is not None:
            self._al_terminar.append(al_terminar)
        if not self.en_marcha:
            pendientes, self._al_terminar = self._al_terminar, []
            for funcion in pendientes:
                funcion()
            return
        if self.ejecucion is not None:
            self.ejecucion.cancelar()
        self.etiqueta_paso.set_text("Cancelando: deteniendo fio y borrando el archivo de prueba…")
        self._actualizar_boton()

    def detener_y_esperar(self, segundos=60):
        """Al cerrar la aplicación: cancela y espera a que el hilo termine de limpiar."""
        if self.en_marcha and self.ejecucion is not None:
            self.ejecucion.cancelar()
        if self._hilo is not None:
            self._hilo.join(segundos)
