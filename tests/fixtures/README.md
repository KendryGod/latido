# Fixtures

## smartctl/

Salidas reales de smartctl 7.5 (smartmontools-7.5-11.fc44) en Fedora 44,
tomadas del disco NVMe del sistema (KINGSTON SNV2S1000G).

Comando exacto, tal como quedó registrado en `smartctl.argv` de cada archivo:

```
smartctl --json -x -q noserial /dev/nvme0
```

| Archivo              | Cómo se ejecutó | `exit_status` | Contenido                                  |
|----------------------|-----------------|---------------|--------------------------------------------|
| `nvme_real.json`     | como root       | 0             | Salida completa de `-x`.                   |
| `nvme_sin_root.json` | sin root        | 2 (bit 1)     | Solo el error "Permission denied".         |

"Como root" / "sin root" se deduce del resultado: el JSON no registra el usuario.

**Van sin datos personales.** `-q noserial` suprime el número de serie, el
WWN y el EUI-64 del namespace (ver `man smartctl`). Queda
`nvme_ieee_oui_identifier`, que es el código del fabricante (igual en todos
sus discos), no de esta unidad.

`tests/test_fixtures_sin_datos_personales.py` revisa todos los `.json` de esta
carpeta y falla si aparece alguna clave de identificación con valor.

Ojo: la aplicación NO usa `-q noserial`. El ayudante ejecuta
`smartctl --json=c -x <disco>`, así que una lectura real sí trae el número de
serie. Antes de agregar un fixture nuevo, genéralo con `-q noserial`.

## Fixtures sintéticos

Todos los archivos `sintetico_*.json` son **inventados** para probar casos que
el hardware real no mostró. Llevan la clave `"_sintetico"` para que no se
confundan. **No prueban hardware real.** Ninguno lleva serial, WWN, EUI-64 ni
NGUID; si una prueba necesita un serial, lo inyecta en memoria con un valor que
empieza por `SINTETICO-`.

| Archivo                                  | Caso                                               | Estado esperado |
|------------------------------------------|----------------------------------------------------|-----------------|
| `sintetico_precaucion.json`              | errores de medio y desgaste de 112 %               | PRECAUCION      |
| `sintetico_malo.json`                    | `critical_warning` bit 2                           | MALO            |
| `sintetico_desconocido.json`             | faltan datos obligatorios                          | DESCONOCIDO     |
| `sintetico_temp_critica.json`            | `critical_comp_time` = 37                          | PRECAUCION      |
| `sintetico_precaucion_combinada.json`    | temperatura, medio, repuesto, vida y temp. crítica | PRECAUCION      |
| `sintetico_malo_combinado.json`          | bits 2 y 3 + temp. crítica + errores de medio      | MALO            |
| `sintetico_solo_informativo.json`        | datos que solo se muestran, con valores altos      | BUENO           |
