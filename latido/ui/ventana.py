"""Ventana principal de Latido (docs/diseno.md, «Estructura»)."""

from datetime import datetime

from gi.repository import Adw, Gio, GLib, Gtk

from latido import __version__
from latido.informe_txt import ErrorExportar, construir_texto, escribir_informe, nombre_por_defecto
from latido.ui.estilo import cargar_estilo
from latido.ui.pagina_salud import PaginaSalud
from latido.ui.pagina_velocidad import PaginaVelocidad

# Cabe en una pantalla de 1366x768 con la barra del escritorio.
ANCHO, ALTO = 900, 700
ANCHO_MINIMO, ALTO_MINIMO = 400, 500
# Por debajo de este ancho, las pestañas bajan a una barra inferior.
ANCHO_ANGOSTO = "560sp"
ATAJOS = {
    "win.actualizar": ["<Control>r"],
    "win.exportar": ["<Control>e"],
    "app.salir": ["<Control>q"],
}


class VentanaPrincipal(Adw.ApplicationWindow):
    def __init__(self, discos, lector, error_deteccion=None, aviso_desarrollo=None, servicios_velocidad=None,
                 detectar=None, demo=False, velocidad_demo=None, **kwargs):
        super().__init__(title="Latido", default_width=ANCHO, default_height=ALTO, **kwargs)
        self.demo = demo
        self.set_size_request(ANCHO_MINIMO, ALTO_MINIMO)
        cargar_estilo()
        self.dialogo_cerrar = None
        self._cerrando = False

        self.pila = Adw.ViewStack()
        self.pagina_salud = PaginaSalud(discos, lector, error_deteccion, detectar=detectar)
        self.pila.add_titled_with_icon(self.pagina_salud, "salud", "Salud", "drive-harddisk-symbolic")
        self.pagina_velocidad = PaginaVelocidad(servicios_velocidad, demo=velocidad_demo)
        self.pila.add_titled_with_icon(self.pagina_velocidad, "velocidad", "Velocidad", "power-profile-performance-symbolic")

        self.cabecera = Adw.HeaderBar()
        self.cambiador = Adw.ViewSwitcher(stack=self.pila, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.cabecera.set_title_widget(self.cambiador)
        self.selector = self.pagina_salud.selector  # la página lo maneja; vive en la cabecera
        self.cabecera.pack_start(self.selector)
        menu = Gio.Menu()
        menu.append("Exportar informe…", "win.exportar")
        menu.append("Acerca de Latido", "win.acerca")
        menu.append("Salir", "app.salir")
        self.boton_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menú",
                                         primary=True)
        self.boton_actualizar = Gtk.Button(icon_name="view-refresh-symbolic", action_name="win.actualizar")
        self.cabecera.pack_end(self.boton_menu)
        self.cabecera.pack_end(self.boton_actualizar)

        self.toasts = Adw.ToastOverlay(child=self.pila)
        self.barra_inferior = Adw.ViewSwitcherBar(stack=self.pila)
        vista = Adw.ToolbarView()
        vista.add_top_bar(self.cabecera)
        if aviso_desarrollo:
            vista.add_top_bar(Adw.Banner(title=aviso_desarrollo, revealed=True))
        vista.set_content(self.toasts)
        vista.add_bottom_bar(self.barra_inferior)
        self.set_content(vista)

        self.angosto = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {ANCHO_ANGOSTO}"))
        self.angosto.add_setter(self.cambiador, "visible", False)
        self.angosto.add_setter(self.barra_inferior, "reveal", True)
        self.add_breakpoint(self.angosto)

        for nombre, funcion in (("actualizar", self.actualizar), ("exportar", self.exportar),
                                ("acerca", self.mostrar_acerca_de)):
            accion = Gio.SimpleAction(name=nombre)
            accion.connect("activate", lambda _accion, _parametro, funcion=funcion: funcion())
            self.add_action(accion)
        self.lookup_action("exportar").set_enabled(False)
        self.pagina_salud.al_cambiar_informe = self._actualizar_exportar

        self.pila.connect("notify::visible-child", self._al_cambiar_pestana)
        self.connect("close-request", self._al_pedir_cierre)
        self._al_cambiar_pestana()

    # --- cabecera y acciones ---

    def _al_cambiar_pestana(self, *_):
        en_salud = self.pila.get_visible_child() is self.pagina_salud
        self.selector.set_visible(en_salud)
        self.boton_actualizar.set_tooltip_text(
            "Leer salud (Ctrl+R)" if en_salud else "Volver a comprobar fio y los restos (Ctrl+R)"
        )
        if not en_salud:
            self.pagina_velocidad.al_mostrar()

    def actualizar(self):
        """Ctrl+R: en Salud lee el disco elegido; en Velocidad vuelve a comprobar fio y los restos."""
        if self.pila.get_visible_child() is self.pagina_salud:
            self.pagina_salud.leer()
        else:
            self.pagina_velocidad.actualizar()

    def _actualizar_exportar(self):
        """Exportar informe solo tiene sentido con un informe de salud en pantalla."""
        self.lookup_action("exportar").set_enabled(self.pagina_salud.informe is not None)

    def texto_del_informe(self, fecha=None):
        if self.pagina_salud.informe is None:
            return None
        return construir_texto(
            self.pagina_salud.informe, self.pagina_salud.disco_informe,
            velocidad=self.pagina_velocidad.velocidad_medida, fecha=fecha, demo=self.demo,
        )

    def exportar(self):
        """Ctrl+E: elige dónde guardar (Gtk.FileDialog pide confirmación antes de reemplazar un archivo)."""
        ahora = datetime.now()
        texto = self.texto_del_informe(ahora)
        if texto is None:
            self.avisar("Primero lee la salud de un disco.")
            return
        dialogo = Gtk.FileDialog(title="Exportar informe", initial_name=nombre_por_defecto(ahora), modal=True)
        dialogo.save(self, None, self._destino_elegido, texto)

    def _destino_elegido(self, dialogo, resultado, texto):
        try:
            archivo = dialogo.save_finish(resultado)
        except GLib.Error as error:
            if not error.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                self.avisar(f"No se pudo usar el selector de archivos: {error.message}")
            return
        ruta = archivo.get_path() if archivo else None
        if not ruta:
            self.avisar("Elige una carpeta de un disco local.")
            return
        self.guardar_informe(ruta, texto)

    def guardar_informe(self, ruta, texto):
        try:
            escribir_informe(ruta, texto)
        except ErrorExportar as error:
            self.avisar(str(error))
            return False
        except OSError as error:
            self.avisar(f"No se pudo guardar el informe: {error.strerror}.")
            return False
        self.avisar("Informe guardado.")
        return True

    def mostrar_acerca_de(self):
        self.crear_acerca_de().present(self)

    def crear_acerca_de(self):
        return Adw.AboutDialog(
            application_name="Latido",
            application_icon="drive-harddisk-symbolic",
            version=__version__,
            comments="Salud y velocidad de discos en Linux. Para la salud solo lee el disco; la prueba de "
            "velocidad escribe un archivo temporal en la carpeta que elijas y lo borra al terminar.",
            license_type=Gtk.License.GPL_3_0,
        )

    def avisar(self, texto):
        """Aviso breve (Adw.Toast) que se va solo."""
        self.toasts.add_toast(Adw.Toast(title=texto, timeout=4))

    # --- cerrar ---

    def _al_pedir_cierre(self, _ventana):
        """Con una prueba en marcha, pide confirmación; al confirmar, cancela, limpia y cierra."""
        if not self.pagina_velocidad.en_marcha:
            return False
        if self._cerrando or self.dialogo_cerrar is not None:
            return True
        dialogo = Adw.AlertDialog(
            heading="Hay una prueba de velocidad en marcha",
            body="Si cierras ahora, Latido detiene fio y borra el archivo de prueba antes de salir.",
        )
        dialogo.add_response("seguir", "Seguir midiendo")
        dialogo.add_response("cerrar", "Cancelar y cerrar")
        dialogo.set_response_appearance("cerrar", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("seguir")
        dialogo.set_close_response("seguir")
        dialogo.connect("response", self.responder_cierre)
        self.dialogo_cerrar = dialogo
        dialogo.present(self)
        return True

    def responder_cierre(self, _dialogo, respuesta):
        self.dialogo_cerrar = None
        if respuesta != "cerrar":
            return
        self._cerrando = True
        self.pagina_velocidad.cancelar(al_terminar=self.close)
