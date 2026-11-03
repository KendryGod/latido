"""docs/velocidad.md y el README dicen lo mismo que el código."""

import re
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


def test_el_comando_para_probar_en_btrfs_nombra_todas_las_pruebas_de_velocidad():
    """Cada archivo que nombra existe, y no falta ninguno de Velocidad ni de los simuladores."""
    seccion = DOC.split("## Probar en btrfs", 1)[1]
    nombrados = set(re.findall(r"tests/test_[a-z_]+\.py", seccion))
    for archivo in nombrados:
        assert (RAIZ / archivo).is_file(), archivo
    de_velocidad = {
        f"tests/{ruta.name}" for patron in ("test_*velocidad*.py", "test_simulador_*.py")
        for ruta in (RAIZ / "tests").glob(patron)
    }
    assert de_velocidad - {"tests/test_documentacion_velocidad.py"} <= nombrados
    assert "D=$(mktemp -d ~/.cache/latido-dev-btrfs-XXXXXXXX)" in seccion
    assert 'python3 -m pytest -q -p no:cacheprovider --basetemp="$D/suite"' in seccion
