"""El workflow de CI: runner fijo, checkout con node24 y pruebas con pantalla obligatoria.

Se revisa como texto para no depender de PyYAML en el contenedor de la CI.
"""

import re
from pathlib import Path

CI = (Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_runner_fijo():
    assert re.search(r"^    runs-on: ubuntu-24\.04$", CI, re.M)
    assert re.findall(r"runs-on: (\S+)", CI) == ["ubuntu-24.04"]


def test_contenedor_fedora_44():
    assert re.search(r"^    container: fedora:44$", CI, re.M)


def test_checkout_con_node24():
    assert re.findall(r"uses: (actions/checkout@\S+)", CI) == ["actions/checkout@v5"]


def test_pruebas_con_pantalla_obligatoria():
    assert 'REQUIRE_DISPLAY: "1"' in CI
    assert "xvfb-run -a python3 -m pytest -v" in CI
    assert "python3 -m pyflakes latido tests helper/latido-helper" in CI


def test_dependencias_de_las_pruebas_de_interfaz():
    for paquete in ("xorg-x11-server-Xvfb", "gtk4", "libadwaita", "adwaita-icon-theme", "git"):
        assert re.search(rf"\b{re.escape(paquete)}\b", CI), paquete
