"""Interfaz de la pestaña Velocidad, con Gdk.Display real (fixture gtk de conftest.py).

Sin pantalla se saltan con motivo; con REQUIRE_DISPLAY=1 fallan. Nunca se
ejecuta el fio real: los servicios usan tests/fio_falso.py y falsos.
"""

import os
import time

import pytest

from conftest import StatvfsFalso, descriptores_hacia, esperar, vivo
from latido.velocidad.carpeta import InfoCarpeta, Revision, revisar_carpeta
from latido.velocidad.ejecucion import Ejecucion
from latido.velocidad.herramientas import EstadoFio
from latido.velocidad.pruebas import GIB, TAMANOS, Configuracion, Direccion
from latido.velocidad.restos import guardar_ultima_carpeta


class Espia:
    def __init__(self):
        self.llamadas = []

    def __call__(self, nombre, funcion):
        def envoltura(*args, **kwargs):
            self.llamadas.append(nombre)
            return funcion(*args, **kwargs)
        return envoltura


def _revisar_con_espacio(ruta, configuracion):
    return revisar_carpeta(ruta, configuracion, statvfs=lambda _ruta: StatvfsFalso(500 * GIB))


def _servicios(fio_falso=None, estado_fio=None, revisar=_revisar_con_espacio, espia=None):
    from latido.ui.pagina_velocidad import ServiciosVelocidad

    espia = espia or Espia()
    estado_fio = estado_fio or EstadoFio("fio-3.40")

    def crear(carpeta, configuracion, al_progresar=None):
        return Ejecucion(
            carpeta, configuracion, al_progresar, fio=str(fio_falso.ruta),
            comprobar=lambda fio: estado_fio, revisar=revisar, segundos_para_terminar=1,
        )

    base = ServiciosVelocidad()
    return ServiciosVelocidad(
        comprobar_fio=espia("comprobar_fio", lambda: estado_fio),
        revisar_carpeta=espia("revisar_carpeta", revisar),
        crear_ejecucion=espia("crear_ejecucion", crear),
        leer_ultima_carpeta=espia("leer_ultima_carpeta", base.leer_ultima_carpeta),
        buscar_restos=espia("buscar_restos", base.buscar_restos),
        borrar_resto=espia("borrar_resto", base.borrar_resto),
    )


def _ventana(servicios):
    from latido.ui.ventana import VentanaPrincipal

    return VentanaPrincipal([], lambda disco: None, servicios_velocidad=servicios)


def _abrir_pestana(ventana):
    ventana.pila.set_visible_child(ventana.pagina_velocidad)
    return ventana.pagina_velocidad


@pytest.fixture
def carpeta(tmp_path):
    carpeta = tmp_path / "medir"
    carpeta.mkdir()
    return carpeta


def test_pestana_velocidad_junto_a_salud(gtk):
    from gi.repository import Gdk

    ventana = _ventana(_servicios())
    paginas = [ventana.pila.get_page(hijo) for hijo in (ventana.pagina_salud, ventana.pagina_velocidad)]
    assert [p.get_title() for p in paginas] == ["Salud", "Velocidad"]
    tema = gtk[1].IconTheme.get_for_display(Gdk.Display.get_default())
    for pagina in paginas:
        assert tema.has_icon(pagina.get_icon_name()), pagina.get_icon_name()
    assert ventana.pila.get_visible_child() is ventana.pagina_salud


def test_al_construir_no_ejecuta_nada(gtk):
    espia = Espia()
    _ventana(_servicios(espia=espia))
    assert espia.llamadas == []


def test_al_abrir_la_pestana_comprueba_fio_y_busca_restos(gtk):
    espia = Espia()
    pagina = _abrir_pestana(_ventana(_servicios(espia=espia)))
    assert espia.llamadas == ["comprobar_fio", "leer_ultima_carpeta"]
    assert pagina.fila_fio.get_subtitle() == "fio-3.40 con motor libaio"
    assert not pagina.banner.get_revealed()
    assert not pagina.boton.get_sensitive()  # falta la carpeta


def test_falta_fio_se_dice_y_no_deja_iniciar(gtk, carpeta):
    problema = "Falta fio (/usr/bin/fio). Instálalo con: sudo dnf install fio fio-engine-libaio"
    pagina = _abrir_pestana(_ventana(_servicios(estado_fio=EstadoFio(problemas=[problema]))))
    pagina.elegir_carpeta(str(carpeta))
    assert pagina.fila_fio.get_subtitle() == problema
    assert not pagina.boton.get_sensitive()
    assert pagina.vistas.get_visible_child_name() == "sin_fio"
    assert pagina.pagina_sin_fio.get_title() == "Falta fio"
    assert pagina.pagina_sin_fio.get_description() == problema


