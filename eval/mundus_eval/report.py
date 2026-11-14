"""Aggregates runs.jsonl into one table per harness combination (pass rate, tokens, cost, latency)."""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _med(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 2) if xs else None


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_combo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        by_combo[r["combo"]].append(r)
    out: dict[str, Any] = {"combos": {}, "tasks": {}}
    for name, rs in by_combo.items():
        graded = [r for r in rs if r["grade"].get("pass") is not None]
        m = [r["metrics"] for r in rs]
        costs = [x.get("est_cost_usd") for x in m]
        row = {"runs": len(rs), "graded": len(graded), "errors": sum(1 for r in rs if r.get("error")),
               "pass_rate": round(sum(1 for r in graded if r["grade"]["pass"]) / len(graded), 3) if graded else None,
               "mean_score": _mean([r["grade"].get("score") for r in graded]),
               "citation_valid_rate": round(sum(1 for r in rs if any(
                   c["check"] == "citation_validity" and c["ok"] for c in r["grade"].get("checks", []))) / len(rs), 3),
               "median_wall_clock_s": _med([r["wall_clock_s"] for r in rs]),
               "median_time_to_first_action_s": _med([r.get("time_to_first_action_s") for r in rs]),
               "mean_tokens_in": _mean([x.get("tokens_in") for x in m]), "mean_tokens_out": _mean([x.get("tokens_out") for x in m]),
               "mean_tokens_total": _mean([x.get("tokens_total") for x in m]),
               "mean_model_calls": _mean([x.get("model_calls") for x in m]), "mean_tool_calls": _mean([x.get("tool_calls") for x in m]),
               "mean_images": _mean([x.get("images") for x in m]),
               "mean_cost_usd": _mean(costs) if all(c is not None for c in costs) else None,
               "by_group": {}}
        for g in sorted({r["group"] for r in rs}):
            gr = [r for r in graded if r["group"] == g]
            row["by_group"][g] = round(sum(1 for r in gr if r["grade"]["pass"]) / len(gr), 3) if gr else None
        out["combos"][name] = row
    for r in runs:
        t = out["tasks"].setdefault(r["task_id"], {})
        c = t.setdefault(r["combo"], {"pass": 0, "runs": 0, "tokens": []})
        c["runs"] += 1
        c["pass"] += int(bool(r["grade"].get("pass")))
        c["tokens"].append(r["metrics"].get("tokens_total"))
    for t in out["tasks"].values():
        for c in t.values():
            c["mean_tokens"] = _mean(c.pop("tokens"))
    return out


def write_report(out_dir: Path) -> str:
    runs = [json.loads(x) for x in (out_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    s = summarize(runs)
    (out_dir / "summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    cols = ["runs", "pass_rate", "mean_score", "citation_valid_rate", "median_wall_clock_s", "median_time_to_first_action_s",
            "mean_tokens_in", "mean_tokens_out", "mean_tokens_total", "mean_model_calls", "mean_tool_calls", "mean_cost_usd"]
    lines = ["# Mundus eval results", "", "| combination | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, row in s["combos"].items():
        lines.append(f"| {name} | " + " | ".join("unknown" if row[c] is None else str(row[c]) for c in cols) + " |")
    lines += ["", "## Pass rate by group", "", "| combination | " + " | ".join(sorted({g for r in s['combos'].values() for g in r['by_group']})) + " |"]
    groups = sorted({g for r in s["combos"].values() for g in r["by_group"]})
    lines.append("|---|" + "---|" * len(groups))
    for name, row in s["combos"].items():
        lines.append(f"| {name} | " + " | ".join(str(row["by_group"].get(g)) for g in groups) + " |")
    names = list(s["combos"])
    lines += ["", "## Per task (passes / runs, mean tokens)", "", "| task | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for tid, t in sorted(s["tasks"].items()):
        lines.append(f"| {tid} | " + " | ".join(
            f"{t[n]['pass']}/{t[n]['runs']}, {t[n]['mean_tokens']}" if n in t else "" for n in names) + " |")
    text = "\n".join(lines) + "\n"
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    return text
