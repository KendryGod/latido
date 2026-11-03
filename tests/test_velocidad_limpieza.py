"""Limpieza: tras éxito, error, cancelación o excepción no queda ningún archivo ni carpeta.

Todo con el fio falso (tests/fio_falso.py) en tmp_path. La cancelación es
real: el fio falso duerme con un proceso hijo y Latido detiene el grupo entero.
"""

import os
import threading
import time

import pytest

from conftest import FIXTURES_FIO, StatvfsFalso, vivo
from latido.velocidad.carpeta import revisar_carpeta
from latido.velocidad.ejecucion import Cancelado, Ejecucion, ErrorVelocidad
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import MIB, PRUEBAS, Configuracion, Direccion, Paso


@pytest.fixture
def carpeta(tmp_path):
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    return carpeta


def _ejecucion(carpeta, fio_falso, pasadas=1, **opciones):
    def revisar(ruta, conf):
        return revisar_carpeta(ruta, conf, statvfs=lambda _ruta: StatvfsFalso(10**12))

    opciones.setdefault("segundos_para_terminar", 1)
    return Ejecucion(
        str(carpeta), Configuracion(256 * MIB, pasadas), fio=str(fio_falso.ruta),
        comprobar=lambda fio: EstadoFio("fio-falso"), revisar=revisar, **opciones,
    )


def _vacia(carpeta):
    return os.listdir(carpeta) == []


def test_exito_no_deja_nada(carpeta, fio_falso):
    resultado = _ejecucion(carpeta, fio_falso, pasadas=3).ejecutar()
    assert resultado.completo
    assert resultado.limpieza.completa and resultado.limpieza.archivo_borrado and resultado.limpieza.directorio_borrado
    assert resultado.limpieza.texto() == "Se borraron el archivo de prueba y su carpeta temporal."
    assert _vacia(carpeta)
    # 3 pasadas: el fio falso da 100, 200 y 300 MB/s.
    resumen = resultado.resumen(PRUEBAS[0], Direccion.LECTURA)
    assert (resumen.promedio, resumen.mejor, resumen.peor) == (200e6, 300e6, 100e6)


def test_error_de_fio_muestra_su_mensaje_y_limpia(carpeta, fio_falso):
    fio_falso.configurar(["ok", "ok", "falla"])
    with pytest.raises(ErrorVelocidad) as error:
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert error.value.mensaje == (
        "fio falló en «SEQ1M Q8T1 · escritura · pasada 1 de 1».\n"
        "fio terminó con el código 1. Mensaje de fio:\n"
        "fio: error inventado por el fio falso (err=22/Invalid argument)"
    )
    assert error.value.limpieza.completa
    assert _vacia(carpeta)


def test_error_en_la_preparacion_limpia(carpeta, fio_falso):
    fio_falso.configurar(["falla"])
    with pytest.raises(ErrorVelocidad, match="Preparando el archivo de prueba"):
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert _vacia(carpeta)


@pytest.mark.parametrize("modo, mensaje", [
    ("json_invalido", "no es un JSON válido"),
    ("truncado", "no es un JSON válido"),
    ("sin_trabajos", "no trae el trabajo"),
])
def test_salida_mala_de_fio_limpia(carpeta, fio_falso, modo, mensaje):
    fio_falso.configurar(["ok", modo])
    with pytest.raises(ErrorVelocidad, match=mensaje):
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert _vacia(carpeta)


def _cancelar_cuando_duerma(ejecucion, fio_falso):
    resultado = {}

    def correr():
        try:
            resultado["valor"] = ejecucion.ejecutar()
        except BaseException as error:  # se revisa en la prueba
            resultado["valor"] = error

    hilo = threading.Thread(target=correr)
    hilo.start()
    limite = time.monotonic() + 10
    while not fio_falso.hijos() and time.monotonic() < limite:
        time.sleep(0.02)
    assert fio_falso.hijos(), "el fio falso no llegó a dormir"
    principal = fio_falso.invocaciones()[-1]["pid"]
    hijo = fio_falso.hijos()[-1]
    assert vivo(principal) and vivo(hijo)
    inicio = time.monotonic()
    ejecucion.cancelar()
    hilo.join(20)
    assert not hilo.is_alive()
    return resultado["valor"], principal, hijo, time.monotonic() - inicio


def test_cancelar_durante_una_medicion_detiene_el_grupo_y_limpia(carpeta, fio_falso):
    fio_falso.configurar(["ok", "ok", "duerme"])
    valor, principal, hijo, _ = _cancelar_cuando_duerma(_ejecucion(carpeta, fio_falso), fio_falso)
    assert isinstance(valor, Cancelado)
    assert not vivo(principal) and not vivo(hijo)
    assert valor.limpieza.completa and valor.limpieza.archivo_borrado
    assert _vacia(carpeta)


