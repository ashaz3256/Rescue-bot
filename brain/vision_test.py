"""Compare vision models (Nemotron vs Cosmos) on the same photos.

  python brain/vision_test.py --list            # exact model ids on your account
  python brain/vision_test.py                   # run COMPARE_MODELS on test_photos/
  python brain/vision_test.py --models a b c    # pick models

test_photos/answers.csv (optional, for scoring):
    file,person,distance_m
    hall_empty.jpg,no,
    person_2m.jpg,yes,2
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

from PIL import Image

import config
import models
import prompts

ROOT = os.path.join(os.path.dirname(__file__), "..")
PHOTO_DIR = os.path.join(ROOT, "test_photos")


def load_answers() -> dict[str, dict]:
    path = os.path.join(PHOTO_DIR, "answers.csv")
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        return {row["file"]: row for row in csv.DictReader(f)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--models", nargs="*")
    args = ap.parse_args()

    if args.list:
        print("\n".join(models.list_models()))
        return

    model_ids = args.models or config.COMPARE_MODELS
    answers = load_answers()
    photos = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    if not photos:
        sys.exit("Put some photos in test_photos/ first.")

    stats = {m: {"n": 0, "hit": 0, "scored": 0, "err": [], "secs": [], "bad": 0} for m in model_ids}
    rows = []
    for photo in photos:
        img = Image.open(os.path.join(PHOTO_DIR, photo))
        truth = answers.get(photo)
        for m in model_ids:
            try:
                text, secs = models.ask(m, prompts.COMPARE, img)
            except Exception as e:  # keep going if one model errors
                print(f"{m} | {photo} | ERROR {e}")
                continue
            s = stats[m]
            s["n"] += 1
            s["secs"].append(secs)
            data = models.parse_json(text)
            row = {"model": m, "photo": photo, "secs": round(secs, 2)}
            if data is None:
                s["bad"] += 1
                row["raw"] = text[:300]
                print(f"{m:40s} | {photo:28s} | unparseable ({secs:.1f}s)")
                rows.append(row)
                continue
            seen = bool(data.get("person_visible"))
            mark = ""
            if truth:
                expected = truth["person"].strip().lower() == "yes"
                ok = seen == expected
                s["scored"] += 1
                s["hit"] += int(ok)
                mark = "OK" if ok else "WRONG"
                row["correct"] = ok
                if expected and seen and truth.get("distance_m") and data.get("person_distance_m") is not None:
                    try:
                        s["err"].append(abs(float(data["person_distance_m"]) - float(truth["distance_m"])))
                    except (TypeError, ValueError):
                        pass
            row.update({k: data.get(k) for k in ("person_visible", "person_bearing", "person_distance_m",
                                                  "obstacle_close", "safe_direction", "observation")})
            rows.append(row)
            print(f"{m:40s} | {photo:28s} | person={seen!s:5s} dist={data.get('person_distance_m')} "
                  f"| {secs:.1f}s {mark}")

    out = os.path.join(ROOT, "results.csv")
    with open(out, "w", newline="") as f:
        keys = sorted({k for r in rows for k in r})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    print("\n=== SUMMARY ===")
    print(f"{'model':40s} {'person found':>13s} {'avg dist err':>13s} {'avg secs':>9s} {'bad json':>9s}")
    for m, s in stats.items():
        acc = f"{s['hit']}/{s['scored']}" if s["scored"] else "-"
        err = f"{sum(s['err']) / len(s['err']):.1f} m" if s["err"] else "-"
        sec = f"{sum(s['secs']) / len(s['secs']):.1f}" if s["secs"] else "-"
        print(f"{m:40s} {acc:>13s} {err:>13s} {sec:>9s} {s['bad']:>9d}")
    print(f"\nAll answers saved to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
