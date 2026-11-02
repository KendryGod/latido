"""Modelo del informe de salud. Sin GTK.

Todo dato que no venga en el JSON de smartctl queda en None; la interfaz
lo muestra como "No disponible", nunca como 0.
"""

from dataclasses import dataclass, field
from enum import Enum


class Estado(Enum):
    BUENO = "bueno"
    PRECAUCION = "precaucion"
    MALO = "malo"
    DESCONOCIDO = "desconocido"


@dataclass
class FilaRegistro:
    """Una fila del registro de salud NVMe, lista para mostrar."""

    clave: str  # nombre de la clave en el JSON de smartctl
    nombre: str
    valor: object  # valor tal como viene en el JSON
    texto: str  # valor formateado para la interfaz
    explicacion: str


@dataclass
class InformeSalud:
    # Nunca BUENO por omisión: solo el diagnóstico puede subirlo.
    estado: Estado = Estado.DESCONOCIDO
    motivos: list[str] = field(default_factory=list)

    tipo: str | None = None  # "nvme" o "ata"
    dispositivo: str | None = None
    modelo: str | None = None
    firmware: str | None = None
    capacidad: int | None = None  # bytes
    protocolo: str | None = None

    vida_pct: int | None = None  # max(0, 100 - uso_pct)
    uso_pct: int | None = None  # percentage_used real; puede pasar de 100
    temperatura: int | None = None  # °C
    temperatura_advertencia: int | None = None  # °C, solo si el JSON la trae
    temperatura_critica: int | None = None  # °C, solo si el JSON la trae
    horas: int | None = None
    ciclos: int | None = None
    tb_escritos: float | None = None
    tb_leidos: float | None = None
    errores_medio: int | None = None
    repuesto_pct: int | None = None
    repuesto_umbral_pct: int | None = None

    smartctl_exit: int | None = None  # máscara combinada (JSON y proceso)
    registro_nvme: list[FilaRegistro] = field(default_factory=list)
    atributos_ata: list = field(default_factory=list)  # reservado para la Fase 2