def test_sin_fio_reintentar_vuelve_a_comprobar(gtk):
    espia = Espia()
    problema = "Falta fio (/usr/bin/fio). Instálalo con: sudo dnf install fio fio-engine-libaio"
    pagina = _abrir_pestana(_ventana(_servicios(estado_fio=EstadoFio(problemas=[problema]), espia=espia)))
    pagina.boton_reintentar.emit("clicked")
    assert espia.llamadas.count("comprobar_fio") == 2


def test_resumen_antes_de_iniciar(gtk, carpeta):
    def revisar(ruta, configuracion):
        info = InfoCarpeta(ruta=ruta, tipo="btrfs", punto_montaje="/home", fuente="/dev/nvme0n1p5",
                           libre=int(366.5 * GIB), disco_sistema=True, discos=frozenset({"nvme0n1"}))
        return Revision(info=info, avisos=["aviso de desgaste", "aviso del disco del sistema"])

    pagina = _abrir_pestana(_ventana(_servicios(revisar=revisar)))
    pagina.elegir_carpeta(str(carpeta))
    assert pagina.fila_carpeta.get_subtitle() == str(carpeta)
    assert pagina.fila_libre.get_subtitle() == "366.5 GiB libres · hacen falta 2 GiB (1 GiB + 1 GiB de margen)"
    assert pagina.fila_sistema.get_subtitle() == "btrfs · /dev/nvme0n1p5 montado en /home"
    assert pagina.fila_escritura.get_subtitle() == "13 GiB (13.96 GB) como máximo"
    assert [f.get_title() for f in pagina._filas_avisos] == ["aviso de desgaste", "aviso del disco del sistema"]
    assert pagina.boton.get_sensitive() and pagina.boton.get_label() == "Iniciar"


def test_tamano_y_pasadas_por_defecto_y_al_cambiarlos(gtk, carpeta):
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert TAMANOS[pagina.fila_tamano.get_selected()] == GIB
    assert pagina.fila_pasadas.get_value() == 3
    pagina.fila_tamano.set_selected(TAMANOS.index(2 * GIB))
    pagina.fila_pasadas.set_value(1)
    assert pagina.configuracion().tamano == 2 * GIB and pagina.configuracion().pasadas == 1
    assert pagina.fila_escritura.get_subtitle() == "10 GiB (10.74 GB) como máximo"


def test_carpeta_invalida_muestra_el_error_y_no_deja_iniciar(gtk):
    pagina = _abrir_pestana(_ventana(_servicios()))
    pagina.elegir_carpeta("/dev/shm")
    assert [f.get_title() for f in pagina._filas_avisos] == [
        "Latido no hace pruebas dentro de /dev (la carpeta está en «/dev/shm»)."
    ]
    assert not pagina.boton.get_sensitive()


def test_unidades_explicadas_en_pantalla(gtk):
    pagina = _ventana(_servicios()).pagina_velocidad
    assert "MB/s = 1,000,000 bytes por segundo" in pagina.nota.get_text()
    assert "no se guardan" in pagina.nota.get_text()
    assert [c.prueba.nombre for c in pagina.cuadros.values()] == ["SEQ1M Q8T1", "SEQ1M Q1T1", "RND4K Q32T1", "RND4K Q1T1"]


def test_rejilla_de_resultados_lectura_y_escritura(gtk):
    from gi.repository import Gtk

    pagina = _ventana(_servicios()).pagina_velocidad
    assert isinstance(pagina.rejilla, Gtk.Grid)
    assert [e.get_text() for e in pagina.encabezados] == ["Lectura", "Escritura"]
    for fila in pagina.cuadros.values():
        for celda in fila.columnas.values():
            assert {"numeric", "title-1"} <= set(celda.valor.get_css_classes())
            assert celda.unidad.get_text() == "MB/s"
            assert isinstance(celda.barra, Gtk.LevelBar)
            # Sin los umbrales de GTK: si no, una barra corta sale con el color de advertencia y una llena, verde.
            assert not any(celda.barra.get_offset_value(nombre)[0] for nombre in ("low", "high", "full"))
            assert celda.valor.get_text() == "—" and celda.barra.get_value() == 0
            assert not celda.unidad.get_visible()  # «—» solo, no «— MB/s»
            assert not celda.estado.get_visible()  # antes de la primera prueba no dice nada


