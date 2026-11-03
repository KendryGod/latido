"""Formato de tamaños y velocidades.

Misma convención que latido/salud/formato.py (es_HN): punto decimal y coma
para los miles, fija para que no dependa del locale.
"""

from latido.velocidad.pruebas import GIB, MIB

BYTES_POR_MB = 1_000_000  # MB/s = 1 000 000 bytes por segundo


def tamano(num_bytes):
    """Tamaños binarios (MiB, GiB): así se eligen los tamaños de prueba."""
    if num_bytes < MIB:
        return f"{num_bytes:,} bytes"
    if num_bytes >= GIB:
        divisor, unidad = GIB, "GiB"
    else:
        divisor, unidad = MIB, "MiB"
    if num_bytes % divisor == 0:
        return f"{num_bytes // divisor:,} {unidad}"
    return f"{num_bytes / divisor:,.1f} {unidad}"


def gigabytes(num_bytes):
    """Gigabytes decimales (10⁹ bytes), como la resistencia (TBW) de los SSD."""
    return f"{num_bytes / 10**9:,.2f} GB"


def mb_s(bytes_por_segundo):
    return f"{bytes_por_segundo / BYTES_POR_MB:,.2f}"


def iops(valor):
    return f"{valor:,.0f}"
