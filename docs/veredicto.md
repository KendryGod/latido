# Veredicto de Latido

Latido da dos respuestas separadas:

1. **Salud**, con color: Bueno, Precaución, Peligro o Sin datos. Sale de la tabla de reglas de abajo
   (`latido/salud/reglas.py`).
2. **Autenticidad**, sin color: «Sin señales de falsificación», «Sospechoso», «Falso o manipulado» o «No
   concluyente». Nunca cambia el color de salud.

## Cómo se decide la salud

- Cada regla que se cumple sale en «Por qué», en español, con su fuente debajo.
- Gana el peor color: Peligro sobre Precaución, y Precaución sobre Sin datos.
- Bueno solo sale si no se disparó ninguna regla y están todos los datos obligatorios: `critical_warning`,
  `media_errors`, `available_spare`, `available_spare_threshold` y `percentage_used`.
- La FUENTE es la especificación NVMe, el manual de smartctl o un documento del fabricante, con su sección.
- Una regla **SIN FUENTE** es «criterio de Latido». Como mucho da amarillo, nunca rojo; una prueba lo
  comprueba. En la pantalla dice «Criterio de Latido (sin fuente)».
- Fuentes usadas:
  - *NVM Express Base Specification, Revision 2.0c* (4 de octubre de 2022), de nvmexpress.org;
  - `man smartctl` de smartmontools 7.5 (2025-04-30).

## Tabla de reglas

| ID | Condición | Resultado | FUENTE |
|----|-----------|-----------|--------|
| SALIDA-INVALIDA | smartctl no devolvió JSON válido, o su código de salida no es válido | Sin datos (gris) | SIN FUENTE |
| SMART-SIN-DATOS | smartctl no obtuvo datos válidos (bit 0 o 1 de su código de salida) | Sin datos (gris) | man smartctl, EXIT STATUS, bits 0 y 1 |
| SMART-INCOMPLETO | Falló alguna orden SMART (bit 2): los datos pueden estar incompletos | Sin datos (gris) | man smartctl, EXIT STATUS, bit 2 |
| FALTAN-DATOS | Falta algún dato obligatorio para opinar | Sin datos (gris) | SIN FUENTE |
| TIPO-SIN-ANALISIS | El disco no es NVMe: Latido todavía no lo analiza | Sin datos (gris) | SIN FUENTE |
| SMART-PREFALLA | Hay atributos de prefalla en o por debajo de su umbral (bit 4) | Peligro (rojo) | man smartctl, EXIT STATUS, bit 4, y opción -A: «Pre-failure Attributes … indicate pending disk failure» |
| SMART-UMBRAL-PASADO | Algún atributo estuvo en o por debajo de su umbral en el pasado (bit 5) | Precaución (amarillo) | SIN FUENTE |
| SMART-REGISTRO-ERRORES | El registro de errores del disco tiene entradas (bit 6) | Precaución (amarillo) | SIN FUENTE |
| SMART-AUTODIAGNOSTICO | El registro de autodiagnósticos tiene errores (bit 7) | Precaución (amarillo) | SIN FUENTE |
| NVME-FALLA-SIN-DETALLE | smartctl dice que el disco falla y no hay critical_warning | Peligro (rojo) | man smartctl, EXIT STATUS, bit 3: «SMART status check returned DISK FAILING» |
| NVME-CONTRADICCION | critical_warning es 0 pero smartctl dice que el disco falla | Peligro (rojo) | man smartctl, EXIT STATUS, bit 3: «SMART status check returned DISK FAILING» |
| NVME-AC-RESERVA | critical_warning, bit 0: el repuesto bajó de su umbral | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 0 |
| NVME-AC-TEMPERATURA | critical_warning, bit 1: la temperatura pasó su umbral (por defecto, WCTEMP) | Precaución (amarillo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 1; sección 5.27.1.3 (umbral por defecto = WCTEMP) |
| NVME-AC-CONFIABILIDAD | critical_warning, bit 2: la confiabilidad bajó | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 2 |
| NVME-AC-SOLO-LECTURA | critical_warning, bit 3: todo el medio pasó a solo lectura | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 3 |
| NVME-AC-RESPALDO | critical_warning, bit 4: falló el respaldo de la memoria volátil | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 4 |
| NVME-AC-PMR | critical_warning, bit 5: la memoria persistente quedó en solo lectura o no es confiable | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, byte 00, bit 5 |
| NVME-AC-RESERVADO | critical_warning, bit 6 o 7 (reservados) activo | Precaución (amarillo) | SIN FUENTE |
| NVME-RESERVA | available_spare < available_spare_threshold | Peligro (rojo) | NVMe Base Specification 2.0c, figura 207, bytes 03 y 04, y byte 00 bit 0 |
| NVME-USO-100 | percentage_used >= 100 (una estimación, no una falla) | Precaución (amarillo) | NVMe Base Specification 2.0c, figura 207, byte 05 |
| LATIDO-VIDA | 90 <= percentage_used < 100 (vida estimada de 10 % o menos) | Precaución (amarillo) | SIN FUENTE |
| NVME-TEMP-ADVERTENCIA | temperatura compuesta >= umbral de advertencia del disco (WCTEMP) | Precaución (amarillo) | NVMe Base Specification 2.0c, figura 275, bytes 267:266 (WCTEMP) |
| NVME-TEMP-CRITICA | temperatura compuesta >= umbral crítico del disco (CCTEMP) | Peligro (rojo) | NVMe Base Specification 2.0c, figura 275, bytes 269:268 (CCTEMP) |
| NVME-ERRORES-MEDIO | media_errors > 0 | Precaución (amarillo) | SIN FUENTE |
| NVME-TIEMPO-CRITICO | critical_comp_time > 0 (minutos por encima de la temperatura crítica) | Precaución (amarillo) | SIN FUENTE |
| NVME-APAGADOS-INSEGUROS | unsafe_shutdowns: se muestra en «Todos los datos», nunca da color | Solo informa | NVMe Base Specification 2.0c, figura 207, bytes 159:144 |

## Lo que dicen las fuentes

- **critical_warning** (figura 207, byte 00): "This field indicates critical warnings for the state of the
  controller."
  - Bit 0: "the available spare capacity has fallen below the threshold".
  - Bit 1: "a temperature is: a) greater than or equal to an over temperature threshold; or b) less than or
    equal to an under temperature threshold". Sección 5.27.1.3: "The default value of the over temperature
    threshold feature for Composite Temperature is the value in the Warning Composite Temperature Threshold
    (WCTEMP) field". Por eso el bit 1 da amarillo y no rojo.
- **WCTEMP** (figura 275): "an overheating condition during which controller operation continues. Immediate
  remediation is recommended".
- **CCTEMP** (figura 275): "a critical overheating condition (e.g., may prevent continued normal operation,
  possibility of data loss, automatic device shutdown, extreme performance throttling, or permanent
  damage)".
