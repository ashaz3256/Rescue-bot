"""Keyboard takeover while the AI drives (Windows terminal).

  SPACE  emergency stop and pause the AI
  W/A/S/D  short manual moves while paused (forward / left / back / right)
  R      resume the AI
  Q      stop the car and end the run

Keys are read in a background thread, so SPACE works even mid-move.
On non-Windows systems this does nothing and Ctrl+C is the stop.
"""
from __future__ import annotations

import queue
import threading

_pressed: "queue.Queue[str]" = queue.Queue()
paused = threading.Event()
quit_requested = threading.Event()
_started = False


def start() -> bool:
    """Start listening. Returns False if keyboard takeover isn't available here."""
    global _started
    if _started:
        return True
    try:
        import msvcrt  # Windows only
    except ImportError:
        return False

    def listen() -> None:
        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow / function key prefix: skip the second code
                msvcrt.getwch()
                continue
            ch = ch.lower()
            if ch == " ":
                paused.set()
            elif ch == "q":
                quit_requested.set()
                paused.set()
            elif ch == "r":
                paused.clear()
            else:
                _pressed.put(ch)

    threading.Thread(target=listen, daemon=True).start()
    _started = True
    return True


def next_key(timeout: float = 0.1) -> str | None:
    try:
        return _pressed.get(timeout=timeout)
    except queue.Empty:
        return None


def stop_requested() -> bool:
    """True when the current move should be cut short."""
    return paused.is_set() or quit_requested.is_set()
