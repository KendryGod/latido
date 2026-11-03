"""Ventana principal de Latido."""

from gi.repository import Adw

from latido.ui.estilo import cargar_estilo
from latido.ui.pagina_salud import PaginaSalud
from latido.ui.pagina_velocidad import PaginaVelocidad


ANCHO, ALTO = 800, 900
ANCHO_MINIMO, ALTO_MINIMO = 400, 500


class VentanaPrincipal(Adw.ApplicationWindow):
    def __init__(self, discos, lector, error_deteccion=None, aviso_desarrollo=None, servicios_velocidad=None, **kwargs):
        super().__init__(title="Latido", default_width=ANCHO, default_height=ALTO, **kwargs)
        self.set_size_request(ANCHO_MINIMO, ALTO_MINIMO)
        cargar_estilo()
        self.dialogo_cerrar = None
        self._cerrando = False

        self.pila = Adw.ViewStack()
        self.pagina_salud = PaginaSalud(discos, lector, error_deteccion)
        self.pila.add_titled_with_icon(self.pagina_salud, "salud", "Salud", "drive-harddisk-symbolic")
        self.pagina_velocidad = PaginaVelocidad(servicios_velocidad)
        self.pila.add_titled_with_icon(self.pagina_velocidad, "velocidad", "Velocidad", "power-profile-performance-symbolic")
        self.pila.connect("notify::visible-child", self._al_cambiar_pestana)

        cabecera = Adw.HeaderBar()
        cabecera.set_title_widget(Adw.ViewSwitcher(stack=self.pila, policy=Adw.ViewSwitcherPolicy.WIDE))

        vista = Adw.ToolbarView()
        vista.add_top_bar(cabecera)
        if aviso_desarrollo:
            vista.add_top_bar(Adw.Banner(title=aviso_desarrollo, revealed=True))
        vista.set_content(self.pila)
        self.set_content(vista)
        self.connect("close-request", self._al_pedir_cierre)

    def _al_cambiar_pestana(self, *_):
        if self.pila.get_visible_child() is self.pagina_velocidad:
            self.pagina_velocidad.al_mostrar()

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
