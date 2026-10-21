"""Pretends to be the ESP32, so the brain can be tested with no hardware.

Terminal 1:  python brain/fake_car.py
Terminal 2:  DRY_RUN=0 CAR_IP=127.0.0.1 python brain/navigator.py --source test_photos
(Windows: set DRY_RUN=0 and set CAR_IP=127.0.0.1 first.)

Prints every command it receives, sends telemetry back like the real car,
and applies the same 300 ms watchdog.
"""
import socket
import time

import config

WATCHDOG_S = 0.3


def main(mode: str = "AUTO") -> None:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("0.0.0.0", config.CMD_PORT))
    rx.settimeout(1 / config.SEND_HZ)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Fake ESP32 listening on :{config.CMD_PORT}, telemetry to :{config.TELEMETRY_PORT}, mode {mode}")

    steer = throttle = 0.0
    last_cmd = 0.0
    laptop = None
    last_print = ""
    while True:
        try:
            data, addr = rx.recvfrom(128)
            laptop = addr[0]
            parts = data.decode(errors="ignore").strip().split(",")
            if len(parts) == 3 and parts[0] == "S":
                steer, throttle = float(parts[1]), float(parts[2])
                last_cmd = time.time()
        except (socket.timeout, ValueError):
            pass

        if mode == "AUTO" and time.time() - last_cmd > WATCHDOG_S and throttle != 0.0:
            steer = throttle = 0.0
            print("   watchdog: no command for 300 ms, motor stopped")

        line = f"steer {steer:+.2f}  throttle {throttle:+.2f}"
        if line != last_print:
            print(line)
            last_print = line

        if laptop:
            tx.sendto(f"T,{steer:.3f},{throttle:.3f},{mode}\n".encode(), (laptop, config.TELEMETRY_PORT))


if __name__ == "__main__":
    import sys
    main("MANUAL" if "--manual" in sys.argv else "AUTO")
