import copy
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from latido.velocidad.pruebas import ARCHIVO_PRUEBA

FIXTURES = Path(__file__).parent / "fixtures" / "smartctl"
FIXTURES_FIO = Path(__file__).parent / "fixtures" / "fio"
FIO_FALSO = Path(__file__).parent / "fio_falso.py"


def cargar(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.fixture
def nvme_real():
    return cargar("nvme_real.json")


@pytest.fixture
def base_sintetica():
    """Copia de sintetico_precaucion.json reparada para quedar en BUENO; cada test la altera."""
    datos = copy.deepcopy(cargar("sintetico_precaucion.json"))
    datos["nvme_smart_health_information_log"].update(media_errors=0, percentage_used=3)
    return datos


# --- Ninguna prueba ejecuta el fio real ni git (la CI no tiene fio). ---

PROGRAMAS_PROHIBIDOS = {"fio", "git"}


def _programa(args, ejecutable=None):
    primero = ejecutable if ejecutable is not None else (args if isinstance(args, (str, bytes, os.PathLike)) else args[0])
    return os.fsdecode(primero)


def es_programa_prohibido(args, ejecutable=None):
    programa = _programa(args, ejecutable)
    if os.path.basename(programa) in PROGRAMAS_PROHIBIDOS:
        return True
    return os.path.isabs(programa) and os.path.realpath(programa) in {
        os.path.realpath(f"/usr/bin/{p}") for p in PROGRAMAS_PROHIBIDOS
    }


@pytest.fixture(autouse=True)
def sin_fio_ni_git_reales(monkeypatch):
    original = subprocess.Popen

    class PopenVigilado(original):
        def __init__(self, args, *resto, **opciones):
            if es_programa_prohibido(args, opciones.get("executable")):
                raise AssertionError(f"Una prueba intentó ejecutar {args!r}: fio y git reales están prohibidos")
            super().__init__(args, *resto, **opciones)

    monkeypatch.setattr(subprocess, "Popen", PopenVigilado)


@pytest.fixture(autouse=True)
def estado_aislado(tmp_path_factory, monkeypatch):
    """La última carpeta usada nunca se guarda en el ~/.local/state real durante las pruebas."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path_factory.mktemp("estado")))


# --- Pantalla para las pruebas de interfaz ---

def _hay_pantalla():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk

    Gtk.init_check()
    return Gdk.Display.get_default() is not None


@pytest.fixture(scope="module")
def gtk():
    """Con Gdk.Display.get_default() real. Sin pantalla: se salta con motivo; con REQUIRE_DISPLAY=1, falla."""
    if not _hay_pantalla():
        motivo = "Sin pantalla: Gdk.Display.get_default() devolvió None"
        if os.environ.get("REQUIRE_DISPLAY") == "1":
            pytest.fail(motivo + " y REQUIRE_DISPLAY=1")
        pytest.skip(motivo)
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    Adw.init()
    return GLib, Gtk


def esperar(GLib, condicion, segundos=5):
    contexto = GLib.MainContext.default()
    limite = time.monotonic() + segundos
    while not condicion() and time.monotonic() < limite:
        contexto.iteration(False)
        time.sleep(0.01)
    while contexto.pending():
        contexto.iteration(False)


# --- fio falso (tests/fio_falso.py) ---

class FioFalso:
    def __init__(self, carpeta):
        carpeta.mkdir(parents=True, exist_ok=True)
        self.ruta = carpeta / "fio_falso"
        self.registro = carpeta / "registro.jsonl"
        self.ruta.write_text(f"#!{sys.executable}\n" + FIO_FALSO.read_text(encoding="utf-8"), encoding="utf-8")
        self.ruta.chmod(0o755)
        self.configurar(["ok"])

    def configurar(self, modos, fixtures=None, enlace=None, destino=None):
        datos = {
            "modos": modos,
            "registro": str(self.registro),
            "fixtures": {nombre: str(ruta) for nombre, ruta in (fixtures or {}).items()},
            "enlace": enlace,
            "destino": destino,
        }
        Path(str(self.ruta) + ".json").write_text(json.dumps(datos), encoding="utf-8")

    def _lineas(self):
        if not self.registro.exists():
            return []
        return [json.loads(l) for l in self.registro.read_text(encoding="utf-8").splitlines() if l.strip()]

    def invocaciones(self):
        return [linea for linea in self._lineas() if "argv" in linea]

    def hijos(self):
        return [linea["hijo"] for linea in self._lineas() if "hijo" in linea]


@pytest.fixture
def fio_falso(tmp_path):
    return FioFalso(tmp_path / "bin")


class StatvfsFalso:
    def __init__(self, libre, solo_lectura=False):
        self.f_bavail = libre
        self.f_frsize = 1
        self.f_flag = os.ST_RDONLY if solo_lectura else 0


def vivo(pid):
    """Proceso vivo (un zombi cuenta como terminado)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as archivo:
            estado = archivo.read().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return estado != "Z"


def descriptores_hacia(ruta):
    """Descriptores abiertos de este proceso que apuntan a ruta o a algo dentro (aunque esté borrado)."""
    ruta = str(ruta)
    hallados = []
    for nombre in os.listdir("/proc/self/fd"):
        try:
            destino = os.readlink(f"/proc/self/fd/{nombre}")
        except OSError:
            continue  # el que usó listdir ya se cerró
        if destino == ruta or destino.startswith(ruta + "/"):
            hallados.append((int(nombre), destino))
    return hallados


# --- Simulador de reutilización de números de inodo ---

STAT_REAL, LSTAT_REAL, FSTAT_REAL = os.stat, os.lstat, os.fstat


class SimuladorInodos:
    """Imita un sistema de archivos que da a un archivo nuevo el número de inodo
    de uno que ya no existe. Se deduce del log de la CI (run 41575524354) que
    ocurrió. En tmpfs y btrfs no se repitió en 200 intentos; en tmpfs, la prueba
    de la CI pasaba en local.

    Solo cambia lo que ven os.stat, os.lstat y os.fstat de ESTE proceso, y solo
    para archivos normales con los nombres indicados. Regla, la de un sistema de
    archivos local según man 2 unlink y man 7 inode: cuando aparece un archivo nuevo con el mismo nombre en la
    misma carpeta, recibe el número del anterior solo si el anterior ya no
    existe: sin nombre en esa carpeta y sin ningún descriptor de este proceso
    abierto hacia él. No mira descriptores de otros procesos ni nombres en otras
    carpetas.

    decisiones: una (nombre, motivo) cada vez que aparece un archivo nuevo donde
    había otro; motivo es "reutilizado", "anterior abierto" o "anterior con nombre".
    """

    def __init__(self, nombres):
        self.nombres = set(nombres)
        self.decisiones = []
        self._ultimo = {}  # (dev_carpeta, ino_carpeta, nombre) -> (dev, ino_real, ino_informado)
        self._traduccion = {}  # (dev, ino_real) -> ino_informado

    def stat(self, ruta, *, dir_fd=None, follow_symlinks=True):
        return self._observar(STAT_REAL(ruta, dir_fd=dir_fd, follow_symlinks=follow_symlinks), ruta, dir_fd)

    def lstat(self, ruta, *, dir_fd=None):
        return self._observar(LSTAT_REAL(ruta, dir_fd=dir_fd), ruta, dir_fd)

    def fstat(self, descriptor):
        return self._traducir(FSTAT_REAL(descriptor))

    @staticmethod
    def _con_numero(info, ino):
        _clase, (visibles, ocultos) = info.__reduce__()
        visibles = list(visibles)
        visibles[1] = ino  # st_ino
        return os.stat_result(visibles, ocultos)

    def _traducir(self, info):
        ino = self._traduccion.get((info.st_dev, info.st_ino))
        return info if ino is None else self._con_numero(info, ino)

    def _observar(self, info, ruta, dir_fd):
        if isinstance(ruta, int) or not stat.S_ISREG(info.st_mode):
            return self._traducir(info)
        texto = os.fsdecode(ruta)
        relativa = dir_fd is not None and not os.path.isabs(texto)
        nombre = os.path.basename(texto)
        if nombre not in self.nombres or (relativa and "/" in texto):
            return self._traducir(info)
        if relativa:
            carpeta, datos = dir_fd, FSTAT_REAL(dir_fd)
        else:
            carpeta = os.path.dirname(os.path.abspath(texto))
            datos = STAT_REAL(carpeta)
        clave = (datos.st_dev, datos.st_ino, nombre)
        real = (info.st_dev, info.st_ino)
        if real in self._traduccion:
            return self._traducir(info)
        anterior = self._ultimo.get(clave)
        if anterior is None or anterior[:2] == real:
            self._ultimo.setdefault(clave, (*real, real[1]))
            return info
        if self._abierto(anterior[:2]):
            motivo = "anterior abierto"
        elif self._con_nombre(carpeta, anterior[:2]):
            motivo = "anterior con nombre"
        else:
            motivo = "reutilizado"
        self.decisiones.append((nombre, motivo))
        if motivo != "reutilizado":
            self._ultimo[clave] = (*real, real[1])
            return info
        self._ultimo[clave] = (*real, anterior[2])
        self._traduccion[real] = anterior[2]
        return self._con_numero(info, anterior[2])

    @staticmethod
    def _abierto(identidad):
        for nombre in os.listdir("/proc/self/fd"):
            try:
                info = FSTAT_REAL(int(nombre))
            except OSError:
                continue
            if (info.st_dev, info.st_ino) == identidad:
                return True
        return False

    @staticmethod
    def _con_nombre(carpeta, identidad):
        try:
            nombres = os.listdir(carpeta)
        except OSError:
            return False
        for nombre in nombres:
            try:
                if isinstance(carpeta, int):
                    info = STAT_REAL(nombre, dir_fd=carpeta, follow_symlinks=False)
                else:
                    info = LSTAT_REAL(os.path.join(carpeta, nombre))
            except OSError:
                continue
            if (info.st_dev, info.st_ino) == identidad:
                return True
        return False


@pytest.fixture
def reutilizar_inodos(monkeypatch):
    """SimuladorInodos para el archivo de prueba de Velocidad. No es autouse: solo
    lo usan las pruebas que lo piden, y monkeypatch lo deshace al terminar cada una."""
    simulador = SimuladorInodos({ARCHIVO_PRUEBA})
    monkeypatch.setattr(os, "stat", simulador.stat)
    monkeypatch.setattr(os, "lstat", simulador.lstat)
    monkeypatch.setattr(os, "fstat", simulador.fstat)
    return simulador


# --- Simulador del listado de carpetas de btrfs ---

OPEN_REAL, LISTDIR_REAL, LSEEK_REAL, CLOSE_REAL = os.open, os.listdir, os.lseek, os.close


class SimuladorListado:
    """Imita lo que se midió en btrfs con el kernel 7.2.14: os.listdir(fd)
    devuelve la carpeta como estaba al abrir ese descriptor, o en su última
    llamada a os.listdir o a os.lseek. Lo borrado desaparece enseguida; lo
    creado, lo vuelto a crear con el mismo nombre o lo renombrado después no
    aparece hasta la llamada siguiente. Un descriptor abierto después lo ve
    todo. En tmpfs todo aparece al momento.

    Solo afecta a os.listdir con un descriptor de carpeta abierto con os.open
    mientras el simulador está activo; con una ruta, la lista está al día.
    Distingue cada entrada por (nombre, número de inodo): si un sistema de
    archivos repitiera el número al volver a crear un nombre, el simulador la
    mostraría antes que btrfs. Para saber qué hay de verdad abre la carpeta
    otra vez, así que también sirve si las pruebas corren en btrfs.
    """

    def __init__(self):
        self._fotos = {}  # descriptor -> ((st_dev, st_ino) de la carpeta, {(nombre, ino) visibles})

    @staticmethod
    def _ahora(descriptor):
        """[(nombre, ino)] de lo que hay de verdad, en el orden de os.listdir, con un descriptor nuevo."""
        nuevo = OPEN_REAL(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=descriptor)
        try:
            entradas = []
            for nombre in LISTDIR_REAL(nuevo):
                try:
                    entradas.append((nombre, STAT_REAL(nombre, dir_fd=nuevo, follow_symlinks=False).st_ino))
                except FileNotFoundError:
                    pass  # lo borraron entre el listado y el stat
            return entradas
        finally:
            CLOSE_REAL(nuevo)

    def _fotografiar(self, descriptor):
        info = FSTAT_REAL(descriptor)
        self._fotos[descriptor] = ((info.st_dev, info.st_ino), set(self._ahora(descriptor)))

    def open(self, ruta, flags, mode=0o777, *, dir_fd=None):
        descriptor = OPEN_REAL(ruta, flags, mode, dir_fd=dir_fd)
        self._fotos.pop(descriptor, None)
        try:
            es_carpeta = stat.S_ISDIR(FSTAT_REAL(descriptor).st_mode)
        except OSError:
            es_carpeta = False
        if es_carpeta:
            self._fotografiar(descriptor)
        return descriptor

    def listdir(self, ruta="."):
        foto = self._fotos.get(ruta) if isinstance(ruta, int) else None
        if foto is None:
            return LISTDIR_REAL(ruta)
        info = FSTAT_REAL(ruta)
        if (info.st_dev, info.st_ino) != foto[0]:  # ese número de descriptor ya es otra cosa
            del self._fotos[ruta]
            return LISTDIR_REAL(ruta)
        ahora = self._ahora(ruta)
        visibles = [nombre for nombre, ino in ahora if (nombre, ino) in foto[1]]
        self._fotos[ruta] = (foto[0], set(ahora))  # la llamada siguiente ya lo ve
        return visibles

    def lseek(self, descriptor, posicion, desde):
        resultado = LSEEK_REAL(descriptor, posicion, desde)
        if descriptor in self._fotos:
            self._fotografiar(descriptor)
        return resultado

    def close(self, descriptor):
        self._fotos.pop(descriptor, None)
        CLOSE_REAL(descriptor)


@pytest.fixture
def listar_como_btrfs(monkeypatch):
    """SimuladorListado. No es autouse: solo lo usan las pruebas que lo piden, y
    monkeypatch lo deshace al terminar cada una."""
    simulador = SimuladorListado()
    monkeypatch.setattr(os, "open", simulador.open)
    monkeypatch.setattr(os, "listdir", simulador.listdir)
    monkeypatch.setattr(os, "lseek", simulador.lseek)
    monkeypatch.setattr(os, "close", simulador.close)
    return simulador
