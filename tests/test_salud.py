"""Lógica de salud: parser NVMe, máscara de bits, cálculos y estados."""

import pytest

from conftest import cargar
from latido.salud import Estado, InformeSalud, analizar, explicaciones, formato
from latido.salud.analisis import leer_entero
from latido.salud.salida_smartctl import bits_activos, combinar_codigos


def _log(datos):
    return datos["nvme_smart_health_information_log"]


# --- Fixtures reales ---------------------------------------------------------
# Los valores esperados están copiados de tests/fixtures/smartctl/nvme_real.json.

def test_nvme_real_valores(nvme_real):
    informe = analizar(nvme_real)
    assert informe.tipo == "nvme"
    assert informe.protocolo == "NVMe"
    assert informe.dispositivo == "/dev/nvme0"
    assert informe.modelo == "KINGSTON SNV2S1000G"
    assert informe.firmware == "SBI02105"
    assert informe.capacidad == 1000204886016
    assert informe.uso_pct == 1
    assert informe.vida_pct == 99
    assert informe.temperatura == 46
    assert informe.temperatura_advertencia == 83
    assert informe.temperatura_critica == 90
    assert informe.horas == 4921
    assert informe.ciclos == 934
    assert informe.errores_medio == 0
    assert informe.repuesto_pct == 100
    assert informe.repuesto_umbral_pct == 10
    assert informe.smartctl_exit == 0
    assert informe.atributos_ata == []


def test_nvme_real_terabytes(nvme_real):
    informe = analizar(nvme_real)
    # data_units × 512 000 / 10^12, con los data_units del fixture.
    assert informe.tb_escritos == 25537435 * 512000 / 10**12
    assert informe.tb_leidos == 32418229 * 512000 / 10**12
    assert formato.terabytes(informe.tb_escritos) == "13.08 TB"
    assert formato.terabytes(informe.tb_leidos) == "16.60 TB"


def test_nvme_real_es_bueno(nvme_real):
    informe = analizar(nvme_real)
    assert informe.estado is Estado.BUENO
    assert "El disco no reporta advertencias críticas." in informe.motivos


def test_nvme_real_registro_completo_y_explicado(nvme_real):
    informe = analizar(nvme_real)
    claves = [fila.clave for fila in informe.registro_nvme]
    assert claves == list(_log(nvme_real).keys())
    for fila in informe.registro_nvme:
        assert fila.clave in explicaciones.CAMPOS, fila.clave
        assert fila.explicacion and fila.explicacion != explicaciones.SIN_EXPLICACION
        assert fila.texto


def test_nvme_sin_root_es_desconocido():
    informe = analizar(cargar("nvme_sin_root.json"))
    assert informe.estado is Estado.DESCONOCIDO
    assert informe.smartctl_exit == 2
    assert any("bit 1" in m for m in informe.motivos)
    assert any("Permission denied" in m for m in informe.motivos)
    for campo in ("vida_pct", "temperatura", "horas", "ciclos", "tb_escritos", "tb_leidos",
                  "errores_medio", "repuesto_pct", "modelo"):
        assert getattr(informe, campo) is None, campo
    assert informe.registro_nvme == []


# --- Fixtures sintéticos (inventados: no prueban hardware real) --------------

@pytest.mark.parametrize("nombre, estado", [
    ("sintetico_precaucion.json", Estado.PRECAUCION),
    ("sintetico_malo.json", Estado.MALO),
    ("sintetico_desconocido.json", Estado.DESCONOCIDO),
])
def test_fixtures_sinteticos(nombre, estado):
    assert analizar(cargar(nombre)).estado is estado


def test_sintetico_precaucion_uso_mayor_a_100():
    informe = analizar(cargar("sintetico_precaucion.json"))
    assert informe.uso_pct == 112  # se conserva el valor real
    assert informe.vida_pct == 0
    assert informe.errores_medio == 7


# --- Máscara de bits del código de salida -----------------------------------

def test_bits_activos():
    assert bits_activos(0) == []
    assert bits_activos(2) == [1]
    assert bits_activos(0b1100_0101) == [0, 2, 6, 7]


def test_combinar_codigos():
    assert combinar_codigos(0, 0) == (0, [])
    assert combinar_codigos(4, None) == (4, [])
    assert combinar_codigos(None, 64) == (64, [])
    mascara, avisos = combinar_codigos(0, 64)
    assert mascara == 64 and "no coincide" in avisos[0]
    assert combinar_codigos(None, None)[0] is None
    assert combinar_codigos(0, -9)[0] is None  # terminó por una señal
    assert combinar_codigos(True, 0)[0] is None
    assert combinar_codigos(256, 0)[0] is None


@pytest.mark.parametrize("bit", [0, 1])
def test_bits_0_y_1_invalidan_aunque_los_datos_parezcan_buenos(base_sintetica, bit):
    base_sintetica["smartctl"]["exit_status"] = 1 << bit
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.DESCONOCIDO
    assert informe.vida_pct is None  # no se usan datos inválidos


