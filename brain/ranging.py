"""Distance from a single fixed camera: the lower an object touches the floor in the frame, the closer it is.

With the camera at a fixed height and tilt, a point on flat ground at distance d appears at image row
    row = horizon + k / d
so two numbers (horizon, k) fitted from a few ruler photos turn a pixel row into centimetres.

  python brain/ranging.py calibration/points_2026-10-27.csv     # fit and save calibration/camera.json
  python brain/ranging.py --row 0.70                            # distance for a row given as a fraction of height

Valid only while the camera mount stays exactly as it was during calibration.
Accurate up close (where stop/turn decisions happen); far away the rows bunch up and it gets rough.
"""
from __future__ import annotations

import csv
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
CAL_FILE = os.path.join(ROOT, "calibration", "camera.json")


def fit(points: list[tuple[float, float]]) -> dict:
    """points = [(distance_cm, row_fraction)]. Least-squares fit of row = horizon + k / d."""
    n = len(points)
    xs = [1.0 / d for d, _ in points]
    ys = [r for _, r in points]
    mx, my = sum(xs) / n, sum(ys) / n
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    horizon = my - k * mx
    return {"horizon": horizon, "k": k}


def to_fraction(value) -> float | None:
    """A model's row answer -> fraction of image height. Accepts the 0-1000 scale we ask for,
    and a 0-1 fraction if a model answers that way. Anything else -> None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= v <= 1:
        return v
    if 1 < v <= 1000:
        return v / 1000.0
    return None


def distance_cm(row_fraction: float, cal: dict | None = None) -> float | None:
    """Row where an object meets the floor (0 = top of frame, 1 = bottom) -> distance in cm.
    Returns None at or above the horizon (too far to measure)."""
    cal = cal or load()
    gap = row_fraction - cal["horizon"]
    if gap <= 0.002:
        return None
    return cal["k"] / gap


def load() -> dict:
    with open(CAL_FILE) as f:
        return json.load(f)


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--row":
        d = distance_cm(float(sys.argv[2]))
        print("beyond the horizon" if d is None else f"{d:.0f} cm")
        return
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "calibration", "points_2026-10-27.csv")
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    points = [(float(r["distance_cm"]), float(r["contact_row_px"]) / float(r["image_height_px"])) for r in rows]
    cal = fit(points)
    cal["source"] = os.path.basename(path)
    os.makedirs(os.path.dirname(CAL_FILE), exist_ok=True)
    with open(CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2)
    print(f"horizon at {cal['horizon']:.3f} of frame height, k = {cal['k']:.2f}\n")
    print(f"{'real':>6} {'calibrated':>11} {'error':>8}")
    for d, r in points:
        est = distance_cm(r, cal)
        print(f"{d:>5.0f}cm {est:>9.0f}cm {est - d:>+7.0f}cm")
    print(f"\nSaved {os.path.normpath(CAL_FILE)}")


if __name__ == "__main__":
    main()
