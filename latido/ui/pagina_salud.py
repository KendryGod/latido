"""Pestaña "Salud": selector de disco, panel de estado y registro NVMe."""

import threading
import traceback

from gi.repository import Adw, GLib, Gtk, Pango

from latido.salud import Estado, formato
from latido.sistema.lectura import ErrorLectura, TipoError

# Estado: (texto, clase de latido/ui/estilo.py, ícono simbólico, frase).
# El ícono y el texto hacen que el color no sea la única señal.
APARIENCIA = {
    Estado.BUENO: ("BUENO", "latido-bueno", "object-select-symbolic", "Sin señales de daño en los datos SMART."),
    Estado.PRECAUCION: (
        "PRECAUCIÓN", "latido-precaucion", "dialog-warning-symbolic", "Hay señales de riesgo. Revisa los motivos."
    ),
    Estado.MALO: ("MALO", "latido-malo", "dialog-error-symbolic", "El disco reporta fallas. Mejor evítalo."),
    Estado.DESCONOCIDO: (
        "DESCONOCIDO", "latido-desconocido", "dialog-question-symbolic", "No hay datos suficientes para opinar."
    ),
}
CLASES_ESTADO = [clase for _, clase, _, _ in APARIENCIA.values()]

FILAS_RESUMEN = [
    ("vida", "Vida restante"),
    ("temperatura", "Temperatura"),
    ("horas", "Horas encendido"),
    ("ciclos", "Ciclos de encendido"),
    ("tb_escritos", "Datos escritos"),
    ("tb_leidos", "Datos leídos"),
]

NOTA = (
    "SMART mide el daño que el disco ha acumulado; no predice fallas. "
    "Las reglas de color son criterio propio de Latido."
)


def _fila(titulo, subtitulo=None):
    fila = Adw.ActionRow(title=titulo, use_markup=False)
    if subtitulo:
        fila.set_subtitle(subtitulo)
    return fila


def _detalle_temperatura(informe):
    umbrales = []
    if informe.temperatura_advertencia is not None:
        umbrales.append(f"advertencia a {formato.temperatura(informe.temperatura_advertencia)}")
    if informe.temperatura_critica is not None:
        umbrales.append(f"crítica a {formato.temperatura(informe.temperatura_critica)}")
    if not umbrales:
        return None
    return "Umbrales del propio disco: " + ", ".join(umbrales)


FILAS_DISCO = [
    ("modelo", "Modelo"),
    ("serie", "Número de serie"),
    ("firmware", "Firmware"),
    ("capacidad", "Capacidad"),
    ("interfaz", "Interfaz"),
]


def _texto_interfaz(informe, disco):
    protocolo = informe.protocolo
    transporte = disco.transporte if disco else None
    if protocolo and transporte and transporte.lower() != protocolo.lower():
        return f"{protocolo} (conexión {transporte.upper()})"
    if protocolo:
        return protocolo
    return transporte.upper() if transporte else formato.NO_DISPONIBLE


def textos_disco(informe, disco=None):
    """Datos de identificación del disco. El número de serie solo va a la pantalla."""
    return {
        "modelo": informe.modelo or formato.NO_DISPONIBLE,
        "serie": informe.numero_serie or formato.NO_DISPONIBLE,
        "firmware": informe.firmware or formato.NO_DISPONIBLE,
        "capacidad": formato.capacidad(informe.capacidad),
        "interfaz": _texto_interfaz(informe, disco),
    }


def _fabrica_selector(elipsis):
    """Etiquetas del selector: con elipsis en el botón para que no ensanche la ventana."""
    fabrica = Gtk.SignalListItemFactory()

    def preparar(_fabrica, elemento):
        etiqueta = Gtk.Label(xalign=0)
        if elipsis:
            etiqueta.set_ellipsize(Pango.EllipsizeMode.END)
        elemento.set_child(etiqueta)

    fabrica.connect("setup", preparar)
    fabrica.connect("bind", lambda _f, elemento: elemento.get_child().set_text(elemento.get_item().get_string()))
    return fabrica


def textos_resumen(informe):
    """Para cada fila del resumen: (valor, detalle o None)."""
    return {
        "vida": (
            formato.porcentaje(informe.vida_pct),
            None if informe.uso_pct is None else f"Desgaste reportado: {informe.uso_pct} %",
        ),
        "temperatura": (formato.temperatura(informe.temperatura), _detalle_temperatura(informe)),
        "horas": (formato.entero(informe.horas), None),
        "ciclos": (formato.entero(informe.ciclos), None),
        "tb_escritos": (formato.terabytes(informe.tb_escritos), None),
        "tb_leidos": (formato.terabytes(informe.tb_leidos), None),
    }


