"""Pestaña Velocidad: analizador de la salida de fio, resúmenes, unidades y comprobación de fio.

Las salidas reales están en tests/fixtures/fio/ (fio 3.40, Fedora 44, 64 MiB);
los sintéticos llevan el prefijo sintetico_. Ver tests/fixtures/README.md.
"""

import json
import subprocess

import pytest

from conftest import FIXTURES_FIO
from latido.velocidad.herramientas import ENTORNO, comprobar_fio
from latido.velocidad import formato
from latido.velocidad.pruebas import FIO, PRUEBAS, Direccion, Paso
from latido.velocidad.resultado import ErrorFio, Medicion, leer_salida_fio, resumir


def _leer(nombre):
    return (FIXTURES_FIO / nombre).read_bytes()


# trabajo: (dirección, io_bytes, runtime ms, bw_bytes, iops)
REALES = {
    "latido-preparar": (Direccion.ESCRITURA, 67108864, 56, 1198372571, 1142.857143),
    "latido-seq1m-q8t1-lectura": (Direccion.LECTURA, 67108864, 49, 1369568653, 1306.122449),
    "latido-seq1m-q8t1-escritura": (Direccion.ESCRITURA, 67108864, 175, 383479222, 365.714286),
    "latido-seq1m-q1t1-lectura": (Direccion.LECTURA, 67108864, 49, 1369568653, 1306.122449),
    "latido-seq1m-q1t1-escritura": (Direccion.ESCRITURA, 67108864, 87, 771366252, 735.632184),
    "latido-rnd4k-q32t1-lectura": (Direccion.LECTURA, 67108864, 118, 568719186, 138847.457627),
    "latido-rnd4k-q32t1-escritura": (Direccion.ESCRITURA, 67108864, 798, 84096320, 20531.328321),
    "latido-rnd4k-q1t1-lectura": (Direccion.LECTURA, 67108864, 1224, 54827503, 13385.620915),
    "latido-rnd4k-q1t1-escritura": (Direccion.ESCRITURA, 67108864, 852, 78766272, 19230.046948),
}

# trabajo: lat_ns.mean, la latencia total media en nanosegundos (HOWTO.rst, «lat»)
LATENCIAS = {
    "latido-preparar": 6101820.875,
    "latido-seq1m-q8t1-lectura": 4052370.453125,
    "latido-seq1m-q8t1-escritura": 20760760.21875,
    "latido-seq1m-q1t1-lectura": 748536.71875,
    "latido-seq1m-q1t1-escritura": 1331276.625,
    "latido-rnd4k-q32t1-lectura": 221787.221802,
    "latido-rnd4k-q32t1-escritura": 1547253.463379,
    "latido-rnd4k-q1t1-lectura": 73641.813232,
    "latido-rnd4k-q1t1-escritura": 50570.604614,
}


def test_hay_un_fixture_real_por_trabajo():
    trabajos = {Paso().trabajo} | {Paso(p, d, 1).trabajo for p in PRUEBAS for d in Direccion}
    assert trabajos == set(REALES)
    for trabajo in trabajos:
        assert (FIXTURES_FIO / f"{trabajo}.json").is_file()


@pytest.mark.parametrize("trabajo", sorted(REALES))
def test_analiza_las_salidas_reales(trabajo):
    direccion, io_bytes, runtime, bw_bytes, iops = REALES[trabajo]
    medicion = leer_salida_fio(_leer(f"{trabajo}.json"), 0, b"", trabajo, direccion)
    assert medicion == Medicion(float(bw_bytes), pytest.approx(iops), io_bytes, runtime, LATENCIAS[trabajo])


@pytest.mark.parametrize("trabajo", sorted(REALES))
def test_lat_ns_son_nanosegundos_en_las_salidas_reales(trabajo):
    """La documentación de fio 3.40 no dice la unidad de lat_ns en el JSON. Ley de Little: con cola C y λ
    operaciones por segundo, la latencia media no pasa de C / λ (en vuelo hay C como mucho). Con datos reales
    queda entre la mitad y el total de C / λ; en microsegundos o milisegundos estaría mil veces lejos."""
    direccion, _, _, _, iops = REALES[trabajo]
    paso = next((Paso(p, direccion, 1) for p in PRUEBAS if Paso(p, direccion, 1).trabajo == trabajo), None)
    cola = paso.prueba.cola if paso else 8  # la preparación usa cola 8 (COLA_PREPARACION)
    tope_ns = cola / iops * 1e9
    assert 0.5 * tope_ns <= LATENCIAS[trabajo] <= tope_ns


