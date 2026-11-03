"""Ventana principal de Latido."""

from gi.repository import Adw

from latido.ui.estilo import cargar_estilo
from latido.ui.pagina_salud import PaginaSalud


class VentanaPrincipal(Adw.ApplicationWindow):
    def __init__(self, discos, lector, error_deteccion=None, aviso_desarrollo=None, **kwargs):
        super().__init__(title="Latido", default_width=760, default_height=880, **kwargs)
        cargar_estilo()

        self.pila = Adw.ViewStack()
        self.pagina_salud = PaginaSalud(discos, lector, error_deteccion)
        self.pila.add_titled_with_icon(self.pagina_salud, "salud", "Salud", "drive-harddisk-symbolic")

        cabecera = Adw.HeaderBar()
        cabecera.set_title_widget(Adw.ViewSwitcher(stack=self.pila, policy=Adw.ViewSwitcherPolicy.WIDE))

        vista = Adw.ToolbarView()
        vista.add_top_bar(cabecera)
        if aviso_desarrollo:
            vista.add_top_bar(Adw.Banner(title=aviso_desarrollo, revealed=True))
        vista.set_content(self.pila)
        self.set_content(vista)
