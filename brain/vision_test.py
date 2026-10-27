"""Compare vision models on the same photos, or compare speed settings for one model.

  python brain/vision_test.py --list            # exact model ids on your account
  python brain/vision_test.py                   # run COMPARE_MODELS on test_photos/
  python brain/vision_test.py --models a b c    # pick models
  python brain/vision_test.py --speed           # EYES_MODEL: old settings vs faster settings

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
import ranging

try:
    CAL = ranging.load()
except (OSError, ValueError, KeyError):
    CAL = None

ROOT = os.path.join(os.path.dirname(__file__), "..")
PHOTO_DIR = os.path.join(ROOT, "test_photos")


def load_answers() -> dict[str, dict]:
    path = os.path.join(PHOTO_DIR, "answers.csv")
    if not os.path.exists(path):
        return {}
    # utf-8-sig copes with the BOM Windows Notepad / PowerShell can add
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = {}
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if row.get("file"):
                rows[row["file"]] = row
        return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--models", nargs="*")
    ap.add_argument("--speed", action="store_true", help="compare speed settings for EYES_MODEL")
    args = ap.parse_args()

    if args.list:
        print("\n".join(models.list_models()))
        return

    # Each variant = one row in the summary: (label, model, prompt, image size, thinking, max tokens)
    fast_prompt = prompts.COMPARE_FAST if config.FAST_PROMPT else prompts.COMPARE
    if args.speed:
        em = config.EYES_MODEL
        variants = [
            ("A long prompt, 768px", em, prompts.COMPARE, 768, "default", 1500),
            ("B short prompt, 512px", em, prompts.COMPARE_FAST, 512, "default", 300),
            ("C short, 512px, no thinking", em, prompts.COMPARE_FAST, 512, "off", 300),
            ("D short, 384px, no thinking", em, prompts.COMPARE_FAST, 384, "off", 300),
        ]
    else:
        variants = [(m, m, fast_prompt, None, None, 600) for m in (args.models or config.COMPARE_MODELS)]
    model_ids = [v[0] for v in variants]
    answers = load_answers()
    photos = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    if not photos:
        sys.exit("Put some photos in test_photos/ first.")

    stats = {m: {"n": 0, "hit": 0, "scored": 0, "err": [], "secs": [], "bad": 0, "seen": 0, "close": 0}
             for m in model_ids}
    rows = []
    for photo in photos:
        img = Image.open(os.path.join(PHOTO_DIR, photo))
        truth = answers.get(photo)
        for m, model_id, prompt, side, thinking, max_tokens in variants:
            try:
                text, secs = models.ask(model_id, prompt, img, max_tokens=max_tokens,
                                        image_side=side, thinking=thinking)
            except Exception as e:  # keep going if one model errors
                print(f"{m} | {photo} | ERROR {str(e)[:200]}")
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
            # Measured distances from the calibration, where the model gave floor rows
            for key, out in (("ahead_floor_y", "ahead_cm"), ("person_floor_y", "person_cm")):
                try:
                    cm = ranging.distance_cm(float(data.get(key)) / 100.0, CAL) if CAL else None
                    row[out] = None if cm is None else round(cm)
                except (TypeError, ValueError):
                    pass
            if row.get("person_cm") is not None and data.get("person_visible"):
                data["person_distance_m"] = round(row["person_cm"] / 100, 2)
            seen = bool(data.get("person_visible"))
            s["seen"] += int(seen)
            s["close"] += int(bool(data.get("obstacle_close")))
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
                                                  "obstacle_close", "safe_direction", "observation",
                                                  "ahead_floor_y", "person_floor_y")})
            rows.append(row)
            print(f"{m:40s} | {photo:28s} | person={seen!s:5s} dist={data.get('person_distance_m')} "
                  f"ahead={row.get('ahead_cm')}cm | {secs:.1f}s {mark}")

    if not rows:
        print("\nNo answers came back: every call failed. Read the ERROR lines above.")
        print("Usually it's a model name that isn't available on your account.")
        print("Run:  python brain/vision_test.py --list   and put exact ids in .env (EYES_MODEL, CHECK_MODEL).")
        sys.exit(1)

    out = os.path.join(ROOT, "results.csv")
    with open(out, "w", newline="") as f:
        keys = sorted({k for r in rows for k in r})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    print("\n=== SUMMARY ===")
    print(f"{'model / setting':40s} {'person right':>12s} {'dist err':>9s} {'avg s':>6s} {'median s':>9s}"
          f" {'saw person':>11s} {'obst close':>11s} {'bad json':>9s}")
    for m, s in stats.items():
        acc = f"{s['hit']}/{s['scored']}" if s["scored"] else "-"
        err = f"{sum(s['err']) / len(s['err']):.1f} m" if s["err"] else "-"
        secs = sorted(s["secs"])
        avg = f"{sum(secs) / len(secs):.1f}" if secs else "-"
        med = f"{secs[len(secs) // 2]:.1f}" if secs else "-"
        print(f"{m:40s} {acc:>12s} {err:>9s} {avg:>6s} {med:>9s} {s['seen']:>11d} {s['close']:>11d} {s['bad']:>9d}")
    print(f"\nAll answers saved to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
