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
import keys
import models
import prompts
import ranging
from car_link import CarLink
from ble_link import BleCarLink
from video_in import FrameSource


def frame_diff(a: Image.Image, b: Image.Image) -> float:
    """Mean pixel change between two frames; near 0 after a forward move means we're stuck."""
    a, b = a.convert("L").resize((64, 48)), b.convert("L").resize((64, 48))
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


_cal = None
try:
    _cal = ranging.load()
except (OSError, ValueError, KeyError):
    print("No calibration/camera.json: distances will be the model's guesses.")


def measure(d: dict) -> None:
    """Replace guessed distances with calibrated ones where the model gave a floor row (0-1000).
    Adds ahead_cm / person_cm to the decision and sets obstacle_close from the measurement."""
    if _cal is None:
        return
    for key, out in (("ahead_floor_y", "ahead_cm"), ("person_floor_y", "person_cm")):
        row = ranging.to_fraction(d.get(key))
        if row is None:
            continue
        cm = ranging.distance_cm(row, _cal)
        d[out] = None if cm is None else round(cm)
    if d.get("ahead_cm") is not None:
        d["obstacle_close"] = d["ahead_cm"] < config.STOP_CM
        # The thing just ahead is often the target itself: that's where we want to go, not an obstacle.
        if (d.get("person_visible") and d.get("person_cm") is not None
                and abs(d["ahead_cm"] - d["person_cm"]) < 20):
            d["obstacle_close"] = False
    if d.get("person_cm") is not None and d.get("person_visible"):
        d["person_distance_m"] = round(d["person_cm"] / 100, 2)
        # The measurement decides "found", both ways: the model often says done as soon as it sees the target.
        d["done"] = d["person_cm"] <= config.FOUND_CM
    elif not d.get("person_visible"):
        d["done"] = False


def spot_target(img, target: str) -> dict:
    """One focused question on a higher-resolution frame: is the target anywhere in view, and where?"""
    prompt = prompts.with_target(
        "Robot car camera at floor level. Look carefully, the target may be small and far away.\n"
        "Is the person in this image? person_x = horizontal centre (0 = left edge, 1000 = right edge), "
        "person_floor_y = where they touch the floor (0 = top, 1000 = bottom).\n"
        'Reply with ONLY this JSON: {"person_visible": false, "person_x": null, "person_floor_y": null, '
        '"observation": "max 8 words"}', target)
    try:
        text, _ = models.ask(config.EYES_MODEL, prompt, img, max_tokens=120, image_side=config.SPOT_SIDE)
        return models.parse_json(text) or {}
    except Exception as e:
        print(f"   second look failed: {e}")
        return {}


def find_exit(img, goal: str) -> dict:
    """Ask where to go when the target isn't here: an open doorway, corridor or the most open floor."""
    prompt = (
        "Robot car camera at floor level, searching a building. GOAL: " + goal + "\n"
        "The target is not in this area. Where should the car drive to search somewhere new? "
        "Prefer an OPEN doorway or a corridor leading out (a real opening you can see through, not an alcove "
        "or a wall recess), otherwise the most open floor. exit_x = horizontal centre of it "
        "(0 = left edge, 1000 = right edge), or null if there is no way out in view.\n"
        'Reply with ONLY this JSON: {"exit_x": null, "is_doorway": false, "what": "max 4 words"}')
    try:
        text, _ = models.ask(config.EYES_MODEL, prompt, img, max_tokens=80, image_side=config.SPOT_SIDE or None)
        r = models.parse_json(text) or {}
        print(f"   [way out] {r.get('what')} x={r.get('exit_x')}")
        return r
    except Exception as e:
        print(f"   way-out check failed: {e}")
        return {}


def crop_around(img, x: float) -> "Image.Image":
    """The part of the frame around horizontal position x (fraction), to remember a doorway by."""
    w, h = img.size
    half = int(w * 0.22)
    cx = int(x * w)
    left = max(0, min(w - 2 * half, cx - half))
    return img.crop((left, 0, left + 2 * half, h)).copy()


def match_exit(img, ref) -> dict:
    """Show the remembered doorway (left) next to the live view (right): is it in view, and where?"""
    w, h = img.size
    ref = ref.resize((int(ref.width * h / ref.height), h))
    pair = Image.new("RGB", (ref.width + 12 + w, h), "white")
    pair.paste(ref, (0, 0))
    pair.paste(img, (ref.width + 12, 0))
    prompt = (
        "LEFT strip: a doorway the robot saw earlier. RIGHT: the robot's camera now. "
        "Is that same doorway visible in the RIGHT image? exit_x = its horizontal centre within the RIGHT "
        "image only (0 = left edge of the right image, 1000 = right edge), or null if not visible.\n"
        'Reply with ONLY this JSON: {"exit_x": null, "what": "max 4 words"}')
    try:
        text, _ = models.ask(config.EYES_MODEL, prompt, pair, max_tokens=80, image_side=config.SPOT_SIDE or None)
        r = models.parse_json(text) or {}
        print(f"   [remembered way out] {r.get('what')} x={r.get('exit_x')}")
        return r
    except Exception as e:
        print(f"   remembered-exit check failed: {e}")
        return {}


