"""Las cuatro pruebas, los pasos de una medición y el comando exacto de fio.

Cada opción está verificada contra la documentación instalada de fio 3.40
(man fio y /usr/share/doc/fio/HOWTO.rst); el detalle está en docs/velocidad.md.
Los tamaños se pasan en bytes, sin sufijos: según HOWTO.rst ("Parameter
types", int) la unidad por defecto de una cantidad de datos es el byte, y los
sufijos k/m/g cambian de significado con kb_base.
"""

import os
from dataclasses import dataclass
from enum import Enum

FIO = "/usr/bin/fio"

MIB = 1024**2
GIB = 1024**3

TAMANOS = (256 * MIB, 512 * MIB, 1 * GIB, 2 * GIB, 4 * GIB, 8 * GIB, 16 * GIB, 32 * GIB)
TAMANO_MINIMO, TAMANO_MAXIMO = TAMANOS[0], TAMANOS[-1]
TAMANO_POR_DEFECTO = 1 * GIB
PASADAS_MINIMO, PASADAS_MAXIMO = 1, 9
PASADAS_POR_DEFECTO = 3

# Tope de cada medición (runtime). fio para al llegar al tope de tiempo o al
# terminar los bytes de size, lo que ocurra primero (HOWTO.rst, runtime).
SEGUNDOS_POR_MEDICION = 5

PREFIJO_DIRECTORIO = ".latido-velocidad-"
ARCHIVO_PRUEBA = "latido-velocidad.dat"

# Caracteres que fio interpreta dentro de un valor (HOWTO.rst): ':' separa
# varios archivos en filename y '\' lo escapa; '$' introduce las palabras
# reservadas ($pagesize, $mb_memory, $ncpus) y las variables ${VAR}.
CARACTERES_ESPECIALES_FIO = (":", "\\", "$")

RUTAS_PROHIBIDAS = ("/dev", "/proc", "/sys")


class Direccion(Enum):
    LECTURA = "read"  # también es la clave de la sección en el JSON de fio
    ESCRITURA = "write"

    @property
    def texto(self):
        return "lectura" if self is Direccion.LECTURA else "escritura"


@dataclass(frozen=True)
class Prueba:
    clave: str
    nombre: str
    descripcion: str
    bloque: int  # bytes por operación (bs)
    cola: int  # operaciones en vuelo (iodepth)
    hilos: int  # trabajos (numjobs)
    aleatoria: bool

    def rw(self, direccion):
        if self.aleatoria:
            return "randread" if direccion is Direccion.LECTURA else "randwrite"
        return "read" if direccion is Direccion.LECTURA else "write"


PRUEBAS = (
    Prueba("seq1m-q8t1", "SEQ1M Q8T1", "Secuencial · bloques de 1 MiB · cola 8 · 1 hilo", MIB, 8, 1, False),
    Prueba("seq1m-q1t1", "SEQ1M Q1T1", "Secuencial · bloques de 1 MiB · cola 1 · 1 hilo", MIB, 1, 1, False),
    Prueba("rnd4k-q32t1", "RND4K Q32T1", "Aleatoria · bloques de 4 KiB · cola 32 · 1 hilo", 4096, 32, 1, True),
    Prueba("rnd4k-q1t1", "RND4K Q1T1", "Aleatoria · bloques de 4 KiB · cola 1 · 1 hilo", 4096, 1, 1, True),
)

# Preparación: escribe el archivo completo una vez, en secuencia, para que las
# lecturas tengan datos. Mismo patrón que SEQ1M Q8T1.
BLOQUE_PREPARACION = MIB
COLA_PREPARACION = 8


@dataclass(frozen=True)
class Paso:
    prueba: Prueba | None = None  # None = preparar el archivo de prueba
    direccion: Direccion | None = None
    pasada: int | None = None

    @property
    def es_preparacion(self):
        return self.prueba is None

    @property
    def trabajo(self):
        """Nombre del trabajo de fio (ASCII). El analizador lo busca en el JSON."""
        if self.es_preparacion:
            return "latido-preparar"
        return f"latido-{self.prueba.clave}-{self.direccion.texto}"

    def descripcion(self, pasadas=None):
        if self.es_preparacion:
            return "Preparando el archivo de prueba"
        texto = f"{self.prueba.nombre} · {self.direccion.texto}"
        if pasadas:
            texto += f" · pasada {self.pasada} de {pasadas}"
        return texto


class ErrorConfiguracion(ValueError):
    pass


