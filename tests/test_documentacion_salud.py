"""El orden de las secciones de Salud en docs/diseno.md es el de la pantalla y el del informe TXT."""

from datetime import datetime
from pathlib import Path

from conftest import cargar
from latido.informe_txt import construir_texto
from latido.salud import analizar
from latido.sistema.discos import Disco

RAIZ = Path(__file__).parent.parent
DISENO = (RAIZ / "docs" / "diseno.md").read_text(encoding="utf-8")

# Cómo nombra docs/diseno.md cada sección de Salud.
NOMBRE_EN_EL_DOC = {
    "veredicto": "tarjeta del veredicto",
    "por qué": "«Por qué»",
    "cifras": "cifras clave",
    "autenticidad": "autenticidad",
    "datos": "«Todos los datos»",
}


def _disco():
    return Disco(nombre="nvme0n1", ruta="/dev/nvme0n1", ruta_lectura="/dev/nvme0", modelo="DISCO", tamano=10**12,
                 transporte="nvme", es_sistema=False, habilitado=True, aviso=None)


def _vinetas_de_salud():
    """Las viñetas que cuelgan de la viñeta «Salud» en la sección Estructura."""
    lineas = DISENO.splitlines()
    inicio = next(i for i, linea in enumerate(lineas) if linea.startswith("- **Salud"))
    vinetas = []
    for linea in lineas[inicio + 1:]:
        if linea.startswith("  - "):
            vinetas.append(linea[4:])
        elif linea.startswith("    ") and vinetas:
            vinetas[-1] += " " + linea.strip()
        else:
            break
    return vinetas


def _secciones_de(texto):
    """Las secciones que nombra un texto, en el orden en que aparecen."""
    posiciones = {clave: texto.find(nombre) for clave, nombre in NOMBRE_EN_EL_DOC.items()}
    return sorted((clave for clave, posicion in posiciones.items() if posicion >= 0), key=posiciones.get)


def orden_documentado():
    return [clave for vineta in _vinetas_de_salud() for clave in _secciones_de(vineta)]


def orden_del_informe_txt():
    lineas = construir_texto(analizar(cargar("nvme_real.json")), _disco(), fecha=datetime(2026, 11, 3)).splitlines()
    salud = next(i for i, linea in enumerate(lineas) if linea.startswith("SALUD:"))
    posiciones = {
        "veredicto": salud,
        "por qué": lineas.index("  Por qué:", salud),
        "cifras": lineas.index("CIFRAS CLAVE"),
        "autenticidad": next(i for i, linea in enumerate(lineas) if linea.startswith("AUTENTICIDAD:")),
        "datos": lineas.index("TODOS LOS DATOS"),
    }
    return sorted(posiciones, key=posiciones.get)


def orden_de_la_pantalla():
    from latido.ui.ventana import VentanaPrincipal

    pagina = VentanaPrincipal([_disco()], lambda disco: None).pagina_salud
    hijos, hijo = [], pagina.contenido.get_first_child()
    while hijo is not None:
        hijos.append(hijo)
        hijo = hijo.get_next_sibling()
    tarjeta = pagina.insignia
    while tarjeta.get_parent() is not pagina.contenido:
        tarjeta = tarjeta.get_parent()
    widgets = {
        "veredicto": tarjeta,
        "por qué": pagina.grupo_motivos,
        "cifras": pagina.grid_cifras,
        "autenticidad": pagina.grupo_autenticidad,
        "datos": pagina.expansor,
    }
    return sorted(widgets, key=lambda clave: hijos.index(widgets[clave]))


def test_el_orden_documentado_es_el_del_informe_txt():
    assert orden_documentado() == orden_del_informe_txt()


def test_el_orden_documentado_es_el_de_la_pantalla(gtk):
    assert orden_documentado() == orden_de_la_pantalla()


def test_una_vineta_por_seccion_en_el_orden_real():
    assert [_secciones_de(vineta) for vineta in _vinetas_de_salud()] == [
        ["veredicto"], ["por qué"], ["cifras"], ["autenticidad"], ["datos"],
    ]