def test_cancelar_durante_la_preparacion_borra_lo_que_creo_fio(carpeta, fio_falso):
    fio_falso.configurar(["duerme"])  # crea el archivo y se queda dormido
    valor, principal, hijo, _ = _cancelar_cuando_duerma(_ejecucion(carpeta, fio_falso), fio_falso)
    assert isinstance(valor, Cancelado)
    assert not vivo(principal) and not vivo(hijo)
    assert valor.limpieza.archivo_borrado
    assert _vacia(carpeta)


def test_si_fio_ignora_sigterm_se_usa_sigkill(carpeta, fio_falso):
    fio_falso.configurar(["ok", "ignora_sigterm"])
    valor, principal, hijo, segundos = _cancelar_cuando_duerma(_ejecucion(carpeta, fio_falso), fio_falso)
    assert isinstance(valor, Cancelado)
    assert 1 <= segundos < 10  # esperó el plazo de SIGTERM y luego SIGKILL
    assert not vivo(principal) and not vivo(hijo)
    assert _vacia(carpeta)


def test_medicion_que_no_termina_se_detiene(carpeta, fio_falso):
    fio_falso.configurar(["ok", "duerme"])
    inicio = time.monotonic()
    with pytest.raises(ErrorVelocidad, match="no terminó la medición en 0.5 s") as error:
        _ejecucion(carpeta, fio_falso, segundos_maximos_medicion=0.5).ejecutar()
    assert time.monotonic() - inicio < 10
    principal = fio_falso.invocaciones()[-1]["pid"]
    assert not vivo(principal) and not any(vivo(h) for h in fio_falso.hijos())
    assert error.value.limpieza.completa
    assert _vacia(carpeta)


def test_excepcion_inesperada_limpia(carpeta, fio_falso):
    def falla_en_el_paso_4(progreso):
        if progreso.indice == 3 and not progreso.terminado:
            raise RuntimeError("fallo inventado")

    with pytest.raises(ErrorVelocidad, match="Error inesperado") as error:
        _ejecucion(carpeta, fio_falso, al_progresar=falla_en_el_paso_4).ejecutar()
    assert isinstance(error.value.__cause__, RuntimeError)
    assert error.value.limpieza.completa
    assert _vacia(carpeta)


def test_interrupcion_del_teclado_tambien_limpia(carpeta, fio_falso):
    def interrumpe(progreso):
        if progreso.indice == 2 and not progreso.terminado:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _ejecucion(carpeta, fio_falso, al_progresar=interrumpe).ejecutar()
    assert _vacia(carpeta)


def test_cancelar_antes_de_empezar_no_crea_nada(carpeta, fio_falso):
    ejecucion = _ejecucion(carpeta, fio_falso)
    ejecucion.cancelar()
    with pytest.raises(Cancelado) as cancelado:
        ejecucion.ejecutar()
    assert cancelado.value.limpieza.texto() == "No se llegó a crear ningún archivo."
    assert fio_falso.invocaciones() == []
    assert _vacia(carpeta)


def test_archivos_ajenos_no_se_borran_y_se_dice(carpeta, fio_falso):
    fio_falso.configurar(["ok", "ensucia"])
    resultado = _ejecucion(carpeta, fio_falso).ejecutar()
    limpieza = resultado.limpieza
    assert limpieza.archivo_borrado and not limpieza.directorio_borrado
    [directorio] = os.listdir(carpeta)
    assert os.listdir(carpeta / directorio) == ["extra.txt"]  # solo queda lo ajeno
    assert limpieza.problemas == [
        f"No se borró {carpeta / directorio}: quedaron archivos que Latido no creó (extra.txt). Revísalos tú."
    ]


def test_reproduce_las_salidas_reales_de_fio(carpeta, fio_falso):
    trabajos = [Paso().trabajo] + [Paso(p, d, 1).trabajo for p in PRUEBAS for d in Direccion]
    fio_falso.configurar(["ok"], fixtures={t: FIXTURES_FIO / f"{t}.json" for t in trabajos})
    resultado = _ejecucion(carpeta, fio_falso).ejecutar()
    assert resultado.completo
    resumen = resultado.resumen(PRUEBAS[0], Direccion.LECTURA)
    assert resumen.promedio == 1369568653
    assert round(resumen.iops_promedio, 6) == 1306.122449
    assert resultado.resumen(PRUEBAS[3], Direccion.ESCRITURA).promedio == 78766272
    assert _vacia(carpeta)
