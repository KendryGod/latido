"""Pestaña "Salud": selector de disco, panel de estado y registro NVMe."""

import threading
import traceback

from gi.repository import Adw, GLib, Gtk, Pango

from latido.salud import Estado, InformeSalud, formato
from latido.salud.cifras import SIN_VALOR, cifras_clave
from latido.sistema.lectura import ErrorLectura, TipoError

# Estado: (texto, clase de latido/ui/estilo.py, ícono simbólico, frase).
# El ícono y el texto hacen que el color no sea la única señal.
APARIENCIA = {
    Estado.BUENO: ("Bueno", "latido-bueno", "object-select-symbolic", "El disco no reporta problemas en sus datos SMART."),
    Estado.PRECAUCION: (
        "Precaución", "latido-precaucion", "dialog-warning-symbolic", "Hay señales de riesgo. Mira el porqué."
    ),
    Estado.MALO: (
        "Peligro", "latido-malo", "dialog-error-symbolic", "El disco reporta fallas: no le confíes datos importantes."
    ),
    Estado.DESCONOCIDO: (
        "Sin datos", "latido-desconocido", "dialog-question-symbolic", "No hay datos suficientes para opinar."
    ),
}
# Estado de una cifra clave: (palabra, clase, ícono). El color nunca va solo.
APARIENCIA_CIFRA = {
    Estado.BUENO: ("Normal", "latido-bueno", "object-select-symbolic"),
    Estado.PRECAUCION: ("Atención", "latido-precaucion", "dialog-warning-symbolic"),
    Estado.MALO: ("Peligro", "latido-malo", "dialog-error-symbolic"),
    None: ("Sin dato", "latido-desconocido", "dialog-question-symbolic"),
    "informativa": ("Informativo", "latido-desconocido", "dialog-information-symbolic"),
}
# Ícono de cada línea de «Por qué» según el estado que da su regla (None: solo informa).
ICONO_MOTIVO = {
    Estado.BUENO: "object-select-symbolic",
    Estado.PRECAUCION: "dialog-warning-symbolic",
    Estado.MALO: "dialog-error-symbolic",
    Estado.DESCONOCIDO: "dialog-question-symbolic",
    None: "dialog-information-symbolic",
}
CLASES_ESTADO = [clase for _, clase, _, _ in APARIENCIA.values()]

NOTA = (
    "SMART mide el daño que el disco ha acumulado; no predice fallas. "
    "Las reglas de color son criterio propio de Latido."
)

ANCHO_CONTENIDO = 760  # Adw.Clamp (docs/diseno.md)

# Errores de lectura: (título, ícono, descripción o None para usar el mensaje del error).
TEXTOS_ERROR = {
    TipoError.CANCELADO: (
        "No se leyó el disco", "dialog-password-symbolic",
        "Cerraste la ventana de contraseña, así que Latido no leyó nada. Cuando quieras, vuelve a intentarlo.",
    ),
    TipoError.NO_AUTORIZADO: ("No se obtuvo permiso", "dialog-password-symbolic", None),
    TipoError.HERRAMIENTAS: ("Faltan piezas para leer la salud", "system-software-install-symbolic", None),
    None: ("No se pudo leer el disco", "dialog-warning-symbolic", None),
}


def _fila(titulo, subtitulo=None):
    fila = Adw.ActionRow(title=titulo, use_markup=False)
    if subtitulo:
        fila.set_subtitle(subtitulo)
    return fila


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


def _etiqueta_valor(texto, ancho=24):
    """Valor a la derecha de una fila: en una línea si es corto; si no, con ajuste."""
    etiqueta = Gtk.Label(label=texto, xalign=1, justify=Gtk.Justification.RIGHT)
    if len(texto) > ancho:
        etiqueta.set_wrap(True)
        etiqueta.set_width_chars(ancho)
        etiqueta.set_max_width_chars(ancho)
    return etiqueta