def test_codigo_del_proceso_tambien_cuenta(base_sintetica):
    assert analizar(base_sintetica, codigo_proceso=2).estado is Estado.DESCONOCIDO
    assert analizar(base_sintetica, codigo_proceso=0).estado is Estado.BUENO


def test_bit_2_impide_bueno(base_sintetica):
    base_sintetica["smartctl"]["exit_status"] = 4
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.DESCONOCIDO
    assert informe.vida_pct == 97  # los datos sí se leen
    assert any("bit 2" in m for m in informe.motivos)


@pytest.mark.parametrize("bit, estado", [
    (4, Estado.MALO),
    (5, Estado.PRECAUCION),
    (6, Estado.PRECAUCION),
    (7, Estado.PRECAUCION),
])
def test_bits_4_a_7_alimentan_el_diagnostico(base_sintetica, bit, estado):
    base_sintetica["smartctl"]["exit_status"] = 1 << bit
    informe = analizar(base_sintetica)
    assert informe.estado is estado
    assert informe.vida_pct == 97  # no invalidan los datos


# --- critical_warning y smart_status ----------------------------------------

def test_solo_bit_de_temperatura_es_precaucion(base_sintetica):
    _log(base_sintetica)["critical_warning"] = 0b10
    base_sintetica["smart_status"]["passed"] = False
    base_sintetica["smartctl"]["exit_status"] = 8  # smartctl lo marca como falla
    assert analizar(base_sintetica).estado is Estado.PRECAUCION


@pytest.mark.parametrize("valor", [0b1, 0b100, 0b1000, 0b1_0000, 0b10_0000, 0b100_0000, 0b110])
def test_cualquier_otro_bit_de_critical_warning_es_malo(base_sintetica, valor):
    _log(base_sintetica)["critical_warning"] = valor
    assert analizar(base_sintetica).estado is Estado.MALO


def test_sin_critical_warning_y_smart_fallido_es_malo(base_sintetica):
    del _log(base_sintetica)["critical_warning"]
    base_sintetica["smart_status"]["passed"] = False
    assert analizar(base_sintetica).estado is Estado.MALO


def test_sin_critical_warning_y_smart_aprobado_es_desconocido(base_sintetica):
    del _log(base_sintetica)["critical_warning"]
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.DESCONOCIDO
    assert any("critical_warning" in m for m in informe.motivos)


def test_critical_warning_0_pero_smartctl_dice_falla_es_malo(base_sintetica):
    base_sintetica["smart_status"]["passed"] = False
    assert analizar(base_sintetica).estado is Estado.MALO


# --- Umbrales de precaución --------------------------------------------------

def test_errores_de_medio_es_precaucion(base_sintetica):
    _log(base_sintetica)["media_errors"] = 1
    assert analizar(base_sintetica).estado is Estado.PRECAUCION


@pytest.mark.parametrize("repuesto, estado", [(10, Estado.PRECAUCION), (9, Estado.PRECAUCION), (11, Estado.BUENO)])
def test_repuesto_en_o_bajo_umbral(base_sintetica, repuesto, estado):
    _log(base_sintetica)["available_spare"] = repuesto
    assert analizar(base_sintetica).estado is estado


@pytest.mark.parametrize("uso, vida, estado", [(89, 11, Estado.BUENO), (90, 10, Estado.PRECAUCION), (150, 0, Estado.PRECAUCION)])
def test_vida(base_sintetica, uso, vida, estado):
    _log(base_sintetica)["percentage_used"] = uso
    informe = analizar(base_sintetica)
    assert (informe.uso_pct, informe.vida_pct, informe.estado) == (uso, vida, estado)


def test_malo_gana_a_precaucion_y_muestra_todos_los_motivos(base_sintetica):
    _log(base_sintetica).update(critical_warning=0b1000, media_errors=3)
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.MALO
    assert any("solo lectura" in m for m in informe.motivos)
    assert any("errores de medio" in m for m in informe.motivos)


# --- Campos ausentes y DESCONOCIDO por omisión -------------------------------

def test_informe_vacio_es_desconocido():
    assert InformeSalud().estado is Estado.DESCONOCIDO


@pytest.mark.parametrize("datos", [None, {}, [], "texto"])
def test_datos_vacios_o_invalidos_son_desconocido(datos):
    assert analizar(datos).estado is Estado.DESCONOCIDO


def test_salida_invalida_es_desconocido(nvme_real):
    informe = analizar(nvme_real, codigo_proceso=0, salida_invalida=True)
    assert informe.estado is Estado.DESCONOCIDO
    assert any("JSON válido" in m for m in informe.motivos)


def test_sin_registro_de_salud_es_desconocido_y_todo_none(nvme_real):
    del nvme_real["nvme_smart_health_information_log"]
    for clave in ("temperature", "power_on_time", "power_cycle_count", "nvme_composite_temperature_threshold"):
        del nvme_real[clave]
    informe = analizar(nvme_real)
    assert informe.estado is Estado.DESCONOCIDO
    for campo in ("vida_pct", "uso_pct", "temperatura", "temperatura_advertencia", "horas", "ciclos",
                  "tb_escritos", "tb_leidos", "errores_medio", "repuesto_pct"):
        assert getattr(informe, campo) is None, campo