def _etiqueta_valor(texto, ancho=24):
    """Valor a la derecha de una fila: en una línea si es corto; si no, con ajuste."""
    etiqueta = Gtk.Label(label=texto, xalign=1, justify=Gtk.Justification.RIGHT)
    if len(texto) > ancho:
        etiqueta.set_wrap(True)
        etiqueta.set_width_chars(ancho)
        etiqueta.set_max_width_chars(ancho)
    return etiqueta


class PaginaSalud(Gtk.ScrolledWindow):
    def __init__(self, discos, lector, error_deteccion=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._discos = discos
        self._lector = lector
        self.leyendo = False

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for lado in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{lado}")(18)
        self.set_child(Adw.Clamp(maximum_size=720, child=caja))

        # Selector de disco y botón.
        fila_selector = Gtk.Box(spacing=12)
        self.selector = Gtk.DropDown.new_from_strings([d.etiqueta for d in discos])
        self.selector.set_factory(_fabrica_selector(elipsis=True))
        self.selector.set_list_factory(_fabrica_selector(elipsis=False))
        self.selector.set_hexpand(True)
        self.selector.connect("notify::selected", self._al_cambiar_disco)
        self.spinner = Adw.Spinner(visible=False)
        self.boton = Gtk.Button(label="Leer salud")
        self.boton.add_css_class("suggested-action")
        self.boton.connect("clicked", self._al_pulsar_leer)
        fila_selector.append(self.selector)
        fila_selector.append(self.spinner)
        fila_selector.append(self.boton)
        caja.append(fila_selector)

        self.aviso = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.aviso.add_css_class("dimmed")
        caja.append(self.aviso)

        # Panel grande de estado.
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.add_css_class("card")
        self.insignia = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, margin_top=24)
        self.insignia.add_css_class("latido-insignia")
        self.icono_estado = Gtk.Image(pixel_size=32, visible=False)
        self.etiqueta_estado = Gtk.Label()
        self.etiqueta_estado.add_css_class("title-1")
        self.insignia.append(self.icono_estado)
        self.insignia.append(self.etiqueta_estado)
        panel.append(self.insignia)
        self.etiqueta_frase = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.etiqueta_frase.add_css_class("title-4")
        self.etiqueta_disco = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin_bottom=24)
        self.etiqueta_disco.add_css_class("dimmed")
        for etiqueta in (self.etiqueta_frase, self.etiqueta_disco):
            etiqueta.set_margin_start(18)
            etiqueta.set_margin_end(18)
            panel.append(etiqueta)
        caja.append(panel)

        self.grupo_disco = Adw.PreferencesGroup(title="Disco")
        self.filas_disco = {}
        for clave, titulo in FILAS_DISCO:
            fila = _fila(titulo)
            valor = Gtk.Label(
                xalign=1, justify=Gtk.Justification.RIGHT, wrap=True,
                wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=32,
            )
            if clave == "serie":
                valor.set_selectable(True)
            fila.add_suffix(valor)
            self.filas_disco[clave] = valor
            self.grupo_disco.add(fila)
        caja.append(self.grupo_disco)

        self.grupo_resumen = Adw.PreferencesGroup(title="Resumen")
        self.filas_resumen = {}
        for clave, titulo in FILAS_RESUMEN:
            fila = _fila(titulo)
            valor = Gtk.Label(xalign=1)
            fila.add_suffix(valor)
            self.filas_resumen[clave] = (fila, valor)
            self.grupo_resumen.add(fila)
        caja.append(self.grupo_resumen)

        self.grupo_motivos = Adw.PreferencesGroup(title="Motivos")
        self._filas_motivos = []
        caja.append(self.grupo_motivos)

        self.grupo_registro = Adw.PreferencesGroup(
            title="Registro de salud NVMe",
            description="Lo que el propio disco guarda sobre su salud, con la explicación de cada dato.",
        )
        self._filas_registro = []
        caja.append(self.grupo_registro)

        nota = Gtk.Label(label=NOTA, wrap=True, xalign=0)
        nota.add_css_class("dimmed")
        nota.add_css_class("caption")
        caja.append(nota)

        if error_deteccion:
            self._mostrar_vacio(error_deteccion)
        elif not discos:
            self._mostrar_vacio("No se encontró ningún disco NVMe ni SATA.")
        else:
            self._al_cambiar_disco()

    # --- selección ---

    def disco_seleccionado(self):
        indice = self.selector.get_selected()
        if indice == Gtk.INVALID_LIST_POSITION or indice >= len(self._discos):
            return None
        return self._discos[indice]

    def _al_cambiar_disco(self, *_):
        disco = self.disco_seleccionado()
        self._limpiar()
        self._poner_estado("—", "Elige un disco y pulsa «Leer salud».")
        self.etiqueta_disco.set_text(disco.etiqueta if disco else "")
        self.selector.set_tooltip_text(disco.etiqueta if disco else None)
        habilitado = disco is not None and disco.habilitado
        self.boton.set_sensitive(habilitado and not self.leyendo)
        self.aviso.set_text(disco.aviso if disco and disco.aviso else "")
        self.aviso.set_visible(bool(disco and disco.aviso))

    def _mostrar_vacio(self, mensaje):
        self._limpiar()
        self.selector.set_sensitive(False)
        self.boton.set_sensitive(False)
        self._poner_estado("—", mensaje)
        self.etiqueta_disco.set_text("")

    # --- lectura en un hilo ---

    def _al_pulsar_leer(self, _boton):
        disco = self.disco_seleccionado()
        if disco is None or not disco.habilitado or self.leyendo:
            return
        self.leyendo = True
        self.boton.set_sensitive(False)
        self.selector.set_sensitive(False)
        self.spinner.set_visible(True)
        self._limpiar()
        self._poner_estado(
            "Leyendo…", "Si se abre la ventana de contraseña, es para leer: Latido no escribe en el disco."
        )
        threading.Thread(target=self._leer_en_hilo, args=(disco,), daemon=True).start()

    def _leer_en_hilo(self, disco):
        try:
            resultado = self._lector(disco)
        except ErrorLectura as error:
            resultado = error
        except Exception:
            traceback.print_exc()
            resultado = ErrorLectura(
                TipoError.AYUDANTE,
                "Ocurrió un error inesperado en Latido al leer el disco. No se sabe el estado del disco.",
            )
        GLib.idle_add(self._terminar_lectura, disco, resultado)

    def _terminar_lectura(self, disco, resultado):
        self.leyendo = False
        self.spinner.set_visible(False)
        self.selector.set_sensitive(True)
        self.boton.set_sensitive(disco.habilitado)
        if isinstance(resultado, ErrorLectura):
            self.mostrar_error(resultado, disco)
        else:
            self.mostrar_informe(resultado, disco)
        return GLib.SOURCE_REMOVE

    # --- mostrar resultados ---

    def _poner_estado(self, texto, frase, estado=None):
        """Sin estado (antes de leer o leyendo) la insignia queda neutra y sin ícono."""
        for clase in CLASES_ESTADO:
            self.insignia.remove_css_class(clase)
        if estado is None:
            self.icono_estado.set_visible(False)
        else:
            _, clase, icono, _ = APARIENCIA[estado]
            self.insignia.add_css_class(clase)
            self.icono_estado.set_from_icon_name(icono)
            self.icono_estado.set_visible(True)
        self.etiqueta_estado.set_text(texto)
        self.etiqueta_frase.set_text(frase)

    def _limpiar(self):
        for fila in self._filas_motivos:
            self.grupo_motivos.remove(fila)
        for fila in self._filas_registro:
            self.grupo_registro.remove(fila)
        self._filas_motivos = []
        self._filas_registro = []
        for valor in self.filas_disco.values():
            valor.set_text("")
        for grupo in (self.grupo_disco, self.grupo_resumen, self.grupo_motivos, self.grupo_registro):
            grupo.set_visible(False)

    def _agregar_motivos(self, motivos):
        for motivo in motivos:
            fila = _fila(motivo)
            self.grupo_motivos.add(fila)
            self._filas_motivos.append(fila)
        self.grupo_motivos.set_visible(bool(motivos))

    def mostrar_error(self, error, disco=None):
        self._limpiar()
        self._poner_estado(APARIENCIA[Estado.DESCONOCIDO][0], "No se pudo leer el disco.", Estado.DESCONOCIDO)
        self.etiqueta_disco.set_text(disco.etiqueta if disco else "")
        self._agregar_motivos(error.mensaje.split("\n"))

    def mostrar_informe(self, informe, disco=None):
        self._limpiar()
        texto, _, _, frase = APARIENCIA[informe.estado]
        self._poner_estado(texto, frase, informe.estado)

        self.etiqueta_disco.set_text(disco.etiqueta if disco else (informe.dispositivo or ""))

        for clave, valor in textos_disco(informe, disco).items():
            etiqueta = self.filas_disco[clave]
            etiqueta.set_text(valor)
            # Solo los textos largos se parten en varias líneas, y con un ancho mínimo.
            largo = len(valor) > 16
            etiqueta.set_wrap(largo)
            etiqueta.set_width_chars(16 if largo else -1)
        self.grupo_disco.set_visible(True)

        for clave, (valor, detalle) in textos_resumen(informe).items():
            fila, etiqueta = self.filas_resumen[clave]
            etiqueta.set_text(valor)
            fila.set_subtitle(detalle or "")
        self.grupo_resumen.set_visible(True)

        self._agregar_motivos(informe.motivos)

        for fila_registro in informe.registro_nvme:
            fila = _fila(fila_registro.nombre, fila_registro.explicacion)
            fila.add_suffix(_etiqueta_valor(fila_registro.texto))
            self.grupo_registro.add(fila)
            self._filas_registro.append(fila)
        self.grupo_registro.set_visible(bool(informe.registro_nvme))
