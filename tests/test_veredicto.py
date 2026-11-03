"""Veredicto honesto (docs/veredicto.md): la tabla única de reglas con su FUENTE, y la autenticidad aparte."""

import re
from pathlib import Path

import pytest

from conftest import FIXTURES, cargar
from latido.salud import Estado, analizar
from latido.salud import autenticidad as aut
from latido.salud.reglas import POR_ID, REGLAS, SIN_FUENTE

RAIZ = Path(__file__).parent.parent
DOC = (RAIZ / "docs" / "veredicto.md").read_text(encoding="utf-8")
RESULTADO = {Estado.MALO: "Peligro (rojo)", Estado.PRECAUCION: "Precaución (amarillo)",
             Estado.DESCONOCIDO: "Sin datos (gris)", None: "Solo informa"}


def _log(datos):
    return datos["nvme_smart_health_information_log"]


def _reglas(informe):
    return [d.regla for d in informe.disparos if d.regla]


# --- la tabla ---


def test_ids_unicos_y_toda_regla_con_fuente_o_sin_fuente():
    assert len(POR_ID) == len(REGLAS)
    for regla in REGLAS:
        assert regla.fuente == SIN_FUENTE or len(regla.fuente) > 10, regla.id


def test_una_regla_sin_fuente_nunca_da_rojo():
    for regla in REGLAS:
        if regla.fuente == SIN_FUENTE:
            assert regla.resultado is not Estado.MALO, regla.id


def test_el_documento_tiene_cada_regla_tal_cual():
    for regla in REGLAS:
        fila = f"| {regla.id} | {regla.condicion} | {RESULTADO[regla.resultado]} | {regla.fuente} |"
        assert fila in DOC, regla.id


def test_toda_regla_de_la_tabla_se_evalua():
    """La tabla es la única fuente: cada regla que da color aparece en el análisis."""
    codigo = (RAIZ / "latido" / "salud" / "analisis.py").read_text(encoding="utf-8")
    codigo += (RAIZ / "latido" / "salud" / "reglas.py").read_text(encoding="utf-8").split("REGLA_ADVERTENCIA")[1]
    for regla in REGLAS:
        if regla.resultado is not None:
            assert f'"{regla.id}"' in codigo, regla.id


# --- una prueba por regla ---


CASOS = [
    ("SMART-PREFALLA", lambda d: d["smartctl"].update(exit_status=16), Estado.MALO),
    ("SMART-UMBRAL-PASADO", lambda d: d["smartctl"].update(exit_status=32), Estado.PRECAUCION),
    ("SMART-REGISTRO-ERRORES", lambda d: d["smartctl"].update(exit_status=64), Estado.PRECAUCION),
    ("SMART-AUTODIAGNOSTICO", lambda d: d["smartctl"].update(exit_status=128), Estado.PRECAUCION),
    ("SMART-SIN-DATOS", lambda d: d["smartctl"].update(exit_status=2), Estado.DESCONOCIDO),
    ("SMART-INCOMPLETO", lambda d: d["smartctl"].update(exit_status=4), Estado.DESCONOCIDO),
    ("NVME-FALLA-SIN-DETALLE", lambda d: (_log(d).pop("critical_warning"), d["smart_status"].update(passed=False)),
     Estado.MALO),
    ("NVME-CONTRADICCION", lambda d: d["smart_status"].update(passed=False), Estado.MALO),
    ("NVME-AC-RESERVA", lambda d: _log(d).update(critical_warning=0b1), Estado.MALO),
    ("NVME-AC-TEMPERATURA", lambda d: _log(d).update(critical_warning=0b10), Estado.PRECAUCION),
    ("NVME-AC-CONFIABILIDAD", lambda d: _log(d).update(critical_warning=0b100), Estado.MALO),
    ("NVME-AC-SOLO-LECTURA", lambda d: _log(d).update(critical_warning=0b1000), Estado.MALO),
    ("NVME-AC-RESPALDO", lambda d: _log(d).update(critical_warning=0b1_0000), Estado.MALO),
    ("NVME-AC-PMR", lambda d: _log(d).update(critical_warning=0b10_0000), Estado.MALO),
    ("NVME-AC-RESERVADO", lambda d: _log(d).update(critical_warning=0b100_0000), Estado.PRECAUCION),
    ("NVME-RESERVA", lambda d: _log(d).update(available_spare=9), Estado.MALO),
    ("NVME-USO-100", lambda d: _log(d).update(percentage_used=100), Estado.PRECAUCION),
    ("LATIDO-VIDA", lambda d: _log(d).update(percentage_used=90), Estado.PRECAUCION),
    ("NVME-TEMP-ADVERTENCIA", lambda d: _log(d).update(temperature=80), Estado.PRECAUCION),
    ("NVME-TEMP-CRITICA", lambda d: _log(d).update(temperature=85), Estado.MALO),
    ("NVME-ERRORES-MEDIO", lambda d: _log(d).update(media_errors=1), Estado.PRECAUCION),
    ("NVME-TIEMPO-CRITICO", lambda d: _log(d).update(critical_comp_time=1), Estado.PRECAUCION),
    ("FALTAN-DATOS", lambda d: _log(d).pop("media_errors"), Estado.DESCONOCIDO),
    ("TIPO-SIN-ANALISIS", lambda d: d["device"].update(protocol="ATA"), Estado.DESCONOCIDO),
]


def test_hay_un_caso_por_cada_regla_que_da_color():
    con_caso = {regla for regla, _, _ in CASOS} | {"SALIDA-INVALIDA"}
    assert con_caso == {r.id for r in REGLAS if r.resultado is not None}


