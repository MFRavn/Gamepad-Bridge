"""
bridge.py — Traduce eventos de un mando físico a un mando virtual
"Xbox 360 Controller" estándar usando uinput, aplicando el perfil
de mapeo correspondiente.

Uso manual:
    sudo python3 bridge.py /dev/input/eventX

Uso normal: lo lanza udev/systemd automáticamente al conectar un mando
(ver udev/99-gamepad.rules y systemd/gamepad-bridge@.service).

Requisitos:
    - módulo del kernel 'uinput' cargado (sudo modprobe uinput)
    - permisos sobre /dev/uinput (normalmente hace falta root o
      pertenecer a un grupo con esa regla udev, ver README)
    - pip install evdev  (--break-system-packages si usas el Python del sistema)
"""
import sys
import time

from evdev import InputDevice, UInput, ecodes, categorize

from detect import find_profile_for, load_profiles

# Capacidades que anuncia el mando virtual: deben cubrir el superset
# de lo que puede llegar a necesitar cualquier juego que espere un
# Xbox 360 Controller estándar.
VIRTUAL_CAPABILITIES = {
    ecodes.EV_KEY: [
        ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y,
        ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_SELECT, ecodes.BTN_START,
        ecodes.BTN_MODE, ecodes.BTN_THUMBL, ecodes.BTN_THUMBR,
    ],
    ecodes.EV_ABS: [
        (ecodes.ABS_X, (0, -32768, 32767, 16, 128)),
        (ecodes.ABS_Y, (0, -32768, 32767, 16, 128)),
        (ecodes.ABS_RX, (0, -32768, 32767, 16, 128)),
        (ecodes.ABS_RY, (0, -32768, 32767, 16, 128)),
        (ecodes.ABS_Z, (0, 0, 255, 0, 0)),
        (ecodes.ABS_RZ, (0, 0, 255, 0, 0)),
        (ecodes.ABS_HAT0X, (0, -1, 1, 0, 0)),
        (ecodes.ABS_HAT0Y, (0, -1, 1, 0, 0)),
    ],
}

# Vendor/product del Xbox 360 Controller (cableado) tal como lo espera
# el driver xpad. Anunciarnos con este ID ayuda a que Steam/SDL2/juegos
# lo reconozcan sin configuración extra.
VIRTUAL_VENDOR = 0x045E
VIRTUAL_PRODUCT = 0x028E
VIRTUAL_NAME = "Xbox 360 Controller (translated)"


def build_code_maps(profile):
    """Convierte el perfil (nombres en texto) a diccionarios código->código."""
    btn_map = {}
    for src_name, dst_name in profile.get("buttons", {}).items():
        src = getattr(ecodes, src_name, None)
        dst = getattr(ecodes, dst_name, None)
        if src is not None and dst is not None:
            btn_map[src] = dst

    axis_map = {}
    for src_name, cfg in profile.get("axes", {}).items():
        src = getattr(ecodes, src_name, None)
        dst = getattr(ecodes, cfg["to"], None)
        if src is not None and dst is not None:
            axis_map[src] = {"to": dst, "invert": cfg.get("invert", False)}

    return btn_map, axis_map


def run_bridge(source_path: str):
    dev = InputDevice(source_path)
    profile = find_profile_for(dev, load_profiles())
    btn_map, axis_map = build_code_maps(profile)

    print(f"[gamepad-bridge] Origen: {dev.name} ({source_path})")
    print(f"[gamepad-bridge] Perfil: {profile.get('_path')}")

    ui = UInput(
        VIRTUAL_CAPABILITIES,
        name=VIRTUAL_NAME,
        vendor=VIRTUAL_VENDOR,
        product=VIRTUAL_PRODUCT,
    )

    try:
        dev.grab()  # evita que el mando "original" también mande eventos duplicados
    except OSError:
        print("[gamepad-bridge] Aviso: no se pudo hacer grab() del dispositivo "
              "(¿ya está ocupado por otro proceso?)")

    print("[gamepad-bridge] Traduciendo eventos... (Ctrl+C para salir)")
    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.code in btn_map:
                ui.write(ecodes.EV_KEY, btn_map[event.code], event.value)
                ui.syn()

            elif event.type == ecodes.EV_ABS and event.code in axis_map:
                mapping = axis_map[event.code]
                value = event.value
                if mapping["invert"]:
                    absinfo = dev.absinfo(event.code)
                    value = absinfo.max - (value - absinfo.min)
                ui.write(ecodes.EV_ABS, mapping["to"], value)
                ui.syn()

    except KeyboardInterrupt:
        pass
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        ui.close()
        print("[gamepad-bridge] Cerrado.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 bridge.py /dev/input/eventX")
        sys.exit(1)

    # Pequeña espera por si udev lanza esto justo al conectar el mando,
    # antes de que el nodo esté completamente listo.
    time.sleep(0.3)
    run_bridge(sys.argv[1])
