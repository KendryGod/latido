"""Detección de discos, comprobación de herramientas y lectura con pkexec simulado.

Ninguna prueba ejecuta pkexec ni el ayudante: se usa un ejecutor falso.
"""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from conftest import FIXTURES, cargar
from latido.app import ErrorArgumentos, interpretar_argumentos
from latido.salud import Estado
from latido.sistema import discos as modulo_discos
from latido.sistema.discos import AVISO_SD, discos_desde_lsblk, ruta_controlador_nvme
from latido.sistema.herramientas import comprobar_herramientas
from latido.sistema.lectura import ErrorLectura, TipoError, cargar_fixture, construir_comando, leer_salud
from latido.sistema.rutas import HELPER, PKEXEC, POLITICA, SMARTCTL


# --- lsblk --------------------------------------------------------------------

SALIDA_LSBLK = {
    "blockdevices": [
        {"name": "loop0", "path": "/dev/loop0", "type": "loop", "size": 1000, "mountpoints": []},
        {"name": "zram0", "path": "/dev/zram0", "type": "disk", "size": 8181514240, "mountpoints": ["[SWAP]"]},
        {"name": "sr0", "path": "/dev/sr0", "type": "rom", "size": 1000, "mountpoints": []},
        {
            "name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "tran": "nvme",
            "model": "KINGSTON SNV2S1000G", "size": 1000204886016, "mountpoints": [],
            "children": [
                {"name": "nvme0n1p5", "path": "/dev/nvme0n1p5", "type": "part", "mountpoints": ["/home", "/"]},
            ],
        },
        {
            "name": "sda", "path": "/dev/sda", "type": "disk", "tran": "usb",
            "model": "Case USB  ", "size": 500107862016, "mountpoints": [],
            "children": [{"name": "sda1", "path": "/dev/sda1", "type": "part", "mountpoints": [None]}],
        },
        {"name": "mmcblk0", "path": "/dev/mmcblk0", "type": "disk", "size": 1000, "mountpoints": []},
    ]
}


def test_deteccion_filtra_y_clasifica(tmp_path):
    discos = discos_desde_lsblk(SALIDA_LSBLK, sys_block=str(tmp_path))
    assert [d.nombre for d in discos] == ["nvme0n1", "sda"]
    nvme, sda = discos
    assert nvme.habilitado and nvme.aviso is None and nvme.es_sistema
    assert nvme.modelo == "KINGSTON SNV2S1000G" and nvme.tamano == 1000204886016
    assert not sda.habilitado and sda.aviso == AVISO_SD and sda.ruta_lectura is None
    assert not sda.es_sistema
    assert sda.modelo == "Case USB"
    assert AVISO_SD == "SATA y USB llegan en una próxima fase"


def test_ruta_controlador_desde_sysfs(tmp_path):
    controlador = tmp_path / "devices" / "pci0000:00" / "nvme" / "nvme0"
    controlador.mkdir(parents=True)
    (tmp_path / "block" / "nvme0n1").mkdir(parents=True)
    os.symlink(controlador, tmp_path / "block" / "nvme0n1" / "device")
    assert ruta_controlador_nvme("nvme0n1", str(tmp_path / "block")) == "/dev/nvme0"


def test_ruta_controlador_sin_sysfs_usa_el_namespace(tmp_path):
    assert ruta_controlador_nvme("nvme0n1", str(tmp_path)) == "/dev/nvme0n1"