@pytest.mark.parametrize("clave", ["media_errors", "percentage_used", "available_spare", "available_spare_threshold"])
def test_falta_un_dato_clave_es_desconocido(base_sintetica, clave):
    del _log(base_sintetica)[clave]
    assert analizar(base_sintetica).estado is Estado.DESCONOCIDO


def test_ata_todavia_no_se_analiza(nvme_real):
    nvme_real["device"]["protocol"] = "ATA"
    informe = analizar(nvme_real)
    assert informe.tipo == "ata"
    assert informe.estado is Estado.DESCONOCIDO
    assert informe.atributos_ata == []


def test_no_disponible_nunca_cero():
    assert formato.entero(None) == "No disponible"
    assert formato.porcentaje(None) == "No disponible"
    assert formato.temperatura(None) == "No disponible"
    assert formato.terabytes(None) == "No disponible"
    assert formato.entero(0) == "0"


# --- Números grandes ---------------------------------------------------------

def test_variante_s_tiene_prioridad():
    grande = 2**60 + 1
    assert leer_entero({"x": 2**60, "x_s": str(grande)}, "x") == grande
    assert leer_entero({"x": 5}, "x") == 5
    assert leer_entero({"x": True}, "x") is None
    assert leer_entero({"x": "5"}, "x") is None
    assert leer_entero({"x": 5, "x_s": "no-numero"}, "x") == 5


def test_tb_con_variante_s(base_sintetica):
    _log(base_sintetica)["data_units_written_s"] = "20000000000000000000"
    informe = analizar(base_sintetica)
    assert informe.tb_escritos == 20000000000000000000 * 512000 / 10**12
    assert "data_units_written_s" not in [f.clave for f in informe.registro_nvme]


# --- Fase 1: critical_comp_time y datos solo informativos -------------------

@pytest.mark.parametrize("nombre, estado", [
    ("sintetico_temp_critica.json", Estado.PRECAUCION),
    ("sintetico_precaucion_combinada.json", Estado.PRECAUCION),
    ("sintetico_malo_combinado.json", Estado.MALO),
    ("sintetico_solo_informativo.json", Estado.BUENO),
])
def test_fixtures_sinteticos_fase_1(nombre, estado):
    assert analizar(cargar(nombre)).estado is estado


def test_critical_comp_time_mayor_que_cero_es_precaucion(base_sintetica):
    _log(base_sintetica)["critical_comp_time"] = 1
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.PRECAUCION
    assert "El disco pasó 1 minutos en o por encima de su temperatura crítica." in informe.motivos


def test_critical_comp_time_cero_no_cambia_nada(base_sintetica):
    _log(base_sintetica)["critical_comp_time"] = 0
    assert analizar(base_sintetica).estado is Estado.BUENO


def test_critical_comp_time_ausente_no_cambia_nada(base_sintetica):
    del _log(base_sintetica)["critical_comp_time"]
    assert analizar(base_sintetica).estado is Estado.BUENO


def test_critical_comp_time_con_variante_s(base_sintetica):
    _log(base_sintetica)["critical_comp_time_s"] = "9007199254740993"
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.PRECAUCION
    assert any("9,007,199,254,740,993 minutos" in m for m in informe.motivos)


@pytest.mark.parametrize("cambios", [
    {"warning_temp_time": 5000},
    {"unsafe_shutdowns": 10**6},
    {"num_err_log_entries": 4321},
    {"temperature": 120},
])
def test_datos_que_solo_se_muestran(base_sintetica, cambios):
    _log(base_sintetica).update(cambios)
    base_sintetica["temperature"]["current"] = _log(base_sintetica)["temperature"]
    assert analizar(base_sintetica).estado is Estado.BUENO


def test_precaucion_combinada_lista_todos_los_motivos():
    motivos = analizar(cargar("sintetico_precaucion_combinada.json")).motivos
    assert len(motivos) == 5
    assert any("temperatura salió del rango" in m for m in motivos)
    assert any("temperatura crítica" in m for m in motivos)


def test_malo_combinado_conserva_las_precauciones():
    informe = analizar(cargar("sintetico_malo_combinado.json"))
    assert informe.estado is Estado.MALO
    assert any("solo lectura" in m for m in informe.motivos)
    assert any("12 minutos" in m for m in informe.motivos)
    assert any("errores de medio" in m for m in informe.motivos)


def test_explicacion_de_critical_comp_time_en_minutos(base_sintetica):
    _log(base_sintetica)["critical_comp_time"] = 7
    fila = next(f for f in analizar(base_sintetica).registro_nvme if f.clave == "critical_comp_time")
    assert fila.texto == "7 min"
    assert "Minutos" in fila.explicacion
