"""Colores fijos por estado.

Solo colores con nombre de la paleta de libadwaita (definidos con
@define-color en su hoja de estilos); nunca hex. El color va de fondo de una
insignia y el texto encima usa un color fijo, para que el contraste sea el
mismo en tema claro y oscuro. -gtk-icon-palette evita que las partes
"warning"/"error" de los íconos simbólicos tomen los colores del tema.
"""

import re

from gi.repository import Gdk, Gtk

CSS = """
.latido-insignia {
  border-radius: 12px;
  padding: 12px 24px;
}
.latido-bueno {
  background-color: @blue_3;
  color: @light_1;
  -gtk-icon-palette: success @light_1, warning @light_1, error @light_1;
}
.latido-precaucion {
  background-color: @yellow_5;
  color: @dark_4;
  -gtk-icon-palette: success @dark_4, warning @dark_4, error @dark_4;
}
.latido-malo {
  background-color: @red_3;
  color: @light_1;
  -gtk-icon-palette: success @light_1, warning @light_1, error @light_1;
}
.latido-desconocido {
  background-color: @dark_1;
  color: @light_1;
  -gtk-icon-palette: success @light_1, warning @light_1, error @light_1;
}
"""

COLORES_USADOS = sorted(set(re.findall(r"@([a-z0-9_]+)", CSS)))

_pantallas_con_estilo = set()


def cargar_estilo(pantalla=None):
    """Instala el CSS en la pantalla una sola vez. Devuelve los errores de análisis."""
    pantalla = pantalla or Gdk.Display.get_default()
    if pantalla is None or pantalla in _pantallas_con_estilo:
        return []
    errores = []
    proveedor = Gtk.CssProvider()
    proveedor.connect("parsing-error", lambda _p, _seccion, error: errores.append(error.message))
    proveedor.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(pantalla, proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _pantallas_con_estilo.add(pantalla)
    return errores
