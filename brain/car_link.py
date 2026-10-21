"""Laptop <-> ESP32 over UDP. Contract (do not change without telling the team):

  Laptop -> ESP32  port 4210:  "S,<steer>,<throttle>\\n"            floats -1.0..1.0, ~20 Hz
  ESP32 -> laptop  port 4211:  "T,<steer>,<throttle>,<mode>\\n"     mode = MANUAL | AUTO
  ESP32 stops the motor if no packet arrives for 300 ms in AUTO.
"""
from __future__ import annotations

import socket
import threading
import time

import config


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, float(v)))


class CarLink:
    def __init__(self, dry_run: bool | None = None):
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self.mode = "AUTO" if self.dry_run else "UNKNOWN"
        self.stick = (0.0, 0.0)
        self.last_telemetry = 0.0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if not self.dry_run:
            self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._rx.bind(("0.0.0.0", config.TELEMETRY_PORT))
            self._rx.settimeout(0.5)
            threading.Thread(target=self._listen, daemon=True).start()

    # ---------- sending ----------
    def send(self, steer: float, throttle: float) -> None:
        msg = f"S,{_clamp(steer):.3f},{_clamp(throttle):.3f}\n"
        if self.dry_run:
            return
        self._sock.sendto(msg.encode(), (config.CAR_IP, config.CMD_PORT))

    def drive(self, steer: float, throttle: float, seconds: float) -> None:
        """Hold a command for `seconds` (streamed at SEND_HZ so the watchdog stays happy), then stop."""
        if self.dry_run:
            print(f"   [car] steer={steer:+.2f} throttle={throttle:+.2f} for {seconds:.2f}s")
        end = time.time() + seconds
        period = 1.0 / config.SEND_HZ
        while time.time() < end:
            self.send(steer, throttle)
            time.sleep(period)
        self.stop()

    def stop(self) -> None:
        for _ in range(3):
            self.send(0.0, 0.0)
            time.sleep(0.02)

    def do(self, action: str, amount: float = 0.5) -> None:
        """Turn a model action ("forward", "left"...) into a short burst."""
        amount = max(0.2, min(1.0, float(amount)))
        if action == "forward":
            self.drive(0.0, config.FORWARD_THROTTLE, config.FORWARD_SECONDS * amount)
        elif action == "back":
            self.drive(0.0, -config.FORWARD_THROTTLE, config.FORWARD_SECONDS * amount)
        elif action in ("left", "right"):
            steer = -1.0 if action == "left" else 1.0
            self.drive(steer, config.TURN_THROTTLE, config.TURN_SECONDS * amount)
        else:
            self.stop()
        time.sleep(0.3)  # let the car settle before the next frame

    # ---------- telemetry ----------
    def _listen(self) -> None:
        while True:
            try:
                data, _ = self._rx.recvfrom(128)
            except socket.timeout:
                continue
            parts = data.decode(errors="ignore").strip().split(",")
            if len(parts) == 4 and parts[0] == "T":
                try:
                    self.stick = (float(parts[1]), float(parts[2]))
                    self.mode = parts[3]
                    self.last_telemetry = time.time()
                except ValueError:
                    pass

    @property
    def connected(self) -> bool:
        return self.dry_run or time.time() - self.last_telemetry < 1.0

    @property
    def auto(self) -> bool:
        return self.dry_run or (self.connected and self.mode == "AUTO")


if __name__ == "__main__":
    # Manual test: python car_link.py  (run fake_car.py first, with DRY_RUN=0 and CAR_IP=127.0.0.1)
    car = CarLink()
    print("dry run" if car.dry_run else f"sending to {config.CAR_IP}:{config.CMD_PORT}")
    for action in ["forward", "left", "right", "back"]:
        print(action, "| mode:", car.mode)
        car.do(action, 0.6)
