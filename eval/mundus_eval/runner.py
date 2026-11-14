"""mundus-eval: build truth and references, seed warm memory, run the suite, report."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from mundus_eval import graders
from mundus_eval.tasks import DATA_DIR, build_truth, load_combos, load_json, load_tasks, save_json

WARM_SNAPSHOT = "eval-warm"


def world_client(admin: bool = False) -> httpx.Client:
    base = os.environ.get("WORLD_REST_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("WORLD_ADMIN_TOKEN" if admin else "WORLD_API_TOKEN", "")
    return httpx.Client(base_url=base, timeout=60, headers={"Authorization": f"Bearer {token}"} if token else {})


def plan(tasks: list[dict[str, Any]], combos: list[dict[str, Any]], repeats: int) -> list[tuple[int, str, str]]:
    """Run order: sequential and interleaved. Within each repeat, each task runs once per combination back to back,
    so slow drift in the backend or the model providers falls on every combination equally."""
    return [(rep, t["id"], c["name"]) for rep in range(1, repeats + 1) for t in tasks for c in combos]


def reset_memory(mode: str) -> dict[str, Any]:
    with world_client(admin=True) as a:
        body = {"mode": "restore", "name": WARM_SNAPSHOT} if mode == "warm" else {"mode": "empty"}
        r = a.post("/v1/admin/claims/reset", json=body)
        r.raise_for_status()
        return r.json()


async def run_once(agent: Any, question: str, run_id: str, timeout_s: float = 600) -> dict[str, Any]:
    """Runs one question and returns the answer, citations, claims, metrics and wall-clock timings."""
    t0 = time.perf_counter()
    first_action: float | None = None
    events: list[dict[str, Any]] = []
    error = None

    async def consume() -> None:
        nonlocal first_action
        async for _ns, mode, chunk in agent.astream({"messages": [{"role": "user", "content": question}]},
                                                    config={"configurable": {"thread_id": run_id, "run_id": run_id},
                                                            "recursion_limit": 200},
                                                    stream_mode=["custom", "updates"], subgraphs=True):
            if mode == "custom":
                events.append(chunk)
            elif first_action is None and any(k == "tools" for k in (chunk or {})):
                first_action = time.perf_counter() - t0

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except asyncio.TimeoutError:
        error = f"timeout after {timeout_s:.0f}s"
    except Exception as e:  # noqa: BLE001 - a failed run is a result, not a crash of the suite
        error = f"{type(e).__name__}: {str(e)[:300]}"
    wall = time.perf_counter() - t0
    ans = next((e for e in reversed(events) if e["type"] == "answer"), {})
    met = next((e for e in reversed(events) if e["type"] == "metrics"), {})
    route = next((e for e in events if e["type"] == "route"), {})
    return {"run_id": run_id, "error": error, "answer": ans.get("text", ""), "citations": ans.get("citations", []),
            "dropped_markers": ans.get("dropped_markers", []),
            "claims": [{k: e.get(k) for k in ("claim_id", "predicate", "statement", "evidence_ids", "outcome", "agent")}
                       for e in events if e["type"] == "claim"],
            "route": route.get("route"), "wall_clock_s": round(wall, 2),
            "time_to_first_action_s": round(first_action, 2) if first_action is not None else None,
            "metrics": {k: met.get(k) for k in ("model_calls", "tool_calls", "tool_errors", "images", "tokens_in", "tokens_out",
                                                "tokens_total", "est_cost_usd", "claims_read", "claims_written",
                                                "subagents_used", "by_agent", "by_tool", "time_to_first_action_ms")}}


def enrich(run: dict[str, Any], world: httpx.Client) -> dict[str, Any]:
    """Adds the evidence types behind the cited claims and the backend's own call counts for this run."""
    types: set[str] = set()
    for c in run["citations"]:
        for ev in c.get("evidence_ids") or []:
            r = world.get(f"/v1/evidence/{ev}")
            if r.status_code == 200:
                types.add(r.json()["type"])
    run["evidence_types"] = sorted(types)
    r = world.get("/v1/stats", params={"run_id": run["run_id"]})
    if r.status_code == 200:
        s = r.json()
        run["backend"] = {"total_calls": s["total_calls"], "expensive_calls": s["expensive_calls"],
                          "by_op": {o["op"]: o["calls"] for o in s["api_calls"]}, "model_tokens": s.get("model_tokens_total")}
    return run


async def build_agent_for(combo: dict[str, Any]) -> Any:
    for k, v in (combo.get("env") or {}).items():
        os.environ[k] = str(v)
    from mundus_harness.config import load_config
    from mundus_harness.graph import build_agent, load_world_tools

    cfg = load_config()
    return build_agent(cfg, await load_world_tools(cfg))


