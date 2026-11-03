# Diseño de Latido

Una página con lo que decide cómo se ve Latido. Si la interfaz contradice este documento, gana el
documento.

## Principios

- Minimalista y con aire, al nivel de una app de pago de macOS. Una sola cosa importante por pantalla: el
  veredicto.
- Solo libadwaita 1.9: `Adw.ToolbarView`, `Adw.HeaderBar`, `Adw.ViewSwitcher`, tarjetas, `Adw.StatusPage`,
  `Adw.Banner`, `Adw.Toast` y `Adw.AlertDialog`. Ninguna API deprecada.
- Números grandes con la clase `.numeric` y la tipografía del sistema.
- Claro, oscuro y temas de usuario: solo nombres de la paleta de libadwaita, nunca hex. Temas como MacTahoe
  redefinen la paleta, y Latido la sigue porque solo usa nombres.
- El color nunca va solo: siempre ícono + palabra.
- Espacios y radios en múltiplos de 6 px. Sin degradados ni sombras propias. `.dimmed`, nunca `.dim-label`.
- Todo el CSS propio está en `latido/ui/estilo.py`, en una sola hoja cargada con un `Gtk.CssProvider`.

## Estados

| Estado     | Color (paleta)         | Ícono                      | Cuándo                                  |
|------------|------------------------|----------------------------|-----------------------------------------|
| Bueno      | azul (`@blue_3`)       | `object-select-symbolic`   | ninguna regla se disparó                |
| Precaución | amarillo (`@yellow_5`) | `dialog-warning-symbolic`  | la peor regla disparada es amarilla     |
| Peligro    | rojo (`@red_3`)        | `dialog-error-symbolic`    | la peor regla disparada es roja         |
| Sin datos  | gris (`@dark_1`)       | `dialog-question-symbolic` | faltan datos para opinar                |

Las reglas y sus fuentes están en `docs/veredicto.md`. La autenticidad es una etiqueta aparte, que nunca
cambia el color de salud.

## Estructura

- **Cabecera:** el selector de disco (modelo · capacidad, sin número de serie, solo en Salud), las pestañas
  Salud | Velocidad, el botón Actualizar (Ctrl+R) y el menú. El menú tiene Exportar informe (Ctrl+E),
  Acerca de y Salir (Ctrl+Q).
- **Contenido:** centrado en un `Adw.Clamp` de 760 px, con desplazamiento vertical. Por debajo de 560 sp,
  las pestañas bajan a una barra inferior.
- **Salud:**
  - la tarjeta del veredicto: ícono grande, palabra en `.title-1`, una frase y «Por qué»;
  - la autenticidad;
  - seis cifras clave, cada una con su unidad y su estado;
  - «Todos los datos», plegado.
- **Velocidad:** la configuración, un único botón primario (Iniciar/Cancelar), el progreso «Paso n de 8»
  con `Gtk.ProgressBar`, el mensaje del final (con la limpieza) y la rejilla de resultados: una fila por
  prueba, Lectura | Escritura, MB/s grande (`.numeric`), barra relativa (`Gtk.LevelBar` sin umbrales de
  color), IOPS y latencia debajo.
- **Vacíos y errores:** `Adw.StatusPage` con «Reintentar».
- **Confirmaciones:** `Adw.AlertDialog`. Restos de una prueba anterior: `Adw.Banner`. Avisos breves:
  `Adw.Toast`.
- **Modo demo:** banner permanente «Datos de ejemplo, no son de tu disco».

## Esquema de color

Latido no fuerza claro ni oscuro: deja `Adw.StyleManager` en `ColorScheme.DEFAULT`, que sigue la
preferencia del sistema. Nunca toca `GtkSettings:gtk-application-prefer-dark-theme`; dos pruebas lo
comprueban.

El aviso `Using GtkSettings:gtk-application-prefer-dark-theme with libadwaita is unsupported`, que puede
salir en la terminal, **no viene de Latido**. libadwaita lo muestra al iniciar si la configuración del
usuario tiene `gtk-application-prefer-dark-theme=1` en `~/.config/gtk-4.0/settings.ini`. Latido no cambia
esa configuración. Quien quiera quitar el aviso puede borrar esa línea; el modo oscuro lo sigue dando la
preferencia `color-scheme` del escritorio.