def look_around(car, frames, target: str, goal: str, run_dir: str, step: int) -> str | None:
    """Pan the camera left, then right, asking the eyes model each time. Returns the side where the
    target was seen, or None. Always re-centres the camera (the distance calibration needs it)."""
    prompt = prompts.with_target(
        "Robot car camera at floor level, camera turned to one side. Is the search target in this image?\n"
        'Reply with ONLY this JSON: {"person_visible": false, "observation": "max 8 words"}', target)
    try:
        for side in ("left", "right"):
            car.pan_camera(side, config.PAN_SECONDS)
            img = frames.get()
            if img is None:
                continue
            img.save(os.path.join(run_dir, f"step_{step:03d}_look_{side}.jpg"))
            text, secs = models.ask(config.EYES_MODEL, prompt, img, max_tokens=120,
                                    image_side=config.SPOT_SIDE or None)
            r = models.parse_json(text) or {}
            print(f"   [look {side}] {r.get('observation')} ({secs:.1f}s)")
            car.center_camera()
            if r.get("person_visible"):
                return side
        return None
    except Exception as e:
        print(f"   look-around failed: {e}")
        return None
    finally:
        car.center_camera()


def target_seen_recently(memory: list[str], n: int = 3) -> bool:
    """True if the target was in view in any of the last n steps (so the planner shouldn't send the car elsewhere)."""
    return any("[target in view]" in m for m in memory[-n:])


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


def run(goal: str, source: str | None, target: str | None = None) -> None:
    """Run one search. Always leaves the car stopped, even on Ctrl+C or an error."""
    car = None
    try:
        car = _search(goal, source, target)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        if _active_car is not None:
            if hasattr(_active_car, "close"):
                _active_car.close()
            else:
                _active_car.stop()


_active_car = None


