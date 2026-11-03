"""Lectura de la salida JSON de fio y resumen de las pasadas.

HOWTO.rst ("JSON output") documenta que runtime va en milisegundos y bw en
unidades de 1024 bytes por segundo. Latido usa bw_bytes (bytes por segundo);
los fixtures reales de tests/fixtures/fio/ confirman que
bw_bytes = io_bytes * 1000 / runtime. Si falta bw_bytes, no se calcula otro
valor: se informa el error.

MB/s = 1 000 000 bytes por segundo.

Latencia: lat_ns.mean, la latencia total media («lat» en HOWTO.rst: desde que fio crea la operación hasta que
termina). La documentación no dice la unidad en el JSON; el sufijo _ns y la ley de Little con las salidas reales
(tests/test_velocidad_fio.py) confirman nanosegundos. Es secundaria: si falta o no es válida queda en None y la
medición vale igual.
"""

import json
import math
from dataclasses import dataclass, field

from latido.velocidad.pruebas import PRUEBAS, Direccion

BYTES_POR_MB = 1_000_000


class ErrorFio(Exception):
    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


@dataclass(frozen=True)
class Medicion:
    bytes_por_segundo: float
    iops: float
    bytes_totales: int
    milisegundos: int
    latencia_ns: float | None = None  # media; None si fio no la dio

    @property
    def mb_por_segundo(self):
        return self.bytes_por_segundo / BYTES_POR_MB


def _texto(datos):
    if isinstance(datos, bytes):
        return datos.decode("utf-8", errors="replace")
    return datos or ""


def mensaje_de_fio(error, lineas=8):
    """Las últimas líneas que fio escribió en stderr, tal cual."""
    texto = [linea.rstrip() for linea in _texto(error).splitlines() if linea.strip()]
    return "\n".join(texto[-lineas:])


def _numero(seccion, clave, nombre_seccion):
    valor = seccion.get(clave)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
        raise ErrorFio(f"La salida de fio no trae un valor válido de «{clave}» en «{nombre_seccion}».")
    return valor


def _latencia(seccion):
    lat = seccion.get("lat_ns")
    media = lat.get("mean") if isinstance(lat, dict) else None
    if isinstance(media, bool) or not isinstance(media, (int, float)) or not math.isfinite(media) or media < 0:
        return None
    return float(media)


def leer_salida_fio(salida, codigo, error, trabajo, direccion):
    """Devuelve la Medicion del trabajo o lanza ErrorFio diciendo solo lo que se sabe."""
    mensaje = mensaje_de_fio(error)
    if codigo is None:
        raise ErrorFio("fio no terminó.")
    if codigo != 0:
        inicio = f"fio terminó por la señal {-codigo}." if codigo < 0 else f"fio terminó con el código {codigo}."
        raise ErrorFio(inicio + (f" Mensaje de fio:\n{mensaje}" if mensaje else " fio no escribió ningún mensaje."))
    try:
        datos = json.loads(_texto(salida))
    except ValueError:
        raise ErrorFio("La salida de fio no es un JSON válido: está incompleta o tiene otro formato.") from None
    if not isinstance(datos, dict) or not isinstance(datos.get("jobs"), list):
        raise ErrorFio("La salida de fio no trae la lista de trabajos («jobs»).")
    encontrados = [t for t in datos["jobs"] if isinstance(t, dict) and t.get("jobname") == trabajo]
    if not encontrados:
        raise ErrorFio(f"La salida de fio no trae el trabajo «{trabajo}».")
    if len(encontrados) > 1:
        raise ErrorFio(f"La salida de fio trae {len(encontrados)} trabajos «{trabajo}» y se esperaba uno.")
    datos_trabajo = encontrados[0]
    if datos_trabajo.get("error") != 0:
        raise ErrorFio(
            f"fio informó el error {datos_trabajo.get('error')!r} en el trabajo «{trabajo}»."
            + (f" Mensaje de fio:\n{mensaje}" if mensaje else "")
        )
    seccion = datos_trabajo.get(direccion.value)
    if not isinstance(seccion, dict):
        raise ErrorFio(f"La salida de fio no trae la sección «{direccion.value}» del trabajo «{trabajo}».")
    medicion = Medicion(
        bytes_por_segundo=float(_numero(seccion, "bw_bytes", direccion.value)),
        iops=float(_numero(seccion, "iops", direccion.value)),
        bytes_totales=int(_numero(seccion, "io_bytes", direccion.value)),
        milisegundos=int(_numero(seccion, "runtime", direccion.value)),
        latencia_ns=_latencia(seccion),
    )
    if medicion.bytes_totales == 0:
        raise ErrorFio(f"fio no completó ninguna operación de {direccion.texto} en «{trabajo}».")
    return medicion


@dataclass(frozen=True)
class Resumen:
    pasadas: int
    promedio: float  # bytes por segundo
    mejor: float
    peor: float
    iops_promedio: float
    iops_mejor: float
    iops_peor: float
    latencia_promedio: float | None = None  # nanosegundos; solo si todas las pasadas la tienen


def resumir(mediciones):
    """Promedio (resultado principal), mejor y peor de varias pasadas. None si no hay ninguna."""
    if not mediciones:
        return None
    velocidades = [m.bytes_por_segundo for m in mediciones]
    iops = [m.iops for m in mediciones]
    latencias = [m.latencia_ns for m in mediciones]
    return Resumen(
        pasadas=len(mediciones),
        promedio=sum(velocidades) / len(velocidades),
        mejor=max(velocidades),
        peor=min(velocidades),
        iops_promedio=sum(iops) / len(iops),
        iops_mejor=max(iops),
        iops_peor=min(iops),
        latencia_promedio=None if None in latencias else sum(latencias) / len(latencias),
    )


@dataclass
class ResultadoVelocidad:
    """Mediciones por (clave de prueba, dirección). Solo vive en memoria: no se guarda."""

    pasadas: int
    mediciones: dict = field(default_factory=dict)
    limpieza: object = None  # ejecucion.Limpieza
    avisos: list = field(default_factory=list)

    def agregar(self, paso, medicion):
        self.mediciones.setdefault((paso.prueba.clave, paso.direccion), []).append(medicion)

    def de(self, prueba, direccion):
        return list(self.mediciones.get((prueba.clave, direccion), []))

    def resumen(self, prueba, direccion):
        return resumir(self.de(prueba, direccion))

    @property
    def completo(self):
        return all(
            len(self.de(prueba, direccion)) == self.pasadas
            for prueba in PRUEBAS
            for direccion in Direccion
        )
