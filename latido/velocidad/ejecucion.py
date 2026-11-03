"""Ejecuta los pasos de una prueba de velocidad con fio y limpia siempre.

Regla de oro de esta pestaña:
- fio escribe solo <carpeta>/.latido-velocidad-XXXXXXXX/latido-velocidad.dat,
  dentro de un directorio NUEVO creado con tempfile.mkdtemp (modo 0700).
- Antes de cada paso se comprueba que el directorio y el archivo siguen siendo
  los que creó Latido (mismo dispositivo e inodo, sin enlaces simbólicos). El
  archivo no existe antes de la preparación: fio lo crea.
- Al terminar, fallar, cancelar o por una excepción: se detiene el grupo de
  procesos de fio, se borra solo el archivo de prueba por su nombre exacto y
  luego el directorio con rmdir. Nunca rm -r ni shutil.rmtree.
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

_una_a_la_vez = threading.Lock()


class _Cancelacion(Exception):
    """Interna: el usuario pidió cancelar."""


@dataclass
class Limpieza:
    creo_directorio: bool = False
    archivo_borrado: bool = False
    directorio_borrado: bool = False
    problemas: list = field(default_factory=list)

    @property
    def completa(self):
        return not self.problemas

    def texto(self):
        if self.problemas:
            return "La limpieza quedó incompleta:\n" + "\n".join(self.problemas)
        if not self.creo_directorio:
            return "No se llegó a crear ningún archivo."
        if self.archivo_borrado:
            return "Se borraron el archivo de prueba y su carpeta temporal."
        return "Se borró la carpeta temporal; el archivo de prueba no llegó a crearse."


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
        self._identidad_directorio = None
        self._identidad_archivo = None
        self._fio_pudo_crear_archivo = False
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
            self._verificar_antes(paso)
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
                self._registrar_archivo()
                medicion = None
            else:
                resultado.agregar(paso, medicion)
            self._al_progresar(Progreso(indice, total, paso, terminado=True, medicion=medicion))

    def _verificar_antes(self, paso):
        try:
            info = os.lstat(self.directorio)
        except OSError:
            info = None
        if info is None or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._identidad_directorio:
            raise ErrorVelocidad("La carpeta temporal de la prueba cambió o desapareció; Latido se detuvo por seguridad.")
        try:
            info = os.stat(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio, follow_symlinks=False)
        except FileNotFoundError:
            info = None
        if paso.es_preparacion:
            if info is not None:
                raise ErrorVelocidad(
                    "Ya había algo en la ruta del archivo de prueba antes de crearlo; Latido no lo usa y se detuvo."
                )
        elif (
            info is None
            or not stat.S_ISREG(info.st_mode)
            or (info.st_dev, info.st_ino) != self._identidad_archivo
            or info.st_size != self.configuracion.tamano
        ):
            raise ErrorVelocidad("El archivo de prueba cambió o desapareció entre dos pasos; Latido se detuvo por seguridad.")

    def _registrar_archivo(self):
        try:
            info = os.stat(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio, follow_symlinks=False)
        except FileNotFoundError:
            raise ErrorVelocidad("fio terminó la preparación sin crear el archivo de prueba.") from None
        if not stat.S_ISREG(info.st_mode):
            raise ErrorVelocidad("Lo que quedó en la ruta del archivo de prueba no es un archivo normal.")
        if info.st_size != self.configuracion.tamano:
            raise ErrorVelocidad(
                f"El archivo de prueba quedó con {info.st_size:,} bytes en vez de {self.configuracion.tamano:,}."
            )
        self._identidad_archivo = (info.st_dev, info.st_ino)

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
        proceso, self._proceso = self._proceso, None
        if proceso is not None and proceso.returncode is None:
            limpieza.problemas += self._detener(proceso)
        if self.directorio is not None:
            self._borrar_archivo(limpieza)
            self._borrar_directorio(limpieza)
        for descriptor in (self._fd_directorio, self._fd_padre):
            if descriptor is not None:
                os.close(descriptor)
        self._fd_directorio = self._fd_padre = None
        return limpieza

    def _borrar_archivo(self, limpieza):
        if self._fd_directorio is None:
            return  # fio nunca corrió: no puede haber archivo
        try:
            info = os.stat(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as error:
            limpieza.problemas.append(f"No se pudo revisar {self.archivo}: {error.strerror}.")
            return
        if self._identidad_archivo is not None:
            conocido = (info.st_dev, info.st_ino) == self._identidad_archivo
        else:
            conocido = self._fio_pudo_crear_archivo  # se canceló o falló durante la preparación
        if not stat.S_ISREG(info.st_mode) or not conocido:
            limpieza.problemas.append(f"En {self.archivo} hay algo que no es el archivo de prueba de Latido; no se borró.")
            return
        try:
            os.unlink(ARCHIVO_PRUEBA, dir_fd=self._fd_directorio)
            limpieza.archivo_borrado = True
        except OSError as error:
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
        mismo = self._identidad_directorio is None or (info.st_dev, info.st_ino) == self._identidad_directorio
        if not stat.S_ISDIR(info.st_mode) or not mismo:
            limpieza.problemas.append(f"{self.directorio} ya no es la carpeta que creó Latido; no se borró.")
            return
        try:
            os.rmdir(nombre, dir_fd=self._fd_padre)
            limpieza.directorio_borrado = True
        except OSError as error:
            if error.errno in (errno.ENOTEMPTY, errno.EEXIST) and self._fd_directorio is not None:
                quedan = ", ".join(sorted(os.listdir(self._fd_directorio)))
                limpieza.problemas.append(
                    f"No se borró {self.directorio}: quedaron archivos que Latido no creó ({quedan}). Revísalos tú."
                )
            else:
                limpieza.problemas.append(f"No se pudo borrar {self.directorio}: {error.strerror}.")
