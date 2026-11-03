"""Pestaña "Velocidad": lectura y escritura con fio, en una carpeta que elige el usuario."""

import threading
import traceback
from dataclasses import dataclass
from typing import Callable

from gi.repository import Adw, Gio, GLib, Graphene, Gtk, Pango

from latido.informe_txt import VelocidadMedida
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
    "MB/s = 1,000,000 bytes por segundo. IOPS = operaciones por segundo. "
    "El número grande es el promedio de las pasadas; debajo van la mejor y la peor. "
    f"Cada medición dura como máximo {SEGUNDOS_POR_MEDICION} s. Los resultados solo se muestran aquí: no se guardan."
)
SIN_CARPETA = "Elige dónde crear el archivo de prueba"


@dataclass
class ServiciosVelocidad:
    """Lo que la pestaña usa del sistema. Las pruebas lo reemplazan por falsos."""

    comprobar_fio: Callable = comprobar_fio
    revisar_carpeta: Callable = revisar_carpeta
    crear_ejecucion: Callable = Ejecucion  # (carpeta, configuracion, al_progresar=...) -> Ejecucion
    leer_ultima_carpeta: Callable = leer_ultima_carpeta
    buscar_restos: Callable = buscar_restos
    borrar_resto: Callable = borrar_resto


def _fila(titulo, subtitulo=None, icono=None):
    fila = Adw.ActionRow(title=titulo, use_markup=False, title_lines=0, subtitle_lines=0)
    if subtitulo:
        fila.set_subtitle(subtitulo)
    if icono:
        fila.add_prefix(Gtk.Image(icon_name=icono))
    return fila


class ColumnaResultado(Gtk.Box):
    """Lectura o escritura de un cuadro: MB/s grande, IOPS debajo, mejor y peor."""

    def __init__(self, titulo):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        encabezado = Gtk.Label(label=titulo)
        encabezado.add_css_class("caption-heading")
        self.valor = Gtk.Label()
        self.valor.add_css_class("title-1")
        unidad = Gtk.Label(label="MB/s")
        unidad.add_css_class("dimmed")
        self.iops = Gtk.Label()
        # Ancho máximo con ajuste de línea: así un texto largo no ensancha el
        # cuadro y siguen cabiendo dos cuadros por fila.
        self.extremos = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=20)
        self.extremos.add_css_class("caption")
        self.extremos.add_css_class("dimmed")
        self.estado = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=20)
        self.estado.add_css_class("caption")
        for hijo in (encabezado, self.valor, unidad, self.iops, self.extremos, self.estado):
            self.append(hijo)
        self.limpiar()

    def limpiar(self):
        self.valor.set_text("—")
        self.iops.set_text("")
        self.extremos.set_text("")
        self.estado.set_text("Pendiente")

    def midiendo(self, pasada, pasadas):
        self.estado.set_text(f"Midiendo… pasada {pasada} de {pasadas}")

    def mostrar(self, resumen, pasadas):
        self.valor.set_text(formato.mb_s(resumen.promedio))
        self.iops.set_text(f"{formato.iops(resumen.iops_promedio)} IOPS")
        if resumen.pasadas > 1:
            self.extremos.set_text(f"Mejor {formato.mb_s(resumen.mejor)} MB/s\nPeor {formato.mb_s(resumen.peor)} MB/s")
        else:
            self.extremos.set_text("")
        self.estado.set_text("" if resumen.pasadas == pasadas else f"{resumen.pasadas} de {pasadas} pasadas")

    def sin_terminar(self):
        if self.valor.get_text() == "—":
            self.estado.set_text("Sin resultado")


