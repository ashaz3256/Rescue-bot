# Rescue Scout: project context for Copilot

(The same text lives in `CLAUDE.md` at the repo root. Keep them in sync.)

## What this is
Entry for the Nebius x NVIDIA Global AI Hackathon, Physical AI track. Deadline **Fri 30 Oct 2026, 10:00 PDT (17:00 UK)**.
A toy RC car searches a building with no map, finds a person, and reports where they are:
a search-and-rescue scout that goes in before firefighters.

## Hard rules from the hackathon
- Must run on Nebius Token Factory and use at least one NVIDIA open model.
- Public repo, MIT licence, README with clear setup and run steps.
- Demo video ≤ 3 min with ≥ 1 min of the real car operating.

## Hardware
- Toy RC car. ESP32-S3 drives the steering servo, motor and a camera pan/tilt servo.
- Control: Bluetooth LE from the laptop (`brain/ble_link.py`, CAR_LINK=ble). Our own Jupyter controller does manual
  driving over the same link; only one Bluetooth connection at a time.
- Camera: Walksnail Avatar HD Pro on the car → Avatar VRX on the ground → HDMI → USB capture card → laptop (OpenCV).
- The laptop runs all the AI. Nothing AI runs on the car.

## Layout
- `brain/`: Python on the laptop. `config.py` (all settings), `prompts.py`, `models.py` (Token Factory client),
  `video_in.py`, `car_link.py`, `fake_car.py`, `vision_test.py`, `navigator.py` (main loop).
- `car/`: ESP32 Arduino sketch.
- `dashboard/`: Flask + one HTML page, reads `data/runs/<latest>/`.
- `data/`: gitignored run logs and recordings.

## Models (ids in config.py, swappable; only "Public" Token Factory models work with our key)
1. Eyes: `nvidia/Nemotron-3.5-Super-VL`, every step, image → JSON decision.
2. Planner: `nvidia/Nemotron-3_5-Lightning`, every 5 steps, text log → 1–2 sentence plan.
3. Key-moment check: `nvidia/Nemotron-3.5-Super-VL` with a physical-reasoning prompt, first time a person is seen.
   (Cosmos and Nemotron-3-Nano-Omni are Dedicated-only on our account, so not used.)
4. Reflexes: our own code (safety override, stuck detection, watchdog).
Baselines for the model comparison only: `google/gemma-3-27b-it`, `openbmb/MiniCPM-V-4_5`.

## Token Factory API
- OpenAI-compatible: `openai` package, `base_url="https://api.tokenfactory.nebius.com/v1"`, key from `NEBIUS_API_KEY`.
- Never hard-code or commit keys. `.env` is gitignored; `.env.example` documents the variables.
- Images: base64 JPEG data URLs, 512 px by default (MAX_IMAGE_SIDE). temperature 0.1–0.2.
- Speed: short "fast" prompts with `action` first (FAST_PROMPT), reasoning switched off when the model allows
  (THINKING=off, sent as `chat_template_kwargs.enable_thinking=false`, dropped automatically if rejected),
  up to 3 forward moves per model call on clear floor. `vision_test.py --speed` measures the settings.
- `obstacle_close` means within ~30 cm (prompts.CLOSE). Without that definition every model says "close".
- Measured distance: the model reports WHERE things touch the floor (`ahead_floor_y`, `person_floor_y`, 0–1000 of
  image height, the scale VLMs use natively; `ranging.to_fraction` also accepts 0–1); `ranging.py` turns that into cm with `calibration/camera.json` (row = horizon + k/d, fitted from
  ruler photos). Measured values override the model's guesses (STOP_CM, FOUND_CM in config). Accurate under ~1 m.
  Recalibrate if the camera mount changes.
- Search target is configurable (TARGET in .env, or --target on vision_test/navigator). For a test object the
  prompts get a header saying person_* fields refer to that object; JSON keys stay the same.
- Always parse the LAST `{...}` in the reply (reasoning models think first). Never crash on bad JSON.

## Bluetooth protocol (what the car firmware expects; do not change without telling the team)
- 3-byte packet every 50 ms to RX characteristic 6E400002-B5A3-F393-E0A9-E50E24DCCA9E on device ESP32_RC_CAR:
  [movement flags (w=1 s=2 a=4 d=8, camera up/down/left/right = 16/32/64/128), commands (1 centre camera,
  2 centre steering, 4 emergency stop, 8 unlock motor), speed level 1–3].
- Motor starts locked: send emergency stop, then unlock. Always send emergency stop on exit (ble_link.close).
- Keep the camera centred: the distance calibration assumes a fixed camera pose.

## Older Wi-Fi contract (car/ sketch, CAR_LINK=udp; not what the current car runs)
- Laptop → ESP32: UDP port 4210, ASCII `S,<steer>,<throttle>\n`, floats -1.0..1.0, ~20 Hz.
- ESP32 → laptop: UDP port 4211, ASCII `T,<steer>,<throttle>,<mode>\n`, mode = MANUAL | AUTO, 20 Hz.
  Telemetry always carries the stick values (used to record training data).
- Flysky channel 5 switch: MANUAL (sticks) or AUTO (laptop). MANUAL always wins.
- Watchdog: in AUTO, no packet for 300 ms → throttle 0.

## Movement style
Stop-think-go: the car is still while waiting for a model reply, then drives a short burst
(forward ~0.8 s or a ~45° turn at amount=1.0), stops, and takes the next frame.

## Code style
- Python 3.11, type hints, small modules, docstrings on public functions.
- Everything must run with `DRY_RUN=1` and no hardware (photo folder as the camera, fake_car.py as the car).
- Log every step to `data/runs/<timestamp>/` (frames + `log.jsonl` + `report.json`). The dashboard depends on that format.
- Hackathon code: readable over clever. Don't add dependencies without a good reason.
