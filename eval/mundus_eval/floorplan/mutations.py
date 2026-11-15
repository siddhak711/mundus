"""Eval C: small edits to a good layout, each meant to break one rule. The label is never the intent: it is what the
independent checks say changed. A mutant is kept for its intended rule only if that rule actually flips; every other
flip is recorded as a collateral label. Neutral mutations (expected to change nothing) measure false fails.

Operators take (floor, layout dict, rng) and return (floor, layout dict, target, note) or None when not applicable.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Any, Callable

from shapely.geometry import Point, Polygon

from mundus_eval.floorplan import checks as C
from mundus_eval.floorplan.floor import Column, Floor
from mundus_eval.floorplan.layout import parse_layout

Op = Callable[[Floor, dict[str, Any], random.Random], "tuple[Floor, dict[str, Any], str, str] | None"]


# ----------------------------------------------------------------- helpers
def _facade_axis(floor: Floor, unit: dict[str, Any]) -> str:
    """'x' when the unit's glass runs along x (south/north band), else 'y'."""
    poly = Polygon(unit["poly"])
    x0, y0, x1, y1 = floor.rect
    minx, miny, maxx, maxy = poly.bounds
    along_x = (maxx - minx) * ((abs(miny - y0) < 0.1) + (abs(maxy - y1) < 0.1))
    along_y = (maxy - miny) * ((abs(minx - x0) < 0.1) + (abs(maxx - x1) < 0.1))
    return "x" if along_x >= along_y else "y"


def _glass_dir(floor: Floor, unit: dict[str, Any]) -> tuple[int, int]:
    """Unit vector pointing from the glass into the floor."""
    poly = Polygon(unit["poly"])
    x0, y0, x1, y1 = floor.rect
    minx, miny, maxx, maxy = poly.bounds
    cands = [((0, 1), abs(miny - y0)), ((0, -1), abs(maxy - y1)), ((1, 0), abs(minx - x0)), ((-1, 0), abs(maxx - x1))]
    return min(cands, key=lambda c: c[1])[0]


def _rooms(unit, t):
    return [r for r in unit["rooms"] if r["type"] == t]


def _pick(rng, seq):
    seq = list(seq)
    return rng.choice(seq) if seq else None


# ----------------------------------------------------------------- operators (intended rule in the name map below)
def bath_onto_column(floor, lay, rng):
    """Swap a unit's bath with the room a column stands in: the planner put the wet room on the column."""
    cands = []
    for u in lay["units"]:
        baths = _rooms(u, "bath")
        for c in floor.columns:
            for r in u["rooms"]:
                if r["type"] in ("kitchen", "living", "closet", "wardrobe") and baths and \
                        Polygon.from_bounds(*r["rect"]).intersection(c.square).area > 0.05:
                    cands.append((u, r, baths[0], c))
    pick = _pick(rng, cands)
    if not pick:
        return None
    u, r, b, c = pick
    r["type"], b["type"] = "bath", r["type"]
    return floor, lay, u["id"], f"bath swapped into the {b['type']} that holds {c.id}"


def shrink_bath(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "bath")])
    if not u:
        return None
    b = _pick(rng, _rooms(u, "bath"))
    x0, y0, x1, y1 = b["rect"]
    w = rng.choice([1.5, 1.4, 1.6])
    if x1 - x0 <= y1 - y0:
        b["rect"] = [x0, y0, x0 + w, y1]
    else:
        b["rect"] = [x0, y0, x1, y0 + w]
    return floor, lay, u["id"], f"bath narrowed to {w} m"


def move_sink_far(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if any(f["kind"] == "sink" for f in u.get("fixtures") or [])])
    if not u:
        return None
    gx, gy = _glass_dir(floor, u)
    dist = rng.choice([3.0, 4.0, 5.0])
    for f in u["fixtures"]:
        if f["kind"] == "sink":
            f["pos"] = [f["pos"][0] - gx * dist, f["pos"][1] - gy * dist]   # towards the glass = away from the core
    return floor, lay, u["id"], f"sink moved {dist} m towards the glass"


def narrow_entry(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "hall")])
    if not u:
        return None
    h = _rooms(u, "hall")[0]
    x0, y0, x1, y1 = h["rect"]
    w = rng.choice([1.0, 0.95, 1.05])
    h["rect"] = [x0, y0, x0 + w, y1] if x1 - x0 <= y1 - y0 else [x0, y0, x1, y0 + w]
    return floor, lay, u["id"], f"entry hall narrowed to {w} m"


