import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

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

    def configurar(self, modos, fixtures=None, enlace=None):
        datos = {
            "modos": modos,
            "registro": str(self.registro),
            "fixtures": {nombre: str(ruta) for nombre, ruta in (fixtures or {}).items()},
            "enlace": enlace,
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
