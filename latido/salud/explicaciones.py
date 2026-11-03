"""Nombre y explicación en español de cada campo del registro de salud NVMe.

Las claves son las que smartctl 7.5 usa en nvme_smart_health_information_log.
Significados y unidades verificados contra NVM Express Base Specification,
revisión 2.0c, sección 5.16.1.3, figura 207 (SMART / Health Information Log).
"""

from latido.salud import formato

# Bits de critical_warning (especificación NVMe).
BITS_ADVERTENCIA_CRITICA = {
    0: "el repuesto disponible bajó de su umbral",
    1: "la temperatura salió del rango permitido",
    2: "la confiabilidad bajó por errores del medio o internos",
    3: "el disco pasó a modo de solo lectura",
    4: "falló el respaldo de la memoria volátil",
    5: "la región de memoria persistente quedó en solo lectura o no es confiable",
}
BIT_TEMPERATURA = 1


def describir_advertencia_critica(valor):
    if valor == 0:
        return "0 (ninguna)"
    partes = []
    for bit in range(8):
        if valor >> bit & 1:
            partes.append(BITS_ADVERTENCIA_CRITICA.get(bit, f"bit reservado {bit}"))
    return f"{valor} (0x{valor:02X}): " + "; ".join(partes)


def _unidades(valor):
    return f"{formato.terabytes(formato.unidades_nvme_a_tb(valor))} ({valor:,} unidades)"


def _minutos(valor):
    return f"{valor:,} min"


def _sensores(valor):
    return ", ".join(formato.temperatura(t) for t in valor)


# clave: (nombre, explicación, función de formato)
CAMPOS = {
    "nsid": (
        "Namespace del registro",
        "A qué parte del disco corresponde este registro. -1 significa todo el disco (todos los namespaces).",
        str,
    ),
    "critical_warning": (
        "Advertencia crítica",
        "Banderas que el propio disco activa cuando detecta un problema serio. 0 significa ninguna advertencia.",
        describir_advertencia_critica,
    ),
    "temperature": (
        "Temperatura",
        "Temperatura actual del disco.",
        formato.temperatura,
    ),
    "available_spare": (
        "Repuesto disponible",
        "Porcentaje de bloques de reserva que le quedan al disco para reemplazar celdas dañadas. Lo ideal es 100 %.",
        formato.porcentaje,
    ),
    "available_spare_threshold": (
        "Umbral de repuesto",
        "Si el repuesto disponible baja de este porcentaje, el disco activa una advertencia crítica.",
        formato.porcentaje,
    ),
    "percentage_used": (
        "Desgaste",
        "Estimación del fabricante de cuánta vida útil se ha consumido. Puede pasar de 100 %: "
        "eso no significa que el disco haya fallado, sino que superó la resistencia prevista.",
        formato.porcentaje,
    ),
    "data_units_read": (
        "Datos leídos",
        "Cuánto se ha leído del disco. Cada unidad equivale a 512 000 bytes.",
        _unidades,
    ),
    "data_units_written": (
        "Datos escritos",
        "Cuánto se ha escrito en el disco; es la medida principal del desgaste por uso. "
        "Cada unidad equivale a 512 000 bytes.",
        _unidades,
    ),
    "host_reads": (
        "Órdenes de lectura",
        "Cuántas órdenes de lectura le ha enviado el equipo al disco.",
        formato.entero,
    ),
    "host_writes": (
        "Órdenes de escritura",
        "Cuántas órdenes de escritura le ha enviado el equipo al disco.",
        formato.entero,
    ),
    "controller_busy_time": (
        "Tiempo ocupado",
        "Minutos que el controlador del disco ha pasado atendiendo órdenes.",
        _minutos,
    ),
    "power_cycles": (
        "Encendidos",
        "Cuántas veces se ha encendido el disco.",
        formato.entero,
    ),
    "power_on_hours": (
        "Horas encendido",
        "Total de horas que el disco ha estado encendido.",
        formato.entero,
    ),
    "unsafe_shutdowns": (
        "Apagados inseguros",
        "Veces que el disco perdió la energía sin aviso previo, por ejemplo por un corte de luz "
        "o al desconectarlo sin expulsarlo.",
        formato.entero,
    ),
    "media_errors": (
        "Errores de medio",
        "Errores de datos que el disco no pudo corregir. En un disco sano es 0.",
        formato.entero,
    ),
    "num_err_log_entries": (
        "Entradas del registro de errores",
        "Cuántos errores ha anotado el controlador en toda su vida. No todos son daños: "
        "también se anotan órdenes que el disco rechazó.",
        formato.entero,
    ),
    "warning_temp_time": (
        "Tiempo sobre temperatura de advertencia",
        "Minutos que el disco ha pasado en o por encima de su temperatura de advertencia, "
        "sin llegar a la crítica.",
        _minutos,
    ),
    "critical_comp_time": (
        "Tiempo sobre temperatura crítica",
        "Minutos que el disco ha pasado en o por encima de su temperatura crítica. "
        "Si es mayor que 0, Latido lo marca como PRECAUCIÓN.",
        _minutos,
    ),
    "temperature_sensors": (
        "Sensores de temperatura",
        "Lecturas de los sensores internos adicionales del disco.",
        _sensores,
    ),
}

SIN_EXPLICACION = "Latido todavía no tiene una explicación para este dato."
