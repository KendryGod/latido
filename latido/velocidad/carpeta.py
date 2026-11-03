"""Revisión de la carpeta elegida antes de medir.

Todo es de solo lectura y sin root: os.path.realpath, os.lstat, os.access,
os.statvfs, /proc/self/mountinfo y /sys/class/block. Nada aquí escribe.
"""

import os
import re
import stat
from dataclasses import dataclass, field

from latido.velocidad import formato
from latido.velocidad.pruebas import CARACTERES_ESPECIALES_FIO, GIB, RUTAS_PROHIBIDAS, dentro_de

MOUNTINFO = "/proc/self/mountinfo"
SYS_BLOCK = "/sys/class/block"

# Sistemas de archivos virtuales del kernel: no guardan datos en un disco.
SISTEMAS_VIRTUALES = frozenset({
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs", "devpts", "devtmpfs",
    "efivarfs", "fusectl", "hugetlbfs", "mqueue", "nsfs", "proc", "pstore", "rpc_pipefs", "securityfs",
    "selinuxfs", "sysfs", "tracefs",
})
SISTEMAS_EN_MEMORIA = frozenset({"tmpfs", "ramfs"})
SISTEMAS_DE_RED = frozenset({"nfs", "nfs4", "cifs", "smb3", "fuse.sshfs"})

# man 5 btrfs, CHECKSUM ALGORITHMS: desde Linux 6.14 una escritura directa a
# un archivo con suma de verificación de datos pasa a escritura con caché.
KERNEL_BTRFS_DIRECTO_CON_CACHE = (6, 14)


class ErrorCarpeta(Exception):
    pass