def test_descripciones_sin_separar_numero_y_unidad(gtk):
    """En la captura de 720 px se leía «bloques de 4» y en la línea siguiente «KiB»."""
    pagina = _ventana(_servicios()).pagina_velocidad
    textos = [fila.descripcion.get_text() for fila in pagina.cuadros.values()]
    assert textos[0] == "Secuencial · bloques de 1\u00a0MiB · cola\u00a08 · 1\u00a0hilo"
    assert textos[2] == "Aleatoria · bloques de 4\u00a0KiB · cola\u00a032 · 1\u00a0hilo"


def test_barras_relativas_al_mejor_resultado(gtk):
    from latido import demo

    pagina = _ventana(_servicios()).pagina_velocidad
    pagina.mostrar_resultado(demo.velocidad_demo().resultado)

    def barra(clave, direccion):
        return pagina.cuadros[clave].columnas[direccion].barra.get_value()

    assert barra("seq1m-q8t1", Direccion.LECTURA) == pytest.approx(1.0)  # 3,400 MB/s: el más alto
    assert barra("seq1m-q8t1", Direccion.ESCRITURA) == pytest.approx(2900 / 3400)
    assert barra("rnd4k-q1t1", Direccion.LECTURA) == pytest.approx(62 / 3400)


def test_progreso_paso_n_de_8(gtk):
    from latido.ui.pagina_velocidad import texto_del_paso

    configuracion = Configuracion(GIB, 3)
    textos = [texto_del_paso(paso, configuracion) for paso in configuracion.pasos()]
    assert textos[0] == "Preparando el archivo de prueba (escribe 1 GiB)"
    assert textos[1] == "Paso 1 de 8: SEQ1M Q8T1 · lectura · pasada 1 de 3"
    assert textos[6] == "Paso 2 de 8: SEQ1M Q8T1 · escritura · pasada 3 de 3"
    assert textos[-1] == "Paso 8 de 8: RND4K Q1T1 · escritura · pasada 3 de 3"
    numeros = [int(texto.split()[1]) for texto in textos[1:]]
    assert numeros == sorted(numeros) and sorted(set(numeros)) == list(range(1, 9)) and len(numeros) == 24


def test_progreso_en_pantalla(gtk):
    from latido.velocidad.ejecucion import Progreso
    from latido.velocidad.resultado import ResultadoVelocidad

    pagina = _ventana(_servicios()).pagina_velocidad
    configuracion = Configuracion(GIB, 3)
    pagina._configuracion_en_marcha = configuracion
    pagina._parcial = ResultadoVelocidad(3)
    pasos = configuracion.pasos()
    pagina._mostrar_progreso(Progreso(5, len(pasos), pasos[5]))
    assert pagina.etiqueta_paso.get_text() == "Paso 2 de 8: SEQ1M Q8T1 · escritura · pasada 2 de 3"
    assert pagina.progreso.get_fraction() == pytest.approx(5 / 25)
    assert not pagina.progreso.get_show_text()  # el texto va en una etiqueta que se ajusta: nunca se corta
    celda = pagina.cuadros["seq1m-q8t1"].columnas[Direccion.ESCRITURA]
    assert celda.estado.get_visible() and celda.estado.get_text() == "Midiendo… pasada 2 de 3"


def test_angosto_numeros_un_poco_mas_chicos(gtk):
    """Por debajo de 560sp el Adw.Breakpoint cambia title-1 por title-2 en los ocho números, para que quepan."""
    GLib, _ = gtk
    ventana = _ventana(_servicios())
    celdas = [c for f in ventana.pagina_velocidad.cuadros.values() for c in f.columnas.values()]
    assert all(c.valor.get_css_classes() == ["title-1", "numeric"] for c in celdas)
    ventana.set_default_size(400, 700)
    ventana.present()
    try:
        esperar(GLib, lambda: ventana.get_current_breakpoint() is ventana.angosto, 5)
        assert ventana.get_current_breakpoint() is ventana.angosto
        assert all(c.valor.get_css_classes() == ["title-2", "numeric"] for c in celdas)
    finally:
        ventana.destroy()


def test_orden_configuracion_boton_mensaje_y_resultados(gtk):
    """El mensaje de limpieza queda entre el botón y los resultados: se ve al terminar."""
    pagina = _ventana(_servicios()).pagina_velocidad
    caja = pagina.boton.get_parent()
    hijos, hijo = [], caja.get_first_child()
    while hijo is not None:
        hijos.append(hijo)
        hijo = hijo.get_next_sibling()
    orden = [hijos.index(w) for w in (pagina.grupo_resumen, pagina.boton, pagina.zona_progreso, pagina.caja_mensaje,
                                      pagina.resultados, pagina.nota)]
    assert orden == sorted(orden)


