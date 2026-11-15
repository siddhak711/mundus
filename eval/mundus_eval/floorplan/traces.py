"""Step 3: read graded conversion runs back out of LangSmith and count behaviour patterns.

For each root run of a knob it pulls the tool runs in order and reports, per draft: the depth and unit widths the
layout agent asked for, the unit mix and size that came back, the failures the tool reported, and whether the next
draft changed anything. Then it counts patterns across runs.

    mundus-eval floorplan traces --knob baseline
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from mundus_eval.floorplan.runs import PROJECT, RUNS, _client


def _json(x: Any) -> Any:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def tool_calls(client, trace_id: str) -> list[dict[str, Any]]:
    runs = list(client.list_runs(project_name=PROJECT, trace_id=trace_id, run_type="tool"))
    runs.sort(key=lambda r: r.start_time)
    out = []
    for r in runs:
        outputs = r.outputs or {}
        o = outputs.get("output", outputs)
        if isinstance(o, dict) and "content" in o:
            o = o["content"]
        out.append({"name": r.name, "inputs": r.inputs or {}, "output": _json(o), "error": r.error})
    return out


def draft_story(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    story = []
    for c in calls:
        if c["name"] != "draft_layout":
            continue
        inp = c["inputs"].get("input", c["inputs"])
        inp = _json(inp) if isinstance(inp, str) else inp
        sides = (inp or {}).get("sides") or {}
        widths = [u.get("width_m") for side in sides.values() for u in side if u.get("type") != "gap"]
        types = Counter(u.get("type") for side in sides.values() for u in side if u.get("type") != "gap")
        out = c["output"] if isinstance(c["output"], dict) else {}
        gaps = sum(u.get("width_m") or 0 for side in sides.values() for u in side if u.get("type") == "gap")
        n_back = sum((out.get("unit_mix") or {}).values()) or None
        story.append({"depth": (inp or {}).get("unit_depth_m"), "n_req": len(widths), "gap_m": round(gaps, 1),
                      "mean_width": round(sum(w for w in widths if w) / max(1, len([w for w in widths if w])), 2),
                      "types_req": dict(types), "units": n_back, "rentable_sf": out.get("rentable_sf"),
                      "counts": out.get("counts"), "error": out.get("error") or c["error"],
                      "problems": len(out.get("draft_problems") or [])})
    return story


def patterns(stories: dict[str, list[dict[str, Any]]], grades: dict[str, dict[str, Any]]) -> Counter:
    p: Counter = Counter()
    for rid, st in stories.items():
        if not st:
            p["no draft_layout calls in trace"] += 1
            continue
        if any(s["depth"] == "auto" for s in st):
            p["uses depth 'auto' (units run to 10.5 m deep)"] += 1
        if all(s["depth"] == "auto" for s in st):
            p["never tries a fixed depth"] += 1
        if any(s.get("error") for s in st):
            p["a draft_layout call returned an error"] += 1
        last = st[-1]
        if (last.get("counts") or {}).get("fail", 0) == 0 and grades.get(rid, {}).get("claims", {}).get("gap", 0) > 0:
            p["tool said 0 fail but the grader found failing units"] += 1
        if last.get("rentable_sf") and last.get("units"):
            if last["rentable_sf"] / last["units"] > 700:
                p["final average unit over 700 sf"] += 1
        twos = sum(s["types_req"].get("2BR", 0) + s["types_req"].get("3BR", 0) for s in st[-1:])
        if twos >= last.get("n_req", 1) / 2:
            p["half or more of the units are 2BR/3BR"] += 1
        if last.get("gap_m", 0) >= 20:
            p["final draft leaves 20 m or more of facade as gap"] += 1
        if len(st) >= 5:
            p["used all 5 drafts"] += 1
        sizes = [s.get("units") for s in st if s.get("units")]
        if len(sizes) > 1 and max(sizes) == sizes[0]:
            p["never added units after the first draft"] += 1
    return p


def cmd_traces(args) -> int:
    c = _client()
    if c is None:
        print("LangSmith tracing is not configured")
        return 1
    recs = [json.loads(x) for x in (RUNS.parent / "runs.jsonl").read_text().splitlines()]
    recs = [r for r in recs if r["knob"] == args.knob and r.get("trace_id")]
    stories, grades = {}, {}
    for r in recs:
        stories[r["run"]] = draft_story(tool_calls(c, r["trace_id"]))
        grades[r["run"]] = r
    lines = [f"# Trace report: {args.knob} ({len(recs)} runs)", ""]
    for rid, st in stories.items():
        lines.append(f"## {rid}: grade {grades[rid]['total']}")
        lines.append("| draft | depth | units asked | mean width m | facade left as gap m | types asked | units back | sf/unit | tool fail |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for i, s in enumerate(st, 1):
            spu = round(s["rentable_sf"] / s["units"]) if s.get("units") and s.get("rentable_sf") else ""
            lines.append(f"| {i} | {s['depth']} | {s['n_req']} | {s['mean_width']} | {s['gap_m']} | {s['types_req']} | {s.get('units')} | {spu} | "
                         f"{(s.get('counts') or {}).get('fail', s.get('error') or '')} |")
        lines.append("")
    pc = patterns(stories, grades)
    lines += ["## Patterns (runs out of %d)" % len(recs), "", "| pattern | runs |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in pc.most_common()]
    text = "\n".join(lines) + "\n"
    out = RUNS.parent / f"trace-report-{args.knob}.md"
    out.write_text(text)
    print(text)
    return 0


def add_parser(s) -> None:
    t = s.add_parser("traces", help="mine LangSmith traces of graded runs for behaviour patterns")
    t.add_argument("--knob", required=True)
    t.set_defaults(fn=cmd_traces)


def report_path(knob: str) -> Path:
    return RUNS.parent / f"trace-report-{knob}.md"
