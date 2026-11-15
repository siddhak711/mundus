"""Records model calls, tokens, tool calls and latency per agent, and emits a metrics event when a run ends."""
from __future__ import annotations

import json
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from mundus_harness import events, runctx
from mundus_harness.config import Config, est_cost_usd


def _usage(result: Any) -> tuple[int, int]:
    msgs = result.result if hasattr(result, "result") else [result]
    tin = tout = 0
    for m in msgs or []:
        um = getattr(m, "usage_metadata", None) or {}
        tin += um.get("input_tokens", 0) or 0
        tout += um.get("output_tokens", 0) or 0
    return tin, tout


class MetricsMiddleware(AgentMiddleware):
    def __init__(self, cfg: Config, agent: str, is_root: bool = False):
        super().__init__()
        self.cfg, self.agent, self.is_root = cfg, agent, is_root

    def _model_name(self, request) -> str:
        m = request.model
        return str(getattr(m, "model", None) or getattr(m, "model_name", None) or type(m).__name__)

    def _after_model(self, request, result, dt: float) -> None:
        rec = runctx.record(runctx.run_id_from_config())
        tin, tout = _usage(result)
        with runctx.lock():
            a = rec["by_agent"].setdefault(self.agent, {"model_calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0,
                                                        "tool_calls": 0, "models": {}})
            a["model_calls"] += 1
            a["tokens_in"] += tin
            a["tokens_out"] += tout
            a["latency_ms"] += dt * 1000
            name = self._model_name(request)
            m = a["models"].setdefault(name, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
            m["calls"] += 1
            m["tokens_in"] += tin
            m["tokens_out"] += tout

    def wrap_model_call(self, request, handler):
        t0 = time.perf_counter()
        result = handler(request)
        self._after_model(request, result, time.perf_counter() - t0)
        return result

    async def awrap_model_call(self, request, handler):
        t0 = time.perf_counter()
        result = await handler(request)
        self._after_model(request, result, time.perf_counter() - t0)
        return result

    def _after_tool(self, request, result, dt: float) -> None:
        rec = runctx.record(runctx.run_id_from_config())
        name = request.tool_call.get("name", "?")
        err = isinstance(result, ToolMessage) and (getattr(result, "status", "") == "error")
        with runctx.lock():
            if rec["first_action"] is None:
                rec["first_action"] = time.time()
            t = rec["tools"].setdefault(name, {"calls": 0, "errors": 0, "latency_ms": 0.0})
            t["calls"] += 1
            t["errors"] += int(bool(err))
            t["latency_ms"] += dt * 1000
            rec["by_agent"].setdefault(self.agent, {"model_calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0,
                                                    "tool_calls": 0, "models": {}})["tool_calls"] += 1
            if name == "get_claims" or (name == "read_file" and "/world/" in json.dumps(request.tool_call.get("args", {}))):
                rec["claims_read"] += 1

    def wrap_tool_call(self, request, handler):
        t0 = time.perf_counter()
        result = handler(request)
        self._after_tool(request, result, time.perf_counter() - t0)
        return result

    async def awrap_tool_call(self, request, handler):
        t0 = time.perf_counter()
        result = await handler(request)
        self._after_tool(request, result, time.perf_counter() - t0)
        return result

    def before_agent(self, state, runtime):
        if self.is_root:
            runctx.reset(runctx.run_id_from_config())
        return None

    def after_agent(self, state, runtime):
        if not self.is_root:
            return None
        rid = runctx.run_id_from_config()
        summary = summarize(rid)
        line = {"run_id": rid, **summary}
        try:
            self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.cfg.data_dir / "run_metrics.jsonl"
            baseline = None
            if path.exists() and summary.get("place_id"):
                for raw in path.read_text(encoding="utf-8").splitlines():
                    try:
                        old = json.loads(raw)
                    except ValueError:
                        continue
                    if old.get("place_id") == summary["place_id"] and old.get("route") == "cold":
                        baseline = old
                        break
            if baseline:
                def pct(k: str) -> float | None:
                    return round(100 * (1 - summary[k] / baseline[k]), 1) if baseline.get(k) else None
                summary["baseline"] = {k: baseline.get(k) for k in ("model_calls", "tool_calls", "tokens_in", "tokens_out",
                                                                    "tokens_total", "latency_ms", "est_cost_usd")}
                summary["savings"] = {"tokens_pct": pct("tokens_total"), "calls_pct": pct("model_calls"),
                                      "latency_pct": pct("latency_ms")}
            else:
                summary["baseline"], summary["savings"] = None, None
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        except OSError:
            pass
        events.emit("metrics", **summary)
        return None


def summarize(run_id: str) -> dict[str, Any]:
    rec = runctx.record(run_id)
    with runctx.lock():
        by = json.loads(json.dumps(rec["by_agent"]))
        tools = json.loads(json.dumps(rec["tools"]))
        route = rec.get("route") or {}
        started, first = rec["started"], rec["first_action"]
        images, cw, cr = rec["images"], rec["claims_written"], rec["claims_read"]
    tin = sum(a["tokens_in"] for a in by.values())
    tout = sum(a["tokens_out"] for a in by.values())
    cost, known = 0.0, True
    for a in by.values():
        for model, m in a["models"].items():
            c = est_cost_usd(model, m["tokens_in"], m["tokens_out"])
            if c is None:
                known = False
            else:
                cost += c
    return {"route": route.get("route"), "place_id": route.get("place_id"),
            "model_calls": sum(a["model_calls"] for a in by.values()),
            "tool_calls": sum(t["calls"] for t in tools.values()), "tool_errors": sum(t["errors"] for t in tools.values()),
            "images": images, "tokens_in": tin, "tokens_out": tout, "tokens_total": tin + tout,
            "latency_ms": round((time.time() - started) * 1000), "time_to_first_action_ms": round((first - started) * 1000) if first else None,
            "est_cost_usd": round(cost, 6) if known and by else None, "by_agent": by, "by_tool": tools,
            "claims_read": cr, "claims_written": cw, "subagents_used": sorted(k for k in by if k != "orchestrator")}
