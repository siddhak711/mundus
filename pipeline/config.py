"""Paths and API keys. Keys are read from .env in the project root (never committed)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
WEB = ROOT / "web"


def _load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

VEXCEL_API_KEY = os.environ.get("VEXCEL_API_KEY", "")
MATTERPORT_API_KEY = os.environ.get("MATTERPORT_API_KEY", "")
MATTERPORT_API_TOKEN = os.environ.get("MATTERPORT_API_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
