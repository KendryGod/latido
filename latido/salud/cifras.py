"""Las seis cifras clave de la pestaña Salud, listas para mostrar. Sin GTK.

El estado de cada cifra sale de las reglas disparadas que le dan color (Disparo.cifra). Una cifra
informativa (horas, datos escritos) nunca tiene color: solo se muestra.
"""

from dataclasses import dataclass

from latido.salud import formato
from latido.salud.modelo import Estado

SIN_VALOR = "—"


@dataclass(frozen=True)
class Cifra:
    clave: str
    titulo: str
    valor: str  # el número, sin unidad; SIN_VALOR si falta
    unidad: str
    estado: Estado | None  # None: sin dato, o informativa
    informativa: bool
    detalle: str | None


def _estado(informe, clave, valor):
    if valor is None:
        return None
    estados = {disparo.estado for disparo in informe.disparos if disparo.cifra == clave}
    for peor in (Estado.MALO, Estado.PRECAUCION):
        if peor in estados:
            return peor
    return Estado.BUENO


def _umbrales_temperatura(informe):
    partes = []
    if informe.temperatura_advertencia is not None:
        partes.append(f"advertencia {formato.temperatura(informe.temperatura_advertencia)}")
    if informe.temperatura_critica is not None:
        partes.append(f"crítica {formato.temperatura(informe.temperatura_critica)}")
    return "Umbrales del disco: " + " · ".join(partes) if partes else None


def _numero(valor, decimales=0):
    if valor is None:
        return SIN_VALOR
    return f"{valor:,.{decimales}f}" if decimales else f"{valor:,}"


def cifras_clave(informe):
    """Temperatura, vida usada, reserva disponible, horas encendido, datos escritos y errores de medios."""
    filas = [
        ("temperatura", "Temperatura", informe.temperatura, _numero(informe.temperatura), "°C", False,
         _umbrales_temperatura(informe)),
        ("vida", "Vida usada", informe.uso_pct, _numero(informe.uso_pct), "%", False,
         None if informe.vida_pct is None else f"Estimación del propio disco. Queda {informe.vida_pct} %."),
        ("reserva", "Reserva disponible", informe.repuesto_pct, _numero(informe.repuesto_pct), "%", False,
         None if informe.repuesto_umbral_pct is None else f"Umbral del disco: {informe.repuesto_umbral_pct} %"),
        ("horas", "Horas encendido", informe.horas, _numero(informe.horas), "h", True,
         None if informe.ciclos is None else f"{informe.ciclos:,} ciclos de encendido"),
        ("escritos", "Datos escritos", informe.tb_escritos, _numero(informe.tb_escritos, 2), "TB", True,
         None if informe.tb_leidos is None else f"Leídos: {formato.terabytes(informe.tb_leidos)}"),
        ("errores", "Errores de medios", informe.errores_medio, _numero(informe.errores_medio), "", False,
         "Datos que el disco no pudo corregir"),
    ]
    return [
        Cifra(clave, titulo, texto, unidad, None if informativa else _estado(informe, clave, valor), informativa,
              detalle)
        for clave, titulo, valor, texto, unidad, informativa, detalle in filas
    ]
