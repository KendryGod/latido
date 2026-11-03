# Latido

Aplicación para Linux (Python + GTK 4 / libadwaita) que muestra la salud de
tus discos con un color:

- **Azul — BUENO**: sin señales de daño en los datos SMART.
- **Amarillo — PRECAUCIÓN**: hay señales de riesgo.
- **Rojo — MALO**: el disco reporta fallas; evítalo.
- **Gris — DESCONOCIDO**: no hay datos suficientes. Ante la duda, Latido
  dice DESCONOCIDO, nunca BUENO.

SMART mide el daño acumulado; no predice fallas. Las reglas son criterio
propio: ver [docs/reglas-salud.md](docs/reglas-salud.md).

## Estado actual (Fase 0)

- Solo discos **NVMe**. Los discos SATA y USB (`/dev/sd*`) aparecen en la
  lista, deshabilitados, hasta la Fase 2.
- Solo salud (pestaña "Salud"). La velocidad llega en una fase posterior.
- Probado con fixtures; la lectura real con pkexec todavía no se ha probado.

## Dependencias (Fedora 44)

```
sudo dnf install python3 python3-gobject gtk4 libadwaita smartmontools polkit
```

Para las pruebas: `python3-pytest python3-pyflakes`.

## Uso

```
sudo sh tools/instalar-helper-dev.sh     # una vez: ayudante de root + política polkit
python3 -m latido                        # abrir la app
python3 -m latido --desde-fixture tests/fixtures/smartctl/nvme_real.json   # sin root
python3 -m pytest                        # pruebas
```

## Regla de oro

- `/dev/nvme0` es el disco del sistema.
- **Cero escritura a dispositivos y cero órdenes destructivas.** Todo lo de
  SMART es solo lectura.
- El único proceso con root es `/usr/libexec/latido/latido-helper`, y solo
  acepta `leer /dev/nvmeN[nM]`. Ejecuta exactamente
  `/usr/bin/smartctl --json=c -x <disco>`; nada más.
- La app no pide contraseña al abrirse: solo al pulsar "Leer salud".

## Identificadores

- Aplicación: `io.github.kendrygod.latido` (archivos `.desktop` y `.metainfo.xml` en `data/`).
- Acción de polkit: `io.github.kendrygod.latido.leer-salud`.

## Licencia

GPL-3.0-or-later. Ver [LICENSE](LICENSE).
