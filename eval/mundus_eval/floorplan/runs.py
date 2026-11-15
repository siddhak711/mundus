"""Eval D on the merged conversion agent: run it N times per knob, each in its own copy of the floor folder and its own
memory, grade the result (conversion-v0), and post the grade as LangSmith feedback on the run's trace.

    mundus-eval floorplan run --knob baseline --runs 3
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from mundus_eval.floorplan import conversion as K

REPO = Path(__file__).resolve().parents[3]
SCAN = "cEvQ8q5GKZd"
SRC = REPO / "data" / "conversion" / SCAN
RUNS = REPO / "eval" / "data" / "floorplan" / "runs"
PROJECT = "mundus-floorplan-eval"
FLOOR_FILES = ("geometry.json", "structure.json", "grid.npz", "panos.json", "market.md", "market.json", "photocheck.json")


def git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()


def prepare(run_dir: Path, knob: str, memory_seed: Path | None, hidden_columns: bool) -> None:
    data = run_dir / "data" / SCAN
    data.mkdir(parents=True, exist_ok=True)
    (run_dir / "memory").mkdir(exist_ok=True)
    for name in FLOOR_FILES:
        if (SRC / name).exists():
            shutil.copy2(SRC / name, data / name)
    if hidden_columns:     # K2: give the agent the extrapolated grid columns too, marked hypothesised
        from mundus_eval.floorplan.floor import FLOOR16_HIDDEN, HIDDEN_SIZE
        st = json.loads((data / "structure.json").read_text())
        st["columns"] += [{"x": x, "y": y, "w_m": HIDDEN_SIZE, "d_m": HIDDEN_SIZE, "confidence": "hypothesised",
                           "evidence": ["8.5 m column grid extrapolated where the scan found nothing"]} for x, y in FLOOR16_HIDDEN]
        (data / "structure.json").write_text(json.dumps(st, indent=1))
    if memory_seed:        # K4: warm memory
        shutil.copytree(memory_seed, run_dir / "memory", dirs_exist_ok=True)


def run_one(knob: str, rep: int, env_extra: dict[str, str], memory_seed: Path | None, hidden_columns: bool,
            timeout_s: int = 1800) -> dict[str, Any]:
    rid = f"{knob}-{rep}-{uuid.uuid4().hex[:6]}"
    run_dir = RUNS / rid
    prepare(run_dir, knob, memory_seed, hidden_columns)
    env = os.environ | env_extra | {"CONVERSION_DATA_DIR": str(run_dir / "data"), "CONVERSION_MEMORY_DIR": str(run_dir / "memory"),
                                    "LANGSMITH_PROJECT": PROJECT}
    sha = git_sha()
    cmd = [sys.executable, "-m", "mundus_harness.conversion.run", SCAN, "--tag", "floorplan", "--tag", f"knob:{knob}",
           "--tag", f"rep:{rep}", "--tag", f"run:{rid}", "--meta", f"knob={knob}", "--meta", f"rep={rep}", "--meta", f"git={sha}",
           "--meta", f"eval_run_id={rid}", "--meta", f"profile={K.PROFILE}"]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=REPO / "harness", env=env, capture_output=True, text=True, timeout=timeout_s)
    minutes = round((time.time() - t0) / 60, 2)
    (run_dir / "stdout.txt").write_text(p.stdout)
    (run_dir / "stderr.txt").write_text(p.stderr)
    rec: dict[str, Any] = {"run": rid, "knob": knob, "rep": rep, "git": sha, "exit": p.returncode, "minutes": minutes,
                           "profile": K.PROFILE, "answer": p.stdout[-3000:]}
    try:
        final, draft = K.final_draft(run_dir / "data", SCAN)
        floor = K.load_conversion_floor(run_dir / "data" / SCAN)
        g = K.grade_conversion(floor, draft, final)
        rec |= {"total": g["total"], "hard_breaks": g["hard_breaks"], "criteria": {k: v["points"] for k, v in g["criteria"].items()},
                "units": g["units"], "unit_mix": g["unit_mix"], "rentable_sf": g["rentable_sf"], "efficiency": g["efficiency"],
                "noi": g["noi"], "claims": g["claims"], "drafts": len(list((run_dir / "data" / SCAN / "drafts").glob("draft_*.json")))}
        (run_dir / "grade.json").write_text(json.dumps(g, indent=1))
    except Exception as e:  # noqa: BLE001 - a run that wrote no layout scores 0, and the reason is kept
        rec |= {"total": 0.0, "error": f"{type(e).__name__}: {e}"[:300], "hard_breaks": ["no layout written"]}
    rec |= trace_stats(rid)
    post_feedback(rec)
    return rec


def _client():
    from mundus_harness.tracing import enable_tracing
    os.environ.setdefault("LANGSMITH_PROJECT", PROJECT)
    if not enable_tracing():
        return None
    from langsmith import Client
    return Client()


def find_root(client, rid: str, tries: int = 6):
    for _ in range(tries):
        rs = list(client.list_runs(project_name=PROJECT, is_root=True, filter=f'has(tags, "run:{rid}")', limit=1))
        if rs:
            return rs[0]
        time.sleep(5)
    return None


def trace_stats(rid: str) -> dict[str, Any]:
    c = _client()
    if c is None:
        return {}
    root = find_root(c, rid)
    if root is None:
        return {"trace": None}
    return {"trace_id": str(root.trace_id), "root_run_id": str(root.id), "tokens": root.total_tokens,
            "cost_usd": float(root.total_cost or 0)}


def post_feedback(rec: dict[str, Any]) -> None:
    c = _client()
    if c is None or not rec.get("root_run_id"):
        return
    rid = rec["root_run_id"]
    c.create_feedback(rid, key="grade_total", score=rec["total"] / 100, value=rec["total"], comment=K.PROFILE)
    c.create_feedback(rid, key="hard_breaks", score=len(rec.get("hard_breaks") or []), comment="; ".join(rec.get("hard_breaks") or []))
    for k, v in (rec.get("criteria") or {}).items():
        c.create_feedback(rid, key=f"c:{k}", score=v)
    if rec.get("claims"):
        c.create_feedback(rid, key="claim_gap", score=rec["claims"]["gap"],
                          comment=f"agent says {rec['claims']['claimed_units_passing']} pass, grader {rec['claims']['graded_units_passing']}")
    if rec.get("drafts") is not None:
        c.create_feedback(rid, key="drafts_used", score=rec["drafts"])


def cmd_run(args) -> int:
    env_extra = dict(kv.split("=", 1) for kv in args.env or [])
    RUNS.mkdir(parents=True, exist_ok=True)
    seed = Path(args.memory_seed) if args.memory_seed else None
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        recs = list(ex.map(lambda r: run_one(args.knob, r, env_extra, seed, args.hidden_columns), range(1, args.runs + 1)))
    with (RUNS.parent / "runs.jsonl").open("a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    for r in recs:
        print(f"{r['run']}: {r['total']:.1f}  hard {len(r.get('hard_breaks') or [])}  units {r.get('units')}  "
              f"claim gap {(r.get('claims') or {}).get('gap')}  drafts {r.get('drafts')}  {r['minutes']} min  ${r.get('cost_usd', 0):.2f}"
              + (f"  ERROR {r['error']}" if r.get("error") else ""))
    summarize(args.knob)
    return 0


def summarize(knob: str | None = None) -> dict[str, Any]:
    rows = [json.loads(x) for x in (RUNS.parent / "runs.jsonl").read_text().splitlines()] if (RUNS.parent / "runs.jsonl").exists() else []
    out = {}
    for k in sorted({r["knob"] for r in rows}):
        rs = [r for r in rows if r["knob"] == k]
        t = [r["total"] for r in rs]
        out[k] = {"n": len(rs), "mean": round(sum(t) / len(t), 2), "min": min(t), "max": max(t),
                  "hard_mean": round(sum(len(r.get("hard_breaks") or []) for r in rs) / len(rs), 2),
                  "claim_gap_mean": round(sum((r.get("claims") or {}).get("gap", 0) for r in rs) / len(rs), 2),
                  "units_mean": round(sum(r.get("units") or 0 for r in rs) / len(rs), 1),
                  "cost_mean": round(sum(r.get("cost_usd") or 0 for r in rs) / len(rs), 3),
                  "minutes_mean": round(sum(r["minutes"] for r in rs) / len(rs), 2)}
        if knob is None or k == knob:
            print(k, out[k])
    return out


def add_parsers(s) -> None:
    r = s.add_parser("run", help="eval D: run the conversion agent N times for one knob, grade, post LangSmith feedback")
    r.add_argument("--knob", required=True, help="label for this configuration, e.g. baseline, k1-tools")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--workers", type=int, default=3)
    r.add_argument("--env", action="append", help="KEY=VALUE for the agent process (repeatable)")
    r.add_argument("--memory-seed", help="folder copied into the run's memory before it starts (warm memory)")
    r.add_argument("--hidden-columns", action="store_true", help="add the hypothesised grid columns to the floor data")
    r.set_defaults(fn=cmd_run)
    sm = s.add_parser("summary", help="mean and spread per knob")
    sm.set_defaults(fn=lambda a: (summarize(), 0)[1])
    from mundus_eval.floorplan.traces import add_parser as add_traces

    add_traces(s)
