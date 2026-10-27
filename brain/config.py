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

# ---------- car link (see CLAUDE.md for the UDP contract) ----------
CAR_IP = _env("CAR_IP", "192.168.1.60")  # printed on the ESP32 Serial Monitor at boot
CMD_PORT = int(_env("CMD_PORT", "4210"))        # laptop -> ESP32
TELEMETRY_PORT = int(_env("TELEMETRY_PORT", "4211"))  # ESP32 -> laptop
SEND_HZ = 20

# ---------- camera ----------
# An int = capture card / webcam index. A path = video file or folder of images (for testing).
CAMERA_SOURCE = _env("CAMERA_SOURCE", "0")
MAX_IMAGE_SIDE = int(_env("MAX_IMAGE_SIDE", "512"))  # smaller = faster

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

# One "move" at amount=1.0. Tune these on the real car.
FORWARD_SECONDS = 0.8
TURN_SECONDS = 0.6
FORWARD_THROTTLE = 0.35
TURN_THROTTLE = 0.30
METRES_PER_FORWARD = 0.30              # used for dead reckoning
DEGREES_PER_TURN = 45.0

RUNS_DIR = _env("RUNS_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "runs"))
