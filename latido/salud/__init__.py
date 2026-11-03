"""Lógica de salud de discos. Sin GTK."""

from latido.salud.analisis import analizar
from latido.salud.modelo import AtributoAta, Disparo, Estado, FilaRegistro, InformeSalud

__all__ = ["analizar", "AtributoAta", "Disparo", "Estado", "FilaRegistro", "InformeSalud"]