def _search(goal: str, source: str | None, target: str | None = None):
    target = target or config.TARGET
    run_dir = os.path.join(config.RUNS_DIR, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "log.jsonl")

    frames = FrameSource(source)
    global _active_car
    car = BleCarLink() if config.CAR_LINK == "ble" else CarLink()
    _active_car = car
    pose = Pose()
    memory: list[str] = []
    plan = "Scan the surroundings first."
    warning = ""
    prev_img: Image.Image | None = None
    last_action = ""
    checked_person = False
    search_side, search_turns = None, 0  # where the camera last saw the target
    scan_turns, explore_steps = 0, 0  # scans with nothing found; steps heading for a doorway/open path
    exit_ref = None  # photo of the best doorway/way out seen so far (visual memory)
    print(f"Goal: {goal}\nTarget: {target}\nLogging to {run_dir}\n{'DRY RUN' if car.dry_run else 'LIVE CAR'}\n")

    if keys.start():
        print("Keys: SPACE = stop and pause | W/A/S/D = manual moves while paused | R = resume AI | Q = quit\n")

    for step in range(config.MAX_STEPS):
        # Human takeover: SPACE pauses the AI, W/A/S/D drive by hand, R resumes, Q quits.
        if keys.paused.is_set() and not keys.quit_requested.is_set():
            car.stop()
            print("   PAUSED: W/A/S/D to drive, R to resume the AI, Q to quit")
            while keys.paused.is_set() and not keys.quit_requested.is_set():
                k = keys.next_key()
                if k and hasattr(car, "manual"):
                    car.manual(k)
            prev_img, last_action = None, ""  # the view changed by hand, so skip the stuck check
            if not keys.quit_requested.is_set():
                print("   AI resumed")
        if keys.quit_requested.is_set():
            print("Run ended by user (Q).")
            break

        # Only move when the transmitter switch says AUTO. MANUAL always wins.
        waited = 0
        while not car.auto:
            if waited % 10 == 0:
                print("   waiting: car not connected (reconnecting)...")
            time.sleep(0.5)
            waited += 1
            if keys.quit_requested.is_set():
                break

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
                planner_prompt = prompts.with_target(prompts.PLANNER.format(log="\n".join(memory)), target)
                if target_seen_recently(memory):
                    planner_prompt += "\nThe target is in view now: the plan is to drive straight to it."
                plan, _ = models.ask(config.PLANNER_MODEL, planner_prompt,
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
                                         floor_rows=prompts.FLOOR_ROWS,
                                         memory="\n".join(memory[-10:]) or "(nothing yet)")
            max_tokens = 600
        warning = ""
        try:
            text, secs = models.ask(config.EYES_MODEL, prompts.with_target(prompt, target), img, max_tokens=max_tokens)
        except Exception as e:
            print(f"   eyes model failed: {e}")
            continue
        d = models.parse_json(text)
        if not d or "action" not in d:
            print("   bad model output, skipping step")
            continue

        # Measured distances: the model says WHERE things touch the floor, the calibration says HOW FAR.
        # Small or far targets are easy to miss at 512 px. If the eyes model didn't see one, ask again with
        # a short yes/no question on a sharper image before deciding the target isn't there.
        if not d.get("person_visible") and config.SPOT_SIDE > 0:
            spot = spot_target(img, target)
            if spot.get("person_visible"):
                for k in ("person_visible", "person_x", "person_floor_y"):
                    d[k] = spot.get(k)
                d["observation"] = f"{d.get('observation')} | second look: {spot.get('observation')}"
                print(f"   [second look] target found: {spot.get('observation')}")

        measure(d)

        # The model sometimes says "stop" as soon as it thinks it's close. Only the measurement ends a search:
        # target visible but not close enough -> keep going; nothing visible -> turn and keep looking.
        if d["action"] == "stop" and not d.get("done"):
            if d.get("person_visible"):
                d["action"], d["amount"], d["override"] = "forward", 0.5, "target not close enough yet"
            else:
                d["action"], d["amount"], d["override"] = "left", 1.0, "keep searching"

        # Target not in view: search.
        #  1. If the camera already saw it on one side, keep turning that way (full lock, a U-turn if
        #     needed) until the front view sees it again; no need to look around every step.
        #  2. Otherwise look left and right with the camera (car still) and turn towards where it was seen.
        #  3. Seen nowhere: full-lock turn the way the model chose, and look again next step.
        if d.get("person_visible"):
            search_side, search_turns, scan_turns, explore_steps = None, 0, 0, 0
        elif explore_steps > 0 or scan_turns >= config.SCANS_BEFORE_EXPLORE:
            # Looked all round this spot and found nothing: head for a doorway or the most open path.
            if explore_steps == 0:
                explore_steps, scan_turns = config.EXPLORE_STEPS, 0
            ex = match_exit(img, exit_ref) if exit_ref is not None else {}
            if ranging.to_fraction(ex.get("exit_x")) is None:
                ex = find_exit(img, goal)
            x = ranging.to_fraction(ex.get("exit_x"))
            if x is not None:
                explore_steps -= 1  # only count steps actually heading somewhere
            if x is None:
                d["action"], d["amount"], d["override"] = "left", 1.0, "looking for the way out, turning"
                d["spin"] = config.SPIN_SEARCH
            elif abs(x - 0.5) > config.AIM_DEADBAND:
                d["action"] = "left" if x < 0.5 else "right"
                d["amount"], d["override"] = 0.6, f"heading for {ex.get('what') or 'the open path'} (x={x:.2f})"
            else:
                d["action"], d["amount"], d["override"] = "forward", 1.0, f"through {ex.get('what') or 'the open path'}"
        elif search_side and search_turns < config.MAX_SEARCH_TURNS:
            search_turns += 1
            d["action"], d["amount"], d["override"] = (
                search_side, 1.0, f"turning {search_side} to where the camera saw the target ({search_turns})")
            d["spin"] = config.SPIN_SEARCH
        elif d["action"] in ("left", "right", "forward", "back") and not keys.stop_requested():
            search_side, search_turns = None, 0
            seen = None
            if config.CAM_SCAN and hasattr(car, "pan_camera"):
                seen = look_around(car, frames, target, goal, run_dir, step)
            if seen:
                search_side, search_turns = seen, 1
                d["action"], d["amount"], d["override"] = seen, 1.0, f"camera spotted target on the {seen}"
                d["spin"] = config.SPIN_SEARCH
            elif d["action"] in ("left", "right"):
                scan_turns += 1
                d["amount"], d["override"] = 1.0, f"camera look: nothing, full turn to scan ({scan_turns})"
                d["spin"] = config.SPIN_SEARCH
                # Visual memory: while scanning, remember what the way out looks like.
                ex = find_exit(img, goal)
                x = ranging.to_fraction(ex.get("exit_x"))
                if x is not None and ex.get("is_doorway"):
                    exit_ref = crop_around(img, x)
                    exit_ref.save(os.path.join(run_dir, "remembered_exit.jpg"))
                    memory.append(f"step {step}: remembered a way out ({ex.get('what')})")
                    print(f"   [memory] remembered the way out: {ex.get('what')}")

        # Steer to the target: the model says WHERE it is across the image (person_x, 0-1000),
        # our code picks the turn. Keeps the target in the middle of the view as the car closes in.
        x = ranging.to_fraction(d.get("person_x"))
        if d.get("person_visible") and not d.get("done") and x is not None and d["action"] in ("forward", "left", "right"):
            if x < 0.5 - config.AIM_DEADBAND:
                want = "left"
            elif x > 0.5 + config.AIM_DEADBAND:
                want = "right"
            else:
                want = "forward"
            if want != "forward":
                # Turn harder the further off-centre the target is (full turn near the edge of the view).
                amount = min(1.0, 0.3 + 1.2 * abs(x - 0.5))
                # This car rolls forward while it turns, so near the target only make small turns
                # (a full turn at ~1 m drove into the fox in testing).
                if d.get("person_cm") is not None and d["person_cm"] < config.FOUND_CM + 60:
                    amount = min(amount, 0.5)
                d["action"], d["amount"], d["override"] = want, amount, f"steer to target (x={x:.2f})"
            elif d["action"] != "forward":
                d["action"], d["amount"], d["override"] = "forward", 0.5, f"target ahead (x={x:.2f})"

        # Safety override: never drive into something the model itself flagged.
        if d.get("obstacle_close") and d["action"] == "forward":
            d["action"], d["amount"], d["override"] = "back", 0.4, "obstacle close"

        # Key moment: first sighting of a person -> physical reasoning check.
        check = None
        if d.get("person_visible") and not checked_person:
            checked_person = True
            try:
                ctext, _ = models.ask(config.CHECK_MODEL, prompts.with_target(prompts.CHECK, target), img)
                check = models.parse_json(ctext)
                if check:
                    print(f"   [check] {check.get('reason')}")
                    if check.get("path_to_person") == "blocked" and d["action"] == "forward":
                        d["action"], d["override"] = check.get("safest_move", "left"), "path blocked"
            except Exception as e:
                print(f"   check model failed: {e}")

        # Final approach: once the target is close, only creep forward (the shortest move).
        if (d["action"] == "forward" and d.get("person_cm") is not None
                and d["person_cm"] < config.FOUND_CM + 50):
            d["amount"], d["repeat"] = 0.2, 1
        amount = float(d.get("amount") or 0.5)
        print(f"{step:02d} | {d.get('observation')} -> {d['action']} {amount:.1f}"
              f"{' x' + str(d.get('repeat')) if d.get('repeat') and d['action'] == 'forward' else ''}"
              f"{' | ahead ' + str(d['ahead_cm']) + 'cm' if d.get('ahead_cm') is not None else ''}"
              f"{' | person ' + str(d['person_cm']) + 'cm' if d.get('person_cm') is not None else ''}"
              f"{' | OVERRIDE: ' + d['override'] if d.get('override') else ''}"
              f" | {d.get('reason', '')} ({secs:.1f}s)")
        memory.append(f"step {step} ({pose.describe()}): saw {d.get('observation')}"
                      f"{' [target in view]' if d.get('person_visible') else ''}; did {d['action']}")
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
        if keys.stop_requested():
            continue  # paused while the model was thinking: don't act on that decision
        repeat = 1
        if d["action"] == "forward" and not d.get("obstacle_close"):
            try:
                repeat = max(1, min(config.MAX_REPEAT, int(d.get("repeat") or 1)))
            except (TypeError, ValueError):
                repeat = 1
        before = img
        for r in range(repeat):
            if d.get("spin") and d["action"] in ("left", "right") and hasattr(car, "spin"):
                # Three-point turn. If anything is close ahead (or the model can't tell), back out first so
                # the forward half can't hit it; the car's rear sensor guards the reverse half.
                close_ahead = d.get("obstacle_close") or (
                    d.get("ahead_cm") is not None and d["ahead_cm"] < config.STOP_CM + 30)
                car.spin(d["action"], reverse_first=bool(close_ahead))
                pose.update(d["action"], 2.0)
                after = frames.get()
                if after is not None and frame_diff(before, after) < config.STUCK_DIFF:
                    # The turn didn't change the view: wedged against something. Straighten out and back off.
                    print("   turn didn't move the view: backing off")
                    warning = "WARNING: the last turn did not change the view; you were stuck and backed off."
                    car.do("back", 1.0)
                    scan_turns = max(scan_turns, config.SCANS_BEFORE_EXPLORE - 1)
            else:
                car.do(d["action"], amount)
                pose.update(d["action"], getattr(car, "last_amount", amount))
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
    ap.add_argument("--target", default=None, help='what to search for, e.g. "an antiperspirant can"')
    args = ap.parse_args()
    goal = args.goal
    if args.target and goal == ap.get_default("goal"):
        goal = f"find {args.target} and stop next to it"
    run(goal, args.source, args.target)
