"""Paths and API keys. Keys are read from .env in the project root (never committed)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
# Vercel functions can write only to /tmp
CACHE = Path(os.environ.get("ATLAS_CACHE_DIR") or ("/tmp/atlas-cache" if os.environ.get("VERCEL") else ROOT / "cache"))
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
# Ask Atlas talks to the Mundus deep agent (harness/, LangGraph Server) and reads claim text from the World API.
HARNESS_URL = os.environ.get("HARNESS_URL", "http://127.0.0.1:2024").rstrip("/")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")            # only when the agent server sits behind the VM's Caddy
WORLD_REST_URL = os.environ.get("WORLD_REST_URL", "http://127.0.0.1:8000").rstrip("/")
WORLD_API_TOKEN = os.environ.get("WORLD_API_TOKEN", "")
# server.py: the address it listens on, and which site origin may call it (GitHub Pages: https://<user>.github.io)
HOST = os.environ.get("ATLAS_HOST", "127.0.0.1")
CORS_ORIGIN = os.environ.get("ATLAS_CORS_ORIGIN", "*")
