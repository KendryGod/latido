"""docs/velocidad.md y el README dicen lo mismo que el código."""

from pathlib import Path

from latido.velocidad import formato
from latido.velocidad.ejecucion import SEGUNDOS_MAXIMOS_MEDICION, SEGUNDOS_PARA_TERMINAR
from latido.velocidad.pruebas import (
    ARCHIVO_PRUEBA,
    PREFIJO_DIRECTORIO,
    PRUEBAS,
    SEGUNDOS_POR_MEDICION,
    Configuracion,
    construir_comando,
)

RAIZ = Path(__file__).parent.parent
DOC = (RAIZ / "docs" / "velocidad.md").read_text(encoding="utf-8")
README = (RAIZ / "README.md").read_text(encoding="utf-8")
ARCHIVO = f"/x/{PREFIJO_DIRECTORIO}abc/{ARCHIVO_PRUEBA}"


def test_cada_opcion_del_comando_esta_documentada():
    opciones = set()
    for paso in Configuracion(pasadas=1).pasos():
        for argumento in construir_comando(paso, ARCHIVO, 2**30)[1:]:
            opciones.add(argumento.split("=")[0])
    assert opciones == {
        "--output-format", "--eta", "--readonly", "--name", "--filename", "--ioengine", "--direct", "--rw",
        "--bs", "--iodepth", "--numjobs", "--size", "--runtime", "--allow_file_create",
    }
    for opcion in opciones:
        assert f"`{opcion}" in DOC, opcion


def test_valores_documentados():
    maximo = Configuracion().escritura_maxima
    assert f"**{formato.tamano(maximo)} ({formato.gigabytes(maximo)})**" in DOC
    assert "escritura máxima = tamaño × (1 + 4 × pasadas)" in DOC
    assert f"`runtime={SEGUNDOS_POR_MEDICION}`" in DOC
    assert f"más de {SEGUNDOS_MAXIMOS_MEDICION} s" in DOC
    assert f"SIGTERM, {SEGUNDOS_PARA_TERMINAR} s de espera, SIGKILL" in DOC
    assert ARCHIVO_PRUEBA in DOC and PREFIJO_DIRECTORIO in DOC
    assert "**margen = 1 GiB o el 10 % del tamaño, lo que sea mayor**" in DOC
    assert "MB/s = 1,000,000 bytes por segundo" in DOC
    for prueba in PRUEBAS:
        assert prueba.nombre in DOC


def test_readme_pide_fio_y_libaio():
    assert "fio fio-engine-libaio" in README
    assert "docs/velocidad.md" in README
