"""Eval A: does a checker catch it? A model judge gets one rule, one subject and the layout data, and says pass or
fail. Truth is the independent check (checks.py). The costly error is a false pass: the rule is broken and the judge
says it holds. It is reported on its own.

Every judge call goes through mundus_harness.tracing.wrap_anthropic, so it is a LangSmith LLM run tagged with the rule,
the mutation operator and the case id.
"""
from __future__ import annotations

import json
import random
import re
from typing import Any

from mundus_eval.floorplan import checks as C
from mundus_eval.floorplan.floor import Floor
from mundus_eval.floorplan.layout import parse_layout
from mundus_eval.floorplan.mutations import Mutant

PROMPT_VERSION = "rulecheck-1"

RULE_TEXT = {
    "column_footprint": "Test the column's full square footprint (centre +/- size/2) against every room. Overlap above "
                        "0.02 m2 counts. It fails if it lands in a bath, entry hall, corridor, stair link or lobby, in a bedroom, or "
                        "in a living room or kitchen narrower than 3.0 m. Closets and wardrobes are allowed.",
    "room_minimums": "Every living room is at least 120 sf and every bedroom at least 70 sf, and both are at least 7 ft "
                     "(2.134 m) in their smaller dimension. 1 m2 = 10.7639 sf.",
    "rooms_on_glass": "Every bedroom and living room has at least 1 m of its outline on the outer wall of the floor.",
    "entry_width": "The entry hall's clear width is at least 1.07 m, after subtracting any column that stands in it.",
    "door_on_corridor": "The unit door lies on the unit's outline and within 0.15 m of the corridor, a stair link or a lobby.",
    "drain_runs": "Every wet fixture is at most 8.0 m from the core, measured as Manhattan distance (|dx| + |dy|) to the "
                  "nearest point of the core outline. Baths are measured from the bath's centre; sink, dishwasher and washer "
                  "from their positions. A kitchen with no sink position is measured from its farthest corner.",
    "turning_circle": "A 1.524 m (60 in) turning circle fits in the bath with a toilet (0.50 x 0.72 m, centreline 0.43 m "
                      "from a side wall), a lavatory (knee space may overlap the circle) and a 0.92 x 0.92 m shower or 1.524 "
                      "x 0.76 m tub placed against the walls. In mobility units (CBC 11B) the 1.525 x 1.42 m clearance in "
                      "front of the toilet must also be free of the shower and the lavatory. Columns in the bath are obstacles.",
    "paired_wet_rooms": "At least one bath in the unit shares at least 1.0 m of one straight wall with a bath in another unit.",
    "stair_separation": "The two stair doors are at least 1/3 of the floor's diagonal apart.",
    "travel_to_stair": "Travel from the farthest corner of the unit (Manhattan to the door) plus the shortest walk through "
                       "corridors, stair links and lobbies to the nearest stair door is at most 76.2 m (250 ft).",
    "onebed_size": "A one-bedroom unit (not a corner two-bed) is at least 500 sf.",
    "kitchen_run": "The kitchen's longer side is at least 2.4 m.",
    "chases": "The exhaust chase opening is at most 0.6 m and at least 0.6 m from any column.",
    "stair_links": "Each stair door is within 0.15 m of circulation; each stair link is an enclosed rated passage at least "
                   "1.12 m wide.",
    "circulation_clear_of_core": "Corridors, links, lobbies and units overlap the core by at most 0.02 m2 in total.",
}

SYSTEM = """You check one building-code rule on one apartment floor layout. Coordinates are metres. Rooms are axis-aligned
rectangles [x0, y0, x1, y1]. Work the geometry out from the numbers; do not trust any pass/fail flags, and do not assume
a rule holds because the layout looks tidy. Reply with one JSON object and nothing else:
{"status": "pass" | "fail", "value": <the number that decides it>, "reason": "<one sentence>"}"""


def _r(v):
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, (list, tuple)):
        return [_r(x) for x in v]
    if isinstance(v, dict):
        return {k: _r(x) for k, x in v.items()}
    return v


def context(floor: Floor, layout: dict[str, Any], rule: str, subject: str) -> dict[str, Any]:
    """What the judge sees: the floor, and the unit (or the whole circulation for floor rules). Generator flags removed."""
    core = [list(map(list, p.exterior.coords)) for p in getattr(floor.core, "geoms", [floor.core])]
    ctx: dict[str, Any] = {"floor_rect": list(floor.rect), "core_outlines": _r(core),
                           "columns": [{"id": c.id, "x": c.x, "y": c.y, "size": c.size} for c in floor.columns]}
    strip = {"checks", "column_overlaps", "wet_rooms_paired", "drain_runs_m", "drain_run_m", "egress_to_stair_m", "rent_mo", "sinks"}
    units = {u["id"]: {k: v for k, v in u.items() if k not in strip} for u in layout["units"]}
    if subject in units:
        ctx["unit"] = _r(units[subject])
        if rule == "paired_wet_rooms":
            ctx["other_units_baths"] = {k: [r for r in u["rooms"] if r["type"] == "bath"] for k, u in units.items() if k != subject}
    if rule in ("travel_to_stair", "door_on_corridor", "stair_links", "stair_separation", "circulation_clear_of_core"):
        ctx |= {"corridor": layout.get("corridor"), "stair_links": layout.get("stair_links"), "stairs": layout.get("stairs"),
                "lobbies": layout.get("lobbies")}
    if rule == "circulation_clear_of_core":
        ctx["units"] = _r([{"id": u["id"], "poly": u["poly"]} for u in layout["units"]])
    if rule == "column_footprint":
        ctx["column"] = next(c for c in ctx["columns"] if c["id"] == subject)
        ctx["units_near"] = _r([units[u["id"]] for u in layout["units"]
                                if parse_layout({"units": [u]}).units[0].poly.distance(next(
                                    c.square for c in floor.columns if c.id == subject)) < 0.05])
        ctx |= {"corridor": layout.get("corridor"), "stair_links": layout.get("stair_links"), "lobbies": layout.get("lobbies")}
    return ctx


