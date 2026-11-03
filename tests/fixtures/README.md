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

## fio/

Salidas reales de **fio 3.40** (fio-3.40-3.fc44 y fio-engine-libaio-3.40-3.fc44)
en Fedora 44, kernel 7.2.14, tomadas **una sola vez** el 2026-11-02 con el
ejecutor de Latido (`latido/velocidad/ejecucion.py`), en un directorio creado
con `mktemp -d -p ~/.cache/latido-dev` (btrfs en el disco del sistema, no
tmpfs). Tamaño de prueba: 64 MiB, 1 pasada. Al terminar, Latido borró su
archivo y su carpeta, y luego se borraron `$D` y `~/.cache/latido-dev` con
`rmdir`.

Comandos exactos que ejecutó Latido (`$D` = el directorio de `mktemp`):

```
/usr/bin/fio --output-format=json --eta=never --name=latido-preparar --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=write --bs=1048576 --iodepth=8 --numjobs=1 --size=67108864
/usr/bin/fio --output-format=json --eta=never --readonly --name=latido-seq1m-q8t1-lectura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=read --bs=1048576 --iodepth=8 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --name=latido-seq1m-q8t1-escritura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=write --bs=1048576 --iodepth=8 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --readonly --name=latido-seq1m-q1t1-lectura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=read --bs=1048576 --iodepth=1 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --name=latido-seq1m-q1t1-escritura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=write --bs=1048576 --iodepth=1 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --readonly --name=latido-rnd4k-q32t1-lectura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=randread --bs=4096 --iodepth=32 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --name=latido-rnd4k-q32t1-escritura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=randwrite --bs=4096 --iodepth=32 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --readonly --name=latido-rnd4k-q1t1-lectura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=randread --bs=4096 --iodepth=1 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
/usr/bin/fio --output-format=json --eta=never --name=latido-rnd4k-q1t1-escritura --filename=$D/.latido-velocidad-ikhzhhkw/latido-velocidad.dat --ioengine=libaio --direct=1 --rw=randwrite --bs=4096 --iodepth=1 --numjobs=1 --size=67108864 --runtime=5 --allow_file_create=0
```

Las 9 terminaron con código 0 y stderr vacío. Cada `latido-*.json` es la
salida estándar tal cual, con **una sola sustitución**: en
`job options.filename` el comienzo de la ruta (la carpeta de `mktemp`, que
contenía el nombre de usuario) se cambió por `/RUTA-REDACTADA`. No traen el
nombre del equipo ni `disk_util`. La prueba de datos personales revisa todos
los archivos de esta carpeta (rutas personales, usuario y equipo).

Consultas sin E/S (`env -i LC_ALL=C`), guardadas tal cual:

| Archivo                       | Comando                                    | Código |
|-------------------------------|--------------------------------------------|--------|
| `version.stdout`              | `/usr/bin/fio --version`                   | 0      |
| `enghelp_libaio.stdout`       | `/usr/bin/fio --enghelp=libaio`            | 0      |
| `enghelp_inexistente.stdout` y `.stderr` | `/usr/bin/fio --enghelp=motor_que_no_existe` | 1 |

### Sintéticos de fio

Inventados para probar errores. **No son salidas reales de fio.**

| Archivo                       | Caso                                               |
|-------------------------------|----------------------------------------------------|
| `sintetico_truncado.txt`      | la primera mitad de `latido-seq1m-q8t1-lectura.json` |
| `sintetico_json_invalido.txt` | texto que no es JSON                               |
| `sintetico_error_fio.stderr`  | mensaje de error inventado (se prueba con código 1) |
| `sintetico_jobs_vacio.json`   | `"jobs": []`                                       |
| `sintetico_sin_jobs.json`     | falta la clave `jobs`                              |
| `sintetico_otro_trabajo.json` | solo un trabajo con otro nombre                    |