def delete_stair_link(floor, lay, rng):
    if not lay.get("stair_links"):
        return None
    i = rng.randrange(len(lay["stair_links"]))
    del lay["stair_links"][i]
    return floor, lay, f"link{i + 1}", "stair link deleted"


def bedroom_off_glass(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "bed")])
    if not u:
        return None
    gx, gy = _glass_dir(floor, u)
    d = rng.choice([1.0, 1.2, 1.5])
    b = _rooms(u, "bed")[0]
    x0, y0, x1, y1 = b["rect"]
    b["rect"] = [x0 + gx * d, y0 + gy * d, x1 + gx * d, y1 + gy * d]
    return floor, lay, u["id"], f"bedroom moved {d} m off the glass"


def column_in_entry(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "hall")])
    if not u:
        return None
    x0, y0, x1, y1 = _rooms(u, "hall")[0]["rect"]
    size = rng.choice([0.45, 0.6, 0.75])
    floor = copy.deepcopy(floor)
    floor.columns.append(Column(f"M{len(floor.columns) + 1}", (x0 + x1) / 2, (y0 + y1) / 2, size, "probable"))
    return floor, lay, u["id"], f"{size} m column found in the entry hall"


def mirror_interior(floor, lay, rng):
    """Flip a unit's interior along the glass, so its bath leaves the shared wet wall."""
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "bath")])
    if not u:
        return None
    ax = _facade_axis(floor, u)
    minx, miny, maxx, maxy = Polygon(u["poly"]).bounds
    c = (minx + maxx) if ax == "x" else (miny + maxy)
    for r in u["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        r["rect"] = [c - x1, y0, c - x0, y1] if ax == "x" else [x0, c - y1, x1, c - y0]
    for f in u.get("fixtures") or []:
        f["pos"] = [c - f["pos"][0], f["pos"][1]] if ax == "x" else [f["pos"][0], c - f["pos"][1]]
    if u.get("door"):
        u["door"] = [c - u["door"][0], u["door"][1]] if ax == "x" else [u["door"][0], c - u["door"][1]]
    return floor, lay, u["id"], "interior mirrored along the glass"


def shrink_unit(floor, lay, rng):
    """Cut a one-bed below 500 sf by pulling its back wall towards the glass (rooms clipped)."""
    u = _pick(rng, [u for u in lay["units"] if "corner" not in str(u.get("type"))])
    if not u:
        return None
    gx, gy = _glass_dir(floor, u)
    poly = Polygon(u["poly"])
    minx, miny, maxx, maxy = poly.bounds
    width = (maxx - minx) if gy else (maxy - miny)
    depth = 460 / 10.7639 / width
    if gy == 1:
        maxy = miny + depth
    elif gy == -1:
        miny = maxy - depth
    elif gx == 1:
        maxx = minx + depth
    else:
        minx = maxx - depth
    u["poly"] = [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy]]
    keep = []
    for r in u["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        x0, y0, x1, y1 = max(x0, minx), max(y0, miny), min(x1, maxx), min(y1, maxy)
        if x1 - x0 > 0.3 and y1 - y0 > 0.3:
            keep.append({**r, "rect": [x0, y0, x1, y1]})
    u["rooms"] = keep
    return floor, lay, u["id"], "unit cut to about 460 sf"


def door_off_corridor(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if u.get("door")])
    if not u:
        return None
    gx, gy = _glass_dir(floor, u)
    poly = Polygon(u["poly"])
    minx, miny, maxx, maxy = poly.bounds
    d = u["door"]
    u["door"] = [d[0], miny if gy == 1 else maxy] if gy else [minx if gx == 1 else maxx, d[1]]
    return floor, lay, u["id"], "unit door moved to the glass wall"