def etiquetas_selector(discos):
    """Modelo · capacidad, sin número de serie. Si dos discos quedan iguales, se agrega su nombre (nvme1n1)."""
    cortas = [disco.etiqueta_corta for disco in discos]
    return [
        f"{corta} · {disco.nombre}" if cortas.count(corta) > 1 else corta
        for corta, disco in zip(cortas, discos)
    ]


def _numero(valor):
    return SIN_VALOR if valor is None else f"{valor:,}"


class TarjetaCifra(Gtk.Box):
    """Una cifra clave: título, número grande (.numeric) con su unidad, estado (ícono + palabra) y detalle."""

    def __init__(self, cifra):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("card")
        interior = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=18, margin_bottom=18,
                           margin_start=18, margin_end=18)
        self.titulo = Gtk.Label(label=cifra.titulo, xalign=0, wrap=True)
        self.titulo.add_css_class("caption-heading")
        self.titulo.add_css_class("dimmed")
        numero = Gtk.Box(spacing=6)
        self.valor = Gtk.Label(xalign=0, valign=Gtk.Align.BASELINE_FILL)
        self.valor.add_css_class("title-1")
        self.valor.add_css_class("numeric")
        self.unidad = Gtk.Label(label=cifra.unidad, xalign=0, valign=Gtk.Align.BASELINE_FILL)
        self.unidad.add_css_class("title-4")
        self.unidad.add_css_class("dimmed")
        numero.append(self.valor)
        numero.append(self.unidad)
        self.chip = Gtk.Box(spacing=6, halign=Gtk.Align.START)
        self.chip.add_css_class("latido-chip")
        self.icono = Gtk.Image()
        self.palabra = Gtk.Label()
        self.palabra.add_css_class("caption-heading")
        self.chip.append(self.icono)
        self.chip.append(self.palabra)
        self.detalle = Gtk.Label(xalign=0, wrap=True)
        self.detalle.add_css_class("caption")
        self.detalle.add_css_class("dimmed")
        for hijo in (self.titulo, numero, self.chip, self.detalle):
            interior.append(hijo)
        self.append(interior)
        self.mostrar(cifra)

    def mostrar(self, cifra):
        self.valor.set_text(cifra.valor)
        self.unidad.set_visible(bool(cifra.unidad) and cifra.valor != SIN_VALOR)
        clave = "informativa" if cifra.informativa and cifra.valor != SIN_VALOR else cifra.estado
        palabra, clase, icono = APARIENCIA_CIFRA[clave]
        for otra in CLASES_ESTADO:
            self.chip.remove_css_class(otra)
        self.chip.add_css_class(clase)
        self.icono.set_from_icon_name(icono)
        self.palabra.set_text(palabra)
        self.detalle.set_text(cifra.detalle or "")
        self.detalle.set_visible(bool(cifra.detalle))


