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

`sintetico_precaucion.json`, `sintetico_malo.json` y `sintetico_desconocido.json`
son **inventados** para probar casos que el hardware real no mostró. Llevan la
clave `"_sintetico"` para que no se confundan. **No prueban hardware real.**
