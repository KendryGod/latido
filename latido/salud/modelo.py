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
class Disparo:
    """Una línea de «Por qué»: la regla que se disparó (docs/veredicto.md) y lo que dice.

    regla es None y estado es None en las líneas solo informativas. cifra es la cifra clave a la que la
    regla le da color (temperatura, vida, reserva, errores), o None.
    """

    regla: str | None
    estado: Estado | None
    motivo: str
    cifra: str | None = None


@dataclass
class AtributoAta:
    """Una fila de la tabla de atributos SMART de un disco ATA, tal como la da smartctl."""

    id: int
    nombre: str
    valor: int | None
    peor: int | None
    umbral: int | None
    crudo: str


@dataclass
class InformeSalud:
    # Nunca BUENO por omisión: solo el diagnóstico puede subirlo.
    estado: Estado = Estado.DESCONOCIDO
    motivos: list[str] = field(default_factory=list)

    tipo: str | None = None  # "nvme" o "ata"
    dispositivo: str | None = None
    modelo: str | None = None
    # Solo para mostrar en pantalla: repr=False para que nunca acabe en un log
    # o en un mensaje de error que imprima el informe.
    numero_serie: str | None = field(default=None, repr=False)
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
    # Tabla de atributos ATA: se lee y se muestra, pero Latido todavía no la analiza (soporte SATA: fase 5).
    atributos_ata: list[AtributoAta] = field(default_factory=list)
    disparos: list[Disparo] = field(default_factory=list)  # las mismas líneas que motivos, con su regla
