"""Informe TXT de Latido (menú «Exportar informe»). Sin GTK.

Lleva lo que hace falta para leer el estado del disco en otra parte, y nada personal: ni número de serie,
ni usuario, ni nombre del equipo, ni rutas, ni el identificador público de la app. Es una lectura puntual.
"""

import os
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import datetime

from latido import __version__
from latido.salud import formato
from latido.salud.autenticidad import evaluar_autenticidad
from latido.salud.cifras import SIN_VALOR, cifras_clave
from latido.salud.modelo import FRASE_ESTADO, TEXTO_ESTADO, Estado
from latido.salud.reglas import POR_ID
from latido.velocidad import formato as formato_velocidad
from latido.velocidad.pruebas import PRUEBAS, Direccion

ANCHO = 80
DESTINOS_PROHIBIDOS = ("/dev", "/proc", "/sys")
MARCA_DEMO = "DATOS DE EJEMPLO, NO SON DE TU DISCO"
PALABRA_CIFRA = {Estado.BUENO: "Normal", Estado.PRECAUCION: "Atención", Estado.MALO: "Peligro", None: "Sin dato"}


class ErrorExportar(Exception):
    pass


@dataclass
class VelocidadMedida:
    """La última prueba de velocidad terminada: sus resultados y sus parámetros (sin la ruta de la carpeta)."""

    resultado: object  # ResultadoVelocidad
    configuracion: object  # Configuracion
    sistema_archivos: str | None


def nombre_por_defecto(fecha):
    return f"latido-informe-{fecha:%Y-%m-%d}.txt"


def _envolver(texto, sangria="  ", siguiente=None):
    return textwrap.wrap(texto, ANCHO, initial_indent=sangria, subsequent_indent=siguiente or sangria,
                         break_long_words=True, break_on_hyphens=False) or [sangria.rstrip()]


def _par(nombre, valor):
    return _envolver(f"{nombre + ':':<22}{valor}", "  ", " " * 24)


def _fuente(disparo):
    if disparo.regla is None:
        return None
    regla = POR_ID[disparo.regla]
    return "Criterio de Latido (sin fuente)" if regla.criterio_de_latido else f"Fuente: {regla.fuente}"


def _seccion_disco(informe, disco):
    lineas = ["", "DISCO"]
    lineas += _par("Modelo", informe.modelo or formato.NO_DISPONIBLE)
    lineas += _par("Firmware", informe.firmware or formato.NO_DISPONIBLE)
    capacidad = formato.capacidad(informe.capacidad)
    if informe.capacidad is not None:
        capacidad += f" ({informe.capacidad:,} bytes)"
    lineas += _par("Capacidad", capacidad)
    lineas += _par("Interfaz", informe.protocolo or formato.NO_DISPONIBLE)
    if disco is not None:
        lineas += _par("Disco del sistema", "sí" if disco.es_sistema else "no")
    return lineas


def _seccion_salud(informe):
    lineas = ["", f"SALUD: {TEXTO_ESTADO[informe.estado]}"]
    lineas += _envolver(FRASE_ESTADO[informe.estado])
    lineas.append("  Por qué:")
    for disparo in informe.disparos:
        lineas += _envolver(disparo.motivo, "  - ", "    ")
        fuente = _fuente(disparo)
        if fuente:
            lineas += _envolver(fuente, "    ")
    return lineas


def _seccion_autenticidad(informe, disco):
    autenticidad = evaluar_autenticidad(informe, disco.tamano if disco else None)
    lineas = ["", f"AUTENTICIDAD: {autenticidad.etiqueta}", "  Por qué:"]
    for motivo in autenticidad.porque:
        lineas += _envolver(motivo, "  - ", "    ")
    lineas.append("  Qué no se comprobó:")
    for texto in autenticidad.no_comprobado:
        lineas += _envolver(texto, "  - ", "    ")
    return lineas


def _seccion_cifras(informe):
    if informe.tipo != "nvme":
        return []
    lineas = ["", "CIFRAS CLAVE"]
    for cifra in cifras_clave(informe):
        valor = cifra.valor if cifra.valor == SIN_VALOR else f"{cifra.valor} {cifra.unidad}".strip()
        palabra = "Informativo" if cifra.informativa and cifra.valor != SIN_VALOR else PALABRA_CIFRA[cifra.estado]
        lineas += _par(cifra.titulo, f"{valor} · {palabra}")
        if cifra.detalle:
            lineas += _envolver(cifra.detalle, " " * 24)
    return lineas


