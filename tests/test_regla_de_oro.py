"""Regla de oro: el ayudante de root solo lee, y solo discos NVMe exactos.

Ninguna prueba ejecuta smartctl: subprocess.run se reemplaza por un falso.
"""

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

RUTA_HELPER = Path(__file__).parent.parent / "helper" / "latido-helper"


def _cargar_helper():
    cargador = importlib.machinery.SourceFileLoader("latido_helper", str(RUTA_HELPER))
    spec = importlib.util.spec_from_loader("latido_helper", cargador)
    modulo = importlib.util.module_from_spec(spec)
    cargador.exec_module(modulo)
    return modulo


helper = _cargar_helper()


class RunFalso:
    def __init__(self, stdout=b'{"smartctl": {"exit_status": 0}}', returncode=0):
        self.llamadas = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, comando, **kwargs):
        self.llamadas.append((comando, kwargs))
        return SimpleNamespace(stdout=self.stdout, returncode=self.returncode)


@pytest.fixture
def run_falso(monkeypatch):
    falso = RunFalso()
    monkeypatch.setattr(helper.subprocess, "run", falso)
    monkeypatch.setattr(helper, "smartctl_disponible", lambda: True)
    monkeypatch.setattr(helper, "validar_dispositivo", lambda disco: None)
    return falso


# --- El comando es exactamente el esperado -----------------------------------

def test_comando_exacto():
    assert helper.construir_comando("/dev/nvme0") == ["/usr/bin/smartctl", "--json=c", "-x", "/dev/nvme0"]
    assert helper.construir_comando("/dev/nvme1n1") == ["/usr/bin/smartctl", "--json=c", "-x", "/dev/nvme1n1"]


def test_ruta_absoluta_de_smartctl():
    assert helper.SMARTCTL == "/usr/bin/smartctl"


def test_shebang_aislado():
    assert RUTA_HELPER.read_text().splitlines()[0] == "#!/usr/bin/python3 -I"


def test_ejecucion_sin_shell_con_entorno_limpio_y_tiempo_maximo(run_falso, capsys):
    assert helper.main(["leer", "/dev/nvme0"]) == 0
    [(comando, kwargs)] = run_falso.llamadas
    assert comando == ["/usr/bin/smartctl", "--json=c", "-x", "/dev/nvme0"]
    assert kwargs.get("shell", False) is False
    assert kwargs["env"] == {"LC_ALL": "C"}
    assert kwargs["timeout"] > 0
    assert kwargs["stdin"] is subprocess.DEVNULL
    salida = json.loads(capsys.readouterr().out)
    assert salida == {"smartctl_exit": 0, "datos": {"smartctl": {"exit_status": 0}}}


def test_sale_0_aunque_el_disco_reporte_problemas(run_falso, capsys):
    run_falso.returncode = 8 | 64
    assert helper.main(["leer", "/dev/nvme0"]) == 0
    assert json.loads(capsys.readouterr().out)["smartctl_exit"] == 72


@pytest.mark.parametrize("stdout", [b"", b"no es json", b"[1, 2]", b"\xff\xfe"])
def test_salida_invalida_de_smartctl(run_falso, capsys, stdout):
    run_falso.stdout = stdout
    run_falso.returncode = 1
    assert helper.main(["leer", "/dev/nvme0"]) == 0
    assert json.loads(capsys.readouterr().out) == {"smartctl_exit": 1, "datos": None, "salida_invalida": True}


def test_timeout(monkeypatch):
    def lento(*args, **kwargs):
        raise subprocess.TimeoutExpired("smartctl", 60)

    monkeypatch.setattr(helper.subprocess, "run", lento)
    monkeypatch.setattr(helper, "smartctl_disponible", lambda: True)
    monkeypatch.setattr(helper, "validar_dispositivo", lambda disco: None)
    assert helper.main(["leer", "/dev/nvme0"]) == helper.SALIDA_TIEMPO


def test_sin_smartctl(run_falso, monkeypatch):
    monkeypatch.setattr(helper, "smartctl_disponible", lambda: False)
    assert helper.main(["leer", "/dev/nvme0"]) == helper.SALIDA_SIN_SMARTCTL
    assert run_falso.llamadas == []


