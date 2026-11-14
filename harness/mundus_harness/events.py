"""Custom stream events for the frontend. One JSON object per event, with a fixed envelope."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mundus_harness import runctx


def emit(event_type: str, agent: str = "orchestrator", **payload: Any) -> dict[str, Any]:
    rid = runctx.run_id_from_config()
    ev = {"v": 1, "type": event_type, "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
          "agent": agent, "run_id": rid, **payload}
    rec = runctx.record(rid)
    with runctx.lock():
        rec["events"].append(ev)
        if rec["first_action"] is None and event_type not in ("route", "metrics", "answer"):
            import time
            rec["first_action"] = time.time()
    try:
        from langgraph.config import get_stream_writer
        get_stream_writer()(ev)
    except Exception:  # noqa: BLE001 - outside a graph run, or streaming without the custom channel
        pass
    return ev
