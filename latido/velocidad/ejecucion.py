"""Ejecuta los pasos de una prueba de velocidad con fio y limpia siempre.

Regla de oro de esta pestaña:
- fio escribe solo <carpeta>/.latido-velocidad-XXXXXXXX/latido-velocidad.dat,
  dentro de un directorio NUEVO creado con tempfile.mkdtemp (modo 0700).
- El archivo no existe antes de la preparación: lo crea fio. Latido mantiene
  abiertos el directorio desde que lo crea y el archivo desde que termina la
  preparación. Antes y después de cada paso compara lo que tiene abierto
  (os.fstat) con lo que hay en la ruta, sin seguir enlaces simbólicos: un solo
  nombre (st_nlink == 1), mismo dispositivo e inodo y el tamaño pedido.
- Si borran el archivo o ponen otro en su lugar, el que Latido tiene abierto
  sigue existiendo, pero sin ningún nombre (man 2 unlink): os.fstat da
  st_nlink == 0. Eso es lo que detecta el borrado y el reemplazo, sin mirar el
  número de inodo, que un sistema de archivos puede darle a un archivo nuevo
  cuando el anterior ya no existe (en la CI, run 41575524354, ocurrió).
- Comparar dispositivo e inodo sirve para lo demás, por ejemplo si lo movieron
  y pusieron otro en su lugar: dentro de un sistema de archivos, dos archivos
  que existen a la vez no comparten número (man 7 inode).
- Todo esto se afirma solo para sistemas de archivos locales. overlayfs, NFS y
  FUSE no están probados: no se sabe si ahí st_nlink y los números de inodo se
  comportan así.
- Al terminar, fallar, cancelar o por una excepción: se detiene el grupo de
  procesos de fio; se borra el archivo de prueba por su nombre exacto solo si
  sigue siendo el que Latido tiene abierto y tiene un solo nombre; luego el
  directorio con rmdir, y se cierran todos los descriptores. Nunca rm -r ni
  shutil.rmtree. Si rmdir no puede borrar el directorio, la limpieza siempre
  lo dice y nunca lo da por borrado. Para decir qué quedó dentro lo lista con
  un descriptor abierto en ese momento: en btrfs (medido con el kernel
  7.2.14) un descriptor de carpeta no ve lo que se creó después de abrirlo.
- Excepción: si la preparación no terminó bien (se canceló, fio falló o dejó
  algo que no sirve), Latido todavía no tiene el archivo abierto y no puede
  comparar su identidad. Entonces borra lo que haya en la ruta solo si fio
  llegó a lanzarse y es un archivo normal con un solo nombre; un enlace
  simbólico o una carpeta no se borran. Modelo de amenaza: el directorio lo
  creó Latido con modo 0700, estaba vacío al crearse y antes de lanzar fio se
  comprobó que ese nombre no existía; en un sistema de archivos local, solo el
  mismo usuario o root pueden alterar lo que hay dentro.
- Una sola prueba a la vez. fio corre como el usuario, con lista de
  argumentos, ruta absoluta y entorno limpio; nunca a través de un shell.
"""

import errno
import os
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from latido.velocidad.carpeta import revisar_carpeta
from latido.velocidad.herramientas import comprobar_fio
from latido.velocidad.pruebas import ARCHIVO_PRUEBA, FIO, PREFIJO_DIRECTORIO, Direccion, construir_comando
from latido.velocidad.restos import guardar_ultima_carpeta
from latido.velocidad.resultado import ErrorFio, ResultadoVelocidad, leer_salida_fio

ENTORNO = {"LC_ALL": "C"}
# Cada medición tiene un tope de 5 s (runtime); si fio tarda más que esto,
# algo va mal y se detiene. La preparación no tiene tope: se puede cancelar.
SEGUNDOS_MAXIMOS_MEDICION = 120
SEGUNDOS_PARA_TERMINAR = 10  # tras SIGTERM, antes de SIGKILL
INTERVALO = 0.1
# Para vigilar el archivo de prueba: un descriptor normal de solo lectura, no
# O_PATH (man 2 open: con O_PATH "the file itself is not opened"; man 2 unlink
# habla de procesos que tienen el archivo abierto). O_NONBLOCK: no se queda
# esperando si en la ruta hay una FIFO. O_NOFOLLOW: falla ante un enlace simbólico.
ABRIR_PARA_VIGILAR = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
CAMBIO = "El archivo de prueba cambió o desapareció durante la prueba"