def test_codigos_propios_no_usan_los_de_pkexec():
    propios = {helper.SALIDA_OK, helper.SALIDA_USO, helper.SALIDA_DISPOSITIVO,
               helper.SALIDA_SIN_SMARTCTL, helper.SALIDA_TIEMPO, helper.SALIDA_EJECUCION}
    assert len(propios) == 6
    assert not propios & {126, 127}


# --- Rechazos ----------------------------------------------------------------

RECHAZADOS = [
    [],
    ["leer"],
    ["leer", "-t"],
    ["leer", "-t", "long"],
    ["leer", "-s"],
    ["leer", "-s", "on"],
    ["leer", "-d"],
    ["leer", "-d", "sat", "/dev/nvme0"],
    ["leer", "--"],
    ["leer", "--", "/dev/nvme0"],
    ["--", "leer", "/dev/nvme0"],
    ["leer", "/dev/nvme0n1p3"],
    ["leer", "/dev/sda"],
    ["leer", "/dev/sda1"],
    ["leer", "/dev/../dev/nvme0"],
    ["leer", "/dev/nvme0/.."],
    ["leer", "/dev/nvme0/../sda"],
    ["leer", "/dev/./nvme0"],
    ["leer", "nvme0"],
    ["leer", "dev/nvme0"],
    ["leer", "./nvme0"],
    ["leer", "/dev/nvme0\n"],
    ["leer", " /dev/nvme0"],
    ["leer", "/dev/nvme"],
    ["leer", "/dev/nvmeXn1"],
    ["leer", "/dev/nvme٣"],  # dígito no ASCII
    ["leer", "/dev/nvme0", "extra"],
    ["leer", "/dev/nvme0", "-t", "short"],
    ["escribir", "/dev/nvme0"],
    ["LEER", "/dev/nvme0"],
]


@pytest.mark.parametrize("argv", RECHAZADOS, ids=repr)
def test_rechaza_argumentos(argv, run_falso):
    assert helper.main(argv) == helper.SALIDA_USO
    assert run_falso.llamadas == []  # nunca llegó a smartctl


@pytest.mark.parametrize("disco", ["/dev/nvme0", "/dev/nvme0n1", "/dev/nvme12n3"])
def test_acepta_nvme_exactos(disco):
    assert helper.validar_argumentos(["leer", disco]) == disco


def _stat_falso(modo):
    return lambda ruta: SimpleNamespace(st_mode=modo)


@pytest.mark.parametrize("modo", [stat.S_IFBLK | 0o660, stat.S_IFCHR | 0o600])
def test_acepta_dispositivo_de_bloque_o_caracteres(modo):
    helper.validar_dispositivo("/dev/nvme0", lstat=_stat_falso(modo))


@pytest.mark.parametrize("modo", [stat.S_IFLNK | 0o777, stat.S_IFREG | 0o644, stat.S_IFDIR | 0o755])
def test_rechaza_symlink_archivo_y_carpeta(modo):
    with pytest.raises(helper.ErrorHelper) as error:
        helper.validar_dispositivo("/dev/nvme0", lstat=_stat_falso(modo))
    assert error.value.codigo == helper.SALIDA_DISPOSITIVO


def test_symlink_real_no_se_sigue(tmp_path):
    # Un symlink que apunta a un dispositivo real sigue siendo un symlink.
    enlace = tmp_path / "nvme0"
    os.symlink("/dev/null", enlace)
    with pytest.raises(helper.ErrorHelper) as error:
        helper.validar_dispositivo(str(enlace))
    assert error.value.codigo == helper.SALIDA_DISPOSITIVO
    # Y su ruta tampoco pasa el patrón.
    with pytest.raises(helper.ErrorHelper):
        helper.validar_argumentos(["leer", str(enlace)])


def test_dispositivo_inexistente(monkeypatch):
    falso = RunFalso()
    monkeypatch.setattr(helper.subprocess, "run", falso)
    monkeypatch.setattr(helper, "smartctl_disponible", lambda: True)
    assert helper.main(["leer", "/dev/nvme987654"]) == helper.SALIDA_DISPOSITIVO
    assert falso.llamadas == []
