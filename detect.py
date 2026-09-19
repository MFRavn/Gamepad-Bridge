"""
detect.py — Encuentra mandos conectados y decide qué perfil de traducción
usar para cada uno.

Uso manual (debug):
    python3 detect.py

Uso normal: bridge.py importa list_gamepads() y find_profile_for().
"""
import glob
import logging
import os
import yaml
# pyrefly: ignore [missing-import]
from evdev import InputDevice, ecodes, list_devices

log = logging.getLogger("gamepad-bridge.detect")

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "profiles")

# Códigos que consideramos "esto es un mando" si el dispositivo los soporta.
GAMEPAD_HINT_KEYS = {ecodes.BTN_A, ecodes.BTN_SOUTH, ecodes.BTN_GAMEPAD}


def is_gamepad(dev: InputDevice) -> bool:
    caps = dev.capabilities().get(ecodes.EV_KEY, [])
    return any(code in GAMEPAD_HINT_KEYS for code in caps)


def list_gamepads():
    """Devuelve la lista de InputDevice que parecen mandos."""
    gamepads = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        if is_gamepad(dev):
            gamepads.append(dev)
    return gamepads


def load_profiles():
    profiles = []
    for path in glob.glob(os.path.join(PROFILES_DIR, "*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            data["_path"] = path
            profiles.append(data)
    return profiles


def find_profile_for(dev: InputDevice, profiles=None):
    """
    Busca el primer perfil cuyo criterio de 'match' encaje con el dispositivo.
    Si ninguno encaja específicamente, cae al perfil identidad genérico.
    """
    profiles = profiles or load_profiles()
    info = dev.info  # bustype, vendor, product, version

    best = None
    fallback = None
    for profile in profiles:
        match = profile.get("match", {})
        name_match = match.get("name")
        vendor_match = match.get("vendor_id")
        product_match = match.get("product_id")

        is_generic = not (name_match or vendor_match or product_match)
        if is_generic:
            fallback = profile
            continue

        if name_match and name_match != dev.name:
            continue
        if vendor_match and int(vendor_match, 16) != info.vendor:
            continue
        if product_match and int(product_match, 16) != info.product:
            continue

        best = profile
        break

    return best or fallback


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pads = list_gamepads()
    if not pads:
        log.info("No se detectó ningún mando. Conecta uno y vuelve a intentar.")
    for dev in pads:
        profile = find_profile_for(dev)
        log.info("- %s  %s  vendor=%s product=%s",
                  dev.path, dev.name, hex(dev.info.vendor), hex(dev.info.product))
        log.info("  Perfil elegido: %s", profile.get("_path"))
