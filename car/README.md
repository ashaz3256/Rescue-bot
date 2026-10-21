# Car (ESP32)

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