@pytest.mark.parametrize("regla, cambiar, estado", CASOS, ids=[c[0] for c in CASOS])
def test_cada_regla(base_sintetica, regla, cambiar, estado):
    """base_sintetica es BUENO (umbrales de temperatura 80 y 85 °C, repuesto 100 % con umbral 10 %)."""
    assert analizar(base_sintetica).estado is Estado.BUENO
    cambiar(base_sintetica)
    informe = analizar(base_sintetica)
    assert regla in _reglas(informe)
    assert informe.estado is estado
    assert POR_ID[regla].resultado is estado


def test_salida_invalida():
    informe = analizar(None)
    assert _reglas(informe) == ["SALIDA-INVALIDA"] and informe.estado is Estado.DESCONOCIDO


@pytest.mark.parametrize("cambios, no_dispara", [
    ({"available_spare": 10}, "NVME-RESERVA"),  # igual al umbral: no está «por debajo»
    ({"percentage_used": 89}, "LATIDO-VIDA"),
    ({"percentage_used": 99}, "NVME-USO-100"),
    ({"temperature": 79}, "NVME-TEMP-ADVERTENCIA"),
    ({"temperature": 84}, "NVME-TEMP-CRITICA"),
])
def test_bordes_que_no_disparan(base_sintetica, cambios, no_dispara):
    _log(base_sintetica).update(cambios)
    assert no_dispara not in _reglas(analizar(base_sintetica))


def test_temperatura_critica_no_repite_la_advertencia(base_sintetica):
    _log(base_sintetica)["temperature"] = 90
    assert _reglas(analizar(base_sintetica)) == ["NVME-TEMP-CRITICA"]


def test_sin_umbrales_del_disco_la_temperatura_no_juzga(base_sintetica):
    _log(base_sintetica)["temperature"] = 120
    base_sintetica["temperature"].update(op_limit_max=0, critical_limit_max=0)
    base_sintetica.pop("nvme_composite_temperature_threshold", None)
    assert analizar(base_sintetica).estado is Estado.BUENO


def test_apagados_inseguros_solo_informan(base_sintetica):
    _log(base_sintetica)["unsafe_shutdowns"] = 10**6
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.BUENO and "NVME-APAGADOS-INSEGUROS" not in _reglas(informe)


# --- combinaciones: gana el peor color ---


def test_rojo_gana_a_amarillo_y_se_ven_las_dos_razones(base_sintetica):
    _log(base_sintetica).update(temperature=86, media_errors=2)
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.MALO
    assert _reglas(informe) == ["NVME-TEMP-CRITICA", "NVME-ERRORES-MEDIO"]


def test_amarillo_gana_a_gris(base_sintetica):
    _log(base_sintetica).update(media_errors=2)
    _log(base_sintetica).pop("percentage_used")
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.PRECAUCION
    assert _reglas(informe) == ["NVME-ERRORES-MEDIO", "FALTAN-DATOS"]


def test_rojo_con_fuente_y_amarillo_sin_fuente(base_sintetica):
    _log(base_sintetica).update(available_spare=5, percentage_used=95)
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.MALO
    assert _reglas(informe) == ["NVME-RESERVA", "LATIDO-VIDA"]


# --- autenticidad ---


def test_solo_las_cuatro_etiquetas():
    assert aut.ETIQUETAS == ("Sin señales de falsificación", "Sospechoso", "Falso o manipulado", "No concluyente")


def test_nvme_real_es_no_concluyente():
    """El disco real de desarrollo: smartctl y el kernel (lsblk) dicen 1,000,204,886,016 bytes."""
    resultado = aut.evaluar_autenticidad(analizar(cargar("nvme_real.json")), 1000204886016)
    assert resultado.etiqueta == "No concluyente"
    assert resultado.porque == [
        "La capacidad coincide en smartctl y en el kernel: 1.00 TB (1,000,204,886,016 bytes).",
        "Latido aún no verifica la capacidad real.",
    ]
    assert "Una prueba de velocidad sola no prueba la autenticidad." in resultado.no_comprobado


def test_contradiccion_dura_entre_dos_fuentes_es_falso():
    resultado = aut.evaluar_autenticidad(analizar(cargar("nvme_real.json")), 2 * 10**12)
    assert resultado.etiqueta == "Falso o manipulado"
    assert "dos fuentes del propio sistema no coinciden" in resultado.porque[0]


def test_sin_saber_los_espacios_de_nombres_no_se_compara():
    informe = analizar(cargar("sintetico_malo.json"))  # no trae nvme_number_of_namespaces
    resultado = aut.evaluar_autenticidad(informe, 1)
    assert resultado.etiqueta == "No concluyente"
    assert resultado.porque == ["Latido aún no verifica la capacidad real."]


@pytest.mark.parametrize("archivo", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_sin_f3_nunca_sin_senales_de_falsificacion(archivo):
    informe = analizar(cargar(archivo))
    for tamano in (None, informe.capacidad, 1):
        assert aut.evaluar_autenticidad(informe, tamano).etiqueta in ("No concluyente", "Falso o manipulado")


def test_la_autenticidad_no_cambia_el_color_de_salud():
    informe = analizar(cargar("nvme_real.json"))
    aut.evaluar_autenticidad(informe, 1)
    assert informe.estado is Estado.BUENO


def test_los_textos_de_la_tabla_no_usan_palabras_prohibidas():
    textos = " ".join(f"{r.condicion} {r.fuente}" for r in REGLAS) + " " + " ".join(aut.ETIQUETAS + aut.NO_COMPROBADO)
    assert not re.search(r"(?i)\b(original|genuino)", textos)
