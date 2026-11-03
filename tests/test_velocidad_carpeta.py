"""Pestaña Velocidad: revisión de la carpeta (mountinfo, disco del sistema, espacio y avisos).

Todo con datos falsos: mountinfo de texto, statvfs falso y un árbol como
/sys/class/block en tmp_path. Nada escribe en un dispositivo.
"""

import pytest

from conftest import StatvfsFalso
from latido.velocidad.carpeta import (
    discos_de_fuente,
    espacio_necesario,
    leer_mountinfo,
    margen,
    montaje_de,
    revisar_carpeta,
    version_kernel,
)
from latido.velocidad.pruebas import GIB, MIB, Configuracion


MOUNTINFO = """\
44 1 0:36 /root / rw,noatime shared:1 - btrfs /dev/nvme0n1p5 rw,seclabel,compress=zstd:1,ssd,subvolid=256,subvol=/root
40 44 0:7 / /dev rw,nosuid shared:2 - devtmpfs devtmpfs rw,seclabel,mode=755
42 40 0:27 / /dev/shm rw,nosuid,nodev shared:3 - tmpfs tmpfs rw,seclabel
46 44 0:26 / /sys rw,nosuid,nodev,noexec,relatime shared:5 - sysfs sysfs rw,seclabel
53 44 0:25 / /proc rw,nosuid,nodev,noexec,relatime shared:13 - proc proc rw
60 44 0:45 / /tmp rw,nosuid,nodev shared:30 - tmpfs tmpfs rw,seclabel,inode64
62 44 0:36 /home /home rw,noatime shared:32 - btrfs /dev/nvme0n1p5 rw,seclabel,compress=zstd:1,ssd,subvolid=257,subvol=/home
64 44 259:2 / /boot rw,relatime shared:34 - ext4 /dev/nvme0n1p4 rw,seclabel
70 44 8:17 / /run/media/usuario/Disco\\040USB rw,nosuid,nodev,relatime shared:40 - ext4 /dev/sdb1 rw,seclabel
80 44 8:49 / /mnt/apilado rw shared:50 - ext4 /dev/sdd1 rw
81 80 0:70 / /mnt/apilado rw shared:51 - tmpfs tmpfs rw
línea rota sin formato
"""


def test_lee_mountinfo_con_escapes_y_lineas_rotas():
    montajes = leer_mountinfo(MOUNTINFO)
    assert len(montajes) == 11
    usb = [m for m in montajes if m.fuente == "/dev/sdb1"][0]
    assert usb.punto == "/run/media/usuario/Disco USB"
    assert usb.tipo == "ext4"
    home = [m for m in montajes if m.punto == "/home"][0]
    assert (home.raiz, home.tipo, home.fuente) == ("/home", "btrfs", "/dev/nvme0n1p5")
    assert "compress=zstd:1" in home.superopciones


@pytest.mark.parametrize("ruta, punto, tipo", [
    ("/home/usuario/Descargas", "/home", "btrfs"),  # subvolumen btrfs: por ruta, no por st_dev
    ("/homero", "/", "btrfs"),
    ("/tmp/x", "/tmp", "tmpfs"),
    ("/boot/efi", "/boot", "ext4"),
    ("/run/media/usuario/Disco USB/fotos", "/run/media/usuario/Disco USB", "ext4"),
    ("/mnt/apilado/x", "/mnt/apilado", "tmpfs"),  # el montaje de arriba gana
])
def test_montaje_de_una_ruta(ruta, punto, tipo):
    montaje = montaje_de(ruta, leer_mountinfo(MOUNTINFO))
    assert (montaje.punto, montaje.tipo) == (punto, tipo)


def _sys_block(tmp_path):
    """Árbol mínimo como /sys/class/block: nvme0n1 con particiones, sdb con sdb1 y dm-0 sobre nvme0n1p5."""
    if (tmp_path / "block").is_dir():
        return str(tmp_path / "block")
    dispositivos = tmp_path / "devices"
    for disco, particiones in (("nvme0n1", ("nvme0n1p4", "nvme0n1p5")), ("sdb", ("sdb1",))):
        (dispositivos / disco).mkdir(parents=True)
        for particion in particiones:
            (dispositivos / disco / particion).mkdir()
            (dispositivos / disco / particion / "partition").write_text("1\n")
    (dispositivos / "dm-0" / "slaves").mkdir(parents=True)
    (dispositivos / "dm-0" / "slaves" / "nvme0n1p5").mkdir()
    bloque = tmp_path / "block"
    bloque.mkdir()
    enlaces = {"nvme0n1": "nvme0n1", "nvme0n1p4": "nvme0n1/nvme0n1p4", "nvme0n1p5": "nvme0n1/nvme0n1p5",
               "sdb": "sdb", "sdb1": "sdb/sdb1", "dm-0": "dm-0"}
    for nombre, destino in enlaces.items():
        (bloque / nombre).symlink_to(dispositivos / destino)
    return str(bloque)


def test_discos_de_la_fuente(tmp_path):
    bloque = _sys_block(tmp_path)
    assert discos_de_fuente("/dev/nvme0n1p5", bloque) == {"nvme0n1"}
    assert discos_de_fuente("/dev/sdb1", bloque) == {"sdb"}
    assert discos_de_fuente("/dev/sdb", bloque) == {"sdb"}
    mapeo = {"/dev/mapper/luks-x": "/dev/dm-0"}
    assert discos_de_fuente("/dev/mapper/luks-x", bloque, realpath=lambda r: mapeo.get(r, r)) == {"nvme0n1"}
    assert discos_de_fuente("tmpfs", bloque) is None
    assert discos_de_fuente("servidor:/datos", bloque) is None
    assert discos_de_fuente("/dev/nvme9n9", bloque) is None


