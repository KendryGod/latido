"""Limpieza: tras éxito, error, cancelación o excepción no queda ningún archivo, carpeta ni descriptor abierto.

Todo con el fio falso (tests/fio_falso.py) en tmp_path. La cancelación es
real: el fio falso duerme con un proceso hijo y Latido detiene el grupo entero.
"""

import errno
import os
import threading
import time

import pytest

from conftest import FIXTURES_FIO, StatvfsFalso, descriptores_hacia, vivo
from latido.velocidad.carpeta import revisar_carpeta
from latido.velocidad.ejecucion import Cancelado, Ejecucion, ErrorVelocidad, Limpieza
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import (
    ARCHIVO_PRUEBA,
    MIB,
    PREFIJO_DIRECTORIO,
    PRUEBAS,
    Configuracion,
    Direccion,
    Paso,
)


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
    assert descriptores_hacia(carpeta) == []
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
    assert descriptores_hacia(carpeta) == []


def test_error_en_la_preparacion_limpia(carpeta, fio_falso):
    fio_falso.configurar(["falla"])
    with pytest.raises(ErrorVelocidad, match="Preparando el archivo de prueba"):
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


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
    assert descriptores_hacia(carpeta) == []


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
    assert descriptores_hacia(carpeta) == []


def test_cancelar_durante_la_preparacion_borra_lo_que_creo_fio(carpeta, fio_falso):
    fio_falso.configurar(["duerme"])  # crea el archivo y se queda dormido
    valor, principal, hijo, _ = _cancelar_cuando_duerma(_ejecucion(carpeta, fio_falso), fio_falso)
    assert isinstance(valor, Cancelado)
    assert not vivo(principal) and not vivo(hijo)
    assert valor.limpieza.archivo_borrado
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


def test_si_fio_ignora_sigterm_se_usa_sigkill(carpeta, fio_falso):
    fio_falso.configurar(["ok", "ignora_sigterm"])
    valor, principal, hijo, segundos = _cancelar_cuando_duerma(_ejecucion(carpeta, fio_falso), fio_falso)
    assert isinstance(valor, Cancelado)
    assert 1 <= segundos < 10  # esperó el plazo de SIGTERM y luego SIGKILL
    assert not vivo(principal) and not vivo(hijo)
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


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
    assert descriptores_hacia(carpeta) == []


def test_excepcion_inesperada_limpia(carpeta, fio_falso):
    def falla_en_el_paso_4(progreso):
        if progreso.indice == 3 and not progreso.terminado:
            raise RuntimeError("fallo inventado")

    with pytest.raises(ErrorVelocidad, match="Error inesperado") as error:
        _ejecucion(carpeta, fio_falso, al_progresar=falla_en_el_paso_4).ejecutar()
    assert isinstance(error.value.__cause__, RuntimeError)
    assert error.value.limpieza.completa
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


def test_interrupcion_del_teclado_tambien_limpia(carpeta, fio_falso):
    def interrumpe(progreso):
        if progreso.indice == 2 and not progreso.terminado:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _ejecucion(carpeta, fio_falso, al_progresar=interrumpe).ejecutar()
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


def test_cancelar_antes_de_empezar_no_crea_nada(carpeta, fio_falso):
    ejecucion = _ejecucion(carpeta, fio_falso)
    ejecucion.cancelar()
    with pytest.raises(Cancelado) as cancelado:
        ejecucion.ejecutar()
    assert cancelado.value.limpieza.texto() == "No se llegó a crear ningún archivo."
    assert fio_falso.invocaciones() == []
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


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
    assert descriptores_hacia(carpeta) == []


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
    assert descriptores_hacia(carpeta) == []


# --- Si la carpeta temporal no se pudo borrar, el aviso siempre dice la verdad ---

INCOMPLETA = "La limpieza quedó incompleta:\n"


def _limpieza_de(ejecucion):
    """La limpieza de una prueba, haya terminado bien o con un error."""
    try:
        return ejecucion.ejecutar().limpieza
    except ErrorVelocidad as error:
        return error.limpieza


