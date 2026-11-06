"""Las reglas del veredicto de salud, en una sola tabla (docs/veredicto.md).

Cada regla tiene un identificador, la condición en español, el resultado (el estado que da, o None si solo
informa), la FUENTE que la respalda y la cifra clave a la que le da color (o None).

FUENTE es la especificación NVMe, el manual de smartctl o un documento del fabricante, con su sección. Si
no hay, es SIN_FUENTE: la regla es «criterio de Latido» y nunca puede dar rojo (una prueba lo comprueba).
El veredicto es el peor estado de las reglas que se disparan.
"""

from dataclasses import dataclass

from latido.salud.modelo import Estado

SIN_FUENTE = "SIN FUENTE"
NVME = "NVMe Base Specification 2.0c"
SMARTCTL = "man smartctl, EXIT STATUS"


@dataclass(frozen=True)
class Regla:
    id: str
    condicion: str
    resultado: Estado | None  # None: solo informa, nunca da color
    fuente: str
    cifra: str | None = None

    @property
    def criterio_de_latido(self):
        return self.fuente == SIN_FUENTE


REGLAS = (
    # Sin datos (gris): no es un juicio sobre el disco.
    Regla("SALIDA-INVALIDA", "smartctl no devolvió JSON válido, o su código de salida no es válido",
          Estado.DESCONOCIDO, SIN_FUENTE),
    Regla("SMART-SIN-DATOS", "smartctl no obtuvo datos válidos (bit 0 o 1 de su código de salida)",
          Estado.DESCONOCIDO, f"{SMARTCTL}, bits 0 y 1"),
    Regla("SMART-INCOMPLETO", "Falló alguna orden SMART (bit 2): los datos pueden estar incompletos",
          Estado.DESCONOCIDO, f"{SMARTCTL}, bit 2"),
    Regla("FALTAN-DATOS", "Falta algún dato obligatorio para opinar", Estado.DESCONOCIDO, SIN_FUENTE),
    Regla("TIPO-SIN-ANALISIS", "El disco no es NVMe: Latido todavía no lo analiza", Estado.DESCONOCIDO, SIN_FUENTE),
    # smartctl.
    Regla("SMART-PREFALLA", "Hay atributos de prefalla en o por debajo de su umbral (bit 4)", Estado.MALO,
          f"{SMARTCTL}, bit 4, y opción -A: «Pre-failure Attributes … indicate pending disk failure»"),
    Regla("SMART-UMBRAL-PASADO", "Algún atributo estuvo en o por debajo de su umbral en el pasado (bit 5)",
          Estado.PRECAUCION, SIN_FUENTE),
    Regla("SMART-REGISTRO-ERRORES", "El registro de errores del disco tiene entradas (bit 6)", Estado.PRECAUCION,
          SIN_FUENTE),
    Regla("SMART-AUTODIAGNOSTICO", "El registro de autodiagnósticos tiene errores (bit 7)", Estado.PRECAUCION,
          SIN_FUENTE),
    Regla("NVME-FALLA-SIN-DETALLE", "smartctl dice que el disco falla y no hay critical_warning", Estado.MALO,
          f"{SMARTCTL}, bit 3: «SMART status check returned DISK FAILING»"),
    Regla("NVME-CONTRADICCION", "critical_warning es 0 pero smartctl dice que el disco falla", Estado.MALO,
          f"{SMARTCTL}, bit 3: «SMART status check returned DISK FAILING»"),
    # critical_warning (el propio disco).
    Regla("NVME-AC-RESERVA", "critical_warning, bit 0: el repuesto bajó de su umbral", Estado.MALO,
          f"{NVME}, figura 207, byte 00, bit 0", "reserva"),
    Regla("NVME-AC-TEMPERATURA", "critical_warning, bit 1: la temperatura pasó su umbral (por defecto, WCTEMP)",
          Estado.PRECAUCION, f"{NVME}, figura 207, byte 00, bit 1; sección 5.27.1.3 (umbral por defecto = WCTEMP)",
          "temperatura"),
    Regla("NVME-AC-CONFIABILIDAD", "critical_warning, bit 2: la confiabilidad bajó", Estado.MALO,
          f"{NVME}, figura 207, byte 00, bit 2"),
    Regla("NVME-AC-SOLO-LECTURA", "critical_warning, bit 3: todo el medio pasó a solo lectura", Estado.MALO,
          f"{NVME}, figura 207, byte 00, bit 3"),
    Regla("NVME-AC-RESPALDO", "critical_warning, bit 4: falló el respaldo de la memoria volátil", Estado.MALO,
          f"{NVME}, figura 207, byte 00, bit 4"),
    Regla("NVME-AC-PMR", "critical_warning, bit 5: la memoria persistente quedó en solo lectura o no es confiable",
          Estado.MALO, f"{NVME}, figura 207, byte 00, bit 5"),
    Regla("NVME-AC-RESERVADO", "critical_warning, bit 6 o 7 (reservados) activo", Estado.PRECAUCION, SIN_FUENTE),
    # Valores del registro de salud comparados con los umbrales del propio disco.
    Regla("NVME-RESERVA", "available_spare < available_spare_threshold", Estado.MALO,
          f"{NVME}, figura 207, bytes 03 y 04, y byte 00 bit 0", "reserva"),
    Regla("NVME-USO-100", "percentage_used >= 100 (una estimación, no una falla)", Estado.PRECAUCION,
          f"{NVME}, figura 207, byte 05", "vida"),
    Regla("LATIDO-VIDA", "90 <= percentage_used < 100 (vida estimada de 10 % o menos)", Estado.PRECAUCION,
          SIN_FUENTE, "vida"),
    Regla("NVME-TEMP-ADVERTENCIA", "temperatura compuesta >= umbral de advertencia del disco (WCTEMP)",
          Estado.PRECAUCION, f"{NVME}, figura 275, bytes 267:266 (WCTEMP)", "temperatura"),
    Regla("NVME-TEMP-CRITICA", "temperatura compuesta >= umbral crítico del disco (CCTEMP)", Estado.MALO,
          f"{NVME}, figura 275, bytes 269:268 (CCTEMP)", "temperatura"),
    Regla("NVME-ERRORES-MEDIO", "media_errors > 0", Estado.PRECAUCION, SIN_FUENTE, "errores"),
    Regla("NVME-TIEMPO-CRITICO", "critical_comp_time > 0 (minutos por encima de la temperatura crítica)",
          Estado.PRECAUCION, SIN_FUENTE, "temperatura"),
    # Solo informa.
    Regla("NVME-APAGADOS-INSEGUROS", "unsafe_shutdowns: se muestra en «Todos los datos», nunca da color", None,
          f"{NVME}, figura 207, bytes 159:144"),
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

UMBRAL_USO_SIN_FUENTE = 90  # LATIDO-VIDA: criterio de Latido
UMBRAL_USO_FUENTE = 100  # NVME-USO-100: la especificación
