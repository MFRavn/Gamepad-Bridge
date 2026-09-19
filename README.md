# gamepad-bridge (v1.0)

Capa de traducción/compatibilidad para Linux: toma mandos genéricos
(cada uno con su propio mapeo de botones) y los traduce en tiempo
real a un mando virtual "Xbox 360 Controller" estándar, usando
`uinput`. Así cualquier juego, Steam Input o SDL2 lo reconoce sin
configuración adicional.

**Novedades v1.0:**
- Calibración automática de ejes: ya no se asume que el mando usa el
  mismo rango de valores que un Xbox 360 real. `bridge.py` lee el
  rango nativo de cada eje (`dev.absinfo`) y lo escala linealmente al
  rango estándar, mando por mando.
- Logging robusto vía el módulo `logging` (visible con
  `journalctl -u gamepad-bridge@*` cuando corre como servicio).
  Nivel configurable con `GAMEPAD_BRIDGE_LOGLEVEL` (`DEBUG` para ver
  cada evento traducido, útil al depurar un perfil nuevo).
- Manejo explícito de la desconexión del mando: al perder el
  dispositivo, la instancia se cierra limpia (código 0, no cuenta
  como fallo). `Restart=on-failure` en la unit de systemd solo actúa
  ante errores reales; una reconexión física dispara una unit nueva
  vía udev.

## Cómo funciona

```
Mando físico (evdev) --> bridge.py (aplica profiles/*.yaml) --> uinput --> mando virtual estándar
```

- `detect.py` identifica qué mando se ha conectado y elige el perfil de
  `profiles/` que le corresponde (por nombre o por vendor/product ID).
- `bridge.py` lee los eventos reales y los reescribe según ese perfil.
- Si no hay un perfil específico, usa `profiles/generic_identity.yaml`
  (no traduce nada, es la plantilla base).

## Instalación en CachyOS

```bash
sudo pacman -S python-evdev python-yaml   # o: pip install evdev pyyaml --break-system-packages
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf   # que cargue el módulo en cada arranque

sudo usermod -aG input $USER   # cierra sesión y vuelve a entrar para que aplique
```

Copia el proyecto a `/opt/gamepad-bridge` (la unit de systemd asume esa
ruta; cámbiala en `systemd/gamepad-bridge@.service` si usas otra):

```bash
sudo cp -r gamepad-bridge /opt/gamepad-bridge
```

Instala la regla udev y la unit de systemd:

```bash
sudo cp /opt/gamepad-bridge/udev/99-gamepad.rules /etc/udev/rules.d/
sudo cp /opt/gamepad-bridge/systemd/gamepad-bridge@.service /etc/systemd/system/
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
```

Con esto, cada vez que conectes un mando, se lanzará automáticamente
una instancia de `gamepad-bridge@eventX.service` para él.

## Probarlo a mano (sin udev/systemd, para depurar)

```bash
# 1. Averigua qué event device es tu mando:
python3 detect.py

# 2. Lánzalo manualmente:
sudo python3 bridge.py /dev/input/eventX
```

Verifica que el mando virtual aparece con:

```bash
sudo evtest
# Busca "Xbox 360 Controller (translated)" en la lista
```

## Añadir un perfil para un mando nuevo

1. Conecta el mando y ejecuta `sudo evtest` para ver qué código real
   manda cada botón/eje (ej. tu botón "A" en realidad manda `BTN_C`).
2. Copia `profiles/generic_identity.yaml` a `profiles/mi_mando.yaml`.
3. Rellena `match:` con el nombre exacto (`dev.name` que muestra
   `detect.py`) o el vendor/product ID (`cat /proc/bus/input/devices`).
4. En `buttons:` y `axes:`, pon a la izquierda el código real y a la
   derecha el código estándar al que debe traducirse.
5. Reconecta el mando (o relanza `bridge.py` a mano) para probar.

## Logging y depuración

Como servicio, revisa los logs con:

```bash
journalctl -u 'gamepad-bridge@*' -f
```

Para ver cada evento traducido (útil al ajustar un perfil), sube el
nivel de log antes de lanzarlo a mano:

```bash
GAMEPAD_BRIDGE_LOGLEVEL=DEBUG sudo -E python3 bridge.py /dev/input/eventX
```

O edita `Environment=GAMEPAD_BRIDGE_LOGLEVEL=DEBUG` en
`systemd/gamepad-bridge@.service` y recarga (`daemon-reload`) si
quieres ese nivel de forma permanente en el servicio.

## Limitaciones de esta versión

- No traduce vibración/force feedback (solo entrada, no salida).
- El "grab" del dispositivo original es exclusivo: mientras el bridge
  corre, el mando físico deja de generar eventos por su cuenta (es
  intencional, para no tener el mando físico y el virtual mandando
  inputs duplicados).
- Solo se ha podido validar la lógica de escalado con datos simulados,
  no con hardware real (sin mando disponible en el entorno de
  desarrollo). Antes de confiar en la calibración con tu mando,
  prueba con `GAMEPAD_BRIDGE_LOGLEVEL=DEBUG` y verifica que los
  valores traducidos tienen sentido.
- Sigue sin soportar múltiples mandos simultáneos como flujo
  "oficial" (cada uno lanza su propia instancia vía udev, pero no hay
  gestión centralizada ni asignación de "jugador 1/2/3"), ni
  vibración/force feedback, ni una herramienta que genere perfiles
  automáticamente a partir de `evtest`.
