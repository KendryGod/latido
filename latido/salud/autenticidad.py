"""Autenticidad: ¿el disco parece ser lo que dice ser? Sin GTK.

Es una etiqueta aparte, que nunca cambia el color de salud (docs/veredicto.md). Solo hay cuatro etiquetas.
Latido nunca promete lo que no puede comprobar:
- la capacidad real solo se confirma escribiendo y verificando todo el disco (f3, fase 5). Por eso, por
  ahora, «Sin señales de falsificación» no sale nunca;
- «Falso o manipulado» solo sale con una contradicción dura entre dos fuentes del propio sistema.
"""

from dataclasses import dataclass, field

from latido.salud import formato

SIN_SENALES = "Sin señales de falsificación"
SOSPECHOSO = "Sospechoso"
FALSO = "Falso o manipulado"
NO_CONCLUYENTE = "No concluyente"
ETIQUETAS = (SIN_SENALES, SOSPECHOSO, FALSO, NO_CONCLUYENTE)

AUN_NO_VERIFICA = "Latido aún no verifica la capacidad real"
NO_COMPROBADO = (
    "La capacidad real: hace falta escribir y verificar todo el disco (con f3, en una fase posterior).",
    "Que el modelo y la capacidad que informa el disco sean ciertos: Latido solo compara lo que dicen dos "
    "fuentes del propio sistema.",
    "Una prueba de velocidad sola no prueba la autenticidad.",
)


@dataclass
class Autenticidad:
    etiqueta: str
    porque: list[str]
    no_comprobado: tuple[str, ...] = field(default=NO_COMPROBADO)


def evaluar_autenticidad(informe, tamano_kernel=None):
    """informe: InformeSalud (capacidad según smartctl). tamano_kernel: bytes que ve el kernel (lsblk), o None.

    Solo se comparan en NVMe con un solo espacio de nombres: así las dos cifras miden lo mismo.
    """
    capacidad = informe.capacidad
    comparable = informe.tipo == "nvme" and informe.namespaces == 1
    porque = []
    if comparable and capacidad is not None and tamano_kernel is not None:
        if capacidad != tamano_kernel:
            return Autenticidad(FALSO, [
                f"smartctl dice que el disco tiene {capacidad:,} bytes y el kernel ve {tamano_kernel:,} bytes: "
                "dos fuentes del propio sistema no coinciden."
            ])
        porque.append(
            f"La capacidad coincide en smartctl y en el kernel: {formato.capacidad(capacidad)} ({capacidad:,} bytes)."
        )
    porque.append(f"{AUN_NO_VERIFICA}.")
    return Autenticidad(NO_CONCLUYENTE, porque)
