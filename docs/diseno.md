# Diseño de Latido

## Esquema de color

Latido no fuerza claro ni oscuro: deja `Adw.StyleManager` en `ColorScheme.DEFAULT`, que sigue la
preferencia del sistema. Nunca toca `GtkSettings:gtk-application-prefer-dark-theme`; dos pruebas lo
comprueban.

El aviso `Using GtkSettings:gtk-application-prefer-dark-theme with libadwaita is unsupported` que puede
salir en la terminal **no viene de Latido**. libadwaita lo muestra al iniciar si la configuración del
usuario tiene `gtk-application-prefer-dark-theme=1` en `~/.config/gtk-4.0/settings.ini`. Latido no cambia
esa configuración. Quien quiera quitar el aviso puede borrar esa línea; el modo oscuro lo sigue dando la
preferencia `color-scheme` del escritorio.
