"""En qué disco físico está una carpeta (Compuerta C2). Con un /sys falso en tmp_path y un os.stat falso."""

import os

import pytest

from latido.sistema.discos import Disco
from latido.sistema.ubicacion import NO_SE_PUDO, DiscoDeCarpeta, disco_de_carpeta, mismo_disco

NVME = Disco(nombre="nvme0n1", ruta="/dev/nvme0n1", ruta_lectura="/dev/nvme0", modelo="KINGSTON SNV2S1000G",
             tamano=1000204886016, transporte="nvme", es_sistema=True, habilitado=True, aviso=None)
USB = Disco(nombre="sdb", ruta="/dev/sdb", ruta_lectura=None, modelo="Disco USB", tamano=500107862016,
            transporte="usb", es_sistema=False, habilitado=False, aviso="SATA y USB llegan en una próxima fase")
SDC = Disco(nombre="sdc", ruta="/dev/sdc", ruta_lectura=None, modelo="Otro USB", tamano=256060514304,
            transporte="usb", es_sistema=False, habilitado=False, aviso=None)
DISCOS = [NVME, USB, SDC]

UUID_UNO = "11111111-1111-1111-1111-111111111111"
UUID_VARIOS = "22222222-2222-2222-2222-222222222222"
UUID_CIFRADO = "33333333-3333-3333-3333-333333333333"


class StatFalso:
    def __init__(self, mayor, menor):
        self.st_dev = os.makedev(mayor, menor)


def _sys(tmp_path):
    """Árbol mínimo como /sys: dev/block, class/block y fs/btrfs, con enlaces como los del kernel."""
    raiz = tmp_path / "sys"
    dispositivos = raiz / "devices"
    rutas = {
        "nvme0n1": "pci/nvme/nvme0n1",
        "nvme0n1p3": "pci/nvme/nvme0n1/nvme0n1p3",
        "nvme0n1p5": "pci/nvme/nvme0n1/nvme0n1p5",
        "sdb": "usb/sdb",  # disco completo, sin particiones
        "sdc": "usb/sdc",
        "dm-0": "virtual/block/dm-0",  # LUKS o LVM sobre nvme0n1p3
        "md0": "virtual/block/md0",  # RAID sobre sdb y sdc
        "md0p1": "virtual/block/md0/md0p1",
        "loop0": "virtual/block/loop0",
    }
    for nombre, ruta in rutas.items():
        (dispositivos / ruta).mkdir(parents=True, exist_ok=True)
    for particion in ("nvme0n1p3", "nvme0n1p5", "md0p1"):
        (dispositivos / rutas[particion] / "partition").write_text("1\n")
    for virtual, debajo in (("dm-0", ("nvme0n1p3",)), ("md0", ("sdb", "sdc"))):
        (dispositivos / rutas[virtual] / "slaves").mkdir()
        for nombre in debajo:
            (dispositivos / rutas[virtual] / "slaves" / nombre).symlink_to(dispositivos / rutas[nombre])
    numeros = {"259:0": "nvme0n1", "259:3": "nvme0n1p3", "259:5": "nvme0n1p5", "8:16": "sdb", "8:32": "sdc",
               "253:0": "dm-0", "9:0": "md0", "259:9": "md0p1", "7:0": "loop0"}
    (raiz / "dev" / "block").mkdir(parents=True)
    (raiz / "class" / "block").mkdir(parents=True)
    for numero, nombre in numeros.items():
        (raiz / "dev" / "block" / numero).symlink_to(dispositivos / rutas[nombre])
        (raiz / "class" / "block" / nombre).symlink_to(dispositivos / rutas[nombre])
    for uuid, miembros in ((UUID_UNO, ("nvme0n1p5",)), (UUID_VARIOS, ("sdb", "sdc")), (UUID_CIFRADO, ("dm-0",))):
        (raiz / "fs" / "btrfs" / uuid / "devices").mkdir(parents=True)
        for nombre in miembros:
            (raiz / "fs" / "btrfs" / uuid / "devices" / nombre).symlink_to(dispositivos / rutas[nombre])
    return str(raiz)


MOUNTINFO = (
    "1 0 0:36 /root / rw,relatime shared:1 - btrfs /dev/nvme0n1p5 rw,subvol=/root\n"
    "2 1 0:36 /datos /datos rw,relatime shared:2 - btrfs /dev/nvme0n1p5 rw,subvol=/datos\n"
    "3 1 0:50 / /tmp rw shared:3 - tmpfs tmpfs rw\n"
    "4 1 0:60 / /mnt/varios rw shared:4 - btrfs /dev/sdb rw\n"
    "5 1 0:61 / /mnt/cifrado rw shared:5 - btrfs /dev/mapper/luks-x rw\n"
    "6 1 0:62 / /mnt/capas rw shared:6 - overlay overlay rw,lowerdir=/a,upperdir=/b,workdir=/c\n"
    "7 1 0:63 / /mnt/red rw shared:7 - nfs4 servidor:/datos rw\n"
)