@pytest.mark.parametrize("modos, avisos", [
    (["ok", "ensucia"], lambda ej: [
        f"No se borró {ej.directorio}: quedaron archivos que Latido no creó (extra.txt). Revísalos tú.",
    ]),
    (["ok", "enlace_duro", "ok"], lambda ej: [
        f"{ej.archivo} tiene 2 nombres (alguien le hizo un enlace duro); Latido no lo borró.",
        f"No se borró {ej.directorio}: dentro sigue el archivo de prueba de Latido ({ARCHIVO_PRUEBA}).",
    ]),
    (["enlaza"], lambda ej: [
        f"En {ej.archivo} hay algo que no es el archivo de prueba de Latido; no se borró.",
        f"No se borró {ej.directorio}: quedaron archivos que Latido no creó ({ARCHIVO_PRUEBA}). Revísalos tú.",
    ]),
], ids=["algo-ajeno", "su-archivo-con-dos-nombres", "un-enlace-sin-descriptor"])
def test_el_aviso_no_usa_un_descriptor_abierto_antes_de_que_apareciera_lo_que_quedo(
    carpeta, tmp_path, fio_falso, listar_como_btrfs, modos, avisos
):
    """Con el simulador, un descriptor de carpeta no ve lo que apareció después de abrirlo, como en btrfs.
    Latido abre la carpeta temporal al crearla, antes de todo lo que queda dentro: si listara con ese
    descriptor, el aviso no diría qué quedó y esta prueba fallaría."""
    fio_falso.configurar(modos, enlace=str(tmp_path / "fuera.txt"), destino=str(tmp_path / "segundo-nombre.dat"))
    ej = _ejecucion(carpeta, fio_falso)
    limpieza = _limpieza_de(ej)
    assert limpieza.problemas == avisos(ej)
    assert not limpieza.directorio_borrado and not limpieza.completa
    assert limpieza.texto() == INCOMPLETA + "\n".join(avisos(ej))
    assert descriptores_hacia(carpeta) == []


def test_si_no_puede_ver_que_quedo_lo_dice_y_no_la_da_por_borrada(carpeta, fio_falso, monkeypatch):
    """Independiente del listado: si rmdir no pudo borrar la carpeta temporal, siempre hay un aviso."""
    listar = os.listdir
    monkeypatch.setattr(os, "listdir", lambda ruta=".": [] if isinstance(ruta, int) else listar(ruta))
    fio_falso.configurar(["ok", "ensucia"])
    ej = _ejecucion(carpeta, fio_falso)
    limpieza = ej.ejecutar().limpieza
    aviso = f"No se borró {ej.directorio}: no está vacía, pero Latido no pudo ver qué hay dentro. Revísala tú."
    assert limpieza.problemas == [aviso]
    assert limpieza.archivo_borrado and not limpieza.directorio_borrado and not limpieza.completa
    assert limpieza.texto() == INCOMPLETA + aviso
    assert os.listdir(ej.directorio) == ["extra.txt"]  # la carpeta sigue ahí, con lo ajeno
    assert descriptores_hacia(carpeta) == []


@pytest.mark.parametrize("cambio", ["otra-carpeta", "no-se-puede-abrir"])
def test_si_la_carpeta_cambia_al_ir_a_revisarla_lo_dice_y_no_lista_otra(
    carpeta, tmp_path, fio_falso, monkeypatch, cambio
):
    """Cuando rmdir falla, Latido abre la carpeta temporal para ver qué quedó, comprueba con fstat que es la
    que creó (mismo st_dev y st_ino) y cierra ese descriptor pase lo que pase."""
    otra = tmp_path / "otra"
    otra.mkdir()
    (otra / "señuelo.txt").write_text("no listar", encoding="utf-8")
    abrir, borrar_carpeta = os.open, os.rmdir
    rmdir_intentado = []

    def rmdir_espia(ruta, *resto, **opciones):
        if os.fsdecode(ruta).startswith(PREFIJO_DIRECTORIO):
            rmdir_intentado.append(ruta)
        return borrar_carpeta(ruta, *resto, **opciones)

    def open_despues_de_rmdir(ruta, flags, mode=0o777, *, dir_fd=None):
        if rmdir_intentado and os.fsdecode(ruta).startswith(PREFIJO_DIRECTORIO):
            if cambio == "no-se-puede-abrir":
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), ruta)
            return abrir(otra, flags, mode)
        return abrir(ruta, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "rmdir", rmdir_espia)
    monkeypatch.setattr(os, "open", open_despues_de_rmdir)
    fio_falso.configurar(["ok", "ensucia"])
    ej = _ejecucion(carpeta, fio_falso)
    limpieza = ej.ejecutar().limpieza
    if cambio == "otra-carpeta":
        aviso = (
            f"No se borró {ej.directorio}: no estaba vacía, y lo que hay ahora en esa ruta ya no es la carpeta "
            "que creó Latido. Revísala tú."
        )
    else:
        aviso = (
            f"No se borró {ej.directorio}: no está vacía, pero Latido no pudo ver qué hay dentro "
            f"({os.strerror(errno.ENOENT)}). Revísala tú."
        )
    assert limpieza.problemas == [aviso]
    assert not limpieza.directorio_borrado and not limpieza.completa
    assert descriptores_hacia(carpeta) == [] and descriptores_hacia(otra) == []