@pytest.mark.parametrize("cambio", [
    lambda s: s.pop("lat_ns"),
    lambda s: s.__setitem__("lat_ns", {"min": 1}),
    lambda s: s.__setitem__("lat_ns", {"mean": -1}),
    lambda s: s.__setitem__("lat_ns", {"mean": "73"}),
    lambda s: s.__setitem__("lat_ns", {"mean": float("nan")}),
    lambda s: s.__setitem__("lat_ns", 5),
])
def test_sin_latencia_valida_la_medicion_sigue_y_la_latencia_queda_sin_dato(cambio):
    """La latencia es secundaria: si falta o no es válida, se muestra «—» y la medición vale igual."""
    salida = _real_modificado(lambda d: cambio(d["jobs"][0]["read"]))
    medicion = leer_salida_fio(salida, 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)
    assert medicion.latencia_ns is None and medicion.bytes_por_segundo == 1369568653.0


@pytest.mark.parametrize("trabajo", sorted(REALES))
def test_bw_bytes_son_bytes_por_segundo_en_las_salidas_reales(trabajo):
    """Confirma con datos reales: bw_bytes = io_bytes * 1000 / runtime (ms), y bw = bw_bytes / 1024."""
    datos = json.loads(_leer(f"{trabajo}.json"))
    seccion = datos["jobs"][0][REALES[trabajo][0].value]
    assert seccion["bw_bytes"] == seccion["io_bytes"] * 1000 // seccion["runtime"]
    assert seccion["bw"] == seccion["bw_bytes"] // 1024
    assert datos["fio version"] == "fio-3.40"


def test_la_otra_direccion_del_trabajo_real_no_cuenta():
    with pytest.raises(ErrorFio, match="ninguna operación de escritura"):
        leer_salida_fio(_leer("latido-seq1m-q8t1-lectura.json"), 0, b"", "latido-seq1m-q8t1-lectura", Direccion.ESCRITURA)


def test_trabajo_con_otro_nombre_es_error():
    with pytest.raises(ErrorFio, match="no trae el trabajo «latido-preparar»"):
        leer_salida_fio(_leer("latido-seq1m-q8t1-lectura.json"), 0, b"", "latido-preparar", Direccion.LECTURA)


