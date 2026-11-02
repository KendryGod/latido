"""Punto de entrada: latido [--desde-fixture RUTA]."""

import sys

USO = """Uso: latido [--desde-fixture RUTA]

  --desde-fixture RUTA   Modo desarrollo: muestra un JSON de smartctl guardado
                         (o una respuesta del ayudante), sin pedir permisos.
  -h, --ayuda            Muestra esta ayuda."""


class ErrorArgumentos(Exception):
    pass


def interpretar_argumentos(argv):
    """Devuelve (ayuda, ruta_fixture)."""
    ayuda = False
    ruta = None
    restantes = list(argv)
    while restantes:
        argumento = restantes.pop(0)
        if argumento in ("-h", "--ayuda", "--help"):
            ayuda = True
        elif argumento == "--desde-fixture":
            if not restantes:
                raise ErrorArgumentos("falta la RUTA después de --desde-fixture")
            ruta = restantes.pop(0)
        elif argumento.startswith("--desde-fixture="):
            ruta = argumento.split("=", 1)[1]
            if not ruta:
                raise ErrorArgumentos("falta la RUTA después de --desde-fixture=")
        else:
            raise ErrorArgumentos(f"argumento no reconocido: {argumento}")
    return ayuda, ruta


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        ayuda, ruta_fixture = interpretar_argumentos(argv)
    except ErrorArgumentos as error:
        print(f"latido: {error}\n\n{USO}", file=sys.stderr)
        return 2
    if ayuda:
        print(USO)
        return 0

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from latido.ui.aplicacion import Aplicacion

    return Aplicacion(ruta_fixture=ruta_fixture).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