# neutral: should change no rule
def nudge_partition(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if _rooms(u, "living") and _rooms(u, "bed")])
    if not u:
        return None
    ax = _facade_axis(floor, u)
    liv, bed = _rooms(u, "living")[0], _rooms(u, "bed")[0]
    i0, i1 = (0, 2) if ax == "x" else (1, 3)
    d = rng.choice([-0.05, 0.05])
    if abs(liv["rect"][i1] - bed["rect"][i0]) < 1e-3:
        liv["rect"][i1] += d
        bed["rect"][i0] += d
    elif abs(bed["rect"][i1] - liv["rect"][i0]) < 1e-3:
        bed["rect"][i1] += d
        liv["rect"][i0] += d
    else:
        return None
    return floor, lay, u["id"], f"bed/living partition moved {d:+.2f} m"


def nudge_fixture(floor, lay, rng):
    u = _pick(rng, [u for u in lay["units"] if u.get("fixtures")])
    if not u:
        return None
    f = _pick(rng, [f for f in u["fixtures"] if f["kind"] in ("dishwasher", "washer")])
    if not f:
        return None
    gx, gy = _glass_dir(floor, u)
    f["pos"] = [f["pos"][0] + 0.05 * gx, f["pos"][1] + 0.05 * gy]      # 5 cm towards the core
    return floor, lay, u["id"], f"{f['kind']} moved 5 cm towards the core"


OPERATORS: dict[str, tuple[Op, str | None]] = {
    "bath_onto_column": (bath_onto_column, "column_footprint"),
    "shrink_bath": (shrink_bath, "turning_circle"),
    "move_sink_far": (move_sink_far, "drain_runs"),
    "narrow_entry": (narrow_entry, "entry_width"),
    "delete_stair_link": (delete_stair_link, "stair_links"),
    "bedroom_off_glass": (bedroom_off_glass, "rooms_on_glass"),
    "column_in_entry": (column_in_entry, "entry_width"),
    "mirror_interior": (mirror_interior, "paired_wet_rooms"),
    "shrink_unit": (shrink_unit, "onebed_size"),
    "door_off_corridor": (door_off_corridor, "door_on_corridor"),
    "nudge_partition": (nudge_partition, None),
    "nudge_fixture": (nudge_fixture, None),
}


@dataclass
class Mutant:
    id: str
    base: str
    op: str
    intended: str | None
    target: str
    note: str
    flipped: list[str]           # "rule:subject" that went pass -> fail
    fixed: list[str]             # "rule:subject" that went fail -> pass (collateral)
    keep: bool
    floor: Floor
    layout: dict[str, Any]

    def label(self) -> dict[str, Any]:
        return {"id": self.id, "base": self.base, "op": self.op, "intended": self.intended, "target": self.target,
                "note": self.note, "flipped": self.flipped, "fixed": self.fixed, "keep": self.keep,
                "rules_failing": sorted({f.split(":")[0] for f in self.flipped}),
                "extra_columns": [c.__dict__ for c in self.floor.columns if c.id.startswith("M")]}


def _status(floor: Floor, layout: dict[str, Any]) -> dict[str, str]:
    return {f"{r.rule}:{r.subject}": r.status for r in C.run_checks(floor, parse_layout(layout))}


def mutate(floor: Floor, base: dict[str, Any], base_name: str, per_op: int = 10, seed: int = 0,
           ops: list[str] | None = None) -> list[Mutant]:
    before = _status(floor, base)
    out: list[Mutant] = []
    for name in ops or OPERATORS:
        fn, intended = OPERATORS[name]
        rng = random.Random(f"{seed}:{base_name}:{name}")
        seen = set()
        tries = 0
        while sum(m.op == name for m in out) < per_op and tries < per_op * 4:
            tries += 1
            res = fn(floor, copy.deepcopy(base), rng)
            if res is None:
                break
            f2, lay2, target, note = res
            key = (target, note)
            if key in seen:
                continue
            seen.add(key)
            after = _status(f2, lay2)
            flipped = sorted(k for k, v in after.items() if v == "fail" and before.get(k, "pass") == "pass")
            fixed = sorted(k for k, v in after.items() if v == "pass" and before.get(k) == "fail")
            rules = {k.split(":")[0] for k in flipped}
            keep = (intended in rules) if intended else not flipped
            mid = f"{base_name}-{name}-{len([m for m in out if m.op == name]) + 1:02d}"
            out.append(Mutant(mid, base_name, name, intended, target, note, flipped, fixed, keep, f2, lay2))
    return out


def point_in(p, poly) -> bool:
    return Polygon(poly).buffer(1e-6).contains(Point(p))