def test_salida_truncada():
    with pytest.raises(ErrorFio, match="no es un JSON válido"):
        leer_salida_fio(_leer("sintetico_truncado.txt"), 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


def test_json_invalido():
    with pytest.raises(ErrorFio, match="no es un JSON válido"):
        leer_salida_fio(_leer("sintetico_json_invalido.txt"), 0, b"", "latido-preparar", Direccion.ESCRITURA)


def test_error_de_fio_con_codigo_distinto_de_cero_muestra_su_mensaje_tal_cual():
    stderr = _leer("sintetico_error_fio.stderr")
    with pytest.raises(ErrorFio) as error:
        leer_salida_fio(b"", 1, stderr, "latido-preparar", Direccion.ESCRITURA)
    assert error.value.mensaje == (
        "fio terminó con el código 1. Mensaje de fio:\n" + stderr.decode().strip()
    )


def test_error_de_fio_sin_mensaje_no_inventa_la_causa():
    with pytest.raises(ErrorFio) as error:
        leer_salida_fio(b"", 1, b"", "latido-preparar", Direccion.ESCRITURA)
    assert error.value.mensaje == "fio terminó con el código 1. fio no escribió ningún mensaje."


def test_fio_terminado_por_senal():
    with pytest.raises(ErrorFio, match="terminó por la señal 9"):
        leer_salida_fio(b"", -9, b"", "latido-preparar", Direccion.ESCRITURA)


@pytest.mark.parametrize("archivo, mensaje", [
    ("sintetico_jobs_vacio.json", "no trae el trabajo"),
    ("sintetico_sin_jobs.json", "no trae la lista de trabajos"),
    ("sintetico_otro_trabajo.json", "no trae el trabajo"),
])
def test_jobs_faltantes(archivo, mensaje):
    with pytest.raises(ErrorFio, match=mensaje):
        leer_salida_fio(_leer(archivo), 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


def _real_modificado(cambio):
    datos = json.loads(_leer("latido-seq1m-q8t1-lectura.json"))
    cambio(datos)
    return json.dumps(datos).encode()


@pytest.mark.parametrize("clave", ["bw_bytes", "iops", "io_bytes", "runtime"])
def test_falta_un_numero_y_no_se_calcula_otro(clave):
    salida = _real_modificado(lambda d: d["jobs"][0]["read"].pop(clave))
    with pytest.raises(ErrorFio, match=f"«{clave}»"):
        leer_salida_fio(salida, 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


@pytest.mark.parametrize("valor", [None, "123", True, -1, float("nan")])
def test_bw_bytes_invalido(valor):
    salida = _real_modificado(lambda d: d["jobs"][0]["read"].__setitem__("bw_bytes", valor))
    with pytest.raises(ErrorFio, match="bw_bytes"):
        leer_salida_fio(salida, 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


def test_error_dentro_del_trabajo():
    salida = _real_modificado(lambda d: d["jobs"][0].__setitem__("error", 5))
    with pytest.raises(ErrorFio, match="error 5"):
        leer_salida_fio(salida, 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


def test_trabajo_duplicado():
    salida = _real_modificado(lambda d: d["jobs"].append(d["jobs"][0]))
    with pytest.raises(ErrorFio, match="trae 2 trabajos"):
        leer_salida_fio(salida, 0, b"", "latido-seq1m-q8t1-lectura", Direccion.LECTURA)


def test_promedio_mejor_y_peor():
    mediciones = [Medicion(100e6, 100.0, 1, 1), Medicion(300e6, 300.0, 1, 1), Medicion(200e6, 200.0, 1, 1)]
    resumen = resumir(mediciones)
    assert (resumen.promedio, resumen.mejor, resumen.peor) == (200e6, 300e6, 100e6)
    assert (resumen.iops_promedio, resumen.iops_mejor, resumen.iops_peor) == (200.0, 300.0, 100.0)
    assert resumen.pasadas == 3
    assert resumen.latencia_promedio is None  # sin latencia en las pasadas
    assert resumir([]) is None


def test_latencia_promedio_solo_con_todas_las_pasadas():
    con = [Medicion(1e6, 1.0, 1, 1, 1000.0), Medicion(1e6, 1.0, 1, 1, 3000.0)]
    assert resumir(con).latencia_promedio == 2000.0
    assert resumir(con + [Medicion(1e6, 1.0, 1, 1)]).latencia_promedio is None  # no se promedia a medias


def test_formato_de_latencia():
    assert [formato.latencia(n) for n in (73641.813232, 999_949.0, 999_960.0, 1_331_276.625, 20_760_760.2, None)] == [
        "73.6 µs", "999.9 µs", "1.00 ms", "1.33 ms", "20.76 ms", "—"]  # nunca «1,000.0 µs»


def test_mb_por_segundo_es_un_millon_de_bytes():
    assert Medicion(1369568653.0, 1306.1, 1, 1).mb_por_segundo == 1369.568653


class Proceso:
    def __init__(self, codigo, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = codigo, stdout, stderr


def _ejecutar_falso(respuestas, llamadas):
    def ejecutar(comando, **opciones):
        llamadas.append((comando, opciones))
        respuesta = respuestas[tuple(comando[1:])]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta
    return ejecutar


def test_fio_y_libaio_listos_con_salidas_reales():
    llamadas = []
    respuestas = {
        ("--version",): Proceso(0, _leer("version.stdout")),
        ("--enghelp=libaio",): Proceso(0, _leer("enghelp_libaio.stdout")),
    }
    estado = comprobar_fio(ejecutar=_ejecutar_falso(respuestas, llamadas), ejecutable=lambda ruta: True)
    assert estado.listo and estado.version == "fio-3.40"
    assert [comando for comando, _ in llamadas] == [[FIO, "--version"], [FIO, "--enghelp=libaio"]]
    for _, opciones in llamadas:
        assert opciones["env"] == ENTORNO == {"LC_ALL": "C"}
        assert opciones["stdin"] is subprocess.DEVNULL
        assert not opciones.get("shell", False)
        assert opciones["timeout"] > 0


def test_falta_libaio_dice_el_paquete_exacto_y_el_mensaje_de_fio():
    respuestas = {
        ("--version",): Proceso(0, _leer("version.stdout")),
        # Salida real de fio 3.40 con un motor que no se puede cargar.
        ("--enghelp=libaio",): Proceso(1, _leer("enghelp_inexistente.stdout"), _leer("enghelp_inexistente.stderr")),
    }
    estado = comprobar_fio(ejecutar=_ejecutar_falso(respuestas, []), ejecutable=lambda ruta: True)
    assert not estado.listo
    assert estado.problemas[0].startswith(
        "fio no pudo cargar el motor libaio. Instálalo con: sudo dnf install fio-engine-libaio\nMensaje de fio:\n"
    )
    assert "not loadable" in estado.problemas[0]


def test_falta_fio_dice_los_paquetes_exactos_sin_ejecutar_nada():
    llamadas = []
    estado = comprobar_fio(ejecutar=_ejecutar_falso({}, llamadas), ejecutable=lambda ruta: False)
    assert estado.problemas == ["Falta fio (/usr/bin/fio). Instálalo con: sudo dnf install fio fio-engine-libaio"]
    assert llamadas == []


def test_fio_que_no_responde_o_no_se_puede_ejecutar():
    respuestas = {("--version",): subprocess.TimeoutExpired(FIO, 15)}
    estado = comprobar_fio(ejecutar=_ejecutar_falso(respuestas, []), ejecutable=lambda ruta: True)
    assert "no respondió en 15 s" in estado.problemas[0]
    respuestas = {("--version",): PermissionError(13, "Permission denied")}
    estado = comprobar_fio(ejecutar=_ejecutar_falso(respuestas, []), ejecutable=lambda ruta: True)
    assert estado.problemas == ["No se pudo ejecutar /usr/bin/fio: Permission denied."]
