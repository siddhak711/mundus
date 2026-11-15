"""Per-run context: the run id, and an in-process record of what each run did (route, metrics)."""
from __future__ import annotations

import threading
import time
from typing import Any

_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}


def run_id_from_config(config: dict | None = None) -> str:
    """The eval runner passes configurable.run_id; otherwise the thread id identifies the run."""
    if config is None:
        try:
            from langgraph.config import get_config
            config = get_config()
        except Exception:  # noqa: BLE001 - outside a graph
            config = {}
    conf = (config or {}).get("configurable") or {}
    return str(conf.get("run_id") or conf.get("thread_id") or "local")


def record(run_id: str) -> dict[str, Any]:
    with _LOCK:
        r = _RUNS.get(run_id)
        if r is None:
            r = _RUNS[run_id] = {"started": time.time(), "first_action": None, "route": None, "by_agent": {},
                                 "tools": {}, "images": 0, "claims_written": 0, "claims_read": 0, "pano_looks": 0,
                                 "aerial_looks": 0, "events": []}
        return r


def reset(run_id: str) -> dict[str, Any]:
    with _LOCK:
        _RUNS.pop(run_id, None)
    return record(run_id)


def lock() -> threading.Lock:
    return _LOCK
