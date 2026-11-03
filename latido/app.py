"""Punto de entrada: latido [--desde-fixture RUTA | --demo ESTADO]."""

import sys

ESTADOS_DEMO = ("sano", "precaucion", "peligro", "sin-datos")

USO = """Uso: latido [--desde-fixture RUTA | --demo ESTADO]

  --desde-fixture RUTA   Modo desarrollo: muestra un JSON de smartctl guardado
                         (o una respuesta del ayudante), sin pedir permisos.
  --demo ESTADO          Abre Latido con datos de ejemplo: sano, precaucion,
                         peligro o sin-datos. No lee ningún disco ni ejecuta nada.
  -h, --ayuda            Muestra esta ayuda."""


class ErrorArgumentos(Exception):
    pass


def _estado_demo(valor):
    if valor not in ESTADOS_DEMO:
        raise ErrorArgumentos(f"estado de demo desconocido: {valor!r} (usa {', '.join(ESTADOS_DEMO)})")
    return valor


def interpretar_argumentos(argv):
    """Devuelve (ayuda, ruta_fixture, estado_demo)."""
    ayuda = False
    ruta = None
    demo = None
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
        elif argumento == "--demo":
            if not restantes:
                raise ErrorArgumentos("falta el ESTADO después de --demo")
            demo = _estado_demo(restantes.pop(0))
        elif argumento.startswith("--demo="):
            demo = _estado_demo(argumento.split("=", 1)[1])
        else:
            raise ErrorArgumentos(f"argumento no reconocido: {argumento}")
    if ruta and demo:
        raise ErrorArgumentos("usa --desde-fixture o --demo, no los dos")
    return ayuda, ruta, demo


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        ayuda, ruta_fixture, demo = interpretar_argumentos(argv)
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

    return Aplicacion(ruta_fixture=ruta_fixture, demo=demo).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
