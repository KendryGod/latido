# Reglas de salud de Latido

Las reglas con FUENTE se apoyan en la especificación NVMe o en el manual de
smartctl; las que no tienen fuente son **criterio de Latido** y nunca dan rojo
(docs/veredicto.md). SMART mide el **daño acumulado** que el
disco ha registrado; **no predice fallas**. Un disco en Bueno puede fallar
mañana, y uno en Precaución puede durar años.

Código: `latido/salud/analisis.py` y `latido/salud/reglas.py`. Por ahora solo hay reglas para NVMe.
De los discos ATA, Latido lee y muestra la tabla de atributos, pero todavía no la analiza.

## Los cuatro estados

| Estado     | Color (paleta de libadwaita) | Qué quiere decir                          |
|------------|------------------------------|-------------------------------------------|
| Bueno      | azul (`@blue_3`)             | Ninguna regla se disparó                  |
| Precaución | amarillo (`@yellow_5`)       | Hay señales de riesgo                     |
| Peligro    | rojo (`@red_3`)              | El disco reporta fallas: evítalo          |
| Sin datos  | gris (`@dark_1`)             | No hay datos suficientes para opinar      |

**Ante la duda, Sin datos. Nunca Bueno por omisión.**

## Las reglas

Todas las reglas, con su condición, su resultado y su FUENTE, están en una sola tabla:
[docs/veredicto.md](veredicto.md) (en el código, `latido/salud/reglas.py`). Una regla sin fuente es
«criterio de Latido» y nunca da rojo.

El código de salida de smartctl es una máscara de bits (`man smartctl`, sección EXIT STATUS). Latido combina
(OR) el `smartctl.exit_status` del JSON y el código del proceso. Si algún código no es válido (por ejemplo,
smartctl terminó por una señal), o no se conoce ninguno, el estado es Sin datos.

## 3. Cálculos

- **TB escritos/leídos** = `data_units_*` × 512 000 / 10¹². Una unidad NVMe son
  1000 bloques de 512 bytes. Son TB decimales (10¹² bytes).
- **Vida** = max(0, 100 − `percentage_used`). El desgaste real se conserva
  aunque pase de 100 %.
- Si smartctl incluye la variante `_s` (texto) de un número grande, se usa esa
  (`man smartctl`, opción `--json`, letra `v`).
- **Temperatura**: solo se muestran los umbrales que reporta el propio disco
  (`nvme_composite_temperature_threshold`). Latido no inventa umbrales fijos y
  la temperatura actual no cambia el estado.

## 4. Lo que falta

Lo que no viene en el JSON queda vacío y la interfaz dice "No disponible",
nunca 0.
