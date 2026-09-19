"""
bridge.py — Traduce eventos de un mando físico a un mando virtual
"Xbox 360 Controller" estándar usando uinput, aplicando el perfil
de mapeo correspondiente. Incluye calibración automática de ejes
(escala el rango real del mando al rango estándar del virtual) y
logging robusto para diagnosticar problemas vía journalctl.

Uso manual:
    sudo python3 bridge.py /dev/input/eventX

Variables de entorno:
    GAMEPAD_BRIDGE_LOGLEVEL  DEBUG | INFO (default) | WARNING | ERROR

Uso normal: lo lanza udev/systemd automáticamente al conectar un mando
(ver udev/99-gamepad.rules y systemd/gamepad-bridge@.service).

Requisitos:
    - módulo del kernel 'uinput' cargado (sudo modprobe uinput)
    - permisos sobre /dev/uinput (ver README, grupo 'input')
    - pip install evdev pyyaml (--break-system-packages si usas el Python del sistema)
"""
import logging
import os
import sys
import time

# pyrefly: ignore [missing-import]
from evdev import InputDevice, UInput, ecodes

from detect import find_profile_for, load_profiles

log = logging.getLogger("gamepad-bridge")

# Capacidades + rango de valores que anuncia el mando virtual. Estos
# rangos son el "destino" al que escalamos los ejes del mando real,
# sean cuales sean sus valores nativos.
VIRTUAL_ABS_RANGES = {
    ecodes.ABS_X:    (-32768, 32767),
    ecodes.ABS_Y:    (-32768, 32767),
    ecodes.ABS_RX:   (-32768, 32767),
    ecodes.ABS_RY:   (-32768, 32767),
    ecodes.ABS_Z:    (0, 255),
    ecodes.ABS_RZ:   (0, 255),
    ecodes.ABS_HAT0X: (-1, 1),
    ecodes.ABS_HAT0Y: (-1, 1),
}

VIRTUAL_CAPABILITIES = {
    ecodes.EV_KEY: [
        ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y,
        ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_SELECT, ecodes.BTN_START,
        ecodes.BTN_MODE, ecodes.BTN_THUMBL, ecodes.BTN_THUMBR,
    ],
    ecodes.EV_ABS: [
        (code, (0, lo, hi, 16 if code in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY) else 0, 128 if code in (ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY) else 0))
        for code, (lo, hi) in VIRTUAL_ABS_RANGES.items()
    ],
}

# Vendor/product del Xbox 360 Controller (cableado) tal como lo espera
# el driver xpad. Anunciarnos con este ID ayuda a que Steam/SDL2/juegos
# lo reconozcan sin configuración extra.
VIRTUAL_VENDOR = 0x045E
VIRTUAL_PRODUCT = 0x028E
VIRTUAL_NAME = "Xbox 360 Controller (translated)"

RECONNECT_WAIT_SECONDS = 0.3


def setup_logging():
    level_name = os.environ.get("GAMEPAD_BRIDGE_LOGLEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,  # systemd/journald captura stdout tal cual
    )


def build_code_maps(profile):
    """Convierte el perfil (nombres en texto) a diccionarios código->código."""
    btn_map = {}
    for src_name, dst_name in profile.get("buttons", {}).items():
        src = getattr(ecodes, src_name, None)
        dst = getattr(ecodes, dst_name, None)
        if src is None or dst is None:
            log.warning("Código de botón desconocido en el perfil: %s -> %s", src_name, dst_name)
            continue
        btn_map[src] = dst

    axis_map = {}
    for src_name, cfg in profile.get("axes", {}).items():
        src = getattr(ecodes, src_name, None)
        dst = getattr(ecodes, cfg["to"], None)
        if src is None or dst is None:
            log.warning("Código de eje desconocido en el perfil: %s -> %s", src_name, cfg)
            continue
        axis_map[src] = {"to": dst, "invert": cfg.get("invert", False)}

    return btn_map, axis_map


