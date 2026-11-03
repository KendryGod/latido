"""Modo demo: `python3 -m latido --demo sano|precaucion|peligro|sin-datos`. Sin GTK.

Datos de ejemplo, inventados, de un disco que no existe. No se lee ningún disco ni se ejecuta nada: ni
pkexec, ni smartctl, ni fio. La interfaz lo dice con un banner permanente y el informe TXT con una marca.
"""

import copy

from latido.informe_txt import VelocidadMedida
from latido.salud import analizar
from latido.sistema.discos import Disco
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import GIB, PRUEBAS, Configuracion, Direccion, Paso
from latido.velocidad.resultado import Medicion, ResultadoVelocidad

ESTADOS = ("sano", "precaucion", "peligro", "sin-datos")
AVISO = "Datos de ejemplo, no son de tu disco"
CAPACIDAD = 1_000_204_886_016

_BASE = {
    "_ejemplo": "Datos de ejemplo de Latido (modo demo). No son de ningún disco real.",
    "smartctl": {"version": [7, 5], "exit_status": 0},
    "device": {"name": "/dev/nvme0", "type": "nvme", "protocol": "NVMe"},
    "model_name": "Disco de ejemplo NVMe",
    "firmware_version": "EJEMPLO1",
    "user_capacity": {"blocks": CAPACIDAD // 512, "bytes": CAPACIDAD},
    "nvme_number_of_namespaces": 1,
    "smart_status": {"passed": True},
    "nvme_composite_temperature_threshold": {"warning": 80, "critical": 85},
    "temperature": {"current": 41, "op_limit_max": 80, "critical_limit_max": 85},
    "nvme_smart_health_information_log": {
        "nsid": -1, "critical_warning": 0, "temperature": 41, "available_spare": 100,
        "available_spare_threshold": 10, "percentage_used": 3, "data_units_read": 9_765_625,
        "data_units_written": 7_812_500, "host_reads": 61_234_567, "host_writes": 48_765_432,
        "controller_busy_time": 1_234, "power_cycles": 512, "power_on_hours": 2_345, "unsafe_shutdowns": 21,
        "media_errors": 0, "num_err_log_entries": 0, "warning_temp_time": 0, "critical_comp_time": 0,
    },
}

_CAMBIOS = {
    "sano": {},
    "precaucion": {"percentage_used": 95, "media_errors": 3},
    "peligro": {"critical_warning": 0b100, "available_spare": 6},
    "sin-datos": {"critical_warning": None, "media_errors": None, "percentage_used": None},
}


def datos_demo(estado):
    """El JSON de smartctl (inventado) de un estado de la demo."""
    if estado not in ESTADOS:
        raise ValueError(f"estado de demo desconocido: {estado}")
    datos = copy.deepcopy(_BASE)
    registro = datos["nvme_smart_health_information_log"]
    for clave, valor in _CAMBIOS[estado].items():
        if valor is None:
            registro.pop(clave)
        else:
            registro[clave] = valor
    return datos


def informe_demo(estado):
    return analizar(datos_demo(estado))


def disco_demo():
    return Disco(nombre="ejemplo", ruta="modo demo", ruta_lectura=None, modelo="Disco de ejemplo NVMe",
                 tamano=CAPACIDAD, transporte="nvme", es_sistema=False, habilitado=True, aviso=None)


# MB/s de ejemplo (lectura, escritura) por prueba, con 3 pasadas que varían un poco.
_VELOCIDADES = {
    "seq1m-q8t1": (3_400, 2_900),
    "seq1m-q1t1": (2_100, 1_900),
    "rnd4k-q32t1": (1_450, 1_120),
    "rnd4k-q1t1": (62, 160),
}


def velocidad_demo():
    configuracion = Configuracion(GIB, 3)
    resultado = ResultadoVelocidad(configuracion.pasadas)
    for prueba in PRUEBAS:
        for direccion, mb_s in zip(Direccion, _VELOCIDADES[prueba.clave]):
            for pasada, factor in enumerate((0.98, 1.0, 1.02), start=1):
                bytes_por_segundo = mb_s * 1_000_000 * factor
                iops = bytes_por_segundo / prueba.bloque
                resultado.agregar(Paso(prueba, direccion, pasada), Medicion(
                    bytes_por_segundo=bytes_por_segundo, iops=iops, bytes_totales=configuracion.tamano,
                    milisegundos=1_000, latencia_ns=prueba.cola / iops * 1e9,  # ley de Little, cola llena
                ))
    return VelocidadMedida(resultado, configuracion, "ext4 (ejemplo)")


def servicios_velocidad_demo():
    """Servicios de la pestaña Velocidad que no pueden ejecutar fio: crear una prueba falla siempre."""
    from latido.ui.pagina_velocidad import ServiciosVelocidad

    def sin_fio(*_args, **_kwargs):
        raise RuntimeError("En el modo demo no se ejecuta fio.")

    return ServiciosVelocidad(
        comprobar_fio=lambda: EstadoFio("fio no se usa en el modo demo"),
        revisar_carpeta=sin_fio,
        crear_ejecucion=sin_fio,
        leer_ultima_carpeta=lambda: None,
        buscar_restos=lambda carpeta: [],
        borrar_resto=sin_fio,
    )