def _mountinfo_con(carpeta, tipo, fuente, opciones="rw"):
    return MOUNTINFO + f"90 44 0:90 / {carpeta} rw shared:60 - {tipo} {fuente} {opciones}\n"


def _revisar(carpeta, tmp_path, tipo, fuente, opciones="rw", libre=10**12, kernel="7.2.14-200.fc44.x86_64",
             configuracion=None, solo_lectura=False):
    texto = _mountinfo_con(carpeta, tipo, fuente, opciones)
    return revisar_carpeta(
        str(carpeta), configuracion or Configuracion(),
        leer_texto=lambda _ruta: texto,
        statvfs=lambda _ruta: StatvfsFalso(libre, solo_lectura),
        sys_block=_sys_block(tmp_path / "sys"),
        kernel=kernel,
    )


def test_aviso_de_desgaste_con_la_escritura_maxima(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/sdb1")
    assert revision.puede_empezar
    assert revision.avisos[0] == (
        "Se escribirán como máximo 13 GiB (13.96 GB): 1 GiB para preparar el archivo de prueba y hasta "
        "1 GiB en cada una de las 12 mediciones de escritura. En un SSD, toda escritura gasta parte de su vida útil."
    )


def test_disco_del_sistema(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/nvme0n1p4")
    assert revision.info.disco_sistema is True
    assert (
        "La carpeta está en el disco del sistema (nvme0n1): el equipo puede ir lento mientras dura la prueba."
        in revision.avisos
    )


def test_otro_disco_no_es_el_del_sistema(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/sdb1")
    assert revision.info.disco_sistema is False
    assert not any("disco del sistema" in a for a in revision.avisos)


def test_si_no_se_sabe_el_disco_lo_dice(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/nvme9n9p1")
    assert revision.info.disco_sistema is None
    assert "No se pudo comprobar si la carpeta está en el disco del sistema." in revision.avisos


def test_tmpfs_avisa_que_mide_la_memoria(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "tmpfs", "tmpfs")
    assert revision.puede_empezar
    assert revision.info.disco_sistema is False
    texto = [a for a in revision.avisos if "tmpfs" in a][0]
    assert "medirá la memoria, no un disco" in texto
    assert "O_DIRECT" not in texto  # en Linux 7.2 tmpfs sí abrió con O_DIRECT: no se afirma lo contrario


def test_btrfs_cita_man_btrfs_con_kernel_nuevo(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "btrfs", "/dev/sdb1", "rw,compress=zstd:1")
    texto = [a for a in revision.avisos if "btrfs" in a][0]
    assert "man 5 btrfs" in texto and "6.14" in texto and "Tu kernel es 7.2.14-200.fc44.x86_64." in texto


def test_btrfs_sin_aviso_con_kernel_viejo_o_sin_suma_de_verificacion(tmp_path):
    assert not any("btrfs" in a for a in _revisar(tmp_path, tmp_path, "btrfs", "/dev/sdb1", kernel="6.13.2").avisos)
    sin_cow = _revisar(tmp_path, tmp_path, "btrfs", "/dev/sdb1", "rw,nodatacow")
    assert not any("btrfs" in a for a in sin_cow.avisos)


def test_red_avisa(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "nfs4", "servidor:/datos")
    assert "La carpeta está en un sistema de archivos de red (nfs4): el resultado incluirá la red." in revision.avisos


def test_sistema_virtual_es_error(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "proc", "proc")
    assert not revision.puede_empezar
    assert "sistema de archivos virtual" in revision.errores[0]


def test_solo_lectura_es_error(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/sdb1", solo_lectura=True)
    assert revision.errores == ["La carpeta está en un sistema de archivos montado solo para lectura."]


def test_espacio_insuficiente_con_margen(tmp_path):
    revision = _revisar(tmp_path, tmp_path, "ext4", "/dev/sdb1", libre=2 * GIB - 1)
    assert revision.errores == [
        "No hay espacio suficiente: quedan 2.0 GiB libres y hacen falta 2 GiB "
        "(1 GiB del archivo de prueba + 1 GiB de margen)."
    ]
    assert _revisar(tmp_path, tmp_path, "ext4", "/dev/sdb1", libre=2 * GIB).puede_empezar


def test_margen():
    assert margen(256 * MIB) == GIB
    assert margen(GIB) == GIB
    assert margen(16 * GIB) == int(1.6 * GIB)
    assert espacio_necesario(32 * GIB) == 32 * GIB + int(3.2 * GIB)


def test_sin_mountinfo_lo_dice(tmp_path):
    def sin_archivo(_ruta):
        raise OSError("no")

    revision = revisar_carpeta(
        str(tmp_path), Configuracion(), leer_texto=sin_archivo, statvfs=lambda _r: StatvfsFalso(10**12), kernel="7.2"
    )
    assert revision.puede_empezar
    assert "No se pudo saber el sistema de archivos de la carpeta." in revision.avisos
    assert "No se pudo comprobar si la carpeta está en el disco del sistema." in revision.avisos


def test_version_kernel():
    assert version_kernel("7.2.14-200.fc44.x86_64") == (7, 2)
    assert version_kernel("6.14.0") == (6, 14)
    assert version_kernel("raro") is None
