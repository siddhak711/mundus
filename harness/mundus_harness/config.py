"""Harness configuration from environment variables. One place for model ids, limits and prices."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

HARNESS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HARNESS_DIR.parent

# USD per million tokens (input, output). A model missing here costs "unknown" rather than a guess.
# Claude prices are Anthropic's first-party list prices as of 2026-11-03. Add others with MODEL_PRICES
# ("model=in,out;model=in,out").
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-2": (8.00, 40.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    world_rest_url: str
    world_mcp_url: str
    world_token: str
    orch_model: str
    worker_model: str
    router_model: str
    router_use_model: bool
    data_dir: Path
    ui_events_in_state: bool
    max_pano_images: int = 12
    max_aerial_images: int = 4
    orch_model_calls: int = 25
    orch_tool_calls: int = 60
    sub_model_calls: int = 12
    sub_tool_calls: int = 30
    coverage_min_claims: int = 3


def use_mundus_anthropic_key() -> None:
    """Some hosted shells reserve ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL for their own use. When the key is
    supplied as MUNDUS_ANTHROPIC_KEY, point this process at the public API with that key."""
    key = _env("MUNDUS_ANTHROPIC_KEY")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
        os.environ["ANTHROPIC_BASE_URL"] = _env("MUNDUS_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def load_config() -> Config:
    load_dotenv(REPO_ROOT / ".env", override=False)
    load_dotenv(HARNESS_DIR / ".env", override=False)
    use_mundus_anthropic_key()
    rest = _env("WORLD_REST_URL", "http://127.0.0.1:8000").rstrip("/")
    worker = _env("WORKER_MODEL", "anthropic:claude-haiku-5-5")
    dd = Path(_env("HARNESS_DATA_DIR") or (HARNESS_DIR / "data")).resolve()
    for line in _env("MODEL_PRICES").split(";"):       # "model=in,out;model2=in,out"
        if "=" in line:
            m, p = line.split("=", 1)
            try:
                a, b = (float(x) for x in p.split(","))
                PRICES[m.strip()] = (a, b)
            except ValueError:
                pass
    return Config(
        world_rest_url=rest,
        world_mcp_url=_env("WORLD_MCP_URL", rest + "/mcp/"),
        world_token=_env("WORLD_API_TOKEN"),
        orch_model=_env("ORCH_MODEL", "anthropic:claude-sonnet-5-5"),
        worker_model=worker,
        router_model=_env("ROUTER_MODEL", worker),
        router_use_model=_env("ROUTER_USE_MODEL", "0") == "1",
        data_dir=dd,
        ui_events_in_state=_env("UI_EVENTS_IN_STATE", "0") == "1",
    )


def est_cost_usd(model: str, tokens_in: int, tokens_out: int) -> float | None:
    key = model.split(":", 1)[-1]
    p = PRICES.get(model) or PRICES.get(key)
    if not p:
        return None
    return round(tokens_in / 1e6 * p[0] + tokens_out / 1e6 * p[1], 6)