class CuadroPrueba(Gtk.Box):
    def __init__(self, prueba):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.prueba = prueba
        self.add_css_class("card")
        for lado in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{lado}")(0)
        interior = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=14, margin_bottom=14,
                           margin_start=14, margin_end=14)
        titulo = Gtk.Label(label=prueba.nombre, xalign=0)
        titulo.add_css_class("title-3")
        descripcion = Gtk.Label(label=prueba.descripcion, xalign=0, wrap=True)
        descripcion.add_css_class("caption")
        descripcion.add_css_class("dimmed")
        columnas = Gtk.Box(spacing=12, homogeneous=True)
        self.columnas = {Direccion.LECTURA: ColumnaResultado("Lectura"), Direccion.ESCRITURA: ColumnaResultado("Escritura")}
        for columna in self.columnas.values():
            columnas.append(columna)
        for hijo in (titulo, descripcion, columnas):
            interior.append(hijo)
        self.append(interior)


class PaginaVelocidad(Gtk.Box):
    def __init__(self, servicios=None, demo=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.servicios = servicios or ServiciosVelocidad()
        self.modo_demo = demo is not None  # demo: VelocidadMedida de ejemplo; nunca se ejecuta fio
        self.carpeta = None
        self.revision = None
        self.estado_fio = None
        self.ejecucion = None
        self.en_marcha = False
        self.restos = []
        self.dialogo_restos = None
        self._hilo = None
        self._al_terminar = []
        self._parcial = None
        self._configuracion_en_marcha = None
        self.velocidad_medida = None  # la última prueba terminada, para el informe TXT

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
        self.fila_fio = _fila("fio", "Se comprueba al abrir esta pestaña")
        self.fila_libre = _fila("Espacio libre", "—")
        self.fila_sistema = _fila("Sistema de archivos", "—")
        self.fila_escritura = _fila("Escritura máxima", "—")
        for fila in (self.fila_fio, self.fila_libre, self.fila_sistema, self.fila_escritura):
            self.grupo_resumen.add(fila)
        self._filas_avisos = []
        caja.append(self.grupo_resumen)

        # Botón, progreso y mensajes.
        self.boton = Gtk.Button(label="Iniciar", halign=Gtk.Align.CENTER)
        self.boton.add_css_class("suggested-action")
        self.boton.add_css_class("pill")
        self.boton.connect("clicked", self._al_pulsar_boton)
        caja.append(self.boton)
        self.progreso = Gtk.ProgressBar(show_text=True, visible=False)
        self.progreso.set_ellipsize(Pango.EllipsizeMode.END)
        caja.append(self.progreso)
        self.mensaje = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
        caja.append(self.mensaje)

        # Resultados: cuatro cuadros.
        self.flujo = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=1,
            max_children_per_line=2, column_spacing=12, row_spacing=12,
        )
        self.cuadros = {}
        for prueba in PRUEBAS:
            cuadro = CuadroPrueba(prueba)
            self.cuadros[prueba.clave] = cuadro
            self.flujo.append(cuadro)
        caja.append(self.flujo)

        nota = Gtk.Label(label=NOTA, wrap=True, xalign=0)
        nota.add_css_class("caption")
        nota.add_css_class("dimmed")
        self.nota = nota
        caja.append(nota)

        self._actualizar_resumen()
        if self.modo_demo:
            self.velocidad_medida = demo
            self.fila_carpeta.set_subtitle("Modo demo: no se mide nada")
            self.mostrar_resultado(demo.resultado)
            self._mostrar_mensaje("Resultados de ejemplo. En el modo demo no se ejecuta fio.")
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
        mensajes = []
        for resto in self.restos:
            if not resto.se_puede_borrar:
                continue
            try:
                mensajes.append(self.servicios.borrar_resto(resto))
            except ErrorResto as error:
                mensajes.append(str(error))
        self._mostrar_mensaje("\n".join(mensajes))
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
                self._mostrar_mensaje(f"No se pudo usar el selector de carpetas: {error.message}")
            return
        ruta = archivo.get_path() if archivo else None
        if not ruta:
            self._mostrar_mensaje("La carpeta elegida no tiene una ruta local; elige una carpeta de un disco.")
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
            self.boton.set_label("Cancelar")
            self.boton.remove_css_class("suggested-action")
            self.boton.add_css_class("destructive-action")
            self.boton.set_sensitive(self.ejecucion is not None and not self.ejecucion.cancelada)
        else:
            self.boton.set_label("Iniciar")
            self.boton.remove_css_class("destructive-action")
            self.boton.add_css_class("suggested-action")
            self.boton.set_sensitive(self.puede_empezar())
        for control in (self.boton_carpeta, self.fila_tamano, self.fila_pasadas):
            control.set_sensitive(not self.en_marcha and not self.modo_demo)

    def _mostrar_mensaje(self, texto):
        self.mensaje.set_text(texto)
        self.mensaje.set_visible(bool(texto))

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
        self._parcial = ResultadoVelocidad(configuracion.pasadas)
        for cuadro in self.cuadros.values():
            for columna in cuadro.columnas.values():
                columna.limpiar()
        self._mostrar_mensaje("")
        self.progreso.set_fraction(0)
        self.progreso.set_text("Comprobando fio y la carpeta…")
        self.progreso.set_visible(True)
        self.ejecucion = self.servicios.crear_ejecucion(
            self.carpeta, configuracion, al_progresar=lambda progreso: GLib.idle_add(self._mostrar_progreso, progreso)
        )
        self._actualizar_boton()
        self._hilo = threading.Thread(target=self._ejecutar_en_hilo, args=(self.ejecucion,), daemon=True)
        self._hilo.start()
        GLib.idle_add(self._desplazar_a_resultados)
        return True

    def _desplazar_a_resultados(self):
        """Lleva la vista al botón, el progreso y los cuadros."""
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
            texto = f"Paso {progreso.indice + 1} de {progreso.total}: {paso.descripcion(configuracion.pasadas)}"
            if paso.es_preparacion:
                texto += f" (escribe {formato.tamano(configuracion.tamano)})"
            else:
                self.cuadros[paso.prueba.clave].columnas[paso.direccion].midiendo(paso.pasada, configuracion.pasadas)
            self.progreso.set_text(texto)
            self.progreso.set_fraction(progreso.indice / progreso.total)
        else:
            self.progreso.set_fraction((progreso.indice + 1) / progreso.total)
            if progreso.medicion is not None:
                self._parcial.agregar(paso, progreso.medicion)
                columna = self.cuadros[paso.prueba.clave].columnas[paso.direccion]
                columna.mostrar(self._parcial.resumen(paso.prueba, paso.direccion), configuracion.pasadas)
        return GLib.SOURCE_REMOVE

    def _terminar(self, resultado):
        self.en_marcha = False
        self.ejecucion = None
        self.progreso.set_visible(False)
        if isinstance(resultado, ErrorVelocidad):
            texto = resultado.mensaje
            if resultado.limpieza is not None:
                texto += "\n" + resultado.limpieza.texto()
            self._mostrar_mensaje(texto)
            self._marcar_sin_terminar()
        elif isinstance(resultado, Cancelado):
            self._mostrar_mensaje("Prueba cancelada. " + resultado.limpieza.texto())
            self._marcar_sin_terminar()
        else:
            self.mostrar_resultado(resultado)
            info = self.revision.info if self.revision else None
            self.velocidad_medida = VelocidadMedida(resultado, self._configuracion_en_marcha,
                                                    info.tipo if info else None)
            partes = ["Prueba terminada.", resultado.limpieza.texto() if resultado.limpieza else ""]
            self._mostrar_mensaje(" ".join(p for p in partes if p) + "".join("\n" + a for a in resultado.avisos))
        self._actualizar_resumen()
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

    def _marcar_sin_terminar(self):
        for cuadro in self.cuadros.values():
            for columna in cuadro.columnas.values():
                columna.sin_terminar()

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
        self.progreso.set_text("Cancelando: deteniendo fio y borrando el archivo de prueba…")
        self._actualizar_boton()

    def detener_y_esperar(self, segundos=60):
        """Al cerrar la aplicación: cancela y espera a que el hilo termine de limpiar."""
        if self.en_marcha and self.ejecucion is not None:
            self.ejecucion.cancelar()
        if self._hilo is not None:
            self._hilo.join(segundos)