class PaginaSalud(Gtk.ScrolledWindow):
    def __init__(self, discos, lector, error_deteccion=None, detectar=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._discos = list(discos)
        self._lector = lector
        self._detectar = detectar
        self._error_deteccion = error_deteccion
        self.leyendo = False
        self.detectando = False
        self.informe = None  # el último informe mostrado (para exportar)
        self.disco_informe = None

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for lado in ("top", "bottom", "start", "end"):
            getattr(caja, f"set_margin_{lado}")(18)
        self.set_child(Adw.Clamp(maximum_size=ANCHO_CONTENIDO, child=caja))

        # Selector de disco: la ventana lo pone en la cabecera.
        self.selector = Gtk.DropDown.new_from_strings(etiquetas_selector(self._discos))
        self.selector.set_factory(_fabrica_selector(elipsis=True))
        self.selector.set_list_factory(_fabrica_selector(elipsis=False))
        self.selector.connect("notify::selected", self._al_cambiar_disco)

        self.aviso = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.aviso.add_css_class("dimmed")
        caja.append(self.aviso)

        # Antes de leer, leyendo, errores y vacíos: Adw.StatusPage con un botón.
        self.boton = Gtk.Button(label="Leer salud", halign=Gtk.Align.CENTER)
        self.boton.add_css_class("suggested-action")
        self.boton.add_css_class("pill")
        self.boton.connect("clicked", self._al_pulsar_boton)
        self.pagina_estado = Adw.StatusPage(child=self.boton, vexpand=True)
        self.contenido = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.vistas = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        self.vistas.add_named(self.pagina_estado, "estado")
        self.vistas.add_named(self.contenido, "informe")
        caja.append(self.vistas)
        caja = self.contenido  # lo de abajo es el informe

        # Tarjeta del veredicto: ícono grande y palabra, una frase y el disco.
        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tarjeta.add_css_class("card")
        interior = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24, margin_bottom=24,
                           margin_start=24, margin_end=24)
        self.insignia = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self.insignia.add_css_class("latido-insignia")
        self.icono_estado = Gtk.Image(pixel_size=48, visible=False)
        self.etiqueta_estado = Gtk.Label()
        self.etiqueta_estado.add_css_class("title-1")
        self.insignia.append(self.icono_estado)
        self.insignia.append(self.etiqueta_estado)
        self.etiqueta_frase = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.etiqueta_frase.add_css_class("title-4")
        self.etiqueta_disco = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.etiqueta_disco.add_css_class("dimmed")
        for hijo in (self.insignia, self.etiqueta_frase, self.etiqueta_disco):
            interior.append(hijo)
        tarjeta.append(interior)
        caja.append(tarjeta)

        # «Por qué»: una fila por línea, con el ícono del estado que da su regla.
        self.grupo_motivos = Adw.PreferencesGroup(title="Por qué")
        self._filas_motivos = []
        caja.append(self.grupo_motivos)

        # Cifras clave: número grande, unidad y estado propio.
        self.grid_cifras = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
            max_children_per_line=3, column_spacing=12, row_spacing=12,
        )
        self.cifras = {}
        for cifra in cifras_clave(InformeSalud()):
            self.cifras[cifra.clave] = TarjetaCifra(cifra)
            self.grid_cifras.append(self.cifras[cifra.clave])
        caja.append(self.grid_cifras)

        # «Todos los datos», plegado.
        self.expansor = Gtk.Expander(expanded=False)
        titulo_datos = Gtk.Label(label="Todos los datos")
        titulo_datos.add_css_class("heading")
        self.expansor.set_label_widget(titulo_datos)
        datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=12)
        self.expansor.set_child(datos)
        caja.append(self.expansor)

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
        datos.append(self.grupo_disco)

        self.grupo_registro = Adw.PreferencesGroup(
            title="Registro de salud NVMe",
            description="Lo que el propio disco guarda sobre su salud: el valor y su explicación.",
        )
        self._filas_registro = []
        datos.append(self.grupo_registro)

        self.grupo_ata = Adw.PreferencesGroup(
            title="Atributos SMART (ATA)",
            description="La tabla de smartctl, tal cual. Latido todavía no la analiza.",
        )
        self._filas_ata = []
        datos.append(self.grupo_ata)

        nota = Gtk.Label(label=NOTA, wrap=True, xalign=0)
        nota.add_css_class("dimmed")
        nota.add_css_class("caption")
        caja.append(nota)

        self._al_cambiar_disco()

    # --- estados sin informe: Adw.StatusPage ---

    def _mostrar_estado(self, titulo, descripcion, icono=None, boton=None, cargando=False):
        """Muestra la página de estado. La descripción es texto: se escapa para Pango."""
        if cargando:
            self.pagina_estado.set_icon_name(None)
            self.pagina_estado.set_paintable(Adw.SpinnerPaintable.new(self.pagina_estado))
        else:
            self.pagina_estado.set_paintable(None)
            self.pagina_estado.set_icon_name(icono)
        self.pagina_estado.set_title(titulo)
        self.pagina_estado.set_description(GLib.markup_escape_text(descripcion))
        self.boton.set_visible(boton is not None)
        if boton is not None:
            self.boton.set_label(boton)
        self.vistas.set_visible_child_name("estado")

    def mostrando_estado(self):
        return self.vistas.get_visible_child_name() == "estado"

    # --- selección ---

    def disco_seleccionado(self):
        indice = self.selector.get_selected()
        if indice == Gtk.INVALID_LIST_POSITION or indice >= len(self._discos):
            return None
        return self._discos[indice]

    def _al_cambiar_disco(self, *_):
        disco = self.disco_seleccionado()
        self._limpiar()
        self.informe = self.disco_informe = None
        self._poner_estado("—", "")
        self.etiqueta_disco.set_text(disco.etiqueta if disco else "")
        self.selector.set_tooltip_text(disco.etiqueta if disco else None)
        self.selector.set_sensitive(bool(self._discos) and not self.leyendo)
        self.aviso.set_text(disco.aviso if disco and disco.aviso else "")
        self.aviso.set_visible(bool(disco and disco.aviso))
        if not self._discos:
            detalle = self._error_deteccion or "Latido busca discos NVMe y SATA. Conecta uno y vuelve a intentarlo."
            self._mostrar_estado(
                "No se encontró ningún disco", detalle, "drive-harddisk-symbolic",
                "Reintentar" if self._detectar else None,
            )
            self.boton.set_sensitive(self._detectar is not None and not self.detectando)
            return
        self._mostrar_estado(
            "Leer la salud del disco",
            "Latido lee lo que el propio disco guarda sobre su salud (SMART). Si se abre la ventana de "
            "contraseña, es solo para leer: Latido no escribe en el disco.",
            "drive-harddisk-symbolic", "Leer salud",
        )
        self.boton.set_sensitive(disco is not None and disco.habilitado and not self.leyendo)

    def _al_pulsar_boton(self, _boton):
        if not self._discos:
            self.volver_a_detectar()
        else:
            self.leer()

    def volver_a_detectar(self):
        """«Reintentar» sin discos: vuelve a buscarlos (lsblk) en un hilo."""
        if self._detectar is None or self.detectando:
            return
        self.detectando = True
        self.boton.set_sensitive(False)
        threading.Thread(target=self._detectar_en_hilo, daemon=True).start()

    def _detectar_en_hilo(self):
        try:
            resultado = self._detectar()
        except Exception as error:  # ErrorDeteccion u otro: se muestra tal cual
            resultado = error
        GLib.idle_add(self._terminar_deteccion, resultado)

    def _terminar_deteccion(self, resultado):
        self.detectando = False
        if isinstance(resultado, Exception):
            self._discos, self._error_deteccion = [], f"No se pudieron detectar los discos. {resultado}"
        else:
            self._discos, self._error_deteccion = list(resultado), None
        modelo = self.selector.get_model()
        modelo.splice(0, modelo.get_n_items(), etiquetas_selector(self._discos))
        self.selector.set_selected(0 if self._discos else Gtk.INVALID_LIST_POSITION)
        self._al_cambiar_disco()
        return GLib.SOURCE_REMOVE

    # --- lectura en un hilo ---

    def leer(self):
        """Lee la salud del disco elegido (botón de la página o Ctrl+R)."""
        disco = self.disco_seleccionado()
        if disco is None or not disco.habilitado or self.leyendo:
            return
        self.leyendo = True
        self.boton.set_sensitive(False)
        self.selector.set_sensitive(False)
        self._limpiar()
        self._poner_estado("Leyendo…", "")
        self._mostrar_estado(
            "Leyendo…", "Si se abre la ventana de contraseña, es para leer: Latido no escribe en el disco.",
            cargando=True,
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
        for grupo, filas in ((self.grupo_motivos, self._filas_motivos), (self.grupo_registro, self._filas_registro),
                             (self.grupo_ata, self._filas_ata)):
            for fila in filas:
                grupo.remove(fila)
        self._filas_motivos, self._filas_registro, self._filas_ata = [], [], []
        for valor in self.filas_disco.values():
            valor.set_text("")
        for grupo in (self.grupo_disco, self.grupo_motivos, self.grupo_registro, self.grupo_ata):
            grupo.set_visible(False)

    def _agregar_motivos(self, disparos):
        for disparo in disparos:
            fila = _fila(disparo.motivo)
            fila.add_prefix(Gtk.Image(icon_name=ICONO_MOTIVO[disparo.estado]))
            self.grupo_motivos.add(fila)
            self._filas_motivos.append(fila)
        self.grupo_motivos.set_visible(bool(disparos))

    def mostrar_error(self, error, disco=None):
        """Errores en una Adw.StatusPage con «Reintentar». Cerrar la ventana de contraseña no es un error rojo."""
        self._limpiar()
        self.informe = self.disco_informe = None
        self._poner_estado("—", "")
        self.etiqueta_disco.set_text(disco.etiqueta if disco else "")
        titulo, icono, descripcion = TEXTOS_ERROR.get(error.tipo, TEXTOS_ERROR[None])
        if error.tipo is TipoError.HERRAMIENTAS and "Falta smartctl" in error.mensaje:
            titulo = "Falta smartctl"
        self._mostrar_estado(titulo, descripcion or error.mensaje, icono, "Reintentar")

    def mostrar_informe(self, informe, disco=None):
        self._limpiar()
        if not informe.registro_nvme and not informe.atributos_ata:
            # Sin un solo dato SMART no hay informe que mostrar.
            self.informe = self.disco_informe = None
            self._poner_estado("—", "")
            self._mostrar_estado(
                "El disco no entregó datos SMART", "\n".join(informe.motivos) or formato.NO_DISPONIBLE,
                "drive-harddisk-symbolic", "Reintentar",
            )
            return
        self.informe, self.disco_informe = informe, disco
        self.vistas.set_visible_child_name("informe")
        texto, _, _, frase = APARIENCIA[informe.estado]
        self._poner_estado(texto, frase, informe.estado)

        self.etiqueta_disco.set_text(disco.etiqueta if disco else (informe.dispositivo or ""))
        self._agregar_motivos(informe.disparos)

        for cifra in cifras_clave(informe):
            self.cifras[cifra.clave].mostrar(cifra)
        self.grid_cifras.set_visible(informe.tipo == "nvme")  # las seis cifras son de NVMe

        for clave, valor in textos_disco(informe, disco).items():
            etiqueta = self.filas_disco[clave]
            etiqueta.set_text(valor)
            # Solo los textos largos se parten en varias líneas, y con un ancho mínimo.
            largo = len(valor) > 16
            etiqueta.set_wrap(largo)
            etiqueta.set_width_chars(16 if largo else -1)
        self.grupo_disco.set_visible(True)

        for fila_registro in informe.registro_nvme:
            fila = _fila(fila_registro.nombre, fila_registro.explicacion)
            fila.add_suffix(_etiqueta_valor(fila_registro.texto))
            self.grupo_registro.add(fila)
            self._filas_registro.append(fila)
        self.grupo_registro.set_visible(bool(informe.registro_nvme))

        for atributo in informe.atributos_ata:
            fila = _fila(
                f"{atributo.id} · {atributo.nombre}",
                f"Valor {_numero(atributo.valor)} · Peor {_numero(atributo.peor)} · Umbral {_numero(atributo.umbral)}",
            )
            fila.add_suffix(_etiqueta_valor(atributo.crudo))
            self.grupo_ata.add(fila)
            self._filas_ata.append(fila)
        self.grupo_ata.set_visible(bool(informe.atributos_ata))
