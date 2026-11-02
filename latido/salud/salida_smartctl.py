"""Código de salida de smartctl como máscara de bits (man smartctl, EXIT STATUS)."""

DESCRIPCION_BITS = {
    0: "La línea de órdenes de smartctl no se pudo interpretar.",
    1: "No se pudo abrir el disco, el disco no devolvió su identificación o está en modo de bajo consumo.",
    2: "Falló alguna orden SMART u otra orden al disco, o hubo un error de suma de verificación en los datos SMART.",
    3: "La comprobación de estado SMART devolvió «EL DISCO ESTÁ FALLANDO».",
    4: "Hay atributos de prefalla en o por debajo de su umbral.",
    5: "Algún atributo estuvo en o por debajo de su umbral en el pasado, aunque el estado actual es correcto.",
    6: "El registro de errores del disco contiene entradas.",
    7: "El registro de autodiagnósticos del disco contiene errores.",
}

# Bits 0 y 1: no hay datos válidos. Los bits 3 a 7 no invalidan los datos.
BITS_SIN_DATOS = 0b0000_0011
BIT_ORDEN_FALLIDA = 0b0000_0100
BIT_DISCO_FALLANDO = 0b0000_1000
BIT_PREFALLA = 0b0001_0000
BIT_UMBRAL_PASADO = 0b0010_0000
BIT_REGISTRO_ERRORES = 0b0100_0000
BIT_AUTODIAGNOSTICO = 0b1000_0000


def bits_activos(mascara):
    return [bit for bit in range(8) if mascara >> bit & 1]


def describir_bit(bit):
    return f"smartctl (bit {bit}): {DESCRIPCION_BITS[bit]}"


def _es_codigo(valor):
    return isinstance(valor, int) and not isinstance(valor, bool) and 0 <= valor <= 255


def combinar_codigos(codigo_json, codigo_proceso):
    """Combina smartctl.exit_status del JSON y el código del proceso.

    Devuelve (mascara, avisos). mascara es None cuando no hay un código
    utilizable o alguno de los dos no es válido (por ejemplo, smartctl
    terminó por una señal): en ese caso no se puede confiar en los datos.
    """
    avisos = []
    validos = []
    for origen, codigo in (("del JSON", codigo_json), ("del proceso", codigo_proceso)):
        if codigo is None:
            continue
        if not _es_codigo(codigo):
            if isinstance(codigo, int) and not isinstance(codigo, bool) and codigo < 0:
                avisos.append(f"smartctl terminó por una señal ({-codigo}); los datos no son confiables.")
            else:
                avisos.append(f"El código de salida {origen} de smartctl no es válido ({codigo!r}).")
            return None, avisos
        validos.append(codigo)

    if not validos:
        return None, ["No se conoce el código de salida de smartctl."]

    mascara = 0
    for codigo in validos:
        mascara |= codigo
    if len(validos) == 2 and validos[0] != validos[1]:
        avisos.append(
            f"El código de salida del proceso ({codigo_proceso}) no coincide con el del JSON "
            f"({codigo_json}); se toman en cuenta los dos."
        )
    return mascara, avisos
