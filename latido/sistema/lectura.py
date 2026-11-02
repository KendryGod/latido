"""Lectura de salud a través de pkexec y el ayudante de root.

Cada error dice solo lo que realmente se sabe. Según man pkexec:
126 = el usuario cerró el diálogo; 127 = no autorizado, la autenticación
no se pudo obtener o hubo un error (pkexec no distingue entre estos).
"""

import json
import subprocess
from enum import Enum

from latido.salud import analizar
from latido.sistema.herramientas import comprobar_herramientas
from latido.sistema.rutas import HELPER, PKEXEC

TIEMPO_MAXIMO = 300  # segundos, incluye el tiempo de escribir la contraseña

PKEXEC_CANCELADO = 126
PKEXEC_NO_AUTORIZADO = 127

# Códigos propios del ayudante (helper/latido-helper).
MENSAJES_AYUDANTE = {
    2: "El ayudante rechazó el disco: solo acepta discos NVMe (/dev/nvmeN o /dev/nvmeNnM).",
    3: "El ayudante no encontró el disco, o la ruta no es un dispositivo.",
    4: "El ayudante no encontró smartctl en /usr/bin/smartctl.",
    5: "smartctl no terminó a tiempo y el ayudante lo detuvo.",
    6: "El ayudante no pudo ejecutar smartctl.",
}


class TipoError(Enum):
    HERRAMIENTAS = "herramientas"
    CANCELADO = "cancelado"
    NO_AUTORIZADO = "no_autorizado"
    AYUDANTE = "ayudante"
    JSON_INVALIDO = "json_invalido"
    TIEMPO = "tiempo"
    ARCHIVO = "archivo"


class ErrorLectura(Exception):
    def __init__(self, tipo, mensaje):
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje


def construir_comando(disco):
    return [PKEXEC, HELPER, "leer", disco]


def leer_salud(disco, ejecutar=None, comprobar=None):
    """Lee la salud de disco con pkexec. Devuelve un InformeSalud o lanza ErrorLectura."""
    ejecutar = ejecutar or subprocess.run
    comprobar = comprobar or comprobar_herramientas

    faltan = comprobar()
    if faltan:
        raise ErrorLectura(TipoError.HERRAMIENTAS, "No se puede leer la salud todavía.\n" + "\n".join(faltan))

    try:
        proceso = ejecutar(
            construir_comando(disco),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=TIEMPO_MAXIMO,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ErrorLectura(
            TipoError.TIEMPO,
            f"La lectura no terminó en {TIEMPO_MAXIMO // 60} minutos y se detuvo. No se sabe el estado del disco.",
        )
    except OSError:
        raise ErrorLectura(TipoError.AYUDANTE, f"No se pudo ejecutar {PKEXEC}. No se sabe el estado del disco.")

    codigo = proceso.returncode
    if codigo == PKEXEC_CANCELADO:
        raise ErrorLectura(TipoError.CANCELADO, "Cerraste la ventana de contraseña. No se leyó nada del disco.")
    if codigo == PKEXEC_NO_AUTORIZADO:
        raise ErrorLectura(
            TipoError.NO_AUTORIZADO,
            "No se obtuvo permiso para leer el disco. pkexec no indica la causa exacta: "
            "puede ser una contraseña incorrecta, una cuenta sin permisos de administrador "
            "o un error del propio pkexec.",
        )
    if codigo != 0:
        mensaje = MENSAJES_AYUDANTE.get(codigo, f"El ayudante terminó con un error inesperado (código {codigo}).")
        raise ErrorLectura(TipoError.AYUDANTE, mensaje + " No se sabe el estado del disco.")

    try:
        respuesta = json.loads(proceso.stdout)
    except ValueError:
        raise ErrorLectura(
            TipoError.JSON_INVALIDO, "La respuesta del ayudante no es JSON válido. No se sabe el estado del disco."
        )
    return informe_desde_respuesta(respuesta)


def informe_desde_respuesta(respuesta):
    """Convierte {"smartctl_exit", "datos"[, "salida_invalida"]} en un InformeSalud."""
    if not isinstance(respuesta, dict) or "smartctl_exit" not in respuesta or "datos" not in respuesta:
        raise ErrorLectura(
            TipoError.JSON_INVALIDO,
            "La respuesta del ayudante no tiene el formato esperado. No se sabe el estado del disco.",
        )
    return analizar(
        respuesta["datos"],
        codigo_proceso=respuesta["smartctl_exit"],
        salida_invalida=respuesta.get("salida_invalida") is True,
    )


def cargar_fixture(ruta):
    """Modo desarrollo: lee un JSON de smartctl (o una respuesta del ayudante) sin root."""
    try:
        with open(ruta, encoding="utf-8") as archivo:
            contenido = json.load(archivo)
    except FileNotFoundError:
        raise ErrorLectura(TipoError.ARCHIVO, f"El archivo {ruta} no existe.")
    except PermissionError:
        raise ErrorLectura(TipoError.ARCHIVO, f"No tienes permiso para leer el archivo {ruta}.")
    except OSError:
        raise ErrorLectura(TipoError.ARCHIVO, f"No se pudo abrir el archivo {ruta}.")
    except ValueError:
        raise ErrorLectura(TipoError.JSON_INVALIDO, f"El archivo {ruta} no es JSON válido.")
    if isinstance(contenido, dict) and "smartctl_exit" in contenido and "datos" in contenido:
        return informe_desde_respuesta(contenido)
    return analizar(contenido)
