"""El ID de aplicación es io.github.kendrygod.latido en todas partes."""

import configparser
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).parent.parent
ID = "io.github.kendrygod.latido"
DATA = RAIZ / "data"


def test_id_en_minusculas():
    assert ID == ID.lower()


def test_application_id():
    import ast

    arbol = ast.parse((RAIZ / "latido" / "ui" / "aplicacion.py").read_text(encoding="utf-8"))
    valores = [n.value.value for n in ast.walk(arbol)
               if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ID_APLICACION" for t in n.targets)]
    assert valores == [ID]


def test_archivos_de_data():
    assert sorted(p.name for p in DATA.iterdir()) == [
        f"{ID}.desktop",
        f"{ID}.metainfo.xml",
        f"{ID}.policy",  # la política conserva su nombre: está instalada como root
    ]


def test_metainfo_apunta_al_desktop():
    raiz = ET.parse(DATA / f"{ID}.metainfo.xml").getroot()
    assert raiz.findtext("id") == ID
    assert raiz.find("launchable").text == f"{ID}.desktop"


def test_desktop():
    desktop = configparser.ConfigParser(interpolation=None)
    desktop.optionxform = str
    desktop.read(DATA / f"{ID}.desktop", encoding="utf-8")
    entrada = desktop["Desktop Entry"]
    assert entrada["Exec"] == "latido"
    assert entrada["Categories"] == "System;Monitor;"


def test_politica_y_accion_sin_cambios():
    texto = (DATA / f"{ID}.policy").read_text(encoding="utf-8")
    assert '<action id="io.github.kendrygod.latido.leer-salud">' in texto
    assert "/usr/libexec/latido/latido-helper" in texto


def test_no_queda_el_id_viejo():
    viejo = "io.github.kendrygod." + "Latido"
    salida = subprocess.run(["git", "grep", "-l", "-F", viejo], cwd=RAIZ, capture_output=True, text=True)
    assert salida.returncode == 1 and salida.stdout == "", (salida.returncode, salida.stdout)
