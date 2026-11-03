"""Convierte el JSON de smartctl en un InformeSalud con estado y motivos.

Reglas documentadas en docs/reglas-salud.md. Ante la duda, DESCONOCIDO:
nunca BUENO por omisión.
"""

import re

from latido.salud import explicaciones, formato, reglas
from latido.salud.modelo import AtributoAta, Disparo, Estado, FilaRegistro, InformeSalud
from latido.salud.salida_smartctl import (
    BIT_AUTODIAGNOSTICO,
    BIT_DISCO_FALLANDO,
    BIT_ORDEN_FALLIDA,
    BIT_PREFALLA,
    BIT_REGISTRO_ERRORES,
    BIT_UMBRAL_PASADO,
    BITS_SIN_DATOS,
    bits_activos,
    combinar_codigos,
    describir_bit,
)

_DIGITOS = re.compile(r"[0-9]+")


def _dict(valor):
    return valor if isinstance(valor, dict) else {}


def leer_entero(datos, clave):
    """Entero de datos[clave]; si existe la variante clave_s (texto), la usa."""
    datos = _dict(datos)
    texto = datos.get(f"{clave}_s")
    if isinstance(texto, str) and _DIGITOS.fullmatch(texto):
        return int(texto)
    valor = datos.get(clave)
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    return None


def _primero(*valores):
    for valor in valores:
        if valor is not None:
            return valor
    return None


def _texto(valor):
    return valor if isinstance(valor, str) and valor else None


def _mensajes_smartctl(datos):
    mensajes = []
    for mensaje in _dict(datos.get("smartctl")).get("messages") or []:
        texto = _texto(_dict(mensaje).get("string"))
        if texto:
            mensajes.append(f"Mensaje de smartctl, tal cual (en inglés): «{texto}»")
    return mensajes


def _disparo(regla_id, motivo):
    regla = reglas.POR_ID[regla_id]
    return Disparo(regla.id, regla.resultado, motivo, regla.cifra)


def _info(motivo):
    """Línea solo informativa: no viene de una regla y no da color."""
    return Disparo(None, None, motivo)


def _bien(motivo):
    return Disparo(None, Estado.BUENO, motivo)


def _clasificar(disparo, malos, precauciones):
    """El peor color gana: cada disparo va a su lista según el resultado de su regla."""
    (malos if disparo.estado is Estado.MALO else precauciones).append(disparo)


def _registrar(informe, disparos):
    informe.disparos.extend(disparos)
    informe.motivos.extend(disparo.motivo for disparo in disparos)


def analizar(datos, codigo_proceso=None, salida_invalida=False):
    """Analiza la salida JSON de smartctl.

    datos: el JSON ya cargado (dict) o None.
    codigo_proceso: código de salida del proceso smartctl, si se conoce.
    salida_invalida: True si smartctl no devolvió JSON válido.
    """
    informe = InformeSalud()

    if salida_invalida or not isinstance(datos, dict):
        if isinstance(codigo_proceso, int):
            informe.smartctl_exit = codigo_proceso
        _registrar(informe, [_disparo(
            "SALIDA-INVALIDA", "smartctl respondió, pero su salida no es JSON válido. No se puede saber el estado."
        )])
        return informe

    _leer_datos_generales(informe, datos)

    codigo_json = _dict(datos.get("smartctl")).get("exit_status")
    mascara, avisos = combinar_codigos(codigo_json, codigo_proceso)
    informe.smartctl_exit = mascara
    if mascara is None:
        _registrar(informe, [_info(aviso) for aviso in avisos])
        _registrar(informe, [_disparo("SALIDA-INVALIDA", "No se puede saber el estado.")])
        return informe

    if mascara & BITS_SIN_DATOS:
        disparos = [_disparo("SMART-SIN-DATOS", describir_bit(b)) for b in bits_activos(mascara & BITS_SIN_DATOS)]
        disparos.append(_disparo("SMART-SIN-DATOS", "smartctl no obtuvo datos válidos. No se puede saber el estado."))
        disparos.extend(_info(mensaje) for mensaje in _mensajes_smartctl(datos))
        disparos.extend(_info(aviso) for aviso in avisos)
        _registrar(informe, disparos)
        return informe

    if informe.tipo == "nvme":
        _leer_nvme(informe, datos)
        _diagnosticar_nvme(informe, datos, mascara)
    else:
        _leer_ata(informe, datos)
        nombre = informe.protocolo or "desconocido"
        _registrar(informe, [_disparo(
            "TIPO-SIN-ANALISIS", f"Latido todavía no analiza discos de tipo {nombre}. No se puede saber el estado."
        )])
    _registrar(informe, [_info(aviso) for aviso in avisos])
    return informe


def _leer_datos_generales(informe, datos):
    dispositivo = _dict(datos.get("device"))
    informe.dispositivo = _texto(dispositivo.get("name"))
    informe.protocolo = _texto(dispositivo.get("protocol"))
    informe.tipo = {"NVMe": "nvme", "ATA": "ata"}.get(informe.protocolo)
    informe.modelo = _texto(datos.get("model_name"))
    informe.numero_serie = _texto(datos.get("serial_number"))
    informe.firmware = _texto(datos.get("firmware_version"))
    informe.capacidad = leer_entero(datos.get("user_capacity"), "bytes")


