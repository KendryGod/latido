"""Última carpeta usada y restos de una prueba que no se limpió.

Antes de crear nada, Latido guarda la carpeta elegida en
$XDG_STATE_HOME/latido/velocidad.json (si no está definida o no es absoluta:
~/.local/state/latido/velocidad.json). Así, si la app muere sin limpiar, al
abrir la pestaña revisa SOLO esa carpeta y avisa. Nunca borra sin que el
usuario lo confirme en pantalla. Los resultados de las pruebas no se guardan.
"""

import json
import os
import stat
import tempfile
from dataclasses import dataclass

from latido.velocidad import formato
from latido.velocidad.pruebas import ARCHIVO_PRUEBA, PREFIJO_DIRECTORIO


def ruta_estado(entorno=None):
    entorno = os.environ if entorno is None else entorno
    base = entorno.get("XDG_STATE_HOME", "")
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "latido", "velocidad.json")


def guardar_ultima_carpeta(carpeta, ruta=None):
    """Escribe el estado de forma atómica (archivo temporal + os.replace). Lanza OSError si no puede."""
    ruta = ruta or ruta_estado()
    directorio = os.path.dirname(ruta)
    os.makedirs(directorio, mode=0o700, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=".velocidad-", suffix=".tmp", dir=directorio)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump({"ultima_carpeta": carpeta}, archivo)
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def leer_ultima_carpeta(ruta=None):
    try:
        with open(ruta or ruta_estado(), encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError):
        return None
    carpeta = datos.get("ultima_carpeta") if isinstance(datos, dict) else None
    return carpeta if isinstance(carpeta, str) and os.path.isabs(carpeta) else None


class ErrorResto(Exception):
    pass


@dataclass(frozen=True)
class Resto:
    carpeta: str
    nombre: str
    contenido: tuple = ()
    tamano_archivo: int | None = None
    se_puede_borrar: bool = False
    motivo: str | None = None  # por qué Latido no lo borra

    @property
    def ruta(self):
        return os.path.join(self.carpeta, self.nombre)

    def descripcion(self):
        if not self.se_puede_borrar:
            return f"{self.nombre}: {self.motivo}. Latido no lo borrará."
        if self.tamano_archivo is not None:
            return f"{self.nombre}: contiene {ARCHIVO_PRUEBA} ({formato.tamano(self.tamano_archivo)})."
        return f"{self.nombre}: carpeta vacía."


def _examinar(carpeta, nombre):
    ruta = os.path.join(carpeta, nombre)
    try:
        info = os.lstat(ruta)
    except OSError as error:
        return Resto(carpeta, nombre, motivo=f"no se pudo revisar ({error.strerror})")
    if stat.S_ISLNK(info.st_mode):
        return Resto(carpeta, nombre, motivo="es un enlace simbólico")
    if not stat.S_ISDIR(info.st_mode):
        return Resto(carpeta, nombre, motivo="no es una carpeta")
    if info.st_uid != os.getuid():
        return Resto(carpeta, nombre, motivo="pertenece a otro usuario")
    try:
        contenido = tuple(sorted(os.listdir(ruta)))
    except OSError as error:
        return Resto(carpeta, nombre, motivo=f"no se pudo leer su contenido ({error.strerror})")
    ajenos = [n for n in contenido if n != ARCHIVO_PRUEBA]
    if ajenos:
        return Resto(carpeta, nombre, contenido, motivo="contiene archivos que Latido no crea: " + ", ".join(ajenos))
    tamano = None
    if contenido:
        try:
            info_archivo = os.lstat(os.path.join(ruta, ARCHIVO_PRUEBA))
        except OSError as error:
            return Resto(carpeta, nombre, contenido, motivo=f"no se pudo revisar {ARCHIVO_PRUEBA} ({error.strerror})")
        if not stat.S_ISREG(info_archivo.st_mode):
            return Resto(carpeta, nombre, contenido, motivo=f"{ARCHIVO_PRUEBA} no es un archivo normal")
        tamano = info_archivo.st_size
    return Resto(carpeta, nombre, contenido, tamano, True)


def buscar_restos(carpeta):
    """Lista los .latido-velocidad-* de esa carpeta (y solo de esa). Nunca borra."""
    if not carpeta:
        return []
    try:
        nombres = sorted(n for n in os.listdir(carpeta) if n.startswith(PREFIJO_DIRECTORIO))
    except OSError:
        return []
    return [_examinar(carpeta, nombre) for nombre in nombres]


def borrar_resto(resto):
    """Borra el archivo de prueba por su nombre exacto y luego la carpeta con rmdir.

    Todo se revisa otra vez justo antes de borrar, a través de descriptores de
    carpeta (sin seguir enlaces simbólicos). Si algo no cuadra, no se borra nada
    más y se lanza ErrorResto con el motivo.
    """
    actual = _examinar(resto.carpeta, resto.nombre)
    if not actual.se_puede_borrar:
        raise ErrorResto(f"No se borró {resto.nombre}: {actual.motivo}.")
    padre = os.open(resto.carpeta, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        propio = os.open(resto.nombre, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=padre)
        try:
            nombres = os.listdir(propio)
            ajenos = [n for n in nombres if n != ARCHIVO_PRUEBA]
            if ajenos:
                raise ErrorResto(f"No se borró {resto.nombre}: contiene archivos que Latido no crea: {', '.join(ajenos)}.")
            if ARCHIVO_PRUEBA in nombres:
                info = os.stat(ARCHIVO_PRUEBA, dir_fd=propio, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ErrorResto(f"No se borró {resto.nombre}: {ARCHIVO_PRUEBA} no es un archivo normal.")
                os.unlink(ARCHIVO_PRUEBA, dir_fd=propio)
            identidad = os.fstat(propio)
        finally:
            os.close(propio)
        info_carpeta = os.stat(resto.nombre, dir_fd=padre, follow_symlinks=False)
        if (info_carpeta.st_dev, info_carpeta.st_ino) != (identidad.st_dev, identidad.st_ino):
            raise ErrorResto(f"No se borró {resto.nombre}: la carpeta cambió mientras se revisaba.")
        os.rmdir(resto.nombre, dir_fd=padre)
    except OSError as error:
        raise ErrorResto(f"No se pudo borrar {resto.nombre}: {error.strerror}.") from None
    finally:
        os.close(padre)
    return f"Se borró {resto.ruta}."
