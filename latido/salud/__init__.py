"""Lógica de salud de discos. Sin GTK."""

from latido.salud.analisis import analizar
from latido.salud.modelo import Estado, FilaRegistro, InformeSalud

__all__ = ["analizar", "Estado", "FilaRegistro", "InformeSalud"]