def _ubicar(tmp_path, ruta, mayor, menor, mountinfo=MOUNTINFO, discos=DISCOS):
    mapeo = {"/dev/mapper/luks-x": "/dev/dm-0"}
    return disco_de_carpeta(
        ruta, discos,
        stat=lambda _ruta: StatFalso(mayor, menor),
        raiz_sys=_sys(tmp_path),
        leer_mountinfo=lambda: mountinfo,
        realpath=lambda r: mapeo.get(r, r),
    )


# --- se puede afirmar un único disco ---

def test_particion_normal_sube_a_su_disco(tmp_path):
    ubicacion = _ubicar(tmp_path, "/boot/datos", 259, 5)
    assert ubicacion.disco is NVME and ubicacion.motivo is None
    assert ubicacion.texto_antes == f"Se medirá: {NVME.etiqueta_corta}"


def test_disco_completo_sin_particiones(tmp_path):
    ubicacion = _ubicar(tmp_path, "/mnt/usb", 8, 16)
    assert ubicacion.disco is USB
    assert ubicacion.texto_antes == f"Se medirá: {USB.etiqueta_corta}"
    assert USB.etiqueta_corta.startswith("Disco USB · ")


def test_btrfs_de_un_solo_disco_por_el_montaje(tmp_path):
    """btrfs da a cada subvolumen un st_dev anónimo (mayor 0): se mira el montaje y /sys/fs/btrfs."""
    ubicacion = _ubicar(tmp_path, "/datos/medir", 0, 51)
    assert ubicacion.disco is NVME


# --- no se puede afirmar un único disco: no se adivina ---

@pytest.mark.parametrize("ruta, mayor, menor, pista", [
    ("/datos", 253, 0, "LVM, dm-crypt o RAID"),  # dm-0
    ("/raid", 9, 0, "LVM, dm-crypt o RAID"),  # md0
    ("/raid/p1", 259, 9, "LVM, dm-crypt o RAID"),  # partición de md0
    ("/mnt/varios/x", 0, 60, "varios discos"),  # btrfs sobre sdb y sdc
    ("/mnt/cifrado/x", 0, 61, "LVM, dm-crypt o RAID"),  # btrfs de un dispositivo, pero es dm-0
    ("/mnt/capas/x", 0, 62, "overlay"),
    ("/tmp/x", 0, 50, "tmpfs"),
    ("/mnt/red/x", 0, 63, "nfs4"),
    ("/imagen", 7, 0, "loop0"),  # no está en la lista de discos
    ("/nada", 8, 99, "no dice"),  # el kernel no tiene ese dispositivo en /sys/dev/block
])
def test_no_resoluble(tmp_path, ruta, mayor, menor, pista):
    ubicacion = _ubicar(tmp_path, ruta, mayor, menor)
    assert ubicacion.disco is None
    assert pista in ubicacion.motivo
    assert ubicacion.texto_antes == NO_SE_PUDO == "No se pudo saber en qué disco está esta carpeta"


def test_sin_montaje_para_un_st_dev_anonimo(tmp_path):
    ubicacion = _ubicar(tmp_path, "/datos/medir", 0, 51, mountinfo="")
    assert ubicacion.disco is None and ubicacion.motivo


def test_si_no_se_puede_leer_la_carpeta(tmp_path):
    def falla(_ruta):
        raise PermissionError(13, "Permiso denegado")

    ubicacion = disco_de_carpeta("/x", DISCOS, stat=falla, raiz_sys=_sys(tmp_path), leer_mountinfo=lambda: "")
    assert ubicacion.disco is None and ubicacion.motivo


def test_disco_que_ya_no_esta_en_la_lista(tmp_path):
    assert _ubicar(tmp_path, "/boot", 259, 5, discos=[USB]).disco is None


# --- comparar el disco de la velocidad con el de Salud ---

def test_mismo_disco():
    copia = Disco(**{**NVME.__dict__})
    assert mismo_disco(NVME, copia)
    assert not mismo_disco(NVME, USB)
    assert not mismo_disco(USB, NVME)
    assert not mismo_disco(None, NVME) and not mismo_disco(NVME, None) and not mismo_disco(None, None)


def test_el_resultado_es_inmutable():
    with pytest.raises(AttributeError):
        DiscoDeCarpeta(NVME).disco = USB