def test_listar_discos_usa_lsblk_absoluto_sin_shell():
    llamadas = []

    def ejecutar(comando, **kwargs):
        llamadas.append((comando, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(SALIDA_LSBLK).encode())

    modulo_discos.listar_discos(ejecutar)
    [(comando, kwargs)] = llamadas
    assert comando[0] == "/usr/bin/lsblk" and "--json" in comando
    assert kwargs.get("shell", False) is False


@pytest.mark.parametrize("respuesta", [
    SimpleNamespace(returncode=1, stdout=b""),
    SimpleNamespace(returncode=0, stdout=b"no json"),
    SimpleNamespace(returncode=0, stdout=b"[]"),
])
def test_listar_discos_errores(respuesta):
    with pytest.raises(modulo_discos.ErrorDeteccion):
        modulo_discos.listar_discos(lambda comando, **kwargs: respuesta)


# --- Herramientas ---------------------------------------------------------------

def test_comprobar_herramientas_todo_listo():
    assert comprobar_herramientas(ejecutable=lambda r: True, existe=lambda r: True) == []


def test_comprobar_herramientas_un_mensaje_por_pieza():
    faltan = comprobar_herramientas(ejecutable=lambda r: False, existe=lambda r: False)
    assert len(faltan) == 4
    for ruta, mensaje in zip((SMARTCTL, PKEXEC, HELPER, POLITICA), faltan):
        assert ruta in mensaje


def test_comprobar_herramientas_solo_falta_la_politica():
    faltan = comprobar_herramientas(ejecutable=lambda r: True, existe=lambda r: r != POLITICA)
    assert len(faltan) == 1 and POLITICA in faltan[0]


# --- leer_salud con pkexec simulado -------------------------------------------

class PkexecFalso:
    def __init__(self, returncode=0, stdout=b"", excepcion=None):
        self.returncode = returncode
        self.stdout = stdout
        self.excepcion = excepcion
        self.llamadas = []

    def __call__(self, comando, **kwargs):
        self.llamadas.append((comando, kwargs))
        if self.excepcion:
            raise self.excepcion
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=b"")


def _respuesta(datos, codigo=0, **extra):
    return json.dumps({"smartctl_exit": codigo, "datos": datos, **extra}).encode()


def _leer(pkexec):
    return leer_salud("/dev/nvme0", ejecutar=pkexec, comprobar=lambda: [])


def test_comando_pkexec_exacto():
    assert construir_comando("/dev/nvme0") == [
        "/usr/bin/pkexec", "/usr/libexec/latido/latido-helper", "leer", "/dev/nvme0",
    ]


def test_lectura_correcta(nvme_real):
    pkexec = PkexecFalso(stdout=_respuesta(nvme_real))
    informe = _leer(pkexec)
    assert informe.estado is Estado.BUENO
    [(comando, kwargs)] = pkexec.llamadas
    assert comando == construir_comando("/dev/nvme0")
    assert kwargs.get("shell", False) is False
    assert kwargs["timeout"] > 0


def test_faltan_herramientas_no_ejecuta_pkexec():
    pkexec = PkexecFalso()
    with pytest.raises(ErrorLectura) as error:
        leer_salud("/dev/nvme0", ejecutar=pkexec, comprobar=lambda: ["Falta el ayudante de Latido (...)"])
    assert error.value.tipo is TipoError.HERRAMIENTAS
    assert "Falta el ayudante" in error.value.mensaje
    assert pkexec.llamadas == []


def test_cancelado():
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(returncode=126))
    assert error.value.tipo is TipoError.CANCELADO
    assert "Cerraste la ventana de contraseña" in error.value.mensaje


def test_no_autorizado_no_inventa_la_causa():
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(returncode=127))
    assert error.value.tipo is TipoError.NO_AUTORIZADO
    assert "no indica la causa exacta" in error.value.mensaje


@pytest.mark.parametrize("codigo, texto", [
    (2, "solo acepta discos NVMe"),
    (3, "no encontró el disco"),
    (4, "smartctl"),
    (5, "no terminó a tiempo"),
    (6, "no pudo ejecutar smartctl"),
    (1, "error inesperado (código 1)"),
])
def test_ayudante_fallo(codigo, texto):
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(returncode=codigo))
    assert error.value.tipo is TipoError.AYUDANTE
    assert texto in error.value.mensaje
    assert "No se sabe el estado del disco." in error.value.mensaje


@pytest.mark.parametrize("stdout", [b"", b"basura", b"\xff"])
def test_respuesta_del_ayudante_no_es_json(stdout):
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(stdout=stdout))
    assert error.value.tipo is TipoError.JSON_INVALIDO
    assert "no es JSON válido" in error.value.mensaje


@pytest.mark.parametrize("stdout", [b"[]", b'{"datos": {}}', b'{"smartctl_exit": 0}'])
def test_respuesta_del_ayudante_con_formato_inesperado(stdout):
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(stdout=stdout))
    assert error.value.tipo is TipoError.JSON_INVALIDO


