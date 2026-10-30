"""All settings in one place. Override any of them with environment variables or a .env file."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# ---------- Nebius Token Factory ----------
API_BASE = _env("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
API_KEY = os.environ.get("NEBIUS_API_KEY", "")

# Check exact ids with:  python brain/vision_test.py --list
# Only models marked "Public" in Token Factory work with a normal API key.
EYES_MODEL = _env("EYES_MODEL", "nvidia/Nemotron-3.5-Super-VL")        # vision, every step
PLANNER_MODEL = _env("PLANNER_MODEL", "nvidia/Nemotron-3_5-Lightning")  # text, every PLAN_EVERY steps
CHECK_MODEL = _env("CHECK_MODEL", "nvidia/Nemotron-3.5-Super-VL")       # vision, when a person is first seen
# Models vision_test.py compares (comma-separated). Non-NVIDIA open models are baselines only.
COMPARE_MODELS = list(dict.fromkeys(
    m.strip() for m in _env("COMPARE_MODELS",
                            "nvidia/Nemotron-3.5-Super-VL,google/gemma-3-27b-it,openbmb/MiniCPM-V-4_5").split(",")
    if m.strip()))

# ---------- car link ----------
# "ble" = our ESP32-S3 car over Bluetooth (brain/ble_link.py). "udp" = the Wi-Fi sketch in car/ (car_link.py).
CAR_LINK = _env("CAR_LINK", "ble")
BLE_NAME = _env("BLE_NAME", "ESP32_RC_CAR")
BLE_ADDRESS = _env("BLE_ADDRESS", "")   # optional: the car's address from `python brain/ble_link.py --scan`
BLE_RX_UUID = _env("BLE_RX_UUID", "6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
BLE_SPEED = int(_env("BLE_SPEED", "1"))  # 1 = slowest; keep it low indoors
TURN_SPEED = int(_env("TURN_SPEED", _env("BLE_SPEED", "1")))  # speed level for turns (try 2 if turns stall)
STEER_TRIM = max(-1.0, min(1.0, float(_env("STEER_TRIM", "0"))))  # car pulls right? try -0.2 (left taps)

# UDP link settings (only used when CAR_LINK=udp; see CLAUDE.md for that contract)
CAR_IP = _env("CAR_IP", "192.168.1.60")  # printed on the ESP32 Serial Monitor at boot
CMD_PORT = int(_env("CMD_PORT", "4210"))        # laptop -> ESP32
TELEMETRY_PORT = int(_env("TELEMETRY_PORT", "4211"))  # ESP32 -> laptop
SEND_HZ = 20

# ---------- camera ----------
# An int = capture card / webcam index. A path = video file or folder of images (for testing).
CAMERA_SOURCE = _env("CAMERA_SOURCE", "0")
MAX_IMAGE_SIDE = int(_env("MAX_IMAGE_SIDE", "512"))  # smaller = faster
MASK_OSD = _env("MASK_OSD", "1") == "1"  # black out the VRX on-screen text on live frames
SPOT_SIDE = int(_env("SPOT_SIDE", "1024"))  # sharper second look when the target isn't seen (0 = off)

# What the scout searches for. "person" for real runs; any object for tests, e.g. "an antiperspirant can".
TARGET = _env("TARGET", "person")

# ---------- speed ----------
THINKING = _env("THINKING", "off")      # "off" skips the model's reasoning phase when supported
FAST_PROMPT = _flag("FAST_PROMPT", True)  # short JSON answer, action first
MAX_REPEAT = 3                          # forward moves allowed per model call on clear floor

# ---------- behaviour ----------
DRY_RUN = _flag("DRY_RUN", True)       # True = print car commands instead of sending
MAX_STEPS = int(_env("MAX_STEPS", "60"))
PLAN_EVERY = 5
STUCK_DIFF = 3.0
STOP_CM = float(_env("STOP_CM", "30"))     # measured obstacle closer than this = obstacle_close
FOUND_CM = float(_env("FOUND_CM", "100"))  # measured person closer than this = done                       # mean pixel change below this after "forward" = stuck
AIM_DEADBAND = float(_env("AIM_DEADBAND", "0.08"))  # target this far off centre (fraction of width) -> turn towards it
CAM_SCAN = _env("CAM_SCAN", "1") == "1"  # target lost: look left/right with the camera before turning the car
PAN_SECONDS = float(_env("PAN_SECONDS", "0.5"))  # how long to hold the camera pan for one look
MAX_SEARCH_TURNS = int(_env("MAX_SEARCH_TURNS", "8"))  # full-lock turns towards a camera sighting before looking again
SPIN_SEARCH = _env("SPIN_SEARCH", "1") == "1"  # search turns are three-point turns (turn on the spot)

# One "move" at amount=1.0. Tune these on the real car.
FORWARD_SECONDS = float(_env("FORWARD_SECONDS", "0.8"))
MIN_MOVE_SECONDS = float(_env("MIN_MOVE_SECONDS", "0.45"))  # shorter bursts barely move the car
TURN_SECONDS = float(_env("TURN_SECONDS", "0.6"))
SEARCH_TURN_SECONDS = float(_env("SEARCH_TURN_SECONDS", "1.0"))  # each half of a search three-point turn (bigger = turns further)
SPIN_REVERSE_SHARE = float(_env("SPIN_REVERSE_SHARE", "0.6"))  # reverse half of a three-point turn, as a share of the forward half
PRESTEER_SECONDS = float(_env("PRESTEER_SECONDS", "0.6"))  # turn the wheels before driving a turn (0 = off)
FORWARD_THROTTLE = 0.35
TURN_THROTTLE = 0.30
METRES_PER_FORWARD = float(_env("METRES_PER_FORWARD", "0.30"))              # used for dead reckoning
DEGREES_PER_TURN = float(_env("DEGREES_PER_TURN", "45"))

RUNS_DIR = _env("RUNS_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "runs"))