def _leer_nvme(informe, datos):
    registro = _dict(datos.get("nvme_smart_health_information_log"))

    informe.uso_pct = leer_entero(registro, "percentage_used")
    if informe.uso_pct is not None:
        informe.vida_pct = max(0, 100 - informe.uso_pct)

    temperatura = _dict(datos.get("temperature"))
    umbrales = _dict(datos.get("nvme_composite_temperature_threshold"))
    informe.temperatura = _primero(leer_entero(registro, "temperature"), leer_entero(temperatura, "current"))
    informe.temperatura_advertencia = _primero(
        leer_entero(umbrales, "warning"), leer_entero(temperatura, "op_limit_max")
    )
    informe.temperatura_critica = _primero(
        leer_entero(umbrales, "critical"), leer_entero(temperatura, "critical_limit_max")
    )

    informe.horas = _primero(
        leer_entero(registro, "power_on_hours"), leer_entero(datos.get("power_on_time"), "hours")
    )
    informe.ciclos = _primero(leer_entero(registro, "power_cycles"), leer_entero(datos, "power_cycle_count"))

    escritos = leer_entero(registro, "data_units_written")
    leidos = leer_entero(registro, "data_units_read")
    informe.tb_escritos = None if escritos is None else formato.unidades_nvme_a_tb(escritos)
    informe.tb_leidos = None if leidos is None else formato.unidades_nvme_a_tb(leidos)

    informe.errores_medio = leer_entero(registro, "media_errors")
    informe.repuesto_pct = leer_entero(registro, "available_spare")
    informe.repuesto_umbral_pct = leer_entero(registro, "available_spare_threshold")

    informe.namespaces = leer_entero(datos, "nvme_number_of_namespaces")
    informe.registro_nvme = construir_registro(registro)


