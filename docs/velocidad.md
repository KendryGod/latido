# Pestaña "Velocidad"

Mide la velocidad de lectura y escritura de un disco con **fio**, en una
carpeta que eliges tú. fio corre como tu usuario: no pide contraseña y el
ayudante de root no participa. Los resultados solo se muestran en pantalla;
no se guardan.

Código: `latido/velocidad/` y `latido/ui/pagina_velocidad.py`.

## Las cuatro pruebas

Cada prueba mide lectura y escritura, y cada medición se repite tantas
**pasadas** como elijas (por defecto 3; de 1 a 9).

| Prueba       | Patrón     | Bloque (`bs`) | Cola (`iodepth`) | Hilos (`numjobs`) |
|--------------|------------|---------------|------------------|-------------------|
| SEQ1M Q8T1   | secuencial | 1 MiB         | 8                | 1                 |
| SEQ1M Q1T1   | secuencial | 1 MiB         | 1                | 1                 |
| RND4K Q32T1  | aleatorio  | 4 KiB         | 32               | 1                 |
| RND4K Q1T1   | aleatorio  | 4 KiB         | 1                | 1                 |

- **MB/s = 1,000,000 bytes por segundo** (MB decimal). IOPS = operaciones por
  segundo.
- El número grande es el **promedio** de las pasadas; debajo van la **mejor** y
  la **peor**.
- Latido usa `bw_bytes` del JSON de fio (bytes por segundo). Los fixtures
  reales (`tests/fixtures/fio/`) confirman que
  `bw_bytes = io_bytes × 1000 / runtime` (runtime en ms) y que `bw` va en
  unidades de 1024 bytes/s, como dice HOWTO.rst ("JSON output"). Si falta
  `bw_bytes`, Latido no calcula otro valor: muestra el error.
- `runtime` viene en milisegundos enteros: en mediciones muy cortas el
  resultado tiene poca resolución (con 64 MiB, dos lecturas de 49 ms dieron
  exactamente el mismo valor).

## Tamaño y tope de tiempo

- Tamaño del archivo de prueba: de 256 MiB a 32 GiB (por defecto 1 GiB).
- Cada medición se detiene al llegar a `size` bytes **o** a los 5 s
  (`runtime=5`), lo que ocurra primero (HOWTO.rst, `runtime`). Así una
  medición de escritura nunca escribe más que el tamaño elegido.
- Si fio tarda más de 120 s en una medición, Latido lo detiene y lo dice.

## Los pasos

1. **Preparar el archivo** (escritura secuencial, `bs=1 MiB`, cola 8): escribe
   el archivo completo una vez para que las lecturas tengan datos.
2. Por cada prueba: sus pasadas de **lectura** y después sus pasadas de
   **escritura**.

Hay **una invocación de fio por paso** (1 + 4 × 2 × pasadas): así el progreso
avanza paso a paso y cancelar detiene solo el fio en curso.

### Qué hace fio si el archivo no existe (HOWTO.rst, fio 3.40)

- `create_on_open` (línea 945): "Default: false -- pre-create all necessary
  files when the job starts".
- `allow_file_create` (línea 957): "If true, fio is permitted to create files
  as part of its workload. If this option is false, then fio will error out if
  the files it needs to use don't already exist. Default: true."
- `create_only` (línea 951) llama a ese paso "laid out or updated on disk".
- `size` (línea 1953): "If the files do not exist, size must be given."

Por eso Latido no deja que una lectura cree el archivo: lo crea un paso de
**escritura** explícito (la preparación), cuyos bytes se cuentan en el aviso de
desgaste, y todas las mediciones llevan `--allow_file_create=0` (si el archivo
no está, fio da error en vez de crearlo). Las lecturas llevan además
`--readonly` (HOWTO.rst línea 174: impide escrituras).

## Escritura máxima (aviso de desgaste)

```
escritura máxima = tamaño × (1 + 4 × pasadas)
```

1 preparación + 4 pruebas de escritura × pasadas, y cada una escribe como
máximo `size`. Con 1 GiB y 3 pasadas: **13 GiB (13.96 GB)**. Se muestra antes
de empezar, junto con el aviso de que en un SSD toda escritura gasta parte de
su vida útil.

## Espacio libre

Latido exige `espacio libre ≥ tamaño + margen`, con
**margen = 1 GiB o el 10 % del tamaño, lo que sea mayor**. El espacio libre es
`f_bavail × f_frsize` de `os.statvfs` (el que puede usar un usuario sin root).
El margen evita dejar el disco lleno mientras dura la prueba.

