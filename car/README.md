# Car (ESP32-S3)

**`esp32_ble_car/esp32_ble_car.ino` is the firmware the car runs.** The laptop drives it over Bluetooth LE
(`brain/ble_link.py`): a 3-byte packet every 50 ms (movement keys, commands, speed level 1-3).

What the firmware does:
- Steering and camera pan/tilt servos move smoothly while a key is held and stay where they are until a
  centre command (the laptop pre-steers before a turn and re-centres after every move).
- Motor starts locked; emergency stop on connect, then unlock. Stops if no packet arrives for 350 ms.
- Forward <-> reverse needs a neutral pause (cheap ESC: forward, neutral, brake, neutral, reverse).
- Optional rear ultrasonic sensor (HC-SR04, TRIG 15 / ECHO 16 via a divider): refuses to reverse into
  anything closer than 20 cm. Without the sensor it reads "clear".
- Tuning at the top of the sketch: `STEER_TRIM` (straight-ahead), `STEER_RANGE` (full lock),
  `YAW_RANGE` (camera pan), `FORWARD_LOW/MED/HIGH` (speed levels).

Pins: steering GPIO 4, camera pitch 5, camera yaw 6, ESC 7.

`../tools/jupyter_controller.py` is our manual keyboard controller over the same Bluetooth link.

---

## Older Wi-Fi option (not what the car runs)

`esp32_scout/esp32_scout.ino` is a reference sketch. If your existing iBus + servo code already works, copy in the UDP, mode switch and watchdog parts rather than starting again.

## Wiring (defaults, change at the top of the sketch)

| From | To ESP32 pin |
|---|---|
| Flysky receiver iBus signal | GPIO 16 (Serial2 RX) |
| Steering servo signal | GPIO 18 |
| ESC signal (or H-bridge PWM) | GPIO 19 |
| H-bridge direction A / B (only if no ESC) | GPIO 25 / 26 |
| Grounds | all common |

If the motor goes through an H-bridge (L298N / TB6612) instead of an ESC, uncomment `#define MOTOR_HBRIDGE`.

## Flashing

1. Arduino IDE → install the **esp32** board package (Boards Manager).
2. Library Manager → install **IBusBM** and **ESP32Servo**.
3. Set `WIFI_SSID` / `WIFI_PASS` to a network the laptop is also on (phone hotspot works). The laptop still needs internet for the AI, so don't make the ESP32 its own access point.
4. Upload, open Serial Monitor at 115200, and note the printed **Car IP**. Put it in the laptop's `.env` as `CAR_IP`.

## Bench test (wheels off the ground)

1. Transmitter switch on **MANUAL**: sticks should steer and drive as normal.
2. On the laptop: `DRY_RUN=0 python brain/car_link.py` (with `CAR_IP` set).
3. Flip the switch to **AUTO**: the car should do forward, left, right and back bursts.
4. Stop the laptop script mid-move: the motor must stop within about 0.3 s (watchdog).
5. Flip back to **MANUAL** mid-move: sticks take over instantly.

Don't run it on the floor until steps 4 and 5 both pass.

## Settings to tune

- `STEER_LEFT_US / CENTER / RIGHT`: so full left and right don't strain the servo.
- `ESC_FORWARD_US / REVERSE_US`: keep these gentle for indoor demos.
- On the laptop in `brain/config.py`: `FORWARD_SECONDS`, `TURN_SECONDS`, `FORWARD_THROTTLE`, `METRES_PER_FORWARD`, `DEGREES_PER_TURN`. Measure them once on the real floor so the breadcrumb map is roughly right.
