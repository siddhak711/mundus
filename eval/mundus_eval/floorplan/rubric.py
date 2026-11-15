"""Rubric v1.0, frozen. 14 criteria, 100 points, minus 5 per hard-rule break.

Weights and formulas are the v3/v4 rubric (the one the grader used from v3 on; see reviews/floor16-v3-review.md and
scripts/apartment_study_v4.py:score). Every input comes from checks.py or from geometry, never from the generator's
own flags or money block. Change anything here and RUBRIC_VERSION must change; old runs are rescored, not compared.

Criteria tagged "soft" rest on labels the JSON cannot prove (fire ratings written on walls). They are scored by code
from what the JSON declares, and are the place a model grader or a human should spot-check.
"""
from __future__ import annotations

import math
from typing import Any

from shapely.geometry import box
from shapely.ops import unary_union

from mundus_eval.floorplan import checks as C
from mundus_eval.floorplan.assumptions import ASSUMPTIONS
from mundus_eval.floorplan.floor import Floor
from mundus_eval.floorplan.layout import M2SF, Layout, parse_layout

RUBRIC_VERSION = "1.0"
CEILING = 92.0          # practical maximum on floor 16 under this money model (handoff 3c); report share of it

# Money model, frozen (grader's model from the v2 feedback on). Floor-16 inputs.
MONEY = dict(rent_icpt=974, rent_slope=3.34, premium=1.10, corner2bed=600, vacancy=0.05, opex=0.35, other=75,
             c_units=500, c_amenity=150, c_core=25, plumbing=1.0e6, linkage=16.76, linkage_sf=21178, acq=216,
             gross_sf=25667, need=0.0715, office_noi=0.68e6, fitout_per_unit=55000, fitout_base_units=22)

CRITERIA = [  # name, max, group, source
    ("LA zoning", 5, "compliance", "code"),
    ("Room size, daylight, escape", 7, "compliance", "code"),
    ("Exits and stairs", 8, "compliance", "code"),
    ("Accessibility", 8, "compliance", "code"),
    ("Fire, sound, ventilation", 7, "compliance", "soft"),
    ("No hard failures", 5, "compliance", "code"),
    ("Detected columns", 10, "structure", "code"),
    ("Hidden columns", 8, "structure", "code"),
    ("Drains to the core", 7, "structure", "code"),
    ("Loads and earthquake", 5, "structure", "code"),
    ("Buyer yield", 12, "money", "code"),
    ("Owner view vs office", 8, "money", "code"),
    ("Share of floor rented", 6, "money", "code"),
    ("Unit size vs market", 4, "money", "code"),
]
assert sum(m for _, m, _, _ in CRITERIA) == 100


def areas(floor: Floor, lay: Layout) -> dict[str, float]:
    gross = floor.gross_m2
    units = unary_union([u.poly for u in lay.units]) if lay.units else box(0, 0, 0, 0)
    circ = lay.circulation.difference(floor.core) if not lay.circulation.is_empty else box(0, 0, 0, 0)
    storage = floor.outline.difference(units).difference(circ).difference(floor.core)
    return dict(gross_sf=gross * M2SF, core_sf=floor.core.area * M2SF, units_sf=units.area * M2SF,
                circulation_sf=circ.area * M2SF, storage_sf=storage.area * M2SF,
                efficiency=units.area / max(1e-9, gross - floor.core.area))


def money(lay: Layout, A: dict[str, float], with_fitout: bool = False) -> dict[str, float]:
    G = MONEY
    rents = [(G["rent_icpt"] + G["rent_slope"] * round(u.sf)) * G["premium"] + (G["corner2bed"] if u.corner else 0)
             for u in lay.units]
    n = len(rents)
    noi = 12 * (sum(rents) + n * G["other"]) * (1 - G["vacancy"]) * (1 - G["opex"])
    build = G["c_units"] * (A["units_sf"] + A["circulation_sf"]) + G["c_amenity"] * A["storage_sf"] + \
        G["c_core"] * A["core_sf"] + G["plumbing"]
    fit = G["fitout_per_unit"] * max(0, n - G["fitout_base_units"]) if with_fitout else 0.0
    owner = build + G["linkage"] * G["linkage_sf"] + fit
    buyer = owner + G["acq"] * G["gross_sf"]
    gap = noi - G["office_noi"] - (G["need"] * fit if with_fitout else 0.0)
    return dict(units=n, noi=noi, owner_cost=owner, buyer_cost=buyer, yoc_buyer=noi / buyer if buyer else 0.0,
                yoc_owner=noi / owner if owner else 0.0, vs_office=gap,
                owner_points=8.0 if gap >= 0 else max(0.0, 5 + 20 * gap / 1e6))