@pytest.mark.parametrize("limpieza, completa, texto", [
    (Limpieza(), True, "No se llegó a crear ningún archivo."),
    (Limpieza(creo_directorio=True, archivo_borrado=True, directorio_borrado=True), True,
     "Se borraron el archivo de prueba y su carpeta temporal."),
    (Limpieza(creo_directorio=True, archivo_borrado_por_otro=True, directorio_borrado=True), True,
     "Se borró la carpeta temporal; el archivo de prueba ya lo había borrado otro programa."),
    (Limpieza(creo_directorio=True, directorio_borrado=True), True,
     "Se borró la carpeta temporal; el archivo de prueba no llegó a crearse."),
    (Limpieza(creo_directorio=True, archivo_borrado=True), False, INCOMPLETA + "No se borró la carpeta temporal."),
    (Limpieza(creo_directorio=True), False, INCOMPLETA + "No se borró la carpeta temporal."),
    (Limpieza(creo_directorio=True, archivo_borrado=True, directorio_borrado=True, problemas=["fio sigue activo."]),
     False, INCOMPLETA + "fio sigue activo."),
], ids=["nada-creado", "todo-borrado", "archivo-borrado-por-otro", "archivo-sin-crear",
        "carpeta-sin-borrar-y-sin-avisos", "nada-borrado-y-sin-avisos", "con-avisos"])
def test_completa_y_texto_salen_de_lo_que_de_verdad_se_borro(limpieza, completa, texto):
    """Nunca de «no hubo avisos»: sin la carpeta temporal borrada, la limpieza no está completa."""
    assert limpieza.completa is completa
    assert limpieza.texto() == texto


# --- Sin archivo al limpiar: solo se afirma «no llegó a crearse» si fio nunca se lanzó ---

NO_HABIA_ARCHIVO = (
    "Se borró la carpeta temporal; no había archivo de prueba (fio no llegó a crearlo, o lo borró otro programa)."
)
NO_LLEGO_A_CREARSE = "Se borró la carpeta temporal; el archivo de prueba no llegó a crearse."


def test_texto_si_fio_se_lanzo_y_no_habia_archivo():
    limpieza = Limpieza(creo_directorio=True, fio_pudo_crear_archivo=True, directorio_borrado=True)
    assert limpieza.completa
    assert limpieza.texto() == NO_HABIA_ARCHIVO


@pytest.mark.parametrize("modo", ["falla", "borra"], ids=["fio-falla-antes-de-crearlo", "lo-crea-y-desaparece"])
def test_si_fio_se_lanzo_y_no_hay_archivo_no_afirma_que_no_llego_a_crearse(carpeta, fio_falso, modo):
    """En la preparación Latido aún no tiene descriptor: no sabe si fio llegó a crear el archivo. Con
    «borra», el fio falso lo crea y lo borra, y «no llegó a crearse» sería falso."""
    fio_falso.configurar([modo])
    with pytest.raises(ErrorVelocidad) as error:
        _ejecucion(carpeta, fio_falso).ejecutar()
    assert len(fio_falso.invocaciones()) == 1  # fio llegó a lanzarse
    limpieza = error.value.limpieza
    assert limpieza.directorio_borrado and not limpieza.archivo_borrado and limpieza.completa
    assert limpieza.texto() == NO_HABIA_ARCHIVO
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []


def test_si_fio_no_llego_a_lanzarse_el_archivo_no_llego_a_crearse(carpeta, fio_falso):
    def falla_antes_de_lanzar_fio(progreso):
        if progreso.indice == 0 and not progreso.terminado:
            raise RuntimeError("fallo inventado antes de la preparación")

    with pytest.raises(ErrorVelocidad, match="Error inesperado") as error:
        _ejecucion(carpeta, fio_falso, al_progresar=falla_antes_de_lanzar_fio).ejecutar()
    assert fio_falso.invocaciones() == []  # fio nunca se lanzó
    limpieza = error.value.limpieza
    assert limpieza.directorio_borrado and limpieza.completa
    assert limpieza.texto() == NO_LLEGO_A_CREARSE
    assert _vacia(carpeta)
    assert descriptores_hacia(carpeta) == []
