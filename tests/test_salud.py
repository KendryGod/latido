"""Lógica de salud: parser NVMe, máscara de bits, cálculos y estados."""

import pytest

from conftest import FIXTURES, cargar
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


@pytest.mark.parametrize("valor", [0b1, 0b100, 0b1000, 0b1_0000, 0b10_0000, 0b110])
def test_cualquier_otro_bit_de_critical_warning_es_malo(base_sintetica, valor):
    _log(base_sintetica)["critical_warning"] = valor
    assert analizar(base_sintetica).estado is Estado.MALO


@pytest.mark.parametrize("valor", [0b100_0000, 0b1000_0000])
def test_bits_reservados_de_critical_warning_son_precaucion_sin_fuente(base_sintetica, valor):
    """La especificación los marca «Reserved»: sin fuente, la regla no puede dar rojo (criterio de Latido)."""
    _log(base_sintetica)["critical_warning"] = valor
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.PRECAUCION
    assert [d.regla for d in informe.disparos] == ["NVME-AC-RESERVADO"]


def test_sin_critical_warning_y_smart_fallido_es_malo(base_sintetica):
    del _log(base_sintetica)["critical_warning"]
    base_sintetica["smart_status"]["passed"] = False
    assert analizar(base_sintetica).estado is Estado.MALO


def test_sin_critical_warning_y_smart_aprobado_es_desconocido(base_sintetica):
    del _log(base_sintetica)["critical_warning"]
    informe = analizar(base_sintetica)
    assert informe.estado is Estado.DESCONOCIDO
    assert any("Faltan datos: advertencia crítica" in m for m in informe.motivos)  # el nombre que se ve en «Todos los datos»


def test_critical_warning_0_pero_smartctl_dice_falla_es_malo(base_sintetica):
    base_sintetica["smart_status"]["passed"] = False
    assert analizar(base_sintetica).estado is Estado.MALO


# --- Umbrales de precaución --------------------------------------------------

def test_errores_de_medio_es_precaucion(base_sintetica):
    _log(base_sintetica)["media_errors"] = 1
    assert analizar(base_sintetica).estado is Estado.PRECAUCION


@pytest.mark.parametrize("repuesto, estado", [(10, Estado.BUENO), (9, Estado.MALO), (11, Estado.BUENO)])
def test_repuesto_bajo_umbral_es_malo(base_sintetica, repuesto, estado):
    """NVMe Base 2.0c, figura 207: el aviso es cuando el repuesto «has fallen below the threshold» (umbral 10)."""
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
])
def test_datos_que_solo_se_muestran(base_sintetica, cambios):
    _log(base_sintetica).update(cambios)
    base_sintetica["temperature"]["current"] = _log(base_sintetica)["temperature"]
    assert analizar(base_sintetica).estado is Estado.BUENO


def test_precaucion_combinada_lista_todos_los_motivos():
    motivos = analizar(cargar("sintetico_precaucion_combinada.json")).motivos
    assert len(motivos) == 4  # el repuesto 10 de 10 no está «por debajo» del umbral
    assert not any("repuesto" in m for m in motivos)
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


# --- Número de serie: solo en memoria y en pantalla --------------------------

SERIE_FALSA = "SINTETICO-0001-XYZ"


def test_numero_serie_se_lee_pero_no_sale_en_repr_ni_motivos(nvme_real):
    nvme_real["serial_number"] = SERIE_FALSA  # inyectado en memoria; nunca en un fixture
    informe = analizar(nvme_real)
    assert informe.numero_serie == SERIE_FALSA
    assert SERIE_FALSA not in repr(informe)
    assert SERIE_FALSA not in str(informe)
    assert not any(SERIE_FALSA in m for m in informe.motivos)
    assert not any(SERIE_FALSA in f.texto for f in informe.registro_nvme)


def test_numero_serie_ausente(nvme_real):
    assert analizar(nvme_real).numero_serie is None


