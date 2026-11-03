"""Las reglas del veredicto de salud, en una sola tabla (docs/veredicto.md).

Cada regla tiene un identificador, la condición en español, el resultado (el estado que da) y la cifra
clave a la que le da color (temperatura, vida, reserva o errores), o None si no colorea ninguna.
"""

from dataclasses import dataclass

from latido.salud.modelo import Estado


@dataclass(frozen=True)
class Regla:
    id: str
    condicion: str
    resultado: Estado
    cifra: str | None = None


REGLAS = (
    Regla("SALIDA-INVALIDA", "smartctl no devolvió JSON válido, o su código de salida no es válido", Estado.DESCONOCIDO),
    Regla("SMART-SIN-DATOS", "smartctl no obtuvo datos válidos (bit 0 o 1 de su código de salida)", Estado.DESCONOCIDO),
    Regla("SMART-INCOMPLETO", "Falló alguna orden SMART (bit 2): los datos pueden estar incompletos", Estado.DESCONOCIDO),
    Regla("SMART-PREFALLA", "Hay atributos de prefalla en o por debajo de su umbral (bit 4)", Estado.MALO),
    Regla("SMART-UMBRAL-PASADO", "Algún atributo estuvo en o por debajo de su umbral en el pasado (bit 5)",
          Estado.PRECAUCION),
    Regla("SMART-REGISTRO-ERRORES", "El registro de errores del disco tiene entradas (bit 6)", Estado.PRECAUCION),
    Regla("SMART-AUTODIAGNOSTICO", "El registro de autodiagnósticos tiene errores (bit 7)", Estado.PRECAUCION),
    Regla("NVME-AC-RESERVA", "critical_warning, bit 0: el repuesto bajó de su umbral", Estado.MALO, "reserva"),
    Regla("NVME-AC-TEMPERATURA", "critical_warning, bit 1: la temperatura salió del rango permitido",
          Estado.PRECAUCION, "temperatura"),
    Regla("NVME-AC-CONFIABILIDAD", "critical_warning, bit 2: la confiabilidad bajó", Estado.MALO),
    Regla("NVME-AC-SOLO-LECTURA", "critical_warning, bit 3: el disco pasó a solo lectura", Estado.MALO),
    Regla("NVME-AC-RESPALDO", "critical_warning, bit 4: falló el respaldo de la memoria volátil", Estado.MALO),
    Regla("NVME-AC-PMR", "critical_warning, bit 5: la memoria persistente quedó en solo lectura", Estado.MALO),
    Regla("NVME-AC-RESERVADO", "critical_warning, bit 6 o 7 (reservados) activo", Estado.MALO),
    Regla("NVME-FALLA-SIN-DETALLE", "smartctl dice que el disco falla y no hay critical_warning", Estado.MALO),
    Regla("NVME-CONTRADICCION", "critical_warning es 0 pero smartctl dice que el disco falla", Estado.MALO),
    Regla("NVME-ERRORES-MEDIO", "media_errors > 0", Estado.PRECAUCION, "errores"),
    Regla("NVME-RESERVA", "available_spare <= available_spare_threshold", Estado.PRECAUCION, "reserva"),
    Regla("LATIDO-VIDA", "vida estimada <= 10 % (percentage_used >= 90)", Estado.PRECAUCION, "vida"),
    Regla("NVME-TIEMPO-CRITICO", "critical_comp_time > 0 (minutos en o sobre la temperatura crítica)",
          Estado.PRECAUCION, "temperatura"),
    Regla("FALTAN-DATOS", "Falta algún dato obligatorio para opinar", Estado.DESCONOCIDO),
    Regla("TIPO-SIN-ANALISIS", "El disco no es NVMe: Latido todavía no lo analiza", Estado.DESCONOCIDO),
)

POR_ID = {regla.id: regla for regla in REGLAS}

# Bits de critical_warning (especificación NVMe) -> regla.
REGLA_ADVERTENCIA_CRITICA = {
    0: "NVME-AC-RESERVA",
    1: "NVME-AC-TEMPERATURA",
    2: "NVME-AC-CONFIABILIDAD",
    3: "NVME-AC-SOLO-LECTURA",
    4: "NVME-AC-RESPALDO",
    5: "NVME-AC-PMR",
}
