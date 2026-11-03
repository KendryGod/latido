"""Un fio FALSO para las pruebas. Nunca se ejecuta el fio real.

Las pruebas lo copian a tmp_path como ejecutable (con el Python actual en la
primera línea) y lo pasan a Ejecucion(fio=...). Lee su configuración de un
JSON al lado: <ruta>.json con

  modos:     lista de modos, uno por invocación (el último se repite)
  registro:  archivo donde anota cada invocación (una línea JSON, con adónde
             apuntan los descriptores que heredó al arrancar)
  fixtures:  {nombre_de_trabajo: ruta de una salida real de fio}
  enlace:    destino del enlace simbólico del modo "enlaza"
  destino:   ruta nueva de los modos "mueve" y "enlace_duro"

Modos: ok, duerme, ignora_sigterm, falla, json_invalido, truncado,
sin_trabajos, ensucia, y estos, que cambian el archivo de prueba (después de
crearlo, si hacía falta):
  reemplaza    lo borra y crea otro con el mismo nombre y tamaño. Según el
               sistema de archivos, el nuevo puede recibir el mismo número de
               inodo que el borrado: tmpfs y btrfs no lo repiten, pero en la
               CI (run 41575524354) se repitió.
  enlaza       lo borra y pone en su lugar un enlace simbólico a "enlace"
  carpeta      lo borra y pone en su lugar una carpeta vacía
  borra        lo borra sin poner nada en su lugar
  mueve        le cambia el nombre a "destino"
  enlace_duro  le agrega un segundo nombre en "destino"
"""

import json
import os
import signal
import subprocess
import sys
import time

BASE = 100_000_000  # 100 MB/s


def opciones(argv):
    valores = {}
    for argumento in argv[1:]:
        if argumento.startswith("--"):
            clave, _, valor = argumento[2:].partition("=")
            valores[clave] = valor
    return valores


def anotar(registro, **datos):
    with open(registro, "a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(datos) + "\n")


def invocaciones_previas(registro):
    try:
        with open(registro, encoding="utf-8") as archivo:
            lineas = [json.loads(linea) for linea in archivo if linea.strip()]
    except FileNotFoundError:
        return []
    return [linea for linea in lineas if "argv" in linea]  # sin las líneas de los hijos


def salida_ok(op, previas):
    nombre = op["name"]
    repeticion = sum(1 for p in previas if p.get("nombre") == nombre)
    bw = BASE * (repeticion + 1)
    bloque = int(op["bs"])
    seccion = {"io_bytes": int(op["size"]), "bw_bytes": bw, "iops": bw / bloque, "runtime": 1000}
    vacia = {"io_bytes": 0, "bw_bytes": 0, "iops": 0.0, "runtime": 0}
    escribe = op["rw"] in ("write", "randwrite")
    return {
        "fio version": "fio-falso",
        "jobs": [{
            "jobname": nombre,
            "error": 0,
            "read": vacia if escribe else seccion,
            "write": seccion if escribe else vacia,
        }],
    }


def descriptores_heredados():
    """Adónde apunta cada descriptor abierto al arrancar, salvo 0, 1 y 2."""
    destinos = []
    for nombre in os.listdir("/proc/self/fd"):
        if int(nombre) > 2:
            try:
                destinos.append(os.readlink(f"/proc/self/fd/{nombre}"))
            except OSError:
                pass  # el que usó listdir ya se cerró
    return sorted(destinos)


def preparar_archivo(op):
    """Imita lo que hace fio con el archivo: lo crea en una escritura si falta."""
    ruta = op["filename"]
    if os.path.lexists(ruta):
        return True
    if op["rw"] not in ("write", "randwrite") or op.get("allow_file_create") == "0":
        print(f"fio: {ruta}: No such file or directory", file=sys.stderr)
        return False
    with open(ruta, "xb") as archivo:
        archivo.truncate(int(op["size"]))  # disperso: no ocupa espacio real
    return True


def main():
    descriptores = descriptores_heredados()  # antes de abrir nada
    configuracion = json.loads(open(sys.argv[0] + ".json", encoding="utf-8").read())
    registro = configuracion["registro"]
    previas = invocaciones_previas(registro)
    modos = configuracion.get("modos") or ["ok"]
    modo = modos[min(len(previas), len(modos) - 1)]
    op = opciones(sys.argv)
    anotar(
        registro, argv=sys.argv, nombre=op.get("name"), modo=modo, pid=os.getpid(), pgid=os.getpgrp(),
        sid=os.getsid(0), cwd=os.getcwd(), entorno=dict(os.environ), descriptores=descriptores,
    )

    if modo in ("duerme", "ignora_sigterm"):
        if modo == "ignora_sigterm":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        preparar_archivo(op)
        hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        anotar(registro, hijo=hijo.pid)
        time.sleep(600)
        return 0
    if modo == "falla":
        print("fio: error inventado por el fio falso (err=22/Invalid argument)", file=sys.stderr)
        return 1
    if not preparar_archivo(op):
        return 1
    if modo == "ensucia":
        with open(os.path.join(os.getcwd(), "extra.txt"), "w", encoding="utf-8") as archivo:
            archivo.write("algo que Latido no creó\n")
    elif modo == "reemplaza":
        os.unlink(op["filename"])
        with open(op["filename"], "xb") as archivo:
            archivo.truncate(int(op["size"]))
    elif modo == "enlaza":
        os.unlink(op["filename"])
        os.symlink(configuracion["enlace"], op["filename"])
    elif modo == "carpeta":
        os.unlink(op["filename"])
        os.mkdir(op["filename"])
    elif modo == "borra":
        os.unlink(op["filename"])
    elif modo == "mueve":
        os.rename(op["filename"], configuracion["destino"])
    elif modo == "enlace_duro":
        os.link(op["filename"], configuracion["destino"])
    fixture = (configuracion.get("fixtures") or {}).get(op.get("name"))
    if fixture:
        texto = open(fixture, encoding="utf-8").read()
    else:
        texto = json.dumps(salida_ok(op, previas), indent=2)
    if modo == "json_invalido":
        texto = "{esto no es json"
    elif modo == "truncado":
        texto = texto[: len(texto) // 2]
    elif modo == "sin_trabajos":
        texto = json.dumps({"fio version": "fio-falso", "jobs": []})
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