- **Percentage Used** (figura 207, byte 05): "A value of 100 indicates that the estimated endurance of the
  NVM in the NVM subsystem has been consumed, but may not indicate an NVM subsystem failure."
- **Media and Data Integrity Errors** (figura 207, bytes 175:160): "the number of occurrences where the
  controller detected an unrecovered data integrity error". La especificación no dice desde cuántos es grave:
  el amarillo es criterio de Latido.
- **Unsafe Shutdowns** (figura 207, bytes 159:144): solo cuenta apagados sin aviso; no dice que sean daño.
- **smartctl, EXIT STATUS:**
  - bit 3: "SMART status check returned "DISK FAILING"";
  - bit 4: "We found prefail Attributes <= threshold";
  - y en `-A`: "Pre-failure Attributes are ones which, if less than or equal to their threshold values,
    indicate pending disk failure".
  - Los bits 5, 6 y 7 describen lo que pasó, pero no dicen qué tan grave es: el amarillo es criterio de
    Latido.

## Autenticidad

- **Una prueba de velocidad sola no prueba la autenticidad.** La capacidad real solo se confirma escribiendo
  y verificando todo el disco (f3, en una fase posterior; requiere el case).
- «Falso o manipulado» solo sale con una contradicción dura entre dos fuentes del propio sistema. Hoy: la
  capacidad que da smartctl (`user_capacity`) contra la que ve el kernel (lsblk). Se comparan solo en NVMe
  con un solo espacio de nombres, para que midan lo mismo.
- Sin esa contradicción: «No concluyente», con el texto «Latido aún no verifica la capacidad real».
- Las otras dos etiquetas todavía no salen:
  - «Sin señales de falsificación»: hace falta f3;
  - «Sospechoso»: todavía no hay reglas con fuente que lo justifiquen.
- La pantalla muestra la etiqueta, el porqué y «Qué no se comprobó».
