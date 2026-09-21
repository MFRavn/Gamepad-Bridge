"""
test_inputs.py — Herramienta de terminal para probar el mando
conectado sin pasar por la capa de traducción. Solo escucha (no hace
grab del dispositivo), así que no interfiere con nada más que lo esté
usando a la vez.

Por ahora cubre: cruceta (d-pad), LB/RB, gatillos (LT/RT) y A/B/X/Y.

Uso:
    python3 test_inputs.py                  # detecta el mando automáticamente
    python3 test_inputs.py /dev/input/eventX # fuerza un dispositivo concreto
"""
import sys

# pyrefly: ignore [missing-import]
from evdev import InputDevice, ecodes

from detect import list_gamepads

BUTTON_NAMES = {
    ecodes.BTN_A: "A",
    ecodes.BTN_B: "B",
    ecodes.BTN_X: "X",
    ecodes.BTN_Y: "Y",
    ecodes.BTN_TL: "LB",
    ecodes.BTN_TR: "RB",
    # Algunos mandos mandan la cruceta como botones digitales en vez
    # de como eje (hat); los cubrimos también por si acaso.
    ecodes.BTN_DPAD_UP: "CRUCETA ARRIBA",
    ecodes.BTN_DPAD_DOWN: "CRUCETA ABAJO",
    ecodes.BTN_DPAD_LEFT: "CRUCETA IZQUIERDA",
    ecodes.BTN_DPAD_RIGHT: "CRUCETA DERECHA",
}

TRIGGER_NAMES = {
    ecodes.ABS_Z: "LT",
    ecodes.ABS_RZ: "RT",
}
# % del recorrido a partir del cual consideramos el gatillo "presionado".
TRIGGER_THRESHOLD_PCT = 30

HAT_X_NAMES = {-1: "CRUCETA IZQUIERDA", 1: "CRUCETA DERECHA"}
HAT_Y_NAMES = {-1: "CRUCETA ARRIBA", 1: "CRUCETA ABAJO"}


def pick_device(forced_path=None):
    if forced_path:
        return InputDevice(forced_path)

    pads = list_gamepads()
    if not pads:
        print("No se detectó ningún mando conectado.")
        sys.exit(1)
    if len(pads) == 1:
        return pads[0]

    print("Se detectaron varios mandos:")
    for i, dev in enumerate(pads):
        print(f"  [{i}] {dev.name} ({dev.path})")
    idx = int(input("Elige el número del mando a probar: "))
    return pads[idx]


def handle_button(event):
    name = BUTTON_NAMES[event.code]
    if event.value == 1:
        print(f'Botón "{name}" presionado')
    elif event.value == 0:
        print(f'Botón "{name}" soltado')
    # value == 2 es autorepeat del kernel; lo ignoramos.


def handle_trigger(dev, event, trigger_state):
    name = TRIGGER_NAMES[event.code]
    absinfo = dev.absinfo(event.code)
    span = max(1, absinfo.max - absinfo.min)
    pct = (event.value - absinfo.min) / span * 100
    pressed = pct > TRIGGER_THRESHOLD_PCT

    if pressed and not trigger_state[event.code]:
        print(f'Gatillo "{name}" presionado ({pct:.0f}%)')
    elif not pressed and trigger_state[event.code]:
        print(f'Gatillo "{name}" soltado')

    trigger_state[event.code] = pressed


def handle_hat_axis(event, current_state, names):
    """current_state es una lista de 1 elemento para poder mutarla desde fuera."""
    if event.value == current_state[0]:
        return
    if event.value == 0 and current_state[0] in names:
        print(f'"{names[current_state[0]]}" soltada')
    elif event.value in names:
        print(f'"{names[event.value]}" presionada')
    current_state[0] = event.value


def main():
    forced_path = sys.argv[1] if len(sys.argv) > 1 else None
    dev = pick_device(forced_path)

    print(f"Escuchando '{dev.name}' en {dev.path}.")
    print("Prueba la cruceta, LB/RB, los gatillos y A/B/X/Y. Ctrl+C para salir.\n")

    trigger_state = {code: False for code in TRIGGER_NAMES}
    hat_x_state = [0]
    hat_y_state = [0]

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.code in BUTTON_NAMES:
                handle_button(event)

            elif event.type == ecodes.EV_ABS and event.code in TRIGGER_NAMES:
                handle_trigger(dev, event, trigger_state)

            elif event.type == ecodes.EV_ABS and event.code == ecodes.ABS_HAT0X:
                handle_hat_axis(event, hat_x_state, HAT_X_NAMES)

            elif event.type == ecodes.EV_ABS and event.code == ecodes.ABS_HAT0Y:
                handle_hat_axis(event, hat_y_state, HAT_Y_NAMES)

    except KeyboardInterrupt:
        print("\nSaliendo...")
    except OSError:
        print("\nEl mando se ha desconectado.")


if __name__ == "__main__":
    main()
