"""El ID de aplicación es io.github.kendrygod.latido en todas partes."""

import configparser
import os
import stat
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
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


# El ID viejo se arma por partes para que este archivo no se encuentre a sí mismo.
ID_VIEJO = "io.github.kendrygod." + "Latido"

# No son parte del proyecto: los genera git, Python, pytest o setuptools.
CARPETAS_IGNORADAS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".venv", "venv", "build", "dist",
}


@dataclass
class Busqueda:
    revisados: list = field(default_factory=list)    # archivos leídos
    coincidencias: list = field(default_factory=list)
    ilegibles: list = field(default_factory=list)    # (archivo, error): no se sabe si contienen el texto
    omitidos: list = field(default_factory=list)     # enlaces simbólicos y archivos especiales: no se abren


def buscar_texto(raiz, texto):
    """Busca texto (sensible a mayúsculas) en todos los archivos bajo raiz, sin git.

    Compara bytes: un archivo binario no rompe la búsqueda, y en un archivo de
    texto UTF-8 buscar los bytes del texto equivale a buscar el texto.
    """
    buscado = texto.encode("utf-8")
    resultado = Busqueda()
    for carpeta, subcarpetas, archivos in os.walk(raiz, onerror=lambda e: resultado.ilegibles.append((e.filename, e))):
        subcarpetas[:] = sorted(
            d for d in subcarpetas if d not in CARPETAS_IGNORADAS and not d.endswith(".egg-info")
        )
        for nombre in sorted(archivos):
            ruta = Path(carpeta) / nombre
            try:
                modo = ruta.lstat().st_mode
                if not stat.S_ISREG(modo):
                    resultado.omitidos.append(ruta)
                    continue
                contenido = ruta.read_bytes()
            except OSError as error:
                resultado.ilegibles.append((ruta, error))
                continue
            resultado.revisados.append(ruta)
            if buscado in contenido:
                resultado.coincidencias.append(ruta)
    return resultado


def test_no_queda_el_id_viejo():
    resultado = buscar_texto(RAIZ, ID_VIEJO)
    revisados = {p.relative_to(RAIZ).as_posix() for p in resultado.revisados}
    # Si el recorrido no vio nada (o no vio estos), la prueba no pasa en vacío.
    for esperado in ("README.md", "packaging/latido.spec", "latido/ui/aplicacion.py",
                     f"data/{ID}.desktop", f"data/{ID}.metainfo.xml", "tests/test_identificador.py"):
        assert esperado in revisados, f"el recorrido no revisó {esperado}"
    assert resultado.ilegibles == [], f"no pude leer: {resultado.ilegibles}"
    assert resultado.coincidencias == [], f"queda el ID viejo en: {resultado.coincidencias}"


def test_la_busqueda_detecta_el_id_viejo(tmp_path):
    (tmp_path / "limpio.txt").write_text(f"{ID}\n", encoding="utf-8")
    (tmp_path / "con_id.desktop").write_text(f"Icon={ID_VIEJO}\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "binario.bin").write_bytes(b"\x00\xff\xfe" + ID_VIEJO.encode() + b"\x00\x80")
    (tmp_path / "sub" / "binario_limpio.bin").write_bytes(b"\x00\xff\xfe\x80" * 10)

    resultado = buscar_texto(tmp_path, ID_VIEJO)

    assert sorted(p.name for p in resultado.coincidencias) == ["binario.bin", "con_id.desktop"]
    assert len(resultado.revisados) == 4
    assert resultado.ilegibles == []


def test_la_busqueda_distingue_mayusculas(tmp_path):
    (tmp_path / "minusculas.txt").write_text(ID_VIEJO.lower(), encoding="utf-8")
    resultado = buscar_texto(tmp_path, ID_VIEJO)
    assert resultado.revisados and resultado.coincidencias == []


def test_la_busqueda_ignora_carpetas_generadas(tmp_path):
    for carpeta in (".git", "__pycache__", ".pytest_cache", "build", "latido.egg-info"):
        (tmp_path / carpeta).mkdir()
        (tmp_path / carpeta / "x").write_text(ID_VIEJO, encoding="utf-8")
    (tmp_path / "a.txt").write_text("nada", encoding="utf-8")

    resultado = buscar_texto(tmp_path, ID_VIEJO)

    assert [p.name for p in resultado.revisados] == ["a.txt"]
    assert resultado.coincidencias == []


def test_la_busqueda_en_carpeta_vacia_no_revisa_nada(tmp_path):
    resultado = buscar_texto(tmp_path, ID_VIEJO)
    assert resultado == Busqueda()


def test_la_busqueda_distingue_ilegible_de_sin_coincidencias(tmp_path, monkeypatch):
    # Se simula el error en vez de usar chmod: en la CI las pruebas corren como root.
    (tmp_path / "ilegible.txt").write_text(ID_VIEJO, encoding="utf-8")
    (tmp_path / "legible.txt").write_text("nada", encoding="utf-8")
    leer = Path.read_bytes

    def leer_falso(ruta):
        if ruta.name == "ilegible.txt":
            raise PermissionError(13, "Permiso denegado", str(ruta))
        return leer(ruta)

    monkeypatch.setattr(Path, "read_bytes", leer_falso)
    resultado = buscar_texto(tmp_path, ID_VIEJO)

    assert [p.name for p in resultado.revisados] == ["legible.txt"]
    assert resultado.coincidencias == []
    assert [(p.name, type(e)) for p, e in resultado.ilegibles] == [("ilegible.txt", PermissionError)]


def test_la_busqueda_no_sigue_enlaces_simbolicos(tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "objetivo.txt").write_text(ID_VIEJO, encoding="utf-8")
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / "enlace.txt").symlink_to(fuera / "objetivo.txt")
    (raiz / "carpeta_enlazada").symlink_to(fuera, target_is_directory=True)

    resultado = buscar_texto(raiz, ID_VIEJO)

    assert resultado.revisados == [] and resultado.coincidencias == []
    assert [p.name for p in resultado.omitidos] == ["enlace.txt"]
