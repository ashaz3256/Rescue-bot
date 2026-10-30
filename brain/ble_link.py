"""Laptop -> ESP32-S3 car over Bluetooth LE (the protocol our car firmware uses).

Packet (3 bytes, sent every 50 ms to the RX characteristic):
  byte 0  movement flags: w=1 forward, s=2 reverse, a=4 left, d=8 right,
          camera: up=16, down=32, left=64, right=128
  byte 1  commands: 1 centre camera, 2 centre steering, 4 emergency stop, 8 unlock motor
  byte 2  speed level 1-3 (1 = slowest)

Same interface as car_link.CarLink (do / drive / stop / auto / connected / dry_run),
so navigator.py doesn't care which link is used.

Test with the wheels off the ground:   python brain/ble_link.py
Steering only (no throttle):           python brain/ble_link.py --steer
On the floor, measure one turn:        python brain/ble_link.py --turn
On the floor, measure one forward move: python brain/ble_link.py --forward
Camera pan check:                      python brain/ble_link.py --pan
Three-point turn (search):             python brain/ble_link.py --spin
List Bluetooth devices:                python brain/ble_link.py --scan
Close the Jupyter controller first: the car accepts one Bluetooth connection at a time.
"""
from __future__ import annotations

import asyncio
import threading
import time

import config
import keys

W, S, A, D = 1, 2, 4, 8
CAM_UP, CAM_DOWN, CAM_LEFT, CAM_RIGHT = 16, 32, 64, 128
CAM_CENTER, STEER_CENTER, ESTOP, UNLOCK = 1, 2, 4, 8


UART_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"  # Nordic UART service the car firmware advertises


async def find_car(BleakScanner):
    """Find the car by address (BLE_ADDRESS), then by name, then by its UART service.
    Windows often hides device names, so the service check is the reliable fallback."""
    if config.BLE_ADDRESS:
        return await BleakScanner.find_device_by_address(config.BLE_ADDRESS, timeout=15)
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    for device, adv in found.values():
        if (adv.local_name or device.name or "") == config.BLE_NAME:
            return device
    for device, adv in found.values():
        if UART_SERVICE in [u.lower() for u in (adv.service_uuids or [])]:
            print(f"Found the car by its service at {device.address}")
            return device
    return None