def build_calibration(dev, axis_map):
    """
    Para cada eje mapeado, lee el rango REAL que reporta el mando
    (dev.absinfo) y calcula los parámetros para escalarlo linealmente
    al rango del eje virtual correspondiente. Así no asumimos que el
    mando usa el mismo rango que un Xbox 360 real.
    """
    calibration = {}
    for src_code, mapping in axis_map.items():
        dst_code = mapping["to"]
        try:
            absinfo = dev.absinfo(src_code)
        except OSError:
            log.warning("El mando no reporta absinfo para %s, se omite ese eje", src_code)
            continue

        src_min, src_max = absinfo.min, absinfo.max
        dst_min, dst_max = VIRTUAL_ABS_RANGES.get(dst_code, (src_min, src_max))

        if src_max == src_min:
            log.warning("Rango inválido (min==max) en eje %s, se usa passthrough", src_code)
            src_min, src_max = dst_min, dst_max

        calibration[src_code] = {
            "src_min": src_min, "src_max": src_max,
            "dst_min": dst_min, "dst_max": dst_max,
            "invert": mapping["invert"],
        }
        log.debug(
            "Calibración eje %s -> %s: origen[%s, %s] -> destino[%s, %s]",
            src_code, dst_code, src_min, src_max, dst_min, dst_max,
        )
    return calibration


def scale_value(value, cal):
    src_min, src_max = cal["src_min"], cal["src_max"]
    dst_min, dst_max = cal["dst_min"], cal["dst_max"]

    # normaliza a 0..1 dentro del rango de origen, clamp por seguridad
    ratio = (value - src_min) / (src_max - src_min)
    ratio = max(0.0, min(1.0, ratio))

    if cal["invert"]:
        ratio = 1.0 - ratio

    return round(dst_min + ratio * (dst_max - dst_min))


def run_bridge(source_path: str):
    dev = InputDevice(source_path)
    profile = find_profile_for(dev, load_profiles())
    btn_map, axis_map = build_code_maps(profile)
    calibration = build_calibration(dev, axis_map)

    log.info("Origen: %s (%s)", dev.name, source_path)
    log.info("Perfil: %s", profile.get("_path"))

    ui = UInput(
        VIRTUAL_CAPABILITIES,
        name=VIRTUAL_NAME,
        vendor=VIRTUAL_VENDOR,
        product=VIRTUAL_PRODUCT,
    )
    log.info("Mando virtual creado: %s", VIRTUAL_NAME)

    try:
        dev.grab()  # evita que el mando "original" también mande eventos duplicados
    except OSError:
        log.warning("No se pudo hacer grab() del dispositivo (¿ya está ocupado por otro proceso?)")

    log.info("Traduciendo eventos... (Ctrl+C para salir)")
    exit_code = 0
    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.code in btn_map:
                ui.write(ecodes.EV_KEY, btn_map[event.code], event.value)
                ui.syn()
                log.debug("BTN %s -> %s = %s", event.code, btn_map[event.code], event.value)

            elif event.type == ecodes.EV_ABS and event.code in calibration:
                cal = calibration[event.code]
                scaled = scale_value(event.value, cal)
                dst_code = axis_map[event.code]["to"]
                ui.write(ecodes.EV_ABS, dst_code, scaled)
                ui.syn()
                log.debug("ABS %s=%s -> %s=%s", event.code, event.value, dst_code, scaled)

    except KeyboardInterrupt:
        log.info("Interrumpido por el usuario.")
    except OSError as exc:
        # Típico cuando el mando físico se desconecta: el nodo /dev/input/eventX
        # deja de existir a mitad de lectura. No es un error del programa,
        # así que salimos limpio con código 0 para que systemd no lo trate
        # como un fallo (el reconecte lo disparará udev con una unit nueva).
        log.info("El mando se ha desconectado (%s). Cerrando esta instancia.", exc)
    except Exception:
        log.exception("Error inesperado en el bucle de traducción")
        exit_code = 1
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        ui.close()
        log.info("Cerrado.")

    return exit_code


if __name__ == "__main__":
    setup_logging()

    if len(sys.argv) != 2:
        log.error("Uso: python3 bridge.py /dev/input/eventX")
        sys.exit(1)

    # Pequeña espera por si udev lanza esto justo al conectar el mando,
    # antes de que el nodo esté completamente listo.
    time.sleep(RECONNECT_WAIT_SECONDS)

    try:
        code = run_bridge(sys.argv[1])
    except FileNotFoundError:
        log.error("No existe el dispositivo %s (¿se desconectó antes de arrancar?)", sys.argv[1])
        code = 0  # no reintentar con systemd: el nodo puede no volver a existir con este nombre

    sys.exit(code)