def _seccion_datos(informe):
    lineas = ["", "TODOS LOS DATOS"]
    if informe.registro_nvme:
        lineas.append("  Registro de salud NVMe:")
        for fila in informe.registro_nvme:
            lineas += _envolver(f"{fila.nombre}: {fila.texto}", "  - ", "    ")
            lineas += _envolver(fila.explicacion, "    ")
    if informe.atributos_ata:
        lineas.append("  Atributos SMART (ATA), tal cual; Latido todavía no los analiza:")
        for atributo in informe.atributos_ata:
            valores = ", ".join(
                f"{nombre} {SIN_VALOR if valor is None else valor}"
                for nombre, valor in (("valor", atributo.valor), ("peor", atributo.peor), ("umbral", atributo.umbral))
            )
            lineas += _envolver(f"{atributo.id} {atributo.nombre}: {valores}, crudo {atributo.crudo}", "  - ", "    ")
    if not informe.registro_nvme and not informe.atributos_ata:
        lineas.append("  El disco no entregó datos SMART.")
    return lineas


def _seccion_velocidad(velocidad):
    lineas = ["", "VELOCIDAD"]
    if velocidad is None:
        lineas.append("  Sin una prueba de velocidad terminada en esta sesión.")
        return lineas
    configuracion = velocidad.configuracion
    sistema = velocidad.sistema_archivos or "no se pudo saber"
    lineas += _envolver(
        f"Archivo de prueba de {formato_velocidad.tamano(configuracion.tamano)}, {configuracion.pasadas} "
        f"pasada{'s' if configuracion.pasadas != 1 else ''}, sistema de archivos {sistema}. "
        "MB/s = 1,000,000 bytes por segundo; el número es el promedio de las pasadas."
    )
    for prueba in PRUEBAS:
        lineas.append(f"  {prueba.nombre}")
        for direccion in Direccion:
            resumen = velocidad.resultado.resumen(prueba, direccion)
            if resumen is None:
                texto = "sin resultado"
            else:
                texto = (f"{formato_velocidad.mb_s(resumen.promedio)} MB/s · "
                         f"{formato_velocidad.iops(resumen.iops_promedio)} IOPS")
            lineas += _envolver(f"{direccion.texto.capitalize()}: {texto}", "    ", "      ")
    return lineas


def construir_texto(informe, disco=None, velocidad=None, fecha=None, demo=False):
    """El informe completo, en líneas de 80 columnas como máximo."""
    fecha = fecha or datetime.now()
    lineas = ["Latido: informe de disco"]
    if demo:
        lineas.append(MARCA_DEMO)
    lineas += [
        f"Versión de Latido: {__version__}",
        f"Fecha: {fecha:%Y-%m-%d %H:%M}",
    ]
    lineas += _envolver("Es una lectura puntual: muestra el disco en el momento en que se leyó.", "")
    lineas += _seccion_disco(informe, disco)
    lineas += _seccion_salud(informe)
    lineas += _seccion_autenticidad(informe, disco)
    lineas += _seccion_cifras(informe)
    lineas += _seccion_datos(informe)
    lineas += _seccion_velocidad(velocidad)
    if demo:
        lineas += ["", MARCA_DEMO]
    return "\n".join(lineas) + "\n"


def destino_permitido(ruta):
    """Nunca en /dev, /proc ni /sys, tampoco a través de un enlace simbólico."""
    carpeta = os.path.realpath(os.path.dirname(os.path.abspath(ruta)))
    return not any(carpeta == prohibida or carpeta.startswith(prohibida + "/") for prohibida in DESTINOS_PROHIBIDOS)


def escribir_informe(ruta, texto):
    """Archivo temporal en la misma carpeta y os.replace, con modo 0600. No deja temporales si falla."""
    ruta = os.path.abspath(ruta)
    if not destino_permitido(ruta):
        raise ErrorExportar("No se puede guardar el informe en /dev, /proc ni /sys. Elige una carpeta normal.")
    descriptor, temporal = tempfile.mkstemp(prefix=".latido-informe-", suffix=".tmp", dir=os.path.dirname(ruta))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            archivo.write(texto)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.chmod(temporal, 0o600)
        os.replace(temporal, ruta)
    except BaseException:
        if os.path.lexists(temporal):
            os.unlink(temporal)
        raise