def build_cases(mutants: list[Mutant], bases: dict[str, tuple[Floor, dict[str, Any]]], seed: int = 0) -> list[dict[str, Any]]:
    """Fail cases: the intended (rule, subject) of every kept mutant. Pass cases: the same rule on another subject of
    the same mutant that still passes, and one random passing rule per neutral mutant."""
    rng = random.Random(seed)
    cases = []
    for m in mutants:
        if not m.keep:
            continue
        status = {(r.rule, r.subject): r.status for r in C.run_checks(m.floor, parse_layout(m.layout))}
        if m.intended:
            fails = [k for k in m.flipped if k.startswith(m.intended + ":")]
            rule, subj = fails[0].split(":", 1)
            cases.append({"id": f"{m.id}/fail", "mutant": m.id, "op": m.op, "rule": rule, "subject": subj, "truth": "fail"})
            others = [s for (r, s), st in status.items() if r == rule and st == "pass"]
        else:
            others = [f"{r}:{s}" for (r, s), st in status.items() if st == "pass"]
            rule = None
        if others:
            pick = rng.choice(sorted(others))
            r_, s_ = (rule, pick) if rule else pick.split(":", 1)
            cases.append({"id": f"{m.id}/pass", "mutant": m.id, "op": m.op, "rule": r_, "subject": s_, "truth": "pass"})
    return cases


def parse_reply(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    st = str(d.get("status", "")).lower()
    return {"status": st if st in ("pass", "fail") else "unparsed", "value": d.get("value"), "reason": str(d.get("reason", ""))[:300]}


def judge(case: dict[str, Any], floor: Floor, layout: dict[str, Any], model: str, client: Any = None,
          max_tokens: int = 4000) -> dict[str, Any]:
    import anthropic
    from mundus_harness.tracing import wrap_anthropic

    client = client or wrap_anthropic(anthropic.Anthropic(), name="floorplan-judge")
    prompt = (f"RULE ({case['rule']}):\n{RULE_TEXT[case['rule']]}\n\nSUBJECT: {case['subject']}\n\nDATA:\n"
              f"{json.dumps(context(floor, layout, case['rule'], case['subject']), separators=(',', ':'))}")
    try:
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=SYSTEM,
                                      messages=[{"role": "user", "content": prompt}],
                                      **_trace_kwargs(case, model))
    except anthropic.APIError as e:
        return {"status": "error", "error": str(e)[:200]}
    text = "".join(b.text for b in resp.content if b.type == "text")
    out = parse_reply(text)
    out["tokens"] = {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
    return out


def _trace_kwargs(case: dict[str, Any], model: str) -> dict[str, Any]:
    """langsmith's wrapped client accepts langsmith_extra for run name, tags and metadata; a plain client does not."""
    return {"langsmith_extra": {"name": f"judge:{case['rule']}", "tags": ["floorplan", "eval-A", case["rule"], case["op"], model],
                                "metadata": {"case_id": case["id"], "truth": case["truth"], "prompt_version": PROMPT_VERSION}}} \
        if _wrapped() else {}


def _wrapped() -> bool:
    from mundus_harness.tracing import enable_tracing
    try:
        import langsmith  # noqa: F401
    except ImportError:
        return False
    return enable_tracing()


def score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per rule: precision and recall for catching a failure, and the false-pass rate (truth fail, judged pass)."""
    rules: dict[str, dict[str, int]] = {}
    for r in results:
        d = rules.setdefault(r["rule"], {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "bad": 0})
        pred = r["pred"]
        if pred not in ("pass", "fail"):
            d["bad"] += 1
            pred = "pass"            # an unusable answer catches nothing
        if r["truth"] == "fail":
            d["tp" if pred == "fail" else "fn"] += 1
        else:
            d["fp" if pred == "fail" else "tn"] += 1
    out = {}
    for rule, d in sorted(rules.items()):
        fails = d["tp"] + d["fn"]
        out[rule] = d | {"precision": round(d["tp"] / (d["tp"] + d["fp"]), 3) if d["tp"] + d["fp"] else None,
                         "recall": round(d["tp"] / fails, 3) if fails else None,
                         "false_pass_rate": round(d["fn"] / fails, 3) if fails else None}
    tot = {k: sum(d[k] for d in rules.values()) for k in ("tp", "fp", "fn", "tn", "bad")}
    fails = tot["tp"] + tot["fn"]
    out["_all"] = tot | {"accuracy": round((tot["tp"] + tot["tn"]) / max(1, sum(tot[k] for k in ("tp", "fp", "fn", "tn"))), 3),
                         "false_pass_rate": round(tot["fn"] / fails, 3) if fails else None}
    return out
