"""`mundus-eval floorplan ...`: grade layouts, build mutants (eval C), run the rule-check judge (eval A).

Everything written goes under eval/data/floorplan/ (git-ignored: layouts are in licensed scan coordinates).
"""
from __future__ import annotations

import json
import random
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from mundus_eval.floorplan import rubric
from mundus_eval.floorplan.floor import Column, Floor, load_shell, shell_path
from mundus_eval.floorplan.synthetic import synthetic

FP_DATA = Path(__file__).resolve().parents[2] / "data" / "floorplan"
SEED_DIR = FP_DATA / "seed"


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def bases(names: list[str] | None) -> dict[str, tuple[Floor, dict[str, Any]]]:
    """'synthetic', or seed layouts in eval/data/floorplan/seed/<name>.json graded on shell.json."""
    out: dict[str, tuple[Floor, dict[str, Any]]] = {}
    for n in names or ["synthetic"]:
        if n == "synthetic":
            out[n] = synthetic()
            continue
        p = Path(n) if Path(n).suffix == ".json" else SEED_DIR / f"{n}.json"
        out[p.stem] = (load_shell(), json.loads(p.read_text(encoding="utf-8")))
    return out


def cmd_grade(args) -> int:
    floor = load_shell(Path(args.shell)) if args.shell else None
    rows = []
    for path in args.layouts:
        if path == "synthetic":
            f, lay = synthetic()
        else:
            f, lay = floor or load_shell(), json.loads(Path(path).read_text(encoding="utf-8"))
        g = rubric.grade_layout(f, lay)
        gap = rubric.calibration_gap(g, lay)
        rows.append({"layout": path, "rubric_version": g["rubric_version"], "total": g["total"], "groups": g["groups"],
                     "hard_breaks": g["hard_breaks"], "self_score_gap": gap})
        print(f"\n{path}: {g['total']:.1f} / 100 (rubric {g['rubric_version']}, {g['share_of_ceiling']:.0%} of the "
              f"{rubric.CEILING:.0f} ceiling); hard breaks {len(g['hard_breaks'])}")
        claimed = rubric.claimed_self_score(lay) or {}
        for k, v in g["criteria"].items():
            self_ = f"self {claimed[k]:5.2f}" if k in claimed else ""
            print(f"  {k:28s} {v['points']:5.2f} / {v['max']:2d}  {self_:11s} {v['measured']}")
        if gap:
            print(f"  self-score gap {gap['total_gap']:+.2f} (eval B pass: {gap['pass']})")
        if args.verbose:
            for r in g["checks"]:
                if r["status"] != "pass":
                    print(f"    {r['status'].upper():7s} {r['rule']}:{r['subject']} {r['value']} {r['detail'][:100]}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


def cmd_mutate(args) -> int:
    from mundus_eval.floorplan.mutations import mutate

    out = Path(args.out or FP_DATA / "mutants")
    (out / "layouts").mkdir(parents=True, exist_ok=True)
    labels = []
    for name, (floor, lay) in bases(args.bases.split(",") if args.bases else None).items():
        ms = mutate(floor, lay, name, per_op=args.per_op, seed=args.seed)
        for m in ms:
            (out / "layouts" / f"{m.id}.json").write_text(json.dumps(m.layout), encoding="utf-8")
            labels.append(m.label())
        kept = sum(m.keep for m in ms)
        print(f"{name}: {len(ms)} mutants, {kept} kept")
    with (out / "labels.jsonl").open("w", encoding="utf-8") as fh:
        for row in labels:
            fh.write(json.dumps(row) + "\n")
    print(f"wrote {len(labels)} labels to {out / 'labels.jsonl'}")
    return 0


def load_mutants(folder: Path, base_map: dict[str, tuple[Floor, dict[str, Any]]]):
    from mundus_eval.floorplan.mutations import Mutant
    ms = []
    for line in (folder / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        lb = json.loads(line)
        floor, _ = base_map[lb["base"]]
        if lb["extra_columns"]:
            floor = Floor(floor.rect, floor.core, floor.columns + [Column(**c) for c in lb["extra_columns"]], floor.name)
        lay = json.loads((folder / "layouts" / f"{lb['id']}.json").read_text(encoding="utf-8"))
        ms.append(Mutant(lb["id"], lb["base"], lb["op"], lb["intended"], lb["target"], lb["note"], lb["flipped"], lb["fixed"],
                         lb["keep"], floor, lay))
    return ms


def cmd_rulecheck(args) -> int:
    from mundus_eval.floorplan import rulecheck as R

    folder = Path(args.mutants or FP_DATA / "mutants")
    base_names = sorted({json.loads(x)["base"] for x in (folder / "labels.jsonl").read_text().splitlines()})
    ms = load_mutants(folder, bases(base_names))
    by_id = {m.id: m for m in ms}
    cases = R.build_cases(ms, {}, seed=args.seed)
    if args.rules:
        cases = [c for c in cases if c["rule"] in args.rules.split(",")]
    if args.sample and len(cases) > args.sample:
        cases = random.Random(args.seed).sample(cases, args.sample)
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out = FP_DATA / "rulecheck" / run_id
    out.mkdir(parents=True, exist_ok=True)
    print(f"{len(cases)} cases ({sum(c['truth'] == 'fail' for c in cases)} fail, {sum(c['truth'] == 'pass' for c in cases)} pass), "
          f"model {args.model}, writing {out}")

    def one(c):
        m = by_id[c["mutant"]]
        res = R.judge(c, m.floor, m.layout, args.model)
        return c | {"pred": res.get("status"), "judge": res, "model": args.model, "prompt_version": R.PROMPT_VERSION}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(one, cases))
    with (out / "results.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r) + "\n")
    summary = R.score(results) | {"_meta": {"model": args.model, "cases": len(cases), "prompt_version": R.PROMPT_VERSION,
                                            "git": _git_sha(), "mutants": str(folder)}}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"{'rule':28s} {'tp':>3} {'fn':>3} {'fp':>3} {'tn':>3}  recall  false-pass")
    for rule, d in summary.items():
        if rule.startswith("_"):
            continue
        print(f"{rule:28s} {d['tp']:3d} {d['fn']:3d} {d['fp']:3d} {d['tn']:3d}  {d['recall']!s:6}  {d['false_pass_rate']}")
    a = summary["_all"]
    print(f"all: accuracy {a['accuracy']}, false-pass rate {a['false_pass_rate']}, unusable answers {a['bad']}")
    return 0


def add_parser(sub) -> None:
    fp = sub.add_parser("floorplan", help="floor-plan evals: grade, mutate, rulecheck")
    s = fp.add_subparsers(dest="fp_cmd", required=True)
    g = s.add_parser("grade", help=f"grade layout JSONs with rubric {rubric.RUBRIC_VERSION}")
    g.add_argument("layouts", nargs="+", help="layout JSON paths, or 'synthetic'")
    g.add_argument("--shell", help=f"shell.json (default {shell_path()})")
    g.add_argument("--out")
    g.add_argument("-v", "--verbose", action="store_true")
    g.set_defaults(fn=cmd_grade)
    m = s.add_parser("mutate", help="build labelled mutants (eval C)")
    m.add_argument("--bases", help="comma-separated: synthetic, or seed names in eval/data/floorplan/seed/")
    m.add_argument("--per-op", type=int, default=10)
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--out")
    m.set_defaults(fn=cmd_mutate)
    r = s.add_parser("rulecheck", help="eval A: model judge against the labelled mutants")
    r.add_argument("--model", default="claude-haiku-5-5")
    r.add_argument("--mutants")
    r.add_argument("--rules")
    r.add_argument("--sample", type=int)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--workers", type=int, default=6)
    r.set_defaults(fn=cmd_rulecheck)
    from mundus_eval.floorplan.runs import add_parsers

    add_parsers(s)