@dataclass(frozen=True)
class Configuracion:
    tamano: int = TAMANO_POR_DEFECTO
    pasadas: int = PASADAS_POR_DEFECTO

    def __post_init__(self):
        if type(self.tamano) is not int or not TAMANO_MINIMO <= self.tamano <= TAMANO_MAXIMO or self.tamano % MIB:
            raise ErrorConfiguracion("El tamaño de la prueba debe estar entre 256 MiB y 32 GiB, en MiB enteros.")
        if type(self.pasadas) is not int or not PASADAS_MINIMO <= self.pasadas <= PASADAS_MAXIMO:
            raise ErrorConfiguracion(f"Las pasadas deben estar entre {PASADAS_MINIMO} y {PASADAS_MAXIMO}.")

    def pasos(self):
        """Preparación y, por cada prueba, sus lecturas y luego sus escrituras."""
        pasos = [Paso()]
        for prueba in PRUEBAS:
            for direccion in (Direccion.LECTURA, Direccion.ESCRITURA):
                for pasada in range(1, self.pasadas + 1):
                    pasos.append(Paso(prueba, direccion, pasada))
        return pasos

    @property
    def mediciones_de_escritura(self):
        return len(PRUEBAS) * self.pasadas

    @property
    def escritura_maxima(self):
        """Bytes escritos como máximo: la preparación y cada medición de escritura.

        Cada medición de escritura escribe como mucho size bytes (HOWTO.rst,
        size y runtime: para con lo que ocurra primero).
        """
        return self.tamano * (1 + self.mediciones_de_escritura)


class RutaNoPermitida(ValueError):
    pass


def dentro_de(ruta, base):
    return ruta == base or ruta.startswith(base.rstrip("/") + "/")


def comprobar_ruta_archivo(archivo):
    """Única forma de ruta que fio puede recibir: /…/.latido-velocidad-XXXX/latido-velocidad.dat."""
    if not isinstance(archivo, str) or not os.path.isabs(archivo) or os.path.normpath(archivo) != archivo:
        raise RutaNoPermitida("La ruta del archivo de prueba no es absoluta y normalizada.")
    for caracter in CARACTERES_ESPECIALES_FIO:
        if caracter in archivo:
            raise RutaNoPermitida(f"La ruta del archivo de prueba contiene «{caracter}», que fio interpreta.")
    if any(ord(c) < 32 or ord(c) == 127 for c in archivo):
        raise RutaNoPermitida("La ruta del archivo de prueba contiene caracteres de control.")
    for prohibida in RUTAS_PROHIBIDAS:
        if dentro_de(archivo, prohibida):
            raise RutaNoPermitida(f"Latido nunca escribe dentro de {prohibida}.")
    directorio, nombre = os.path.split(archivo)
    if nombre != ARCHIVO_PRUEBA or not os.path.basename(directorio).startswith(PREFIJO_DIRECTORIO):
        raise RutaNoPermitida("La ruta no es el archivo de prueba dentro de un directorio de Latido.")
    return archivo


def construir_comando(paso, archivo, tamano, fio=FIO):
    """Lista de argumentos para fio (nunca un texto para un shell).

    - Opciones de la línea de órdenes primero; desde --name, opciones del
      trabajo (HOWTO.rst, name: en la línea de órdenes, --name abre un trabajo).
    - Las lecturas llevan --readonly: fio se niega a escribir.
    - Las mediciones llevan --allow_file_create=0: si el archivo no existe,
      fio da error en vez de crearlo.
    """
    comprobar_ruta_archivo(archivo)
    comando = [fio, "--output-format=json", "--eta=never"]
    if paso.es_preparacion:
        rw, bloque, cola, hilos = "write", BLOQUE_PREPARACION, COLA_PREPARACION, 1
    else:
        prueba = paso.prueba
        rw, bloque, cola, hilos = prueba.rw(paso.direccion), prueba.bloque, prueba.cola, prueba.hilos
        if paso.direccion is Direccion.LECTURA:
            comando.append("--readonly")
    comando += [
        f"--name={paso.trabajo}",
        f"--filename={archivo}",
        "--ioengine=libaio",
        "--direct=1",
        f"--rw={rw}",
        f"--bs={bloque}",
        f"--iodepth={cola}",
        f"--numjobs={hilos}",
        f"--size={tamano}",
    ]
    if not paso.es_preparacion:
        comando += [f"--runtime={SEGUNDOS_POR_MEDICION}", "--allow_file_create=0"]
    return comando