def test_prueba_completa_con_fio_falso(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    assert pagina.en_marcha and pagina.boton.get_label() == "Cancelar"
    assert not pagina.boton_carpeta.get_sensitive()
    esperar(GLib, lambda: not pagina.en_marcha, 30)
    assert not pagina.en_marcha
    lectura = pagina.cuadros["seq1m-q8t1"].columnas[Direccion.LECTURA]
    assert lectura.valor.get_text() == "200.00"  # promedio de 100, 200 y 300 MB/s
    assert lectura.iops.get_text() == "191 IOPS"
    assert lectura.latencia.get_text() == "2.00 ms"  # el fio falso da 1, 2 y 3 ms
    assert lectura.unidad.get_visible()
    assert lectura.extremos.get_text() == "Mejor 300.00 · peor 100.00"
    assert lectura.barra.get_value() == pytest.approx(1.0)  # el fio falso da lo mismo en las ocho
    aleatoria = pagina.cuadros["rnd4k-q32t1"].columnas[Direccion.ESCRITURA]
    assert aleatoria.iops.get_text() == "48,828 IOPS"  # 200 MB/s en bloques de 4 KiB
    assert pagina.mensaje.get_text() == "Prueba terminada. Se borraron el archivo de prueba y su carpeta temporal."
    assert pagina.caja_mensaje.get_visible() and pagina.icono_mensaje.get_icon_name() == "object-select-symbolic"
    assert not pagina.zona_progreso.get_visible()
    assert pagina.boton.get_label() == "Iniciar" and pagina.boton.get_sensitive()
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []


def _esperar_que_duerma(GLib, fio_falso):
    esperar(GLib, lambda: bool(fio_falso.hijos()), 10)
    assert fio_falso.hijos()
    return fio_falso.invocaciones()[-1]["pid"], fio_falso.hijos()[-1]


def test_cancelar_desde_la_interfaz_detiene_fio_y_limpia(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["ok", "duerme"])
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    principal, hijo = _esperar_que_duerma(GLib, fio_falso)
    pagina.boton.emit("clicked")  # Cancelar
    assert pagina.boton.get_label() == "Cancelando…" and not pagina.boton.get_sensitive()
    esperar(GLib, lambda: not pagina.en_marcha, 20)
    assert pagina.mensaje.get_text() == "Prueba cancelada. Se borraron el archivo de prueba y su carpeta temporal."
    assert pagina.icono_mensaje.get_icon_name() == "dialog-information-symbolic"
    assert pagina.cuadros["seq1m-q8t1"].columnas[Direccion.LECTURA].estado.get_text() == "Sin resultado"
    assert not vivo(principal) and not vivo(hijo)
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []


def test_error_de_fio_se_muestra_tal_cual(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["falla"])
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    esperar(GLib, lambda: not pagina.en_marcha, 20)
    assert pagina.mensaje.get_text() == (
        "fio falló en «Preparando el archivo de prueba».\n"
        "fio terminó con el código 1. Mensaje de fio:\n"
        "fio: error inventado por el fio falso (err=22/Invalid argument)\n"
        # fio se lanzó y falló en la preparación. El falso falla antes de crear el archivo, pero Latido no tiene
        # descriptor y no lo sabe: solo ve que no había archivo.
        "Se borró la carpeta temporal; no había archivo de prueba (fio no llegó a crearlo, o lo borró otro programa)."
    )
    assert pagina.icono_mensaje.get_icon_name() == "dialog-warning-symbolic"
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []


def test_cerrar_la_ventana_en_plena_prueba_pide_confirmacion_y_limpia(gtk, carpeta, fio_falso):
    GLib, _ = gtk
    fio_falso.configurar(["ok", "duerme"])
    ventana = _ventana(_servicios(fio_falso))
    ventana.realize()  # Gtk.Window.close() no hace nada en una ventana sin realizar
    pagina = _abrir_pestana(ventana)
    cierres = []
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    principal, hijo = _esperar_que_duerma(GLib, fio_falso)

    ventana.close()  # emite close-request: se bloquea y pregunta
    from gi.repository import Adw

    assert isinstance(ventana.dialogo_cerrar, Adw.AlertDialog)
    assert pagina.en_marcha and vivo(principal)
    ventana.responder_cierre(ventana.dialogo_cerrar, "seguir")
    assert pagina.en_marcha and vivo(principal)  # "Seguir midiendo" no toca nada

    ventana.connect("close-request", lambda _v: cierres.append(time.monotonic()) or False)
    ventana.close()
    ventana.responder_cierre(ventana.dialogo_cerrar, "cerrar")
    esperar(GLib, lambda: bool(cierres), 20)
    assert cierres, "la ventana no se cerró después de limpiar"
    assert not pagina.en_marcha
    assert not vivo(principal) and not vivo(hijo)
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []


def test_cerrar_sin_prueba_no_pregunta(gtk):
    ventana = _ventana(_servicios())
    ventana.realize()
    cierres = []
    ventana.connect("close-request", lambda _v: cierres.append(1) or False)
    ventana.close()
    assert cierres == [1] and ventana.dialogo_cerrar is None


def _resto(carpeta, nombre=".latido-velocidad-abcd1234"):
    resto = carpeta / nombre
    resto.mkdir()
    (resto / "latido-velocidad.dat").write_bytes(b"\0" * 4096)
    return resto


def test_restos_de_la_ultima_carpeta_se_avisan_y_solo_se_borran_al_confirmar(gtk, carpeta):
    resto = _resto(carpeta)
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert pagina.banner.get_revealed()
    assert str(carpeta) in pagina.banner.get_title()
    assert resto.exists()  # avisar no borra

    pagina.banner.emit("button-clicked")
    assert pagina.dialogo_restos is not None
    pagina.responder_restos(pagina.dialogo_restos, "cancelar")
    assert resto.exists()

    pagina.banner.emit("button-clicked")
    pagina.responder_restos(pagina.dialogo_restos, "borrar")
    assert not resto.exists()
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []
    assert pagina.mensaje.get_text() == f"Se borró {resto}."
    assert not pagina.banner.get_revealed()


def test_restos_ajenos_no_se_ofrecen_para_borrar(gtk, carpeta):
    resto = _resto(carpeta)
    (resto / "mio.txt").write_text("del usuario", encoding="utf-8")
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert pagina.banner.get_revealed()
    pagina.banner.emit("button-clicked")
    assert not pagina.dialogo_restos.get_response_enabled("borrar")
    pagina.responder_restos(pagina.dialogo_restos, "borrar")
    assert sorted(os.listdir(resto)) == ["latido-velocidad.dat", "mio.txt"]


def test_solo_revisa_la_ultima_carpeta_usada(gtk, tmp_path, carpeta):
    otra = tmp_path / "otra"
    otra.mkdir()
    _resto(otra)
    guardar_ultima_carpeta(str(carpeta))
    pagina = _abrir_pestana(_ventana(_servicios()))
    assert not pagina.banner.get_revealed()


def test_al_salir_de_la_app_se_detiene_fio_y_se_espera_la_limpieza(gtk, carpeta, fio_falso):
    """Lo que hace Aplicacion.do_shutdown (por ejemplo, con Ctrl+C en la terminal)."""
    GLib, _ = gtk
    fio_falso.configurar(["ok", "duerme"])
    pagina = _abrir_pestana(_ventana(_servicios(fio_falso)))
    pagina.elegir_carpeta(str(carpeta))
    pagina.boton.emit("clicked")
    principal, hijo = _esperar_que_duerma(GLib, fio_falso)
    pagina.detener_y_esperar(20)  # bloquea hasta que el hilo de la prueba termina de limpiar
    assert not pagina._hilo.is_alive()
    assert not vivo(principal) and not vivo(hijo)
    assert os.listdir(carpeta) == []
    assert descriptores_hacia(carpeta) == []


def test_la_aplicacion_detiene_cada_ventana_al_salir(gtk, monkeypatch):
    from gi.repository import Adw

    from latido.ui.aplicacion import Aplicacion

    llamadas = []

    class Pagina:
        def detener_y_esperar(self):
            llamadas.append("detener")

    class Ventana:
        pagina_velocidad = Pagina()

    aplicacion = Aplicacion(ruta_fixture="x")
    monkeypatch.setattr(aplicacion, "get_windows", lambda: [Ventana(), Ventana()])
    monkeypatch.setattr(Adw.Application, "do_shutdown", lambda self: llamadas.append("adw"))
    Aplicacion.do_shutdown(aplicacion)
    assert llamadas == ["detener", "detener", "adw"]  # primero limpia, luego el cierre normal