async def _scan() -> None:
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    for device, adv in sorted(found.values(), key=lambda x: -(x[1].rssi or -999)):
        mark = "  <-- CAR?" if (adv.local_name == config.BLE_NAME or
                               UART_SERVICE in [u.lower() for u in (adv.service_uuids or [])]) else ""
        print(f"{device.address}  rssi {adv.rssi:>4}  name {adv.local_name or device.name}{mark}")


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
        self._last_dir = 0
        if not self.dry_run:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            if not self._connected.wait(25):
                raise SystemExit(f"Could not connect to {config.BLE_NAME} over Bluetooth: {self._error or 'timeout'}. "
                                 "Is the car on, and the Jupyter controller disconnected?")
            # Start safe, exactly like the Jupyter controller: emergency stop on connect, centre things,
            # then the unlock command ON ITS OWN in a separate packet (the firmware may ignore an unlock
            # that arrives combined with other commands), then hold neutral so the ESC is ready.
            self._queue(ESTOP)
            time.sleep(0.5)
            self._queue(STEER_CENTER | CAM_CENTER)
            time.sleep(0.3)
            self._queue(UNLOCK)
            time.sleep(1.0)
            print(f"Connected to {config.BLE_NAME}, motor unlocked, camera centred")

    # ---------- Bluetooth loop (background thread) ----------
    def _run(self) -> None:
        try:
            asyncio.run(self._loop())
        except Exception as e:  # surface the reason to the main thread
            self._error = e

    async def _loop(self) -> None:
        from bleak import BleakClient, BleakScanner
        device = await find_car(BleakScanner)
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
    def drive(self, steer: float, throttle: float, seconds: float, manual: bool = False) -> None:
        """Hold a direction for `seconds`, then stop. An AI move is cut short the moment SPACE (pause)
        or Q is pressed; manual moves are not.

        How the firmware behaves (car sketch): holding A/D moves the steering a little every 20 ms and it
        STAYS there until a centre command; a change between forward and reverse needs the keys released
        and ~0.7 s of neutral first. So turns pre-steer while stopped, and direction changes wait."""
        flags = 0
        if throttle > 0.05:
            flags |= W
        elif throttle < -0.05:
            flags |= S
        steer_bit = A if steer < -0.3 else D if steer > 0.3 else 0
        if self.dry_run:
            print(f"   [car] flags={flags | steer_bit:04b} for {seconds:.2f}s")
            return
        direction = flags & (W | S)
        if direction and self._last_dir and direction != self._last_dir:
            self._gear_change(direction)
        if steer_bit and config.PRESTEER_SECONDS > 0:
            # Turn the wheels first while stopped: sharper, repeatable turns with less forward roll.
            self._set(steer_bit)
            time.sleep(config.PRESTEER_SECONDS)
        flags |= steer_bit
        self._set(flags)
        if direction:
            self._last_dir = direction
        # Software trim (laptop side) for a car that pulls to one side. Better: STEER_TRIM in the sketch.
        trim = config.STEER_TRIM if flags in (W, S) else 0.0
        trim_bit = A if trim < 0 else D
        start = time.time()
        end = start + seconds
        while time.time() < end:
            if not manual and keys.stop_requested():
                break
            if trim:
                phase = ((time.time() - start) % 0.2) / 0.2
                self._set(flags | trim_bit if phase < abs(trim) else flags)
            time.sleep(0.02)
        self.stop()

    def spin(self, direction: str) -> None:
        """Three-point turn: forward with full lock one way, then reverse with full lock the other way.
        Both halves rotate the car the same way, so it turns about twice as far with almost no travel."""
        fwd = -1.0 if direction == "left" else 1.0
        self.last_amount = 1.0
        self.drive(fwd, 1.0, config.TURN_SECONDS)
        if not self.dry_run:
            self._queue(STEER_CENTER)   # jump the steering back to centre before locking the other way
            time.sleep(0.35)
        if keys.stop_requested():
            return
        self.drive(-fwd, -1.0, config.TURN_SECONDS)
        if not self.dry_run:
            self._queue(STEER_CENTER)
        time.sleep(0.3)

    def _gear_change(self, direction: int) -> None:
        """Forward <-> reverse: tap the new direction, release, wait out the firmware's neutral period."""
        self._set(direction)
        time.sleep(0.1)
        self._set(0)
        time.sleep(0.8)

    def stop(self) -> None:
        if not self.dry_run:
            self._set(0)
            time.sleep(0.1)

    def do(self, action: str, amount: float = 0.5) -> None:
        amount = max(0.2, min(1.0, float(amount)))
        # Very short bursts barely move this car (it needs time to get going), so never go below
        # MIN_MOVE_SECONDS. last_amount is the amount actually used, for the position estimate.
        base = config.TURN_SECONDS if action in ("left", "right") else config.FORWARD_SECONDS
        amount = min(1.0, max(amount, config.MIN_MOVE_SECONDS / base)) if base > 0 else amount
        self.last_amount = amount
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

    def manual(self, key: str) -> None:
        """One short manual move for W/A/S/D while the AI is paused."""
        moves = {"w": (0.0, 1.0), "s": (0.0, -1.0), "a": (-1.0, 1.0), "d": (1.0, 1.0)}
        if key in moves:
            self.drive(*moves[key], 0.35, manual=True)
            if not self.dry_run:
                self._queue(STEER_CENTER)

    def pan_camera(self, direction: str, seconds: float) -> None:
        """Hold the camera pan servo left or right for `seconds` (the car itself doesn't move)."""
        if self.dry_run:
            print(f"   [car] camera {direction} for {seconds:.2f}s")
            return
        self._set(CAM_LEFT if direction == "left" else CAM_RIGHT)
        time.sleep(seconds)
        self._set(0)
        time.sleep(0.4)  # let the picture settle

    def center_camera(self) -> None:
        """Back to the calibrated straight-ahead camera pose."""
        if self.dry_run:
            print("   [car] camera centre")
            return
        self._queue(CAM_CENTER)
        time.sleep(0.5)

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
    import sys
    if "--scan" in sys.argv:  # list nearby Bluetooth devices, strongest signal first
        asyncio.run(_scan())
        raise SystemExit
    car = BleCarLink(dry_run=False)
    try:
        if "--steer" in sys.argv:
            # Steering only, no throttle: the front wheels should turn left, centre, right, centre.
            for name, flags in [("left", A), ("centre", 0), ("right", D), ("centre", 0)]:
                print("steer", name)
                car._set(flags)
                if flags == 0:
                    car._queue(STEER_CENTER)
                time.sleep(1.2)
            car._set(0)
        elif "--turn" in sys.argv:
            # On the floor: one full-size turn each way, to measure how many degrees a turn is.
            for action in ["left", "right"]:
                print(f"turn {action} (TURN_SECONDS={config.TURN_SECONDS})")
                car.do(action, 1.0)
                time.sleep(1.5)
        elif "--pan" in sys.argv:
            # Camera only: look left, centre, look right, centre. Check how far it turns.
            for side in ["left", "right"]:
                print(f"camera {side} (PAN_SECONDS={config.PAN_SECONDS})")
                car.pan_camera(side, config.PAN_SECONDS)
                time.sleep(1.5)
                print("camera centre")
                car.center_camera()
                time.sleep(1.0)
        elif "--spin" in sys.argv:
            # On the floor: one three-point turn each way (what the search uses).
            for side in ["left", "right"]:
                print(f"spin {side}")
                car.spin(side)
                time.sleep(1.5)
        elif "--forward" in sys.argv:
            # On the floor: one full-size forward move, to measure how far it goes.
            print(f"forward (FORWARD_SECONDS={config.FORWARD_SECONDS})")
            car.do("forward", 1.0)
        else:
            # Bench test: wheels off the ground.
            for action in ["forward", "left", "right", "back"]:
                print(action)
                car.do(action, 0.6)
                time.sleep(0.7)
    except KeyboardInterrupt:
        pass
    finally:
        car.close()
        print("Stopped")