_una_a_la_vez = threading.Lock()


class _Cancelacion(Exception):
    """Interna: el usuario pidió cancelar."""


@dataclass
class Limpieza:
    creo_directorio: bool = False
    archivo_borrado: bool = False
    archivo_borrado_por_otro: bool = False  # Latido lo tenía abierto y ya no le quedaba ningún nombre
    directorio_borrado: bool = False
    problemas: list = field(default_factory=list)

    @property
    def completa(self):
        """Sale de lo que de verdad se borró, nunca de «no hubo avisos»: solo si la carpeta temporal no se
        llegó a crear o se borró (rmdir solo borra una carpeta vacía), y además no hubo ningún problema."""
        return (not self.creo_directorio or self.directorio_borrado) and not self.problemas

    def texto(self):
        if not self.completa:
            return "La limpieza quedó incompleta:\n" + "\n".join(self.problemas or ["No se borró la carpeta temporal."])
        if not self.creo_directorio:
            return "No se llegó a crear ningún archivo."
        if self.archivo_borrado:
            return "Se borraron el archivo de prueba y su carpeta temporal."
        if self.archivo_borrado_por_otro:
            return "Se borró la carpeta temporal; el archivo de prueba ya lo había borrado otro programa."
        return "Se borró la carpeta temporal; el archivo de prueba no llegó a crearse."


def _que_hay(info):
    if stat.S_ISLNK(info.st_mode):
        return "un enlace simbólico"
    if stat.S_ISDIR(info.st_mode):
        return "una carpeta"
    if stat.S_ISREG(info.st_mode):
        return "otro archivo"
    return "algo que no es un archivo normal"


def _varios_nombres(cantidad):
    return f"tiene {cantidad} nombres: alguien le hizo un enlace duro"


def motivo_de_cambio(propio, en_ruta, tamano):
    """Por qué el archivo de prueba ya no es el que creó fio, o None si lo sigue siendo.

    propio: os.fstat del descriptor que Latido mantiene abierto.
    en_ruta: os.stat del nombre en el directorio temporal, sin seguir enlaces
    simbólicos, o None si ahí no hay nada.
    Se exige un solo nombre: 0 significa que lo borraron; más de 1, que alguien
    le hizo un enlace duro. Ante la duda, Latido se detiene.
    """
    if propio.st_nlink == 0:
        if en_ruta is None:
            return "lo borró otro programa"
        return f"lo borró otro programa y en su lugar hay {_que_hay(en_ruta)}"
    if propio.st_nlink != 1:
        return _varios_nombres(propio.st_nlink)
    if en_ruta is None:
        return "otro programa lo movió o le cambió el nombre"
    if (en_ruta.st_dev, en_ruta.st_ino) != (propio.st_dev, propio.st_ino):
        return f"otro programa lo movió y en su lugar hay {_que_hay(en_ruta)}"
    if en_ruta.st_nlink != 1:
        return _varios_nombres(en_ruta.st_nlink)
    if propio.st_size != tamano:
        return f"ahora mide {propio.st_size:,} bytes en vez de {tamano:,}"
    return None


