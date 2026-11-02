"""Reglas permanentes del proyecto que se pueden comprobar en el código."""

import re
from pathlib import Path

RAIZ = Path(__file__).parent.parent
CODIGO = sorted(RAIZ.glob("latido/**/*.py")) + [RAIZ / "helper" / "latido-helper"]


def test_hay_codigo():
    assert len(CODIGO) > 5


def test_sin_shell_true():
    for archivo in CODIGO:
        assert "shell=True" not in archivo.read_text(encoding="utf-8"), archivo


def test_sin_colores_hex_ni_css_propio():
    for archivo in CODIGO:
        texto = archivo.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", texto), archivo
        assert "CssProvider" not in texto, archivo


def test_sin_marca_ajena():
    prohibida = "crys" + "tal"
    for archivo in RAIZ.rglob("*"):
        if ".git" in archivo.parts or not archivo.is_file() or archivo.suffix == ".pyc":
            continue
        if archivo.name == "LICENSE":
            continue
        assert prohibida not in archivo.read_text(encoding="utf-8", errors="ignore").lower(), archivo
