"""Rescue Scout main loop: look -> decide -> safety check -> move -> repeat, until a person is found.

  python brain/navigator.py                                  # capture card, DRY_RUN from config
  python brain/navigator.py --source test_photos             # test on a photo folder
  python brain/navigator.py --source walkthrough.mp4 --goal "find anyone in the kitchen"

Every run is logged to data/runs/<timestamp>/ (frames, log.jsonl, report.json).
The dashboard reads that folder.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

from PIL import Image, ImageChops, ImageStat

import config
import models
import prompts
from car_link import CarLink
from video_in import FrameSource


def frame_diff(a: Image.Image, b: Image.Image) -> float:
    """Mean pixel change between two frames; near 0 after a forward move means we're stuck."""
    a, b = a.convert("L").resize((64, 48)), b.convert("L").resize((64, 48))
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


class Pose:
    """Rough position from the entry, from the commands sent (swap in a gyro heading later)."""

    def __init__(self):
        self.x = self.y = 0.0      # metres: x = right of entry, y = forward from entry
        self.heading = 0.0         # degrees, 0 = the way the car faced at the entry

    def update(self, action: str, amount: float) -> None:
        if action in ("left", "right"):
            self.heading += (-1 if action == "left" else 1) * config.DEGREES_PER_TURN * amount
        elif action in ("forward", "back"):
            d = config.METRES_PER_FORWARD * amount * (1 if action == "forward" else -1)
            self.x += d * math.sin(math.radians(self.heading))
            self.y += d * math.cos(math.radians(self.heading))

    def as_dict(self) -> dict:
        return {"x": round(self.x, 2), "y": round(self.y, 2), "heading": round(self.heading % 360, 1)}

    def describe(self) -> str:
        dist = math.hypot(self.x, self.y)
        if dist < 0.1:
            return "at the entry"
        bearing = math.degrees(math.atan2(self.x, self.y)) % 360
        names = ["ahead", "ahead-right", "right", "behind-right", "behind", "behind-left", "left", "ahead-left"]
        return f"{dist:.1f} m {names[int((bearing + 22.5) // 45) % 8]} of the entry"


def run(goal: str, source: str | None) -> None:
    run_dir = os.path.join(config.RUNS_DIR, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "log.jsonl")

    frames = FrameSource(source)
    car = CarLink()
    pose = Pose()
    memory: list[str] = []
    plan = "Scan the surroundings first."
    warning = ""
    prev_img: Image.Image | None = None
    last_action = ""
    checked_person = False
    print(f"Goal: {goal}\nLogging to {run_dir}\n{'DRY RUN' if car.dry_run else 'LIVE CAR'}\n")

    for step in range(config.MAX_STEPS):
        # Only move when the transmitter switch says AUTO. MANUAL always wins.
        while not car.auto:
            print("   waiting: car is in MANUAL or not connected")
            time.sleep(0.5)

        img = frames.get()
        if img is None:
            print("No more frames.")
            break
        frame_file = f"step_{step:03d}.jpg"
        img.save(os.path.join(run_dir, frame_file))

        if prev_img is not None and last_action == "forward" and frame_diff(prev_img, img) < config.STUCK_DIFF:
            warning = "WARNING: the last forward move did not change the view, you are probably stuck. Back up or turn."

        if step and step % config.PLAN_EVERY == 0:
            try:
                plan, _ = models.ask(config.PLANNER_MODEL, prompts.PLANNER.format(log="\n".join(memory)),
                                     max_tokens=400, temperature=0.3)
                plan = plan.strip()
                print(f"   [plan] {plan}")
            except Exception as e:
                print(f"   planner failed: {e}")

        if config.FAST_PROMPT:
            prompt = prompts.EYES_FAST.format(goal=goal, plan=plan, warning=warning,
                                              memory=" | ".join(memory[-5:]) or "nothing yet")
            max_tokens = 250
        else:
            prompt = prompts.EYES.format(goal=goal, plan=plan, warning=warning, close=prompts.CLOSE,
                                         memory="\n".join(memory[-10:]) or "(nothing yet)")
            max_tokens = 600
        warning = ""
        try:
            text, secs = models.ask(config.EYES_MODEL, prompt, img, max_tokens=max_tokens)
        except Exception as e:
            print(f"   eyes model failed: {e}")
            continue
        d = models.parse_json(text)
        if not d or "action" not in d:
            print("   bad model output, skipping step")
            continue

        # Safety override: never drive into something the model itself flagged.
        if d.get("obstacle_close") and d["action"] == "forward":
            d["action"], d["amount"], d["override"] = "back", 0.4, "obstacle close"

        # Key moment: first sighting of a person -> physical reasoning check.
        check = None
        if d.get("person_visible") and not checked_person:
            checked_person = True
            try:
                ctext, _ = models.ask(config.CHECK_MODEL, prompts.CHECK, img)
                check = models.parse_json(ctext)
                if check:
                    print(f"   [check] {check.get('reason')}")
                    if check.get("path_to_person") == "blocked" and d["action"] == "forward":
                        d["action"], d["override"] = check.get("safest_move", "left"), "path blocked"
            except Exception as e:
                print(f"   check model failed: {e}")

        amount = float(d.get("amount") or 0.5)
        print(f"{step:02d} | {d.get('observation')} -> {d['action']} {amount:.1f}"
              f"{' x' + str(d.get('repeat')) if d.get('repeat') and d['action'] == 'forward' else ''}"
              f" | {d.get('reason', '')} ({secs:.1f}s)")
        memory.append(f"step {step} ({pose.describe()}): saw {d.get('observation')}; did {d['action']}")
        with open(log_path, "a") as f:
            f.write(json.dumps({"step": step, "time": time.time(), "frame": frame_file, "secs": round(secs, 2),
                                "plan": plan, "pose": pose.as_dict(), "eyes": d, "check": check}) + "\n")

        if d.get("done"):
            report = {
                "status": "person found",
                "location": pose.describe(),
                "position_m": pose.as_dict(),
                "person_state": (check or {}).get("person_state") or d.get("person_state"),
                "hazards": d.get("hazards"),
                "observation": d.get("observation"),
                "steps": step + 1,
                "photo": frame_file,
            }
            with open(os.path.join(run_dir, "report.json"), "w") as f:
                json.dump(report, f, indent=2)
            car.stop()
            print("\n=== REPORT ===\n" + json.dumps(report, indent=2))
            break
        if d["action"] == "stop":
            print("Model stopped without finding anyone.")
            break

        # On clearly open floor the model may ask for up to MAX_REPEAT forward moves per call.
        # Between extra moves we only do the cheap stuck check, no model call.
        repeat = 1
        if d["action"] == "forward" and not d.get("obstacle_close"):
            try:
                repeat = max(1, min(config.MAX_REPEAT, int(d.get("repeat") or 1)))
            except (TypeError, ValueError):
                repeat = 1
        before = img
        for r in range(repeat):
            car.do(d["action"], amount)
            pose.update(d["action"], amount)
            if r < repeat - 1:
                after = frames.get()
                if after is None or frame_diff(before, after) < config.STUCK_DIFF:
                    warning = "WARNING: a forward move did not change the view, you are probably stuck."
                    break
                before = after
        prev_img, last_action = before, d["action"]
    else:
        print("Ran out of steps.")

    car.stop()
    frames.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", default="search for people and report where they are")
    ap.add_argument("--source", default=None, help="camera index, video file, or folder of images")
    args = ap.parse_args()
    run(args.goal, args.source)
