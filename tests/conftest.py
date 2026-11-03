import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "smartctl"


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


# --- Pantalla para las pruebas de interfaz ---


# --- fio falso (tests/fio_falso.py) ---


class StatvfsFalso:
    def __init__(self, libre, solo_lectura=False):
        self.f_bavail = libre
        self.f_frsize = 1
        self.f_flag = os.ST_RDONLY if solo_lectura else 0