def _entero_o_none(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def _leer_ata(informe, datos):
    """La tabla de atributos ATA (id, nombre, valor, peor, umbral, crudo). Se muestra; no se analiza."""
    tabla = _dict(datos.get("ata_smart_attributes")).get("table")
    for fila in tabla if isinstance(tabla, list) else []:
        fila = _dict(fila)
        identificador = _entero_o_none(fila.get("id"))
        if identificador is None:
            continue
        crudo = _dict(fila.get("raw"))
        valor_crudo = _entero_o_none(crudo.get("value"))
        informe.atributos_ata.append(AtributoAta(
            id=identificador,
            nombre=_texto(fila.get("name")) or f"Atributo {identificador}",
            valor=_entero_o_none(fila.get("value")),
            peor=_entero_o_none(fila.get("worst")),
            umbral=_entero_o_none(fila.get("thresh")),
            crudo=_texto(crudo.get("string")) or (formato.NO_DISPONIBLE if valor_crudo is None else str(valor_crudo)),
        ))


def construir_registro(registro):
    filas = []
    for clave, valor in registro.items():
        if clave.endswith("_s") or clave.endswith("_le"):
            continue  # variantes de un número grande: se usan vía leer_entero
        if isinstance(valor, int) and not isinstance(valor, bool):
            valor = leer_entero(registro, clave)
        nombre, explicacion, formatear = explicaciones.CAMPOS.get(
            clave, (clave, explicaciones.SIN_EXPLICACION, str)
        )
        try:
            texto = formatear(valor)
        except (TypeError, ValueError):
            texto = str(valor)
        filas.append(FilaRegistro(clave, nombre, valor, texto, explicacion))
    return filas


def _diagnosticar_nvme(informe, datos, mascara):
    malos = []
    precauciones = []
    faltan = []

    registro = _dict(datos.get("nvme_smart_health_information_log"))
    advertencia = leer_entero(registro, "critical_warning")
    aprobado = _dict(datos.get("smart_status")).get("passed")
    smartctl_dice_falla = aprobado is False or bool(mascara & BIT_DISCO_FALLANDO)

    if advertencia is None:
        faltan.append("advertencia crítica (critical_warning)")
        if smartctl_dice_falla:
            malos.append(_disparo(
                "NVME-FALLA-SIN-DETALLE",
                "smartctl indica que el disco está fallando y no hay advertencia crítica que detalle el motivo.",
            ))
    else:
        for bit in bits_activos(advertencia):
            texto = explicaciones.BITS_ADVERTENCIA_CRITICA.get(bit, f"bit reservado {bit} activo")
            _clasificar(_disparo(reglas.REGLA_ADVERTENCIA_CRITICA.get(bit, "NVME-AC-RESERVADO"),
                                 f"Advertencia crítica del disco: {texto}."), malos, precauciones)
        if advertencia == 0 and smartctl_dice_falla:
            malos.append(_disparo(
                "NVME-CONTRADICCION",
                "smartctl indica que el disco está fallando, aunque la advertencia crítica es 0. "
                "Los datos se contradicen.",
            ))

    if mascara & BIT_PREFALLA:
        malos.append(_disparo("SMART-PREFALLA", describir_bit(4)))
    for bit_mascara, bit, regla in (
        (BIT_UMBRAL_PASADO, 5, "SMART-UMBRAL-PASADO"),
        (BIT_REGISTRO_ERRORES, 6, "SMART-REGISTRO-ERRORES"),
        (BIT_AUTODIAGNOSTICO, 7, "SMART-AUTODIAGNOSTICO"),
    ):
        if mascara & bit_mascara:
            precauciones.append(_disparo(regla, describir_bit(bit)))

    if informe.errores_medio is None:
        faltan.append("errores de medio")
    elif informe.errores_medio > 0:
        precauciones.append(_disparo(
            "NVME-ERRORES-MEDIO",
            f"El disco tiene {informe.errores_medio:,} errores de medio (datos que no pudo corregir).",
        ))

    if informe.repuesto_pct is None or informe.repuesto_umbral_pct is None:
        faltan.append("repuesto disponible y su umbral")
    elif informe.repuesto_pct < informe.repuesto_umbral_pct:
        _clasificar(_disparo(
            "NVME-RESERVA",
            f"El repuesto disponible ({informe.repuesto_pct} %) está por debajo de su umbral "
            f"({informe.repuesto_umbral_pct} %).",
        ), malos, precauciones)

    if informe.uso_pct is None:
        faltan.append("desgaste (percentage_used)")
    elif informe.uso_pct >= reglas.UMBRAL_USO_FUENTE:
        _clasificar(_disparo(
            "NVME-USO-100",
            f"El disco estima que ya usó el {informe.uso_pct} % de su vida útil. "
            "Es una estimación del fabricante, no una falla.",
        ), malos, precauciones)
    elif informe.uso_pct >= reglas.UMBRAL_USO_SIN_FUENTE:
        _clasificar(_disparo(
            "LATIDO-VIDA", f"Queda {informe.vida_pct} % de vida estimada (desgaste: {informe.uso_pct} %)."
        ), malos, precauciones)

    # Temperatura compuesta contra los umbrales que reporta el propio disco (WCTEMP y CCTEMP). Un umbral 0
    # quiere decir que el disco no lo informa. Si falta, no cambia el estado.
    temperatura = informe.temperatura
    if temperatura is not None and informe.temperatura_critica and temperatura >= informe.temperatura_critica:
        _clasificar(_disparo(
            "NVME-TEMP-CRITICA",
            f"La temperatura ({temperatura} °C) llegó al umbral crítico del propio disco "
            f"({informe.temperatura_critica} °C).",
        ), malos, precauciones)
    elif (temperatura is not None and informe.temperatura_advertencia
          and temperatura >= informe.temperatura_advertencia):
        _clasificar(_disparo(
            "NVME-TEMP-ADVERTENCIA",
            f"La temperatura ({temperatura} °C) llegó al umbral de advertencia del propio disco "
            f"({informe.temperatura_advertencia} °C).",
        ), malos, precauciones)

    # Unidad: minutos (NVMe Base Specification 2.0c, figura 207). No es un
    # dato obligatorio para BUENO: si falta, no cambia el estado.
    minutos_criticos = leer_entero(registro, "critical_comp_time")
    if minutos_criticos is not None and minutos_criticos > 0:
        precauciones.append(_disparo(
            "NVME-TIEMPO-CRITICO",
            f"El disco pasó {minutos_criticos:,} minutos en o por encima de su temperatura crítica.",
        ))

    incompleto = bool(mascara & BIT_ORDEN_FALLIDA)
    aviso_faltan = "Faltan datos: " + ", ".join(faltan) + "."

    if malos:
        informe.estado = Estado.MALO
        disparos = malos + precauciones
    elif precauciones:
        informe.estado = Estado.PRECAUCION
        disparos = precauciones
    elif faltan or incompleto:
        informe.estado = Estado.DESCONOCIDO
        disparos = [_disparo("FALTAN-DATOS", aviso_faltan)] if faltan else []
        disparos.append(_info("No hay datos suficientes para decir que el disco está bien."))
    else:
        informe.estado = Estado.BUENO
        disparos = [_bien(texto) for texto in (
            "El disco no reporta advertencias críticas.",
            "0 errores de medio.",
            f"Repuesto disponible: {informe.repuesto_pct} % (umbral {informe.repuesto_umbral_pct} %).",
            f"Vida estimada restante: {informe.vida_pct} %.",
        )]

    if faltan and informe.estado in (Estado.MALO, Estado.PRECAUCION):
        disparos.append(_disparo("FALTAN-DATOS", aviso_faltan))
    if incompleto:
        disparos.append(_disparo("SMART-INCOMPLETO", describir_bit(2) + " Los datos pueden estar incompletos."))
        disparos.extend(_info(mensaje) for mensaje in _mensajes_smartctl(datos))
    _registrar(informe, disparos)
