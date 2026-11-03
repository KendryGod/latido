"""Pestaña Velocidad: última carpeta usada y restos de una prueba que no se limpió."""

import json
import os

import pytest

from latido.velocidad.restos import (
    ErrorResto,
    Resto,
    borrar_resto,
    buscar_restos,
    guardar_ultima_carpeta,
    leer_ultima_carpeta,
    ruta_estado,
)


def test_ruta_del_estado():
    assert ruta_estado({"XDG_STATE_HOME": "/x/estado"}) == "/x/estado/latido/velocidad.json"
    casa = os.path.expanduser("~")
    assert ruta_estado({"XDG_STATE_HOME": "relativa"}) == f"{casa}/.local/state/latido/velocidad.json"
    assert ruta_estado({}) == f"{casa}/.local/state/latido/velocidad.json"


def test_guardar_y_leer_la_ultima_carpeta(tmp_path):
    ruta = tmp_path / "estado" / "latido" / "velocidad.json"
    assert leer_ultima_carpeta(str(ruta)) is None
    guardar_ultima_carpeta("/run/media/usuario/Disco USB", str(ruta))
    assert leer_ultima_carpeta(str(ruta)) == "/run/media/usuario/Disco USB"
    assert os.listdir(ruta.parent) == ["velocidad.json"]  # sin temporales sueltos
    ruta.write_text("{roto", encoding="utf-8")
    assert leer_ultima_carpeta(str(ruta)) is None
    ruta.write_text(json.dumps({"ultima_carpeta": "relativa"}), encoding="utf-8")
    assert leer_ultima_carpeta(str(ruta)) is None


def test_las_pruebas_no_tocan_el_estado_real():
    assert ruta_estado().startswith(os.environ["XDG_STATE_HOME"])
    assert "/.local/state/" not in ruta_estado()


def _resto(carpeta, nombre, archivo=True, extra=None):
    directorio = carpeta / nombre
    directorio.mkdir()
    if archivo:
        (directorio / "latido-velocidad.dat").write_bytes(b"\0" * 4096)
    if extra:
        (directorio / extra).write_text("ajeno", encoding="utf-8")
    return directorio


def test_buscar_restos_solo_mira_esa_carpeta_y_nunca_borra(tmp_path):
    _resto(tmp_path, ".latido-velocidad-aaaa1111")
    _resto(tmp_path, ".latido-velocidad-bbbb2222", archivo=False)
    _resto(tmp_path, ".latido-velocidad-cccc3333", extra="mio.txt")
    (tmp_path / ".latido-velocidad-dddd4444").write_text("archivo, no carpeta", encoding="utf-8")
    (tmp_path / ".latido-velocidad-eeee5555").symlink_to(tmp_path / ".latido-velocidad-aaaa1111")
    _resto(tmp_path, "otra-carpeta")
    (tmp_path / "sub").mkdir()
    _resto(tmp_path / "sub", ".latido-velocidad-ffff6666")
    restos = {r.nombre: r for r in buscar_restos(str(tmp_path))}
    assert sorted(restos) == [f".latido-velocidad-{x}" for x in ("aaaa1111", "bbbb2222", "cccc3333", "dddd4444", "eeee5555")]
    assert restos[".latido-velocidad-aaaa1111"].se_puede_borrar
    assert restos[".latido-velocidad-aaaa1111"].descripcion() == (
        ".latido-velocidad-aaaa1111: contiene latido-velocidad.dat (4,096 bytes)."
    )
    assert restos[".latido-velocidad-cccc3333"].descripcion().endswith("Latido no lo borrará.")
    assert restos[".latido-velocidad-bbbb2222"].se_puede_borrar
    assert not restos[".latido-velocidad-cccc3333"].se_puede_borrar
    assert "mio.txt" in restos[".latido-velocidad-cccc3333"].motivo
    assert not restos[".latido-velocidad-dddd4444"].se_puede_borrar
    assert restos[".latido-velocidad-eeee5555"].motivo == "es un enlace simbólico"
    assert (tmp_path / ".latido-velocidad-aaaa1111" / "latido-velocidad.dat").exists()  # no borró nada
    assert buscar_restos(str(tmp_path / "no-existe")) == []
    assert buscar_restos(None) == []


def test_borrar_resto_borra_solo_lo_de_latido(tmp_path):
    _resto(tmp_path, ".latido-velocidad-aaaa1111")
    (tmp_path / "mio.txt").write_text("del usuario", encoding="utf-8")
    [resto] = buscar_restos(str(tmp_path))
    assert borrar_resto(resto) == f"Se borró {tmp_path}/.latido-velocidad-aaaa1111."
    assert sorted(os.listdir(tmp_path)) == ["mio.txt"]


def test_borrar_resto_revisa_de_nuevo_antes_de_borrar(tmp_path):
    directorio = _resto(tmp_path, ".latido-velocidad-aaaa1111")
    [resto] = buscar_restos(str(tmp_path))
    (directorio / "nuevo.txt").write_text("apareció después", encoding="utf-8")
    with pytest.raises(ErrorResto, match="nuevo.txt"):
        borrar_resto(resto)
    assert sorted(os.listdir(directorio)) == ["latido-velocidad.dat", "nuevo.txt"]


def test_borrar_resto_no_sigue_enlaces(tmp_path):
    destino = _resto(tmp_path, "destino")
    (tmp_path / ".latido-velocidad-aaaa1111").symlink_to(destino)
    [resto] = buscar_restos(str(tmp_path))
    falso = Resto(resto.carpeta, resto.nombre, ("latido-velocidad.dat",), 4096, True)
    with pytest.raises(ErrorResto, match="enlace simbólico"):
        borrar_resto(falso)
    assert (destino / "latido-velocidad.dat").exists()
