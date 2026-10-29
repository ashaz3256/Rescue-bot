# Rescue Scout

**A small search-and-rescue robot that goes into a room before a firefighter does.** It has no map. It looks, decides, moves, and reports where the casualty is, using NVIDIA open models on Nebius Token Factory.

Built for the [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/), Physical AI track.

> Status: work in progress (October 2026).

## The problem

Firefighters often have to search smoke-filled or unsafe rooms before they know what's inside. Robots that can go first exist, but they're expensive and need a person driving them. UK fire services are trialling firefighting robots that [cost up to £160,000](https://www.fbu.org.uk/magazine/februarymarch-2025/firefighting-robots), and a Boston Dynamics Spot starts at [around $75,000](https://standardbots.com/articles/spot-robot).

Rescue Scout is a cheap, small, autonomous first look. Send it in, and it comes back with "person found, about 3 m ahead-left of the entry, not moving" plus a photo and the route it took.

## How it works

```
Walksnail camera (car) → Avatar VRX → HDMI → capture card → laptop
                                                             │
                     ┌───────────────────────────────────────┤
                     ▼                                       │
  Eyes      Nemotron 3.5 Super VL  every step: what's here, person?, obstacle?, next move
  Planner   Nemotron 3.5 Lightning every 5 steps: reads the log, picks where to search next
  Check     Nemotron 3.5 Super VL  when a person is first seen: distance, path clear?
  Reflexes  our code               safety override, stuck detection, watchdog
                     │
                     ▼
  laptop ──Bluetooth LE──▶ ESP32-S3 ──▶ steering servo + motor (+ camera pan/tilt)
```

- **No map.** The written log of what it saw and did *is* the map. The planner reads it to avoid going in circles.
- **Stop-think-go.** The car is still while a model thinks, then makes a short move. It never drives blind.
- **Safety first.** The car starts with the motor locked, runs at its lowest speed, and the laptop sends an emergency stop whenever a run ends, errors or is cancelled with Ctrl+C.

## Hardware

| Part | Approx. cost |
|---|---|
| Walksnail Avatar HD Pro Kit (camera + video transmitter) | £169 |
| Walksnail Avatar VRX (ground receiver, HDMI out) | £199 |
| Flysky transmitter + receiver | ~£50 |
| Toy RC car | ~£30 |
| ESP32 dev board | ~£10 |
| USB HDMI capture card | ~£12 |
| **Prototype total** | **~£470** |

AI cost per search run is about 1–2p. A production version could swap the FPV kit for an ESP32-CAM over Wi-Fi and come in under £100.

## Quick start (no hardware needed)

```bash
git clone https://github.com/ashaz3256/Rescue-bot
cd Rescue-bot
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then add your NEBIUS_API_KEY
```

1. **Check model ids:** `python brain/vision_test.py --list`, then put the exact ids in `.env`.
2. **Compare models:** put photos in `test_photos/` (see its README) and run `python brain/vision_test.py`. Add `--speed` to compare speed settings for the eyes model.
3. **Dry run the brain on photos:** `python brain/navigator.py --source test_photos`
4. **Watch it:** in a second terminal, `python dashboard/app.py`, then open http://localhost:5000

### Test the car link without the car

```bash
python brain/fake_car.py                                         # terminal 1: pretends to be the ESP32
DRY_RUN=0 CAR_IP=127.0.0.1 python brain/navigator.py --source test_photos   # terminal 2
```

### With the real car

1. Turn the car on. Close our Jupyter controller if it's open (the car takes one Bluetooth connection at a time).
2. Plug the VRX into a USB HDMI capture card. `python brain/video_in.py --list` finds its camera number (put it in `.env` as `CAMERA_SOURCE`), and `python brain/video_in.py --show` opens a live window. Turn the VRX on-screen display off.
3. Bench test with the wheels off the ground: `python brain/ble_link.py` (forward, left, right, back, then stop).
4. Set `DRY_RUN=0` in `.env` and run `python brain/navigator.py --target "..."`. Ctrl+C stops the car at any time.

Every run is saved to `data/runs/<timestamp>/`: frames, `log.jsonl`, and `report.json` when someone is found.

## Model comparison

Same 34 photos (indoor, camera at floor level), same prompt, run with `brain/vision_test.py`.
Target for this round: a stand-in object (an orange spray can) in 13 photos, absent from the other 21.

| Model | Found the target | False alarms | Floor-contact position error | Avg seconds | Endpoint |
|---|---|---|---|---|---|
| **Nemotron 3.5 Super VL (used)** | **12 / 13** | **0 / 21** | **1.7%** of image height | **1.1** | Public (per token) |
| Cosmos 3 Super Reasoner | 12 / 13 | 0 / 21 | 13.6% | 1.5 | Dedicated ($9.40/h) |
| Gemma 3 27B | 13 / 13 | 0 / 21 | – | 3.6 | Public |
| MiniCPM-V 4.5 | 0 / 13 | 0 / 21 | – | 0.6 | Public |

- **Position error** is how far the model's "where the target touches the floor" answer was from the can's real base,
  measured from the photos by colour. It matters because our distance calibration turns that position into centimetres.
- Nemotron and Cosmos tied on spotting (both missed only the can at about 4 m), but Nemotron located it about
  8x more precisely, was faster, and runs on a public pay-per-use endpoint.
- In an earlier round with no target present, Gemma reported a person who wasn't there in 2 of 19 photos; Nemotron reported none.
- Switching to a short prompt, 512 px images and no reasoning step cut Nemotron from about 4.0 s to about 1 s per decision.

## Limits (honest list)

- A normal camera can't see through thick smoke. A real deployment needs a thermal camera.
- Position comes from counting moves, so it drifts over long runs. A phone or IMU gyro would fix the heading.
- It's a toy car: no stairs, no heat protection, indoor floors only.
- Each decision waits on a cloud model call (about a second), so it moves in short bursts.

## Next steps

- Thermal camera for smoke.
- Cheaper build: ESP32-CAM streaming over Wi-Fi instead of the FPV kit.
- A small steering network trained on our own driving (NVIDIA PilotNet style), on Nebius AI Cloud, for smoother movement between model calls.
- Several scouts searching one building and sharing a map.

## Repo layout

```
brain/       laptop code: navigator, models, prompts, camera, car link, fake car, model comparison
car/         ESP32 Arduino sketch + wiring notes
dashboard/   live view (Flask + one HTML page)
docs/        tool feedback log
test_photos/ photos for comparing models (kept out of git by default)
data/        run logs (gitignored)
```

## Licence

MIT. See [LICENSE](LICENSE).