def _share(rows: list[C.CheckResult]) -> float:
    return sum(r.status == "pass" for r in rows) / len(rows) if rows else 0.0


def grade_layout(floor: Floor, layout: Layout | dict[str, Any]) -> dict[str, Any]:
    lay = layout if isinstance(layout, Layout) else parse_layout(layout)
    if not lay.units:
        return {"rubric_version": RUBRIC_VERSION, "total": 0.0, "criteria": {}, "hard_breaks": [], "error": "no units"}
    rows = C.run_checks(floor, lay)
    by = {}
    for r in rows:
        by.setdefault(r.rule, []).append(r)
    n = len(lay.units)
    A = areas(floor, lay)
    M = money(lay, A)
    S: dict[str, tuple[float, str]] = {}

    S["LA zoning"] = (5.0 if n >= 5 else 0.0, f"{n} units")

    rooms_ok = sum(1 for u in lay.units if all(r.status == "pass" for r in by["room_minimums"] + by["rooms_on_glass"]
                                               if r.subject == u.id)) / n
    S["Room size, daylight, escape"] = (7 * rooms_ok, f"{rooms_ok:.0%} of units pass room minimums and on-glass")

    worst = max((r.value or math.inf) if r.status != "unknown" else math.inf for r in by["travel_to_stair"])
    sep_ok = all(r.status == "pass" for r in by["stair_separation"])
    loop = any(len(p.interiors) > 0 for p in getattr(lay.corridor, "geoms", [lay.corridor])) if not lay.corridor.is_empty else False
    links_ok = all(r.status == "pass" for r in by["stair_links"])
    ex = (2 if worst <= C.LIMITS["travel_m"] else 0) + (2 if sep_ok else 0) + (1 if loop else 0) + \
        2 * min(1, len(lay.lobbies) / 2) + (1 if links_ok else 0)
    S["Exits and stairs"] = (float(ex), f"worst travel {worst:.1f} m; separation {'ok' if sep_ok else 'FAIL'}; "
                             f"loop {loop}; lobbies {len(lay.lobbies)}; links {'ok' if links_ok else 'FAIL/none'}")

    nm, nh = math.ceil(0.11 * n), math.ceil(0.04 * n)
    mob = [u for u in lay.units if (u.access or "") == "mobility"]
    hv = [u for u in lay.units if (u.access or "") == "hearing/vision"]
    tc = {r.subject: r for r in by["turning_circle"]}
    bath_ok = _share(by["turning_circle"])
    kit_ok = _share(by["kitchen_run"])
    col_in_mob_bath = [c.subject for c in by["column_footprint"] for h in c.objects["hits"]
                       if h[1] == "bath" and h[2] > C.OVERLAP_TOL and h[0] in {u.id for u in mob}]
    mob_ok = len(mob) >= nm and len(hv) >= nh and not col_in_mob_bath and all(tc[u.id].status == "pass" for u in mob)
    S["Accessibility"] = (3 * bath_ok + 2 * kit_ok + (3 if mob_ok else 0),
                          f"baths {bath_ok:.0%} (fixtures placed; 11B in mobility units), kitchens {kit_ok:.0%}; "
                          f"{len(mob)}/{nm} mobility, {len(hv)}/{nh} hearing/vision; mobility baths clear and 11B: {mob_ok}")

    pairs = _share(by["paired_wet_rooms"])
    ch_ok = _share(by["chases"]) if by["chases"] else 0.0
    S["Fire, sound, ventilation"] = (2 + 2 + 2 * ch_ok + 1 * pairs,
                                     f"demising and corridor ratings assumed labelled (soft); chases {ch_ok:.0%}; paired {pairs:.0%}")

    hard = [f"{r.rule}:{r.subject}" for r in rows if r.hard]
    S["No hard failures"] = (5.0 if not hard else 0.0, f"{len(hard)} breaks")

    cf = {r.subject: r for r in by["column_footprint"]}
    det = [c for c in floor.columns if c.kind != "hidden"]
    hid = [c for c in floor.columns if c.kind == "hidden"]
    det_ok = sum(cf[c.id].status == "pass" for c in det) / len(det) if det else 1.0
    hid_ok = sum(cf[c.id].status == "pass" for c in hid) / len(hid) if hid else 1.0
    S["Detected columns"] = (10 * det_ok, f"{det_ok:.0%} of {len(det)} pass the footprint test")
    S["Hidden columns"] = (8 * hid_ok, f"{hid_ok:.0%} of {len(hid)} pass the footprint test")

    dr = _share(by["drain_runs"])
    S["Drains to the core"] = (5 * dr + 2 * pairs, f"{dr:.0%} of units have every wet fixture <= 8 m; paired {pairs:.0%}")
    S["Loads and earthquake"] = (5 * ch_ok, f"chases {ch_ok:.0%} clear of columns")

    S["Buyer yield"] = (12 * min(1, M["yoc_buyer"] / MONEY["need"]), f"{M['yoc_buyer']:.2%} vs {MONEY['need']:.2%}")
    S["Owner view vs office"] = (M["owner_points"], f"NOI ${M['noi'] / 1e6:.3f}M vs office ${MONEY['office_noi'] / 1e6:.3f}M")
    S["Share of floor rented"] = (6 * min(1, A["efficiency"] / 0.80), f"{A['efficiency']:.1%}")

    ones = [u for u in lay.units if not u.corner]
    avg = sum(u.sf for u in lay.units) / n
    out_band = max(0, avg - 700, 500 - avg)
    base = 4 if all(u.sf >= 450 for u in ones) else 3
    S["Unit size vs market"] = (max(0.0, base - 0.5 * math.ceil(out_band / 50)), f"average {avg:.0f} sf")

    crit = {name: {"points": round(S[name][0], 2), "max": mx, "group": grp, "source": src, "measured": S[name][1]}
            for name, mx, grp, src in CRITERIA}
    total = sum(v["points"] for v in crit.values()) - 5 * len(hard)
    groups = {g: round(sum(v["points"] for v in crit.values() if v["group"] == g), 2) for g in ("compliance", "structure", "money")}
    return {"rubric_version": RUBRIC_VERSION, "total": round(total, 2), "share_of_ceiling": round(total / CEILING, 3),
            "groups": groups, "criteria": crit, "hard_breaks": hard, "units": n, "areas": {k: round(v, 3) for k, v in A.items()},
            "money": {k: round(v, 4) for k, v in M.items()}, "money_with_fitout": {k: round(v, 4) for k, v in money(lay, A, True).items()},
            "checks": [r.row() for r in rows], "assumptions": [a["id"] for a in ASSUMPTIONS]}


def claimed_self_score(layout: dict[str, Any]) -> dict[str, float] | None:
    """The generator's self-score per criterion, if it wrote one (v2 and later)."""
    ss = (layout.get("self_score") or {}).get("items")
    if not ss:
        return None
    return {k: float(v["points"]) for k, v in ss.items()} | {"_total": float(layout["self_score"]["total"])}


def calibration_gap(grade: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any] | None:
    """Eval B: |self-score - grade| per criterion and in total."""
    claimed = claimed_self_score(layout)
    if claimed is None:
        return None
    per = {k: round(claimed.get(k, 0.0) - v["points"], 2) for k, v in grade["criteria"].items()}
    return {"total_gap": round(claimed["_total"] - grade["total"], 2), "per_criterion": per,
            "max_over": max(per.values()), "pass": abs(claimed["_total"] - grade["total"]) <= 2 and max(per.values()) <= 1}
