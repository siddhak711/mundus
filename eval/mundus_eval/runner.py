"""mundus-eval: check the world, build truth and references, run the suite in parallel, report."""
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


def purge_scoped_claims() -> None:
    """Deletes every run-scoped claim. Failure is reported, never swallowed: leftovers sit in the live database."""
    try:
        with world_client(admin=True) as a:
            r = a.post("/v1/admin/claims/purge-scoped")
            r.raise_for_status()
            print("purged private claims:", r.json(), flush=True)
    except httpx.HTTPError as e:
        print(f"WARNING: could not purge private claims ({e}); "
              "run POST /v1/admin/claims/purge-scoped before the next suite", file=sys.stderr, flush=True)


def plan(tasks: list[dict[str, Any]], combos: list[dict[str, Any]], repeats: int) -> list[tuple[int, str, str]]:
    """Run order, interleaved: within each repeat, each task is queued once per combination back to back, so load on
    the backend and the model providers falls on every combination equally."""
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


def preflight(expect_places: int = 15) -> dict[str, Any]:
    """Refuses an eval on a world that is not ready: every place ingested, every selected pano captioned, every
    search document embedded, semantic search answering, and no aerial facts served."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        with world_client() as w:
            h = w.get("/healthz").json()
            add(f"{expect_places} places ingested", h.get("deep_places") == expect_places, h.get("deep_places"))
            c = w.get("/v1/stats").json().get("counts", {})
            add("every selected pano with images is captioned",
                c.get("panos_selected_with_faces", 0) > 0 and c.get("pano_caption") == c.get("panos_selected_with_faces"),
                {"captions": c.get("pano_caption"), "panos": c.get("panos_selected_with_faces")})
            add("every search document is embedded", c.get("docs", 0) > 0 and c.get("docs_embedded") == c.get("docs"),
                {"embedded": c.get("docs_embedded"), "docs": c.get("docs")})
            r = w.post("/v1/interiors/search", json={"text": "somewhere to sit and wait", "limit": 1})
            add("semantic search answers (mode hybrid)", r.status_code == 200 and r.json().get("mode") == "hybrid",
                r.json().get("mode") if r.status_code == 200 else r.status_code)
            p = w.get("/v1/places/search", params={"deep_only": "true", "limit": 1}).json()["places"][0]["place_id"]
            add("aerial facts are not served", w.get(f"/v1/aerial/{p}").status_code == 404
                and "aerial" not in w.get(f"/v1/places/{p}").json())
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        add("World API reachable", False, f"{type(e).__name__}: {str(e)[:160]}")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def cmd_preflight(args) -> int:
    out = preflight(args.places)
    print(json.dumps(out, indent=1))
    return 0 if out["ok"] else 1


def run_key(rec: dict[str, Any]) -> tuple[str, str, int]:
    return rec["task_id"], rec["combo"], int(rec["repeat"])


def finished_keys(path: Path) -> set[tuple[str, str, int]]:
    """Runs already recorded without a run error. A resumed suite skips these and retries the rest."""
    if not path.exists():
        return set()
    recs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return {run_key(r) for r in recs if not r.get("error")}


async def cmd_run(args) -> int:
    tasks = [t for t in load_tasks() if not args.tasks or t["id"] in args.tasks.split(",")]
    cdoc = load_combos()
    combos = [c for c in cdoc["combos"] if not args.combos or c["name"] in args.combos.split(",")]
    repeats = args.runs or cdoc.get("runs_per_task", 3)
    if not args.skip_preflight:
        pf = preflight(args.places)
        if not pf["ok"]:
            print("Preflight failed; no run started:", json.dumps([c for c in pf["checks"] if not c["ok"]], indent=1), file=sys.stderr)
            return 2
    truth = load_json("truth.json")
    if truth is None:
        print("No truth file: run `mundus-eval truth` first.", file=sys.stderr)
        return 2
    refs = load_json("references.json", {})
    out_dir = Path(args.resume) if args.resume else DATA_DIR / "results" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "runs.jsonl"
    done = finished_keys(runs_path)
    by_id = {t["id"]: t for t in tasks}
    order = [o for o in plan(tasks, combos, repeats) if (o[1], o[2], o[0]) not in done]
    workers = max(1, args.workers)
    print(f"{len(order)} runs to do ({len(done)} already recorded): {len(tasks)} tasks x {len(combos)} combinations x "
          f"{repeats} repeats, {workers} at a time -> {out_dir}", flush=True)
    # Each run gets a private, empty claim memory keyed by its run id, so runs are independent and can overlap.
    os.environ["CLAIM_SCOPE"] = "run"
    agents: dict[str, Any] = {}
    for c in combos:                       # built one at a time: building reads the combination's environment
        agents[c["name"]] = await build_agent_for(c)
    sem = asyncio.Semaphore(workers)
    write_lock = asyncio.Lock()
    count = 0
    with world_client() as world, runs_path.open("a", encoding="utf-8") as fh:

        async def one(rep: int, tid: str, cname: str) -> None:
            nonlocal count
            task = by_id[tid]
            async with sem:
                run_id = f"eval-{cname}-{tid}-r{rep}-{int(time.time())}"
                run = await run_once(agents[cname], task["question"], run_id, args.timeout)
                run = await asyncio.to_thread(enrich, run, world)
                if task["grader"] == "code":
                    grade = graders.grade_code(task, truth.get(tid, {}), run)
                elif args.no_model_grader:
                    grade = {"grader": "model", "pass": None, "score": None, "skipped": "model grader disabled",
                             "checks": graders.common_checks(task, run)}
                else:
                    grade = await asyncio.to_thread(graders.grade_model, task, truth.get(tid, {}),
                                                    (refs.get(tid) or {}).get("text"), run)
            rec = {"repeat": rep, "task_id": tid, "group": task["group"], "combo": cname, "memory": "cold",
                   "workers": workers, **run, "grade": grade}
            async with write_lock:
                count += 1
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                m = run["metrics"]
                print(f"[{count}/{len(order)}] {tid} {cname} r{rep}: pass={grade['pass']} {run['wall_clock_s']}s "
                      f"tokens={m.get('tokens_total')} calls={m.get('model_calls')}/{m.get('tool_calls')}"
                      + (f" ERROR {run['error']}" if run["error"] else ""), flush=True)

        try:
            await asyncio.gather(*(one(rep, tid, cname) for rep, tid, cname in order))
        finally:                            # private memories are only needed during the run, even a failed one
            purge_scoped_claims()
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


def use_mundus_anthropic_key() -> None:
    """Same rule as the harness: a key supplied as MUNDUS_ANTHROPIC_KEY is used against the public API."""
    key = os.environ.get("MUNDUS_ANTHROPIC_KEY", "").strip()
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
        os.environ["ANTHROPIC_BASE_URL"] = os.environ.get("MUNDUS_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def main(argv: list[str] | None = None) -> int:
    use_mundus_anthropic_key()
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
    e.add_argument("--workers", type=int, default=6, help="runs executed at the same time (default 6)")
    e.add_argument("--resume", help="results folder to continue: runs already recorded without error are skipped")
    e.add_argument("--places", type=int, default=15, help="number of ingested places the preflight expects")
    e.add_argument("--skip-preflight", action="store_true", help="do not check the world before running (tests only)")
    e.set_defaults(fn=cmd_run)
    pf = sub.add_parser("preflight", help="check the world is fully ingested, captioned and searchable")
    pf.add_argument("--places", type=int, default=15)
    pf.set_defaults(fn=cmd_preflight)
    rp = sub.add_parser("report", help="rebuild the report for a results folder")
    rp.add_argument("--dir")
    rp.set_defaults(fn=cmd_report)
    args = p.parse_args(argv)
    out = args.fn(args)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


if __name__ == "__main__":
    sys.exit(main())