async def cmd_run(args) -> int:
    tasks = [t for t in load_tasks() if not args.tasks or t["id"] in args.tasks.split(",")]
    cdoc = load_combos()
    combos = [c for c in cdoc["combos"] if not args.combos or c["name"] in args.combos.split(",")]
    repeats = args.runs or cdoc.get("runs_per_task", 3)
    truth = load_json("truth.json")
    if truth is None:
        print("No truth file: run `mundus-eval truth` first.", file=sys.stderr)
        return 2
    refs = load_json("references.json", {})
    out_dir = DATA_DIR / "results" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {t["id"]: t for t in tasks}
    by_combo = {c["name"]: c for c in combos}
    agents: dict[str, Any] = {}
    order = plan(tasks, combos, repeats)
    print(f"{len(order)} runs: {len(tasks)} tasks x {len(combos)} combinations x {repeats} repeats -> {out_dir}")
    with world_client() as world, (out_dir / "runs.jsonl").open("a", encoding="utf-8") as fh:
        for n, (rep, tid, cname) in enumerate(order, 1):
            task, combo = by_id[tid], by_combo[cname]
            reset_memory(combo.get("memory", "cold"))
            if cname not in agents or args.fresh_agent:
                agents[cname] = await build_agent_for(combo)
            run_id = f"eval-{cname}-{tid}-r{rep}-{int(time.time())}"
            run = enrich(await run_once(agents[cname], task["question"], run_id, args.timeout), world)
            if task["grader"] == "code" or args.no_model_grader:
                grade = graders.grade_code(task, truth.get(tid, {}), run) if task["grader"] == "code" else \
                    {"grader": "model", "pass": None, "score": None, "skipped": "model grader disabled",
                     "checks": graders.common_checks(task, run)}
            else:
                grade = graders.grade_model(task, truth.get(tid, {}), (refs.get(tid) or {}).get("text"), run)
            rec = {"n": n, "repeat": rep, "task_id": tid, "group": task["group"], "combo": cname,
                   "memory": combo.get("memory", "cold"), **run, "grade": grade}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            m = run["metrics"]
            print(f"[{n}/{len(order)}] {tid} {cname} r{rep}: pass={grade['pass']} {run['wall_clock_s']}s "
                  f"tokens={m.get('tokens_total')} calls={m.get('model_calls')}/{m.get('tool_calls')}"
                  + (f" ERROR {run['error']}" if run["error"] else ""), flush=True)
    from mundus_eval.report import write_report
    print(write_report(out_dir))
    return 0


async def cmd_seed(args) -> int:
    """Builds the warm memory snapshot: runs every task once from an empty store with one combination, then snapshots."""
    tasks = load_tasks()
    combo = next(c for c in load_combos()["combos"] if c["name"] == args.combo) if args.combo else load_combos()["combos"][0]
    reset_memory("cold")
    agent = await build_agent_for(combo)
    for t in tasks:
        r = await run_once(agent, t["question"], f"seed-{t['id']}-{int(time.time())}", args.timeout)
        print(f"seed {t['id']}: {len(r['claims'])} claims, {r['wall_clock_s']}s" + (f" ERROR {r['error']}" if r["error"] else ""))
    with world_client(admin=True) as a:
        s = a.post("/v1/admin/claims/snapshot", json={"name": WARM_SNAPSHOT})
        s.raise_for_status()
        print("snapshot:", s.json())
    return 0


def cmd_truth(_args) -> int:
    with world_client() as w:
        truth = build_truth(load_tasks(), w)
    p = save_json("truth.json", truth)
    missing = {t: [k for k, v in vals.items() if v is None] + vals.get("_errors", []) for t, vals in truth.items()
               if any(v is None for v in vals.values()) or vals.get("_errors")}
    print(f"wrote {p}")
    if missing:
        print("truth values missing (the place may not be ingested):", json.dumps(missing, indent=1))
    return 0


def cmd_references(args) -> int:
    from mundus_eval.references import build_reference

    refs = load_json("references.json", {})
    with world_client() as w:
        for t in load_tasks():
            if not t.get("reference_images") or (t["id"] in refs and refs[t["id"]].get("text") and not args.force):
                continue
            refs[t["id"]] = build_reference(t, w)
            print(t["id"], "ok" if refs[t["id"]].get("text") else refs[t["id"]].get("error"))
            save_json("references.json", refs)
    return 0


def cmd_report(args) -> int:
    from mundus_eval.report import write_report

    root = DATA_DIR / "results"
    d = Path(args.dir) if args.dir else max((p for p in root.iterdir() if p.is_dir()), default=None) if root.exists() else None
    if d is None:
        print("no results yet", file=sys.stderr)
        return 2
    print(write_report(d))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mundus-eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("truth", help="compute ground truth from the World API").set_defaults(fn=cmd_truth)
    r = sub.add_parser("references", help="write visual references from the photos with Claude Fable 5.2")
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_references)
    s = sub.add_parser("seed", help="build the warm-memory snapshot")
    s.add_argument("--combo")
    s.add_argument("--timeout", type=float, default=600)
    s.set_defaults(fn=cmd_seed)
    e = sub.add_parser("run", help="run the suite")
    e.add_argument("--tasks", help="comma-separated task ids (default all)")
    e.add_argument("--combos", help="comma-separated combination names (default all)")
    e.add_argument("--runs", type=int, help="repeats per task and combination (default from combos.yaml)")
    e.add_argument("--timeout", type=float, default=600)
    e.add_argument("--no-model-grader", action="store_true", help="skip the Fable grader (code checks only)")
    e.add_argument("--fresh-agent", action="store_true", help="rebuild the agent before every run")
    e.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="rebuild the report for a results folder")
    rp.add_argument("--dir")
    rp.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    out = args.fn(args)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


if __name__ == "__main__":
    sys.exit(main())