# --- B3: reglas con identificador, cifras clave y tabla ATA ---


@pytest.mark.parametrize("archivo", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_cada_motivo_tiene_su_disparo_con_una_regla_de_la_tabla(archivo):
    from latido.salud.reglas import POR_ID
    from latido.sistema.lectura import cargar_fixture

    informe = cargar_fixture(FIXTURES / archivo)
    assert [d.motivo for d in informe.disparos] == informe.motivos
    for disparo in informe.disparos:
        if disparo.regla is not None:
            assert disparo.regla in POR_ID and disparo.estado is POR_ID[disparo.regla].resultado


def test_tabla_ata_de_sintetico_ata():
    """sintetico_ata.json es inventado: no se midió en hardware."""
    from latido.salud import AtributoAta
    from latido.sistema.lectura import cargar_fixture

    informe = cargar_fixture(FIXTURES / "sintetico_ata.json")
    assert informe.tipo == "ata" and informe.estado is Estado.DESCONOCIDO
    assert informe.atributos_ata[0] == AtributoAta(5, "Reallocated_Sector_Ct", 100, 100, 10, "0")
    assert informe.atributos_ata[3] == AtributoAta(194, "Temperature_Celsius", 64, 50, 0, "36 (Min/Max 20/50)")
    assert [d.regla for d in informe.disparos] == ["TIPO-SIN-ANALISIS"]


def test_cifras_informativas_nunca_tienen_color():
    from latido.salud.cifras import cifras_clave
    from latido.sistema.lectura import cargar_fixture

    for archivo in ("nvme_real.json", "sintetico_malo_combinado.json", "sintetico_solo_informativo.json"):
        for cifra in cifras_clave(cargar_fixture(FIXTURES / archivo)):
            if cifra.clave in ("horas", "escritos"):
                assert cifra.informativa and cifra.estado is None, (archivo, cifra)


def test_en_una_cifra_gana_el_peor_estado():
    from latido.salud import Disparo, InformeSalud
    from latido.salud.cifras import cifras_clave

    informe = InformeSalud(temperatura=95, errores_medio=0)
    informe.disparos = [Disparo("NVME-TIEMPO-CRITICO", Estado.PRECAUCION, "x", "temperatura"),
                        Disparo("NVME-AC-RESERVA", Estado.MALO, "y", "temperatura")]
    estados = {c.clave: c.estado for c in cifras_clave(informe)}
    assert estados["temperatura"] is Estado.MALO
    assert estados["errores"] is Estado.BUENO
    assert estados["vida"] is None  # sin dato


def _cifra_temperatura(informe):
    from latido.salud.cifras import cifras_clave

    return next(c for c in cifras_clave(informe) if c.clave == "temperatura")


def test_cifra_temperatura_fria_con_tiempo_critico_explica_el_historial():
    informe = analizar(cargar("sintetico_temp_critica.json"))
    reglas_temp = [d.regla for d in informe.disparos if d.cifra == "temperatura"]
    assert reglas_temp == ["NVME-TIEMPO-CRITICO"]
    cifra = _cifra_temperatura(informe)
    assert (cifra.valor, cifra.unidad, cifra.estado) == ("41", "°C", Estado.PRECAUCION)
    assert cifra.detalle == (
        "Umbrales del disco: advertencia 80 °C · crítica 85 °C. "
        "Pasó 37 min en o sobre el umbral crítico"
    )


@pytest.mark.parametrize("cambios, regla_actual, estado_esperado", [
    ({"temperature": 80}, "NVME-TEMP-ADVERTENCIA", Estado.PRECAUCION),
    ({"temperature": 85}, "NVME-TEMP-CRITICA", Estado.MALO),
    ({"critical_warning": 0b10}, "NVME-AC-TEMPERATURA", Estado.PRECAUCION),
])
def test_cifra_temperatura_caliente_ahora_y_con_tiempo_critico_muestra_ambos(
    base_sintetica, cambios, regla_actual, estado_esperado
):
    _log(base_sintetica).update(cambios)
    if "temperature" in cambios:
        base_sintetica["temperature"]["current"] = cambios["temperature"]
    estado_sin_historial = _cifra_temperatura(analizar(base_sintetica)).estado
    _log(base_sintetica)["critical_comp_time"] = 15
    informe = analizar(base_sintetica)
    reglas_temp = {d.regla for d in informe.disparos if d.cifra == "temperatura"}
    assert {regla_actual, "NVME-TIEMPO-CRITICO"} <= reglas_temp
    cifra = _cifra_temperatura(informe)
    assert cifra.estado is estado_esperado is estado_sin_historial
    assert cifra.detalle == (
        "Umbrales del disco: advertencia 80 °C · crítica 85 °C. "
        "Pasó 15 min en o sobre el umbral crítico"
    )


def test_cifra_temperatura_con_tiempo_critico_cero_o_ausente_no_agrega_frase(base_sintetica):
    from latido.salud import Disparo

    _log(base_sintetica)["critical_comp_time"] = 0
    cifra_cero = _cifra_temperatura(analizar(base_sintetica))
    assert cifra_cero.estado is Estado.BUENO
    assert cifra_cero.detalle == "Umbrales del disco: advertencia 80 °C · crítica 85 °C"

    del _log(base_sintetica)["critical_comp_time"]
    cifra_ausente = _cifra_temperatura(analizar(base_sintetica))
    assert cifra_ausente.estado is Estado.BUENO
    assert cifra_ausente.detalle == "Umbrales del disco: advertencia 80 °C · crítica 85 °C"

    _log(base_sintetica)["critical_comp_time"] = None
    cifra_none = _cifra_temperatura(analizar(base_sintetica))
    assert cifra_none.estado is Estado.BUENO
    assert cifra_none.detalle == "Umbrales del disco: advertencia 80 °C · crítica 85 °C"

    informe_cero = InformeSalud(
        temperatura=41,
        temperatura_advertencia=80,
        temperatura_critica=85,
        minutos_temperatura_critica=0,
        disparos=[Disparo("NVME-TIEMPO-CRITICO", Estado.PRECAUCION, "x", "temperatura")],
    )
    assert _cifra_temperatura(informe_cero).detalle == "Umbrales del disco: advertencia 80 °C · crítica 85 °C"


def test_cifra_temperatura_desconocida_con_tiempo_critico(base_sintetica):
    del _log(base_sintetica)["temperature"]
    del base_sintetica["temperature"]
    _log(base_sintetica)["critical_comp_time"] = 12
    cifra = _cifra_temperatura(analizar(base_sintetica))
    assert cifra.valor == "—"
    assert cifra.estado is None
    assert cifra.detalle == (
        "Umbrales del disco: advertencia 80 °C · crítica 85 °C. "
        "Pasó 12 min en o sobre el umbral crítico"
    )

    del base_sintetica["nvme_composite_temperature_threshold"]
    cifra_sin_umbrales = _cifra_temperatura(analizar(base_sintetica))
    assert cifra_sin_umbrales.valor == "—"
    assert cifra_sin_umbrales.estado is None
    assert cifra_sin_umbrales.detalle == "Pasó 12 min en o sobre el umbral crítico"


@pytest.mark.parametrize("minutos, texto_minutos", [(1, "1"), (1500, "1,500")])
def test_cifra_temperatura_formato_de_minutos_uno_y_miles(base_sintetica, minutos, texto_minutos):
    _log(base_sintetica)["critical_comp_time"] = minutos
    cifra = _cifra_temperatura(analizar(base_sintetica))
    assert cifra.estado is Estado.PRECAUCION
    assert cifra.detalle == (
        "Umbrales del disco: advertencia 80 °C · crítica 85 °C. "
        f"Pasó {texto_minutos} min en o sobre el umbral crítico"
    )


