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


def test_sin_colores_hex():
    for archivo in CODIGO:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", archivo.read_text(encoding="utf-8")), archivo


def test_css_propio_solo_en_estilo_y_sin_hex():
    from latido.ui.estilo import CSS

    assert "#" not in CSS
    assert not re.search(r"\b(rgb|rgba|hsl|hsla|color-mix)\(", CSS)
    for archivo in CODIGO:
        if "CssProvider" in archivo.read_text(encoding="utf-8"):
            assert archivo.name == "estilo.py", archivo


def test_estados_sin_clases_de_color_de_libadwaita():
    texto = (RAIZ / "latido" / "ui" / "pagina_salud.py").read_text(encoding="utf-8")
    for clase in ('"accent"', '"warning"', '"error"', '"dim-label"'):
        assert clase not in texto, clase


def test_sin_marca_ajena():
    prohibida = "crys" + "tal"
    for archivo in RAIZ.rglob("*"):
        if ".git" in archivo.parts or not archivo.is_file() or archivo.suffix == ".pyc":
            continue
        if archivo.name == "LICENSE":
            continue
        assert prohibida not in archivo.read_text(encoding="utf-8", errors="ignore").lower(), archivo


def test_cada_estado_define_fondo_texto_y_paleta_de_iconos():
    from latido.ui.estilo import CSS

    for clase in ("bueno", "precaucion", "malo", "desconocido"):
        bloque = re.search(r"\.latido-%s \{([^}]*)\}" % clase, CSS).group(1)
        assert re.search(r"background-color: @\w+;", bloque), clase
        texto = re.search(r"(?m)^\s*color: @(\w+);", bloque).group(1)
        assert f"-gtk-icon-palette: success @{texto}, warning @{texto}, error @{texto};" in bloque, clase


def test_latido_no_pone_prefer_dark_theme():
    """El esquema de color sigue al sistema con Adw.StyleManager: Latido nunca toca
    GtkSettings:gtk-application-prefer-dark-theme (libadwaita avisa que no está soportado)."""
    for archivo in CODIGO:
        texto = archivo.read_text(encoding="utf-8")
        assert "prefer-dark-theme" not in texto and "prefer_dark_theme" not in texto, archivo