def margen(tamano):
    """Espacio que debe quedar libre además del archivo: 1 GiB o el 10 %, lo mayor."""
    return max(GIB, tamano // 10)


def espacio_necesario(tamano):
    return tamano + margen(tamano)


# --- validación de la ruta ---

def _caracter_prohibido(ruta):
    for caracter in CARACTERES_ESPECIALES_FIO:
        if caracter in ruta:
            return f"«{caracter}»"
    if any(ord(c) < 32 or ord(c) == 127 for c in ruta):
        return "caracteres de control"
    return None


def validar_carpeta(ruta):
    """Devuelve la ruta real de la carpeta o lanza ErrorCarpeta con el motivo exacto."""
    if not isinstance(ruta, str) or not ruta:
        raise ErrorCarpeta("No se eligió ninguna carpeta.")
    if not os.path.isabs(ruta):
        raise ErrorCarpeta("La ruta de la carpeta no es absoluta.")
    real = os.path.realpath(ruta)
    for prohibida in RUTAS_PROHIBIDAS:
        if dentro_de(real, prohibida):
            raise ErrorCarpeta(f"Latido no hace pruebas dentro de {prohibida} (la carpeta está en «{real}»).")
    if real != os.path.normpath(ruta):
        raise ErrorCarpeta(
            f"La ruta pasa por un enlace simbólico. Su ruta real es «{real}»: elige esa carpeta directamente."
        )
    caracter = _caracter_prohibido(real)
    if caracter:
        raise ErrorCarpeta(
            f"La ruta contiene {caracter}, que fio interpreta de forma especial. Elige otra carpeta."
        )
    try:
        info = os.lstat(real)
    except FileNotFoundError:
        raise ErrorCarpeta(f"La carpeta «{real}» no existe.") from None
    except OSError as error:
        raise ErrorCarpeta(f"No se pudo revisar la carpeta «{real}»: {error.strerror}.") from None
    if not stat.S_ISDIR(info.st_mode):
        raise ErrorCarpeta(f"«{real}» no es una carpeta.")
    if not os.access(real, os.W_OK | os.X_OK):
        raise ErrorCarpeta(f"No tienes permiso para escribir en «{real}».")
    return real


# --- /proc/self/mountinfo (man 5 proc_pid_mountinfo) ---

@dataclass(frozen=True)
class Montaje:
    id: int
    padre: int
    raiz: str
    punto: str
    opciones: tuple
    tipo: str
    fuente: str
    superopciones: tuple


# Espacio, tabulador, salto de línea y barra invertida van como \ooo octal
# (la misma convención que describe man 3 getmntent).
_ESCAPE_OCTAL = re.compile(r"\\([0-7]{3})")


def _desescapar(texto):
    return _ESCAPE_OCTAL.sub(lambda m: chr(int(m.group(1), 8)), texto)


def leer_mountinfo(texto):
    """Interpreta mountinfo. Las líneas con formato desconocido se ignoran."""
    montajes = []
    for linea in texto.splitlines():
        campos = linea.split(" ")
        try:
            separador = campos.index("-", 6)
            montajes.append(Montaje(
                id=int(campos[0]),
                padre=int(campos[1]),
                raiz=_desescapar(campos[3]),
                punto=_desescapar(campos[4]),
                opciones=tuple(campos[5].split(",")),
                tipo=campos[separador + 1],
                fuente=_desescapar(campos[separador + 2]),
                superopciones=tuple(campos[separador + 3].split(",")) if len(campos) > separador + 3 else (),
            ))
        except (ValueError, IndexError):
            continue
    return montajes


def montaje_de(ruta, montajes):
    """Montaje que contiene la ruta: el punto de montaje más largo que la contiene.

    Si hay varios montajes apilados en ese punto, el de arriba es el que no es
    padre de ningún otro en el mismo punto (man 5 proc_pid_mountinfo).
    """
    candidatos = [m for m in montajes if dentro_de(ruta, m.punto)]
    if not candidatos:
        return None
    largo = max(len(m.punto) for m in candidatos)
    en_punto = [m for m in candidatos if len(m.punto) == largo]
    padres = {m.padre for m in en_punto}
    arriba = [m for m in en_punto if m.id not in padres]
    return (arriba or en_punto)[-1]


def _leer_texto(ruta):
    with open(ruta, encoding="utf-8", errors="surrogateescape") as archivo:
        return archivo.read()


# --- de la fuente del montaje al disco físico (/sys/class/block) ---

def discos_de_fuente(fuente, sys_block=SYS_BLOCK, realpath=os.path.realpath):
    """Nombres de los discos bajo una fuente como /dev/nvme0n1p5. None si no se puede saber."""
    if not fuente.startswith("/dev/"):
        return None
    return _discos_de_nombre(os.path.basename(realpath(fuente)), sys_block, 0)


def _discos_de_nombre(nombre, sys_block, profundidad):
    base = os.path.join(sys_block, nombre)
    if profundidad > 8 or not nombre or not os.path.isdir(base):
        return None
    try:
        esclavos = sorted(os.listdir(os.path.join(base, "slaves")))
    except FileNotFoundError:
        esclavos = []
    except OSError:
        return None
    if esclavos:  # device-mapper (LUKS, LVM): los discos de debajo
        discos = set()
        for esclavo in esclavos:
            debajo = _discos_de_nombre(esclavo, sys_block, profundidad + 1)
            if debajo is None:
                return None
            discos |= debajo
        return frozenset(discos)
    if os.path.exists(os.path.join(base, "partition")):  # partición: su disco es la carpeta padre
        return frozenset({os.path.basename(os.path.dirname(os.path.realpath(base)))})
    return frozenset({nombre})


# --- revisión completa ---

@dataclass
class InfoCarpeta:
    ruta: str
    tipo: str | None = None
    punto_montaje: str | None = None
    fuente: str | None = None
    opciones: tuple = ()
    libre: int | None = None  # bytes disponibles sin root
    solo_lectura: bool = False
    disco_sistema: bool | None = None  # None = no se pudo saber
    discos: frozenset | None = None


@dataclass
class Revision:
    info: InfoCarpeta | None = None
    errores: list = field(default_factory=list)  # impiden empezar
    avisos: list = field(default_factory=list)

    @property
    def puede_empezar(self):
        return self.info is not None and not self.errores


def version_kernel(texto):
    coincidencia = re.match(r"(\d+)\.(\d+)", texto or "")
    return (int(coincidencia.group(1)), int(coincidencia.group(2))) if coincidencia else None


def revisar_carpeta(
    ruta,
    configuracion,
    leer_texto=_leer_texto,
    statvfs=os.statvfs,
    sys_block=SYS_BLOCK,
    kernel=None,
):
    """Revisa la carpeta para una configuración. Nunca escribe nada."""
    revision = Revision()
    try:
        real = validar_carpeta(ruta)
    except ErrorCarpeta as error:
        revision.errores.append(str(error))
        return revision
    info = InfoCarpeta(ruta=real)
    revision.info = info

    try:
        montajes = leer_mountinfo(leer_texto(MOUNTINFO))
    except OSError:
        montajes = []
    montaje = montaje_de(real, montajes)
    if montaje is not None:
        info.tipo, info.punto_montaje, info.fuente = montaje.tipo, montaje.punto, montaje.fuente
        info.opciones = montaje.opciones + montaje.superopciones
        if montaje.tipo in SISTEMAS_EN_MEMORIA:
            info.disco_sistema = False
        else:
            raiz = montaje_de("/", montajes)
            discos = discos_de_fuente(montaje.fuente, sys_block)
            discos_raiz = discos_de_fuente(raiz.fuente, sys_block) if raiz else None
            info.discos = discos
            if discos is not None and discos_raiz is not None:
                info.disco_sistema = bool(discos & discos_raiz)

    try:
        datos = statvfs(real)
        info.libre = datos.f_bavail * datos.f_frsize
        info.solo_lectura = bool(datos.f_flag & os.ST_RDONLY)
    except OSError as error:
        revision.errores.append(f"No se pudo leer el espacio libre de «{real}»: {error.strerror}.")

    if info.tipo in SISTEMAS_VIRTUALES:
        revision.errores.append(f"La carpeta está en {info.tipo}, un sistema de archivos virtual del kernel: no es un disco.")
    if info.solo_lectura:
        revision.errores.append("La carpeta está en un sistema de archivos montado solo para lectura.")
    necesario = espacio_necesario(configuracion.tamano)
    if info.libre is not None and info.libre < necesario:
        revision.errores.append(
            f"No hay espacio suficiente: quedan {formato.tamano(info.libre)} libres y hacen falta "
            f"{formato.tamano(necesario)} ({formato.tamano(configuracion.tamano)} del archivo de prueba "
            f"+ {formato.tamano(margen(configuracion.tamano))} de margen)."
        )

    revision.avisos = avisos(info, configuracion, kernel if kernel is not None else os.uname().release)
    return revision


def avisos(info, configuracion, kernel):
    lista = [aviso_desgaste(configuracion)]
    if info.disco_sistema:
        discos = ", ".join(sorted(info.discos or ()))
        lista.append(
            f"La carpeta está en el disco del sistema ({discos}): el equipo puede ir lento mientras dura la prueba."
        )
    elif info.disco_sistema is None:
        lista.append("No se pudo comprobar si la carpeta está en el disco del sistema.")
    if info.tipo is None:
        lista.append("No se pudo saber el sistema de archivos de la carpeta.")
    elif info.tipo in SISTEMAS_EN_MEMORIA:
        lista.append(
            f"La carpeta está en {info.tipo}: sus archivos viven en la memoria (RAM y, si hace falta, swap; "
            "ver man 5 tmpfs). El resultado medirá la memoria, no un disco."
        )
    elif info.tipo == "btrfs" and not {"nodatasum", "nodatacow"} & set(info.opciones):
        version = version_kernel(kernel)
        if version is None or version >= KERNEL_BTRFS_DIRECTO_CON_CACHE:
            texto = (
                "La carpeta está en btrfs. Según man 5 btrfs, desde Linux 6.14 una escritura directa (O_DIRECT) "
                "a un archivo con suma de verificación de datos (lo predeterminado en btrfs) se hace con caché, "
                "con una pequeña penalización de rendimiento."
            )
            texto += f" Tu kernel es {kernel}." if version else " No se pudo leer la versión de tu kernel."
            lista.append(texto)
    elif info.tipo in SISTEMAS_DE_RED:
        lista.append(f"La carpeta está en un sistema de archivos de red ({info.tipo}): el resultado incluirá la red.")
    return lista


def aviso_desgaste(configuracion):
    maximo = configuracion.escritura_maxima
    return (
        f"Se escribirán como máximo {formato.tamano(maximo)} ({formato.gigabytes(maximo)}): "
        f"{formato.tamano(configuracion.tamano)} para preparar el archivo de prueba y hasta "
        f"{formato.tamano(configuracion.tamano)} en cada una de las {configuracion.mediciones_de_escritura} "
        "mediciones de escritura. En un SSD, toda escritura gasta parte de su vida útil."
    )

