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
  Eyes      Nemotron 3 Nano Omni   every step: what's here, person?, obstacle?, next move
  Planner   Nemotron 3 Super       every 5 steps: reads the log, picks where to search next
  Check     Cosmos 3 Reasoner      when a person is first seen: distance, path clear?
  Reflexes  our code               safety override, stuck detection, watchdog
                     │
                     ▼
  laptop ──UDP──▶ ESP32 ──▶ steering servo + motor
  Flysky transmitter ──iBus──▶ ESP32   (manual driving + instant override)
```

- **No map.** The written log of what it saw and did *is* the map. The planner reads it to avoid going in circles.
- **Stop-think-go.** The car is still while a model thinks, then makes a short move. It never drives blind.
- **Safety first.** A transmitter switch flips between manual and autonomous at any moment, and the car stops by itself if the laptop goes quiet for 300 ms.

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
2. **Compare models:** put photos in `test_photos/` (see its README) and run `python brain/vision_test.py`.
3. **Dry run the brain on photos:** `python brain/navigator.py --source test_photos`
4. **Watch it:** in a second terminal, `python dashboard/app.py`, then open http://localhost:5000

### Test the car link without the car

```bash
python brain/fake_car.py                                         # terminal 1: pretends to be the ESP32
DRY_RUN=0 CAR_IP=127.0.0.1 python brain/navigator.py --source test_photos   # terminal 2
```

### With the real car

1. Flash `car/esp32_scout/` (see [car/README.md](car/README.md)) and put the printed IP in `.env` as `CAR_IP`.
2. Plug the VRX into the capture card. `python brain/video_in.py` should save `frame_test.jpg`. Turn the VRX on-screen display off.
3. Bench test with the wheels off the ground (steps in `car/README.md`).
4. Set `DRY_RUN=0`, flip the transmitter to AUTO, and run `python brain/navigator.py`.

Every run is saved to `data/runs/<timestamp>/`: frames, `log.jsonl`, and `report.json` when someone is found.

## Model comparison

Same photos, same prompt (`brain/vision_test.py`). Results to come.

| Model | Person found | Avg distance error | Avg seconds per frame |
|---|---|---|---|
| Nemotron 3 Nano Omni | – | – | – |
| Cosmos 3 Super Reasoner | – | – | – |

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
