"""Manual Bluetooth controller for the Rescue Scout car (run in Jupyter: needs ipywidgets + ipyevents + bleak).
Used for manual driving and tuning. Close it before running brain/navigator.py: the car takes one connection."""
import asyncio
import time
import ipywidgets as widgets

from IPython.display import display
from ipyevents import Event
from bleak import BleakScanner, BleakClient

# ==========================================
# BLUETOOTH SETTINGS
# ==========================================

DEVICE_NAME = "ESP32_RC_CAR"

RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

# Movement bits
KEY_BITS = {
    "w": 1,
    "s": 2,
    "a": 4,
    "d": 8,
    "ArrowUp": 16,
    "ArrowDown": 32,
    "ArrowLeft": 64,
    "ArrowRight": 128,
}

# Command bits
CAM_CENTER = 1
STEER_CENTER = 2
ESTOP = 4
RESET_ESTOP = 8

pressed = set()
commands = 0
speed_level = 1

client = None
controller_task = None
running = False
locked = True

# ==========================================
# INTERFACE
# ==========================================

title = widgets.HTML("""
<h2>ESP32-S3 RC Car Controller</h2>
<p>
<b>W/S:</b> Forward / Reverse<br>
<b>A/D:</b> Steering<br>
<b>Arrow keys:</b> Camera<br>
<b>C:</b> Centre camera<br>
<b>X:</b> Centre steering<br>
<b>1/2/3:</b> Forward speed<br>
<b>SPACE:</b> Emergency stop<br>
<b>R:</b> Unlock motor
</p>
""")

status = widgets.HTML(
    "<h3 style='color:red'>Disconnected</h3>"
)

motor_status = widgets.HTML(
    "<b>Motor:</b> LOCKED"
)

speed_selector = widgets.Dropdown(
    options=[
        ("Low - 1200us", 1),
        ("Medium - 1100us", 2),
        ("High - 1000us", 3),
    ],
    value=1,
    description="Speed:"
)

connect_button = widgets.Button(
    description="CONNECT BLUETOOTH",
    button_style="success",
    layout=widgets.Layout(width="210px")
)

disconnect_button = widgets.Button(
    description="DISCONNECT",
    button_style="warning",
    layout=widgets.Layout(width="160px")
)

stop_button = widgets.Button(
    description="EMERGENCY STOP",
    button_style="danger",
    layout=widgets.Layout(
        width="380px",
        height="55px"
    )
)

unlock_button = widgets.Button(
    description="UNLOCK MOTOR",
    button_style="warning",
    layout=widgets.Layout(width="180px")
)

keyboard_area = widgets.Button(
    description="CLICK HERE, THEN USE KEYBOARD",
    button_style="info",
    layout=widgets.Layout(
        width="400px",
        height="75px"
    )
)

# ==========================================
# KEYBOARD INPUT
# ==========================================

events = Event(
    source=keyboard_area,
    watched_events=[
        "keydown",
        "keyup"
    ],
    prevent_default_action=True
)

def key_handler(event):
    global commands, locked, speed_level

    event_type = event["type"]
    key = event.get("key", "")

    if len(key) == 1:
        key = key.lower()

    if event_type == "keydown":

        if key in KEY_BITS:
            if not locked or key not in ("w", "s"):
                pressed.add(key)

        if event.get("repeat", False):
            return

        if key == "c":
            commands |= CAM_CENTER

        elif key == "x":
            commands |= STEER_CENTER

        elif key == " ":
            emergency_stop()

        elif key == "r":
            unlock_motor()

        elif key in ("1", "2", "3"):
            speed_level = int(key)
            speed_selector.value = speed_level

    elif event_type == "keyup":
        pressed.discard(key)

events.on_dom_event(key_handler)

# ==========================================
# MOTOR SAFETY
# ==========================================

def emergency_stop():
    global commands, locked

    locked = True
    pressed.clear()
    commands |= ESTOP

    motor_status.value = (
        "<b style='color:red'>Motor: EMERGENCY STOP</b>"
    )

def unlock_motor():
    global commands, locked

    if "w" in pressed or "s" in pressed:
        return

    pressed.clear()
    locked = False
    commands |= RESET_ESTOP

    motor_status.value = (
        "<b style='color:green'>Motor: UNLOCKED</b>"
    )

def stop_clicked(button):
    emergency_stop()

def unlock_clicked(button):
    unlock_motor()

def speed_changed(change):
    global speed_level
    if change["name"] == "value":
        speed_level = change["new"]

stop_button.on_click(stop_clicked)
unlock_button.on_click(unlock_clicked)
speed_selector.observe(speed_changed, names="value")

# ==========================================
# BLUETOOTH LOOP
# ==========================================

async def bluetooth_loop():
    global client, running, commands, locked

    try:
        status.value = (
            "<h3 style='color:orange'>Scanning...</h3>"
        )

        device = await BleakScanner.find_device_by_name(
            DEVICE_NAME,
            timeout=15
        )

        if device is None:
            status.value = (
                "<h3 style='color:red'>ESP32 NOT FOUND</h3>"
            )
            return

        status.value = (
            "<h3 style='color:orange'>Connecting...</h3>"
        )

        async with BleakClient(device) as ble:
            client = ble
            running = True
            emergency_stop()

            status.value = (
                "<h3 style='color:green'>"
                "BLUETOOTH CONNECTED"
                "</h3>"
            )

            while running and ble.is_connected:

                flags = 0

                for key in pressed.copy():
                    flags |= KEY_BITS.get(key, 0)

                if locked:
                    flags &= ~(1 | 2)

                packet_commands = commands
                commands = 0

                packet = bytes([
                    flags,
                    packet_commands,
                    speed_level
                ])

                await ble.write_gatt_char(
                    RX_UUID,
                    packet,
                    response=False
                )

                await asyncio.sleep(0.05)

            if ble.is_connected:
                await ble.write_gatt_char(
                    RX_UUID,
                    bytes([0, ESTOP, speed_level]),
                    response=False
                )

    except Exception as error:
        status.value = (
            f"<h3 style='color:red'>ERROR: {error}</h3>"
        )

    finally:
        emergency_stop()
        running = False
        client = None

        if "ERROR" not in status.value:
            status.value = (
                "<h3 style='color:red'>Disconnected</h3>"
            )

# ==========================================
# BUTTON CALLBACKS
# ==========================================

def connect_clicked(button):
    global controller_task

    if controller_task is None or controller_task.done():
        controller_task = asyncio.create_task(
            bluetooth_loop()
        )

def disconnect_clicked(button):
    global running
    emergency_stop()
    running = False

connect_button.on_click(connect_clicked)
disconnect_button.on_click(disconnect_clicked)

# ==========================================
# DISPLAY
# ==========================================

display(
    widgets.VBox([
        title,
        status,
        motor_status,
        speed_selector,
        widgets.HBox([
            connect_button,
            disconnect_button
        ]),
        stop_button,
        unlock_button,
        keyboard_area
    ])
)
