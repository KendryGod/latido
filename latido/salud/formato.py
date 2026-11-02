"""Formato de valores para la interfaz.

Usa la convención de es_HN (la del sistema de desarrollo): punto decimal y
coma para los miles. Es fija a propósito para que no dependa del locale.
"""

NO_DISPONIBLE = "No disponible"

BYTES_POR_UNIDAD_NVME = 512_000  # 1000 bloques de 512 bytes (especificación NVMe)


def unidades_nvme_a_tb(unidades):
    return unidades * BYTES_POR_UNIDAD_NVME / 10**12


def entero(valor):
    return NO_DISPONIBLE if valor is None else f"{valor:,}"


def porcentaje(valor):
    return NO_DISPONIBLE if valor is None else f"{valor} %"


def temperatura(valor):
    return NO_DISPONIBLE if valor is None else f"{valor} °C"


def terabytes(valor):
    return NO_DISPONIBLE if valor is None else f"{valor:,.2f} TB"


def capacidad(num_bytes):
    if num_bytes is None:
        return NO_DISPONIBLE
    if num_bytes >= 10**12:
        return f"{num_bytes / 10**12:,.2f} TB"
    return f"{num_bytes / 10**9:,.1f} GB"
