"""Central configuration: env loading, paths, vendor endpoints, demo defaults."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
TTS_DIR = DATA_DIR / "tts"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
EVENTS_FILE = DATA_DIR / "task_events.jsonl"


def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader; real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Vendor keys
GNANI_API_KEY = os.environ.get("GNANI_API_KEY", "")
JEV_API_KEY = os.environ.get("JEV_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Vendor endpoints (verified 2026-10-09; see docs/m0_vendor_status.md)
TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"          # Jev is a TypeSafe key
GNANI_STT_URL = "https://api.vachana.ai/stt/v3"
GNANI_TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

# Agent defaults
DEFAULT_LANGUAGE = os.environ.get("AGENT_LANGUAGE", "te-IN")
DEFAULT_VOICE = os.environ.get("AGENT_VOICE", "Varuni")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# Mock portal (demo values, not secrets)
PORTAL_TEST_USER = os.environ.get("PORTAL_TEST_USER", "demo_user")
PORTAL_TEST_PASSWORD = os.environ.get("PORTAL_TEST_PASSWORD", "demo_pass_123")
PORTAL_TEST_OTP = os.environ.get("PORTAL_TEST_OTP", "246810")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765")
PORTAL_URL = os.environ.get("PORTAL_URL", f"{BASE_URL}/portal")

for _path in (DATA_DIR, TTS_DIR, SCREENSHOT_DIR):
    _path.mkdir(parents=True, exist_ok=True)