class ErrorVelocidad(Exception):
    def __init__(self, mensaje, limpieza=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.limpieza = limpieza


class Cancelado(Exception):
    def __init__(self, limpieza):
        super().__init__("Prueba cancelada.")
        self.limpieza = limpieza


@dataclass(frozen=True)
class Progreso:
    indice: int  # empieza en 0
    total: int
    paso: object
    terminado: bool = False
    medicion: object = None  # Medicion de un paso de medición ya terminado


def _senal_al_grupo(grupo, senal):
    try:
        os.killpg(grupo, senal)
    except ProcessLookupError:
        pass


def _termino(pid):
    """True si el proceso ya terminó. No lo recoge (WNOWAIT): su PID sigue reservado."""
    try:
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True


class Ejecucion:
    def __init__(
        self,
        carpeta,
        configuracion,
        al_progresar=None,
        fio=FIO,
        comprobar=comprobar_fio,
        revisar=revisar_carpeta,
        guardar_carpeta=guardar_ultima_carpeta,
        segundos_para_terminar=SEGUNDOS_PARA_TERMINAR,
        segundos_maximos_medicion=SEGUNDOS_MAXIMOS_MEDICION,
    ):
        self.carpeta = carpeta
        self.configuracion = configuracion
        self._al_progresar = al_progresar or (lambda progreso: None)
        self._fio = fio
        self._comprobar = comprobar
        self._revisar = revisar
        self._guardar_carpeta = guardar_carpeta
        self._segundos_para_terminar = segundos_para_terminar
        self._segundos_maximos_medicion = segundos_maximos_medicion
        self._cancelar = threading.Event()
        self._usada = False
        self._proceso = None
        self._fd_padre = None
        self._fd_directorio = None
        self._fd_archivo = None  # abierto desde que termina la preparación hasta la limpieza
        self._identidad_directorio = None
        self._fio_pudo_crear_archivo = False
        self._archivo_sigue = False  # la limpieza dejó sin borrar el archivo de prueba de Latido
        self.directorio = None
        self.archivo = None

    def cancelar(self):
        """Se puede llamar desde cualquier hilo. El hilo de la prueba detiene fio y limpia."""
        self._cancelar.set()

    @property
    def cancelada(self):
        return self._cancelar.is_set()

    def ejecutar(self):
        """Bloquea hasta terminar: llamar desde un hilo aparte.

        Devuelve ResultadoVelocidad (con .limpieza) o lanza ErrorVelocidad o
        Cancelado, ambos con .limpieza.
        """
        if self._usada:
            raise ErrorVelocidad("Esta prueba ya se ejecutó.", Limpieza())
        self._usada = True
        if not _una_a_la_vez.acquire(blocking=False):
            raise ErrorVelocidad("Ya hay una prueba de velocidad en marcha. Espera a que termine o cancélala.", Limpieza())
        try:
            return self._ejecutar()
        finally:
            _una_a_la_vez.release()

    # --- pasos ---

    def _ejecutar(self):
        estado = self._comprobar(fio=self._fio)
        if estado.problemas:
            raise ErrorVelocidad("No se puede medir todavía:\n" + "\n".join(estado.problemas), Limpieza())
        revision = self._revisar(self.carpeta, self.configuracion)
        if not revision.puede_empezar:
            raise ErrorVelocidad("\n".join(revision.errores) or "La carpeta no sirve para la prueba.", Limpieza())
        if self._cancelar.is_set():
            raise Cancelado(Limpieza())

        resultado = ResultadoVelocidad(self.configuracion.pasadas)
        real = revision.info.ruta
        try:
            self._guardar_carpeta(real)
        except OSError as error:
            resultado.avisos.append(
                f"No se pudo recordar la carpeta usada ({error.strerror}): si Latido se cierra de golpe, "
                "no podrá avisarte de los restos."
            )
        try:
            self._crear_directorio(real)
            self._correr_pasos(resultado)
        except BaseException as error:
            limpieza = self._limpiar()
            if isinstance(error, _Cancelacion):
                raise Cancelado(limpieza) from None
            if isinstance(error, ErrorVelocidad):
                error.limpieza = limpieza
                raise
            if isinstance(error, Exception):
                raise ErrorVelocidad(f"Error inesperado en Latido durante la prueba: {error!r}", limpieza) from error
            raise
        resultado.limpieza = self._limpiar()
        return resultado

    def _crear_directorio(self, real):
        try:
            self._fd_padre = os.open(real, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.directorio = tempfile.mkdtemp(prefix=PREFIJO_DIRECTORIO, dir=real)
        except OSError as error:
            raise ErrorVelocidad(f"No se pudo crear la carpeta temporal en «{real}»: {error.strerror}.") from None
        nombre = os.path.basename(self.directorio)
        self._fd_directorio = os.open(
            nombre, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._fd_padre
        )
        info = os.fstat(self._fd_directorio)
        self._identidad_directorio = (info.st_dev, info.st_ino)
        self.archivo = os.path.join(self.directorio, ARCHIVO_PRUEBA)
        if os.listdir(self._fd_directorio):
            raise ErrorVelocidad("La carpeta temporal recién creada no está vacía; Latido se detuvo por seguridad.")

    def _correr_pasos(self, resultado):
        pasos = self.configuracion.pasos()
        total = len(pasos)
        for indice, paso in enumerate(pasos):
            if self._cancelar.is_set():
                raise _Cancelacion()
            self._verificar(paso)  # antes: fio abrirá el archivo por su ruta
            self._al_progresar(Progreso(indice, total, paso))
            comando = construir_comando(paso, self.archivo, self.configuracion.tamano, self._fio)
            limite = None if paso.es_preparacion else self._segundos_maximos_medicion
            if paso.es_preparacion:
                self._fio_pudo_crear_archivo = True  # desde aquí, el archivo puede ser de fio
            codigo, salida, error = self._correr(comando, limite)
            direccion = Direccion.ESCRITURA if paso.es_preparacion else paso.direccion
            try:
                medicion = leer_salida_fio(salida, codigo, error, paso.trabajo, direccion)
            except ErrorFio as fallo:
                descripcion = paso.descripcion(self.configuracion.pasadas)
                raise ErrorVelocidad(f"fio falló en «{descripcion}».\n{fallo.mensaje}") from None
            if paso.es_preparacion:
                self._verificar_carpeta()
                self._registrar_archivo()
                medicion = None
            else:
                self._verificar(paso)  # después: la medición se hizo sobre el archivo de Latido
                resultado.agregar(paso, medicion)
            self._al_progresar(Progreso(indice, total, paso, terminado=True, medicion=medicion))

    def _verificar(self, paso):
        """Antes y después de cada paso: la carpeta temporal y el archivo siguen siendo los de Latido."""
        self._verificar_carpeta()
        if paso.es_preparacion:
            if self._en_la_ruta() is not None:
                raise ErrorVelocidad(
                    "Ya había algo en la ruta del archivo de prueba antes de crearlo; Latido no lo usa y se detuvo."
                )
            return
        motivo = motivo_de_cambio(os.fstat(self._fd_archivo), self._en_la_ruta(), self.configuracion.tamano)
        if motivo:
            raise ErrorVelocidad(f"{CAMBIO}: {motivo}. Latido se detuvo por seguridad.")

    def _verificar_carpeta(self):
        # Está abierta desde que se creó (_fd_directorio): su número no puede pasar a otra carpeta.
        try:
            info = os.lstat(self.directorio)
        except OSError:
            info = None
        if info is None or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._identidad_directorio:
            raise ErrorVelocidad("La carpeta temporal de la prueba cambió o desapareció; Latido se detuvo por seguridad.")

    def _en_la_ruta(self):
        """os.stat del nombre del archivo de prueba en el directorio temporal, sin seguir enlaces; None si no hay nada."""
        try:
            return os.stat(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _registrar_archivo(self):
        """Al terminar la preparación: abre el archivo que creó fio y lo mantiene abierto hasta la limpieza."""
        info = self._en_la_ruta()
        if info is None:
            raise ErrorVelocidad("fio terminó la preparación sin crear el archivo de prueba.")
        if not stat.S_ISREG(info.st_mode):
            raise ErrorVelocidad("Lo que quedó en la ruta del archivo de prueba no es un archivo normal.")
        if info.st_size != self.configuracion.tamano:
            raise ErrorVelocidad(
                f"El archivo de prueba quedó con {info.st_size:,} bytes en vez de {self.configuracion.tamano:,}."
            )
        try:
            descriptor = os.open(ARCHIVO_PRUEBA, ABRIR_PARA_VIGILAR, dir_fd=self._fd_directorio)
        except OSError as error:
            raise ErrorVelocidad(f"No se pudo abrir el archivo de prueba para vigilarlo: {error.strerror}.") from None
        try:
            propio = os.fstat(descriptor)
            if (propio.st_dev, propio.st_ino) != (info.st_dev, info.st_ino):
                motivo = "otro programa lo cambió justo al terminar la preparación"
            else:
                motivo = motivo_de_cambio(propio, self._en_la_ruta(), self.configuracion.tamano)
            if motivo:
                raise ErrorVelocidad(f"{CAMBIO}: {motivo}. Latido se detuvo por seguridad.")
        except BaseException:
            os.close(descriptor)
            raise
        self._fd_archivo = descriptor

    def _correr(self, comando, limite_segundos):
        try:
            proceso = subprocess.Popen(
                comando,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=ENTORNO,
                cwd=self.directorio,
                start_new_session=True,  # grupo de procesos propio: se detiene entero
                close_fds=True,
            )
        except OSError as error:
            raise ErrorVelocidad(f"No se pudo ejecutar {comando[0]}: {error.strerror}.") from None
        self._proceso = proceso
        limite = None if limite_segundos is None else time.monotonic() + limite_segundos
        while True:
            try:
                salida, error = proceso.communicate(timeout=INTERVALO)
                break
            except subprocess.TimeoutExpired:
                if self._cancelar.is_set():
                    raise _Cancelacion() from None
                if limite is not None and time.monotonic() > limite:
                    raise ErrorVelocidad(f"fio no terminó la medición en {limite_segundos} s y Latido lo detuvo.") from None
        self._proceso = None
        return proceso.returncode, salida, error

    # --- limpieza ---

    def _detener(self, proceso):
        """SIGTERM al grupo, espera, y SIGKILL a lo que quede. Devuelve los problemas."""
        grupo = proceso.pid
        _senal_al_grupo(grupo, signal.SIGTERM)
        limite = time.monotonic() + self._segundos_para_terminar
        while not _termino(proceso.pid) and time.monotonic() < limite:
            time.sleep(0.05)
        # fio aún no se ha recogido (sigue vivo o zombi): su PID no se reutiliza
        # todavía, así que el grupo sigue siendo el suyo.
        _senal_al_grupo(grupo, signal.SIGKILL)
        try:
            proceso.communicate(timeout=self._segundos_para_terminar)
        except subprocess.TimeoutExpired:
            for tubo in (proceso.stdout, proceso.stderr):
                if tubo:
                    tubo.close()
            return [f"fio (grupo de procesos {grupo}) no terminó ni con SIGKILL; puede seguir activo."]
        return []

    def _limpiar(self):
        limpieza = Limpieza(creo_directorio=self.directorio is not None)
        try:
            proceso, self._proceso = self._proceso, None
            if proceso is not None and proceso.returncode is None:
                limpieza.problemas += self._detener(proceso)
            if self.directorio is not None:
                self._borrar_archivo(limpieza)
                self._borrar_directorio(limpieza)
        finally:
            self._cerrar_descriptores()
        return limpieza

    def _cerrar_descriptores(self):
        """Siempre, pase lo que pase en la limpieza: archivo, directorio temporal y carpeta elegida."""
        descriptores = (self._fd_archivo, self._fd_directorio, self._fd_padre)
        self._fd_archivo = self._fd_directorio = self._fd_padre = None
        for descriptor in descriptores:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass  # no queda nada que hacer con ese; se cierran los demás

    def _borrar_archivo(self, limpieza):
        if self._fd_directorio is None:
            return  # fio nunca corrió: no puede haber archivo
        try:
            en_ruta = self._en_la_ruta()
            propio = None if self._fd_archivo is None else os.fstat(self._fd_archivo)
        except OSError as error:
            limpieza.problemas.append(f"No se pudo revisar {self.archivo}: {error.strerror}.")
            return
        ajeno = f"En {self.archivo} hay algo que no es el archivo de prueba de Latido; no se borró."
        if propio is not None:
            mismo = (
                en_ruta is not None
                and propio.st_nlink != 0
                and (en_ruta.st_dev, en_ruta.st_ino) == (propio.st_dev, propio.st_ino)
            )
            if not mismo:
                if en_ruta is not None:
                    limpieza.problemas.append(ajeno)
                if propio.st_nlink == 0:
                    limpieza.archivo_borrado_por_otro = True
                else:
                    limpieza.problemas.append(
                        "El archivo de prueba de Latido se movió o cambió de nombre (no fue Latido); no se borró."
                    )
                return
        elif en_ruta is None:
            return
        elif not stat.S_ISREG(en_ruta.st_mode) or not self._fio_pudo_crear_archivo:
            # Sin descriptor, la preparación no terminó: un archivo normal solo puede ser el que fio estaba creando.
            limpieza.problemas.append(ajeno)
            return
        if en_ruta.st_nlink != 1:
            self._archivo_sigue = True
            limpieza.problemas.append(
                f"{self.archivo} tiene {en_ruta.st_nlink} nombres (alguien le hizo un enlace duro); Latido no lo borró."
            )
            return
        try:
            os.unlink(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio)
            limpieza.archivo_borrado = True
        except OSError as error:
            self._archivo_sigue = True
            limpieza.problemas.append(f"No se pudo borrar {self.archivo}: {error.strerror}.")

    def _borrar_directorio(self, limpieza):
        nombre = os.path.basename(self.directorio)
        try:
            info = os.stat(nombre, dir_fd=self._fd_padre, follow_symlinks=False)
        except FileNotFoundError:
            limpieza.problemas.append(f"La carpeta temporal {self.directorio} ya no estaba.")
            return
        except OSError as error:
            limpieza.problemas.append(f"No se pudo revisar {self.directorio}: {error.strerror}.")
            return
        identidad = self._identidad_directorio or (info.st_dev, info.st_ino)
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identidad:
            limpieza.problemas.append(f"{self.directorio} ya no es la carpeta que creó Latido; no se borró.")
            return
        try:
            os.rmdir(nombre, dir_fd=self._fd_padre)
            limpieza.directorio_borrado = True
        except OSError as error:
            if error.errno in (errno.ENOTEMPTY, errno.EEXIST):
                limpieza.problemas += self._que_quedo(nombre, identidad)  # siempre al menos un aviso
            else:
                limpieza.problemas.append(f"No se pudo borrar {self.directorio}: {error.strerror}.")

    def _que_quedo(self, nombre, identidad):
        """Avisos de por qué rmdir no pudo borrar la carpeta temporal: qué quedó dentro, o por qué no se sabe.

        Lista con un descriptor abierto en este momento, no con el que se abrió al crear la carpeta: en btrfs
        (medido con el kernel 7.2.14) un descriptor de carpeta no ve lo que se creó después de abrirlo.
        """
        no_se_ve = f"No se borró {self.directorio}: no está vacía, pero Latido no pudo ver qué hay dentro"
        try:
            carpeta = os.open(
                nombre, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._fd_padre
            )
        except OSError as error:
            return [f"{no_se_ve} ({error.strerror}). Revísala tú."]
        try:
            info = os.fstat(carpeta)
            if (info.st_dev, info.st_ino) != identidad:
                return [
                    f"No se borró {self.directorio}: no estaba vacía, y lo que hay ahora en esa ruta ya no es la "
                    "carpeta que creó Latido. Revísala tú."
                ]
            quedan = sorted(os.listdir(carpeta))
            propios = [entrada for entrada in quedan if self._es_el_archivo_de_latido(entrada, carpeta)]
        except OSError as error:
            return [f"{no_se_ve} ({error.strerror}). Revísala tú."]
        finally:
            try:
                os.close(carpeta)
            except OSError:
                pass  # como en _cerrar_descriptores: no queda nada que hacer con ese descriptor
        if not quedan:
            return [f"{no_se_ve}. Revísala tú."]
        avisos = []
        ajenos = [entrada for entrada in quedan if entrada not in propios]
        if ajenos:
            avisos.append(
                f"No se borró {self.directorio}: quedaron archivos que Latido no creó ({', '.join(ajenos)}). "
                "Revísalos tú."
            )
        if propios:
            avisos.append(
                f"No se borró {self.directorio}: dentro sigue el archivo de prueba de Latido ({', '.join(propios)})."
            )
        return avisos

    def _es_el_archivo_de_latido(self, nombre, carpeta):
        """Si ese nombre de la carpeta temporal (abierta en carpeta) es el archivo de prueba de Latido, que quedó
        sin borrar."""
        if self._fd_archivo is None:
            return nombre == ARCHIVO_PRUEBA and self._archivo_sigue
        try:
            info = os.stat(nombre, dir_fd=carpeta, follow_symlinks=False)
            propio = os.fstat(self._fd_archivo)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == (propio.st_dev, propio.st_ino)