## El comando exacto

Lista de argumentos, ruta absoluta `/usr/bin/fio`, entorno limpio
(`LC_ALL=C` y nada más), sin shell, en su propia sesión y grupo de procesos, con
el directorio nuevo como carpeta de trabajo:

```
/usr/bin/fio --output-format=json --eta=never [--readonly]
  --name=latido-<prueba>-<lectura|escritura> --filename=<carpeta>/.latido-velocidad-XXXXXXXX/latido-velocidad.dat
  --ioengine=libaio --direct=1 --rw=<read|write|randread|randwrite> --bs=<bytes> --iodepth=<n> --numjobs=1
  --size=<bytes> --runtime=5 --allow_file_create=0
```

La preparación usa `--name=latido-preparar --rw=write --bs=1048576 --iodepth=8`
y no lleva `--runtime` ni `--allow_file_create=0`.

Cada opción está en `man fio` y en `/usr/share/doc/fio/HOWTO.rst` (líneas de
fio 3.40):

| Opción               | HOWTO.rst | Qué dice / por qué                                                    |
|----------------------|-----------|-----------------------------------------------------------------------|
| `--output-format=json` | 117     | formato de salida `json`                                              |
| `--eta=never`        | 183       | nunca imprime la estimación de tiempo (salida limpia)                 |
| `--readonly`         | 174       | "preventing writes and trims": solo en lecturas                       |
| `--name`             | 658       | en la línea de órdenes, además abre un trabajo nuevo                  |
| `--filename`         | 784       | `:` separa varios archivos (798: hay que escaparlo con `\`)           |
| `--ioengine=libaio`  | 2015, 2049 | E/S asíncrona de Linux; "may only support queued behavior with non-buffered I/O (set direct=1…)" |
| `--direct=1`         | 1147      | E/S sin caché (normalmente O_DIRECT)                                  |
| `--rw`               | 1158      | `read`, `write`, `randread`, `randwrite`                              |
| `--bs`               | 1623      | tamaño de bloque en bytes                                             |
| `--iodepth`          | 3265      | operaciones en vuelo                                                  |
| `--numjobs`          | 674       | clones del trabajo; por defecto 1                                     |
| `--size`             | 1953      | bytes a transferir                                                    |
| `--runtime`          | 687       | tope de tiempo; para con lo que ocurra primero                        |
| `--allow_file_create=0` | 957    | error si el archivo no existe                                         |

Los números se pasan **en bytes, sin sufijos** (`--bs=1048576`, no `1m`):
HOWTO.rst línea 525, "For quantities of data, the default unit is bytes", y los
sufijos cambian de significado con `kb_base`. El tiempo va en segundos
(línea 508: sin unidad, "interpreted as seconds").

## Regla de oro de esta pestaña

- fio escribe **solo** `latido-velocidad.dat` dentro de un directorio **nuevo**
  `.latido-velocidad-XXXXXXXX` que Latido crea con `tempfile.mkdtemp` (modo
  0700) dentro de la carpeta elegida. Nunca `--filename` a un dispositivo ni a
  un archivo que ya existía: el directorio recién creado debe estar vacío.
- Latido mantiene **abiertos** el directorio, desde que lo crea, y el archivo,
  desde que termina la preparación (con `O_RDONLY|O_NONBLOCK|O_NOFOLLOW`, no
  `O_PATH`). **Antes y después de cada paso** compara lo que tiene abierto
  (`os.fstat`) con lo que hay en la ruta, sin seguir enlaces simbólicos: mismo
  dispositivo e inodo, **un solo nombre** (`st_nlink` = 1) y el tamaño pedido.
  Si algo no cuadra, se detiene y dice qué pasó: lo borraron, lo movieron, en
  su lugar hay otra cosa o alguien le hizo un enlace duro.
- Por qué abierto: un sistema de archivos puede darle a un archivo nuevo el
  número de inodo de uno recién borrado. En la CI (run 41575524354) pasó así;
  en tmpfs y btrfs no pasó en 200 intentos. Mientras Latido tenga el archivo
  abierto, el archivo sigue existiendo aunque lo borren (man 2 unlink) y su
  número no puede ser el de otro archivo del mismo sistema de archivos
  (man 7 inode), así que un reemplazo siempre se nota.
- Durante la preparación el archivo todavía no está abierto: lo está creando
  fio. Si la prueba se cancela o falla en ese paso, la limpieza borra el
  archivo normal con un solo nombre que haya en su ruta, porque solo puede ser
  el que fio estaba creando (el directorio es 0700: solo tu usuario o root
  pueden poner otra cosa ahí).
- Carpetas rechazadas: que no existen, que no son carpetas, sin permiso de
  escritura, montadas solo para lectura, en un sistema de archivos virtual del
  kernel, o cuya ruta real queda dentro de `/dev`, `/proc` o `/sys`. También
  las rutas que pasan por un enlace simbólico (se muestra la ruta real) y las
  que contienen `:`, `\` o `$`, porque fio los interpreta (HOWTO.rst: `:` en
  `filename`, línea 798; `$` en "Environment variables", línea 418, y
  "Reserved keywords", línea 453).
- Al terminar, fallar, cancelar, cerrar la ventana o salir de la aplicación:
  Latido detiene el grupo de procesos de fio (SIGTERM, 10 s de espera, SIGKILL),
  borra **solo** `latido-velocidad.dat` por su nombre exacto (y solo si sigue
  siendo el archivo que tiene abierto y tiene un solo nombre), luego el
  directorio con `rmdir`, y cierra todos sus descriptores. Nunca `rm -r` ni
  `shutil.rmtree`. Si en el directorio aparece algo que Latido no creó, o si su
  archivo tiene otro nombre o se movió, no lo borra y lo dice; si otro programa
  ya lo había borrado, también lo dice.
- Una sola prueba a la vez.
- Cerrar la ventana en plena prueba pide confirmación; al confirmar, Latido
  cancela, limpia y luego cierra.

## Si Latido muere sin limpiar

Antes de crear nada, Latido guarda la carpeta elegida en
`$XDG_STATE_HOME/latido/velocidad.json` (o `~/.local/state/latido/velocidad.json`).
Al abrir la pestaña revisa **solo esa carpeta** y, si queda un
`.latido-velocidad-*`, lo avisa. No lo borra sin tu confirmación en pantalla, y
solo borra el archivo de prueba y la carpeta vacía; si hay algo más, no toca
nada.

Si el proceso de Latido muere de golpe (por ejemplo, con SIGKILL), fio sigue en
su propia sesión hasta terminar el paso en curso: como máximo 5 s si era una
medición, o hasta escribir el archivo completo si era la preparación.

## Antes de empezar: comprobaciones y avisos

- **fio y libaio**: `fio --version` y `fio --enghelp=libaio`. Con fio 3.40,
  `--enghelp=libaio` carga de verdad el motor (con `LD_DEBUG=files` se ve el
  dlopen de `/usr/lib64/fio/fio-libaio.so`) y sale con 0; con un motor que no se
  puede cargar sale con 1 y dice "not loadable". En Fedora 44 el motor es el
  paquete `fio-engine-libaio` (`rpm -qf /usr/lib64/fio/fio-libaio.so`).
  - Falta fio: `sudo dnf install fio fio-engine-libaio`
  - Falta libaio: `sudo dnf install fio-engine-libaio`
- **Sistema de archivos**: de `/proc/self/mountinfo` (man 5 proc_pid_mountinfo),
  por el punto de montaje más largo que contiene la carpeta. No se usa `st_dev`:
  en btrfs cada subvolumen tiene su propio `st_dev` y no coincide con el de
  mountinfo (comprobado: `/home` da 0:50 y mountinfo dice 0:36).
- **Disco del sistema**: se sigue la fuente del montaje por `/sys/class/block`
  (particiones y device-mapper) hasta el disco, y se compara con el disco de `/`.
  Si no se puede saber, se dice.
- **tmpfs**: según man 5 tmpfs, sus archivos viven en memoria virtual (RAM y, si
  hace falta, swap): el resultado mide la memoria, no un disco. Latido **no**
  afirma que tmpfs rechace O_DIRECT: en el kernel 7.2.14 un archivo de tmpfs se
  abrió y escribió con O_DIRECT sin error.
- **btrfs**: HOWTO.rst de fio no menciona btrfs. El aviso cita man 5 btrfs
  (sección CHECKSUM ALGORITHMS): desde Linux 6.14 una escritura directa a un
  archivo con suma de verificación de datos (lo predeterminado) pasa a escritura
  con caché: "This will bring a small performance penalty". No se muestra con kernels
  anteriores ni si el montaje usa `nodatasum` o `nodatacow`.
- **Red** (nfs, nfs4, cifs, smb3, fuse.sshfs): el resultado incluye la red.
- Si fio falla (por ejemplo, porque el sistema de archivos no acepta O_DIRECT),
  Latido muestra el mensaje real de fio, sin adivinar la causa.