def test_smartctl_devolvio_json_invalido_es_desconocido():
    informe = _leer(PkexecFalso(stdout=_respuesta(None, 4, salida_invalida=True)))
    assert informe.estado is Estado.DESCONOCIDO
    assert any("no es JSON válido" in m for m in informe.motivos)


def test_sin_root_a_traves_del_ayudante():
    informe = _leer(PkexecFalso(stdout=_respuesta(cargar("nvme_sin_root.json"), 2)))
    assert informe.estado is Estado.DESCONOCIDO


def test_tiempo_agotado():
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(excepcion=subprocess.TimeoutExpired("pkexec", 300)))
    assert error.value.tipo is TipoError.TIEMPO


def test_pkexec_no_se_pudo_ejecutar():
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(excepcion=FileNotFoundError(2, "x")))
    assert error.value.tipo is TipoError.AYUDANTE


# --- Modo desarrollo -----------------------------------------------------------

def test_cargar_fixture_smartctl_directo():
    assert cargar_fixture(FIXTURES / "nvme_real.json").estado is Estado.BUENO


def test_cargar_fixture_formato_del_ayudante(tmp_path, nvme_real):
    archivo = tmp_path / "respuesta.json"
    archivo.write_text(json.dumps({"smartctl_exit": 2, "datos": nvme_real}))
    assert cargar_fixture(archivo).estado is Estado.DESCONOCIDO  # el bit 1 del proceso manda


def test_cargar_fixture_errores(tmp_path):
    with pytest.raises(ErrorLectura) as error:
        cargar_fixture(tmp_path / "no-existe.json")
    assert error.value.tipo is TipoError.ARCHIVO
    roto = tmp_path / "roto.json"
    roto.write_text("{")
    with pytest.raises(ErrorLectura) as error:
        cargar_fixture(roto)
    assert error.value.tipo is TipoError.JSON_INVALIDO


# --- Argumentos ------------------------------------------------------------------

def test_argumentos():
    assert interpretar_argumentos([]) == (False, None)
    assert interpretar_argumentos(["--desde-fixture", "a.json"]) == (False, "a.json")
    assert interpretar_argumentos(["--desde-fixture=a.json"]) == (False, "a.json")
    assert interpretar_argumentos(["--ayuda"]) == (True, None)
    for malos in (["--desde-fixture"], ["--desde-fixture="], ["--otro"]):
        with pytest.raises(ErrorArgumentos):
            interpretar_argumentos(malos)


# --- El número de serie nunca aparece en mensajes de error --------------------

SERIE_FALSA = "SINTETICO-0002-ABC"


@pytest.mark.parametrize("codigo, stdout", [
    (3, b'{"serial_number": "SINTETICO-0002-ABC"}'),
    (1, b"SINTETICO-0002-ABC"),
    (0, b'{"serial_number": "SINTETICO-0002-ABC"'),  # JSON cortado
    (0, b'{"datos": {"serial_number": "SINTETICO-0002-ABC"}}'),  # formato inesperado
])
def test_serie_no_aparece_en_errores(codigo, stdout):
    with pytest.raises(ErrorLectura) as error:
        _leer(PkexecFalso(returncode=codigo, stdout=stdout))
    assert SERIE_FALSA not in error.value.mensaje
    assert SERIE_FALSA not in str(error.value)


def test_lectura_con_serie_lo_entrega_solo_en_el_informe(nvme_real):
    nvme_real["serial_number"] = SERIE_FALSA
    informe = _leer(PkexecFalso(stdout=_respuesta(nvme_real)))
    assert informe.numero_serie == SERIE_FALSA
    assert SERIE_FALSA not in repr(informe)


def test_etiqueta_de_fixture_sin_ruta_larga():
    from latido.ui.aplicacion import disco_de_fixture

    disco = disco_de_fixture("/una/ruta/muy/larga/de/prueba/nvme_real.json")
    assert disco.etiqueta == "Archivo de prueba · nvme_real.json"
    assert disco.ruta_lectura == "/una/ruta/muy/larga/de/prueba/nvme_real.json"
