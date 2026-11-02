# Reglas de salud de Latido

**Estas reglas son criterio propio de Latido**, no un estándar de la industria
ni una recomendación del fabricante. SMART mide el **daño acumulado** que el
disco ha registrado; **no predice fallas**. Un disco en BUENO puede fallar
mañana, y uno en PRECAUCION puede durar años.

Código: `latido/salud/analisis.py`. Por ahora solo hay reglas para NVMe;
los discos ATA/SATA/USB llegan en la Fase 2.

## Los cuatro estados

| Estado      | Color (clase libadwaita) | Qué quiere decir                         |
|-------------|--------------------------|------------------------------------------|
| BUENO       | azul (`accent`)          | Ninguna señal de daño en los datos SMART |
| PRECAUCION  | amarillo (`warning`)     | Hay señales de riesgo                    |
| MALO        | rojo (`error`)           | El disco reporta fallas: evítalo         |
| DESCONOCIDO | gris (`dim-label`)       | No hay datos suficientes para opinar     |

**Ante la duda, DESCONOCIDO. Nunca BUENO por omisión.**

## 1. Código de salida de smartctl

smartctl devuelve una máscara de bits (`man smartctl`, sección EXIT STATUS).
Latido combina (OR) el `smartctl.exit_status` del JSON y el código del proceso.

| Bit | Significado (man smartctl)                                    | Efecto en Latido |
|-----|---------------------------------------------------------------|------------------|
| 0   | La línea de órdenes no se pudo interpretar                     | DESCONOCIDO: no hay datos válidos |
| 1   | No se pudo abrir el disco / sin IDENTIFY / bajo consumo        | DESCONOCIDO: no hay datos válidos |
| 2   | Falló alguna orden SMART, o error de suma de verificación      | Los datos pueden estar incompletos: no puede ser BUENO (queda DESCONOCIDO salvo que haya señales de PRECAUCION o MALO) |
| 3   | El estado SMART dice "DISK FAILING"                            | Ver regla de MALO |
| 4   | Atributos de prefalla en o bajo su umbral                      | MALO |
| 5   | Algún atributo estuvo bajo su umbral en el pasado              | PRECAUCION |
| 6   | El registro de errores del disco tiene entradas                | PRECAUCION |
| 7   | El registro de autodiagnósticos tiene errores                  | PRECAUCION |

Los bits 3 a 7 no invalidan los datos: alimentan el diagnóstico.

Si algún código no es válido (por ejemplo, smartctl terminó por una señal),
o no se conoce ninguno, el estado es DESCONOCIDO. Si el JSON de smartctl no es
válido, también.

## 2. Reglas NVMe

Se aplican solo si los bits 0 y 1 están apagados.

### MALO
- `critical_warning` tiene activo cualquier bit distinto del bit 1 (temperatura).
- No existe `critical_warning` y smartctl dice que el disco falla
  (`smart_status.passed` es `false` o el bit 3 está activo).
- `critical_warning` es 0 pero smartctl dice que el disco falla: los datos se
  contradicen y Latido elige el lado prudente.
- Bit 4 del código de salida.

### PRECAUCION
- `critical_warning` tiene activo solo el bit 1 (temperatura).
- `media_errors` > 0.
- `available_spare` en o por debajo de `available_spare_threshold`.
- Vida estimada <= 10 %, donde vida = max(0, 100 - `percentage_used`).
- Bits 5, 6 o 7 del código de salida.

### DESCONOCIDO
- Bits 0 o 1, JSON inválido o código de salida inválido.
- Falta cualquiera de estos datos: `critical_warning`, `media_errors`,
  `available_spare`, `available_spare_threshold`, `percentage_used`.
- Bit 2 sin otras señales.

### BUENO
Solo si no se cumple nada de lo anterior y están todos los datos de la lista.

Si un disco cumple a la vez reglas de varios estados, gana el más grave
(MALO sobre PRECAUCION sobre DESCONOCIDO) y se muestran todos los motivos.

## 3. Cálculos

- **TB escritos/leídos** = `data_units_*` × 512 000 / 10¹². Una unidad NVMe son
  1000 bloques de 512 bytes. Son TB decimales (10¹² bytes).
- **Vida** = max(0, 100 − `percentage_used`). El desgaste real se conserva
  aunque pase de 100 %.
- Si smartctl incluye la variante `_s` (texto) de un número grande, se usa esa
  (`man smartctl`, opción `--json`, letra `v`).
- **Temperatura**: solo se muestran los umbrales que reporta el propio disco
  (`nvme_composite_temperature_threshold`). Latido no inventa umbrales fijos y
  la temperatura actual no cambia el estado: eso lo decide el bit 1 de
  `critical_warning`, que activa el propio disco.

## 4. Lo que falta

Lo que no viene en el JSON queda vacío y la interfaz dice "No disponible",
nunca 0.
