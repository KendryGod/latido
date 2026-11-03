#!/usr/bin/env python3
"""Capturas PNG de Latido en modo demo, para revisar el diseño. No está en la CI.

Cada estado (sano, precaucion, peligro, sin-datos) × claro/oscuro × ancho normal (1366x768) o angosto
(720x768) × pestaña (salud, velocidad), arriba y desplazada hasta abajo. Sin tocar ningún disco: es el modo
demo.

Uso:
    python3 tools/capturas.py [CARPETA] [--con-mi-tema]

CARPETA es ~/latido-informes/capturas por defecto (modo 0700, archivos 0600). Sin --con-mi-tema, GTK no lee
la configuración del usuario (XDG_CONFIG_HOME apunta a una carpeta que no existe), así que se ve la paleta
de libadwaita; con --con-mi-tema se ve con el tema del usuario.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ANCHOS = {"normal": (1366, 768), "angosto": (720, 768)}


def _argumentos(argv):
    con_mi_tema = "--con-mi-tema" in argv
    resto = [a for a in argv if a != "--con-mi-tema"]
    destino = Path(resto[0]) if resto else Path.home() / "latido-informes" / "capturas"
    return destino, con_mi_tema


def main(argv):
    destino, con_mi_tema = _argumentos(argv)
    if not con_mi_tema:
        os.environ["XDG_CONFIG_HOME"] = "/nonexistent-latido-capturas"
    sys.path.insert(0, str(RAIZ))
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Graphene, Gtk

    from latido.demo import ESTADOS
    from latido.ui.aplicacion import crear_ventana_demo

    def esperar(segundos):
        contexto = GLib.MainContext.default()
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            contexto.iteration(False)
            time.sleep(0.01)

    def capturar(ventana, ruta):
        ancho, alto = ventana.get_width(), ventana.get_height()
        instantanea = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(ventana).snapshot(instantanea, ancho, alto)
        textura = ventana.get_renderer().render_texture(instantanea.to_node(), Graphene.Rect().init(0, 0, ancho, alto))
        descriptor, temporal = tempfile.mkstemp(prefix=".captura-", suffix=".png", dir=ruta.parent)
        os.close(descriptor)
        try:
            textura.save_to_png(temporal)
            os.chmod(temporal, 0o600)
            os.replace(temporal, ruta)
        except BaseException:
            if os.path.lexists(temporal):
                os.unlink(temporal)
            raise
        return ancho, alto

    destino.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destino, 0o700)
    Adw.init()
    esquemas = {"claro": Adw.ColorScheme.FORCE_LIGHT, "oscuro": Adw.ColorScheme.FORCE_DARK}
    hechas = []
    for tema, esquema in esquemas.items():
        Adw.StyleManager.get_default().set_color_scheme(esquema)
        for estado in ESTADOS:
            for nombre_ancho, (ancho, alto) in ANCHOS.items():
                ventana = crear_ventana_demo(estado)
                ventana.set_default_size(ancho, alto)
                ventana.present()
                esperar(0.8)
                for pestana in ("salud", "velocidad"):
                    ventana.pila.set_visible_child_name(pestana)
                    esperar(0.5)
                    desplazable = ventana.pagina_salud if pestana == "salud" else ventana.pagina_velocidad.desplazable
                    for parte in ("arriba", "abajo"):
                        ajuste = desplazable.get_vadjustment()
                        ajuste.set_value(0 if parte == "arriba" else ajuste.get_upper() - ajuste.get_page_size())
                        esperar(0.3)
                        ruta = destino / f"{estado}-{tema}-{nombre_ancho}-{pestana}-{parte}.png"
                        tamano = capturar(ventana, ruta)
                        hechas.append((ruta.name, tamano))
                ventana.destroy()
                esperar(0.1)
    for nombre, (ancho, alto) in hechas:
        print(f"{nombre}  {ancho}x{alto}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
