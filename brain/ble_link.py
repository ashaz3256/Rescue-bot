"""Laptop -> ESP32-S3 car over Bluetooth LE (the protocol our car firmware uses).

Packet (3 bytes, sent every 50 ms to the RX characteristic):
  byte 0  movement flags: w=1 forward, s=2 reverse, a=4 left, d=8 right,
          camera: up=16, down=32, left=64, right=128
  byte 1  commands: 1 centre camera, 2 centre steering, 4 emergency stop, 8 unlock motor
  byte 2  speed level 1-3 (1 = slowest)

Same interface as car_link.CarLink (do / drive / stop / auto / connected / dry_run),
so navigator.py doesn't care which link is used.

Test with the wheels off the ground:   python brain/ble_link.py
Close the Jupyter controller first: the car accepts one Bluetooth connection at a time.
"""
from __future__ import annotations

import asyncio
import threading
import time

import config

W, S, A, D = 1, 2, 4, 8
CAM_CENTER, STEER_CENTER, ESTOP, UNLOCK = 1, 2, 4, 8


class BleCarLink:
    def __init__(self, dry_run: bool | None = None):
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self.mode = "AUTO"
        self._flags = 0
        self._commands = 0
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._running = True
        self._error = None
        if not self.dry_run:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            if not self._connected.wait(25):
                raise SystemExit(f"Could not connect to {config.BLE_NAME} over Bluetooth: {self._error or 'timeout'}. "
                                 "Is the car on, and the Jupyter controller disconnected?")
            # Start safe: stopped, steering and camera centred, then unlock the motor.
            self._queue(ESTOP)
            time.sleep(0.2)
            self._queue(UNLOCK | STEER_CENTER | CAM_CENTER)
            time.sleep(0.3)
            print(f"Connected to {config.BLE_NAME}, motor unlocked, camera centred")

    # ---------- Bluetooth loop (background thread) ----------
    def _run(self) -> None:
        try:
            asyncio.run(self._loop())
        except Exception as e:  # surface the reason to the main thread
            self._error = e

    async def _loop(self) -> None:
        from bleak import BleakClient, BleakScanner
        device = await BleakScanner.find_device_by_name(config.BLE_NAME, timeout=15)
        if device is None:
            self._error = "car not found"
            return
        async with BleakClient(device) as ble:
            self._connected.set()
            while self._running and ble.is_connected:
                with self._lock:
                    packet = bytes([self._flags, self._commands, config.BLE_SPEED])
                    self._commands = 0
                await ble.write_gatt_char(config.BLE_RX_UUID, packet, response=False)
                await asyncio.sleep(0.05)
            if ble.is_connected:  # always leave the car stopped
                await ble.write_gatt_char(config.BLE_RX_UUID, bytes([0, ESTOP, config.BLE_SPEED]), response=False)
                await asyncio.sleep(0.1)
        self._connected.clear()

    def _queue(self, cmd: int) -> None:
        with self._lock:
            self._commands |= cmd

    def _set(self, flags: int) -> None:
        with self._lock:
            self._flags = flags

    # ---------- same interface as CarLink ----------
    def drive(self, steer: float, throttle: float, seconds: float) -> None:
        """Hold a direction for `seconds`, then stop. Steering is left/right/straight (the car is digital)."""
        flags = 0
        if throttle > 0.05:
            flags |= W
        elif throttle < -0.05:
            flags |= S
        if steer < -0.3:
            flags |= A
        elif steer > 0.3:
            flags |= D
        if self.dry_run:
            print(f"   [car] flags={flags:04b} for {seconds:.2f}s")
            return
        self._set(flags)
        time.sleep(seconds)
        self.stop()

    def stop(self) -> None:
        if not self.dry_run:
            self._set(0)
            time.sleep(0.1)

    def do(self, action: str, amount: float = 0.5) -> None:
        amount = max(0.2, min(1.0, float(amount)))
        if action == "forward":
            self.drive(0.0, 1.0, config.FORWARD_SECONDS * amount)
        elif action == "back":
            self.drive(0.0, -1.0, config.FORWARD_SECONDS * amount)
        elif action in ("left", "right"):
            # This car turns while rolling forward, like a real car.
            self.drive(-1.0 if action == "left" else 1.0, 1.0, config.TURN_SECONDS * amount)
        else:
            self.stop()
        if not self.dry_run:
            self._queue(STEER_CENTER)
        time.sleep(0.3)  # let the car settle before the next frame

    def emergency_stop(self) -> None:
        if not self.dry_run:
            self._set(0)
            self._queue(ESTOP)
            time.sleep(0.2)

    def close(self) -> None:
        self.emergency_stop()
        self._running = False
        time.sleep(0.3)

    @property
    def connected(self) -> bool:
        return self.dry_run or self._connected.is_set()

    @property
    def auto(self) -> bool:
        return self.connected


if __name__ == "__main__":
    # Bench test: wheels off the ground. Ctrl+C stops the car.
    car = BleCarLink(dry_run=False)
    try:
        for action in ["forward", "left", "right", "back"]:
            print(action)
            car.do(action, 0.6)
            time.sleep(0.7)
    except KeyboardInterrupt:
        pass
    finally:
        car.close()
        print("Stopped")
