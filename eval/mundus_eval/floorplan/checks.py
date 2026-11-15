"""Independent geometric checks. Each takes (floor, layout) and returns CheckResult rows. Nothing here reads a flag the
generator wrote; every value is recomputed from shapes.

Rule ids are stable: eval A and the mutation labels key on them.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Point, box
from shapely.ops import unary_union

from mundus_eval.floorplan.fixtures import TURN_D, turning_circle
from mundus_eval.floorplan.floor import Floor
from mundus_eval.floorplan.layout import Layout

FT = 0.3048
OVERLAP_TOL = 0.02                 # m2 of a column footprint that counts as "in" a room
FORBIDDEN_ROOMS = {"bath", "hall"}  # a column here is a hard-rule break
ALLOWED_ROOMS = {"living", "kitchen", "closet", "wardrobe"}
LIMITS = dict(entry_m=1.07, door_m=0.91, living_sf=120, bed_sf=70, room_min_m=7 * FT, kitchen_run_m=2.4,
              onebed_sf=500, drain_m=8.0, travel_m=250 * FT, stair_sep_frac=1 / 3, pair_wall_m=1.0,
              chase_max_m=0.6, chase_clear_m=0.6, link_width_m=1.12, glass_tol_m=0.05, door_corridor_tol_m=0.15)

RULES = ["column_footprint", "room_minimums", "rooms_on_glass", "entry_width", "door_on_corridor", "drain_runs",
         "turning_circle", "paired_wet_rooms", "stair_separation", "travel_to_stair", "onebed_size", "kitchen_run",
         "chases", "stair_links", "circulation_clear_of_core"]


@dataclass
class CheckResult:
    rule: str
    subject: str                  # unit id, column id or "floor"
    status: str                   # pass | fail | unknown
    value: Any = None
    threshold: Any = None
    detail: str = ""
    hard: bool = False            # a hard-rule break (costs 5 points and zeroes "No hard failures")
    objects: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        return asdict(self)


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


# ----------------------------------------------------------------- columns
def column_footprint(floor: Floor, lay: Layout) -> list[CheckResult]:
    """Every column's full square against every room, the corridor, stair links and lobbies. A centre-point test is
    the v2 shortcut; the footprint is what matters (C15 put 0.38 m2 into a mobility bath while its centre sat on a wall)."""
    circ = {"corridor": lay.corridor, "stair link": unary_union([box(*s["rect"]) for s in lay.stair_links]),
            "elevator lobby": unary_union([box(*lb["rect"]) for lb in lay.lobbies])}
    out = []
    for c in floor.columns:
        sq = c.square
        hits = []
        for u in lay.units:
            if not u.poly.buffer(0.01).intersects(sq):
                continue
            for r in u.rooms:
                a = r.geom.intersection(sq).area
                if a > 0.0005:
                    hits.append((u.id, r.type, a, r.min_dim))
        for name, g in circ.items():
            a = g.intersection(sq).area if not g.is_empty else 0.0
            if a > 0.0005:
                hits.append(("-", name, a, 0.0))
        counted = [h for h in hits if h[2] > OVERLAP_TOL]
        hard = any(t in FORBIDDEN_ROOMS or t in circ for _, t, _, _ in counted)
        ok = all(t in ALLOWED_ROOMS and (t not in ("living", "kitchen") or mn >= 3.0 - 1e-6) for _, t, _, mn in counted)
        where = "; ".join(f"{uid} {t} {a:.2f} m2" for uid, t, a, _ in hits) or "clear of units"
        out.append(CheckResult("column_footprint", c.id, "pass" if ok else "fail", _r(max([h[2] for h in counted] or [0]), 3),
                               OVERLAP_TOL, where, hard=hard, objects={"kind": c.kind, "hits": [h[:3] for h in hits]}))
    return out


# ----------------------------------------------------------------- rooms
def room_minimums(floor: Floor, lay: Layout) -> list[CheckResult]:
    out = []
    for u in lay.units:
        bad = []
        for r in u.rooms_of("living"):
            if r.sf < LIMITS["living_sf"] or r.min_dim < LIMITS["room_min_m"]:
                bad.append(f"living {r.sf:.0f} sf / {r.min_dim:.2f} m")
        for r in u.rooms_of("bed"):
            if r.sf < LIMITS["bed_sf"] or r.min_dim < LIMITS["room_min_m"]:
                bad.append(f"bed {r.sf:.0f} sf / {r.min_dim:.2f} m")
        if not u.rooms_of("living") or not u.rooms_of("bed"):
            bad.append("missing a living room or bedroom")
        out.append(CheckResult("room_minimums", u.id, "fail" if bad else "pass", "; ".join(bad) or "ok",
                               "living >= 120 sf, bed >= 70 sf, both >= 7 ft", hard=bool(bad)))
    return out


def rooms_on_glass(floor: Floor, lay: Layout) -> list[CheckResult]:
    edge = floor.outline.exterior
    out = []
    for u in lay.units:
        band = edge.buffer(LIMITS["glass_tol_m"])
        off = [f"{r.type} {r.geom.distance(edge):.2f} m from the glass" for r in u.rooms if r.type in ("bed", "living")
               and r.geom.exterior.intersection(band).length < 1.0]
        out.append(CheckResult("rooms_on_glass", u.id, "fail" if off else "pass", "; ".join(off) or "all on the glass",
                               "every bedroom and living room has >= 1 m on the outer wall", hard=bool(off)))
    return out


def entry_width(floor: Floor, lay: Layout) -> list[CheckResult]:
    out = []
    for u in lay.units:
        halls = u.rooms_of("hall")
        if not halls:
            out.append(CheckResult("entry_width", u.id, "fail", None, LIMITS["entry_m"], "no entry hall", hard=True))
            continue
        w = min(h.min_dim for h in halls)
        # a column in the hall narrows the clear width (v1: a 0.75 m column blocked N8's 1.05 m entry)
        for c in floor.columns:
            for h in halls:
                inter = h.geom.intersection(c.square)
                if inter.area > OVERLAP_TOL:
                    w = min(w, h.min_dim - min(inter.bounds[2] - inter.bounds[0], inter.bounds[3] - inter.bounds[1]))
        ok = w >= LIMITS["entry_m"] - 1e-6
        out.append(CheckResult("entry_width", u.id, "pass" if ok else "fail", _r(w), LIMITS["entry_m"], hard=not ok))
    return out


def door_on_corridor(floor: Floor, lay: Layout) -> list[CheckResult]:
    out = []
    for u in lay.units:
        if u.door is None:
            out.append(CheckResult("door_on_corridor", u.id, "fail", None, None, "no door"))
            continue
        d = Point(u.door).distance(lay.circulation) if not lay.circulation.is_empty else math.inf
        ok = d <= LIMITS["door_corridor_tol_m"] and Point(u.door).distance(u.poly.exterior) <= LIMITS["door_corridor_tol_m"]
        out.append(CheckResult("door_on_corridor", u.id, "pass" if ok else "fail", _r(d), LIMITS["door_corridor_tol_m"],
                               "door on the unit wall and touching circulation"))
    return out


def onebed_size(floor: Floor, lay: Layout) -> list[CheckResult]:
    return [CheckResult("onebed_size", u.id, "pass" if (u.corner or u.sf >= LIMITS["onebed_sf"] - 0.5) else "fail",
                        round(u.sf), LIMITS["onebed_sf"]) for u in lay.units]


def kitchen_run(floor: Floor, lay: Layout) -> list[CheckResult]:
    out = []
    for u in lay.units:
        k = u.rooms_of("kitchen")
        run = max((max(r.w, r.d) for r in k), default=0.0)
        out.append(CheckResult("kitchen_run", u.id, "pass" if run >= LIMITS["kitchen_run_m"] - 1e-6 else "fail", _r(run),
                               LIMITS["kitchen_run_m"]))
    return out


# ----------------------------------------------------------------- wet rooms
def _core_dist(floor: Floor, p: tuple[float, float]) -> float:
    """Manhattan distance to the nearest point of the core boundary (drains run along the joists, then across)."""
    samples = _core_samples(floor)
    return float(np.min(np.abs(samples[:, 0] - p[0]) + np.abs(samples[:, 1] - p[1])))


_SAMPLES: dict[int, np.ndarray] = {}


def _core_samples(floor: Floor, step: float = 0.05) -> np.ndarray:
    key = id(floor.core)
    if key not in _SAMPLES:
        pts = []
        for poly in getattr(floor.core, "geoms", [floor.core]):
            ring = poly.exterior
            n = max(2, int(ring.length / step))
            pts += [ring.interpolate(i / n, normalized=True).coords[0] for i in range(n)]
        _SAMPLES[key] = np.array(pts)
    return _SAMPLES[key]


def drain_runs(floor: Floor, lay: Layout) -> list[CheckResult]:
    """Every wet group: each bath from its centre, and every kitchen and laundry fixture at its declared position.
    A kitchen without a declared sink is measured from its far corner (worst case), so leaving fixtures out never helps."""
    out = []
    for u in lay.units:
        runs: dict[str, float] = {}
        for i, b in enumerate(u.rooms_of("bath")):
            runs[f"bath{i + 1}"] = _core_dist(floor, b.geom.centroid.coords[0])
        declared = {f.kind: f.pos for f in u.fixtures if not f.kind.startswith("bath")}
        for k in ("sink", "dishwasher", "washer"):
            if k in declared:
                runs[k] = _core_dist(floor, declared[k])
        if "sink" not in declared:
            for r in u.rooms_of("kitchen"):
                x0, y0, x1, y1 = r.rect
                runs["kitchen (no sink declared, far corner)"] = max(_core_dist(floor, (x, y)) for x in (x0, x1) for y in (y0, y1))
        worst = max(runs.values()) if runs else math.inf
        ok = worst <= LIMITS["drain_m"] + 1e-6
        out.append(CheckResult("drain_runs", u.id, "pass" if ok else "fail", _r(worst), LIMITS["drain_m"],
                               ", ".join(f"{k} {v:.1f}" for k, v in runs.items()), objects={"runs": {k: _r(v) for k, v in runs.items()}}))
    return out


def turning_circle_check(floor: Floor, lay: Layout) -> list[CheckResult]:
    """Mobility units: 11B, fixtures placed, toilet clearance kept clear. Other units: 11A, fixtures placed.
    Columns inside the bath are obstacles too."""
    out = []
    for u in lay.units:
        strict = (u.access or "") == "mobility"
        worst = None
        for b in u.rooms_of("bath"):
            obst = [c.square.intersection(b.geom) for c in floor.columns if c.square.intersection(b.geom).area > 1e-4]
            res = turning_circle(b.rect, True, obst or None, strict=strict)
            if worst is None or res["diameter_m"] < worst["diameter_m"]:
                worst = res
        if worst is None:
            out.append(CheckResult("turning_circle", u.id, "fail", 0, TURN_D, "no bath"))
            continue
        out.append(CheckResult("turning_circle", u.id, "pass" if worst["pass"] else "fail", worst["diameter_m"], TURN_D,
                               f"{'11B' if strict else '11A'} with fixtures placed", objects={"arrangement": worst["arrangement"],
                                                                                              "standard": "11B" if strict else "11A"}))
    return out


def paired_wet_rooms(floor: Floor, lay: Layout) -> list[CheckResult]:
    """A bath is paired when it shares >= 1 m of one straight wall with another unit's bath. Touching at a corner, or
    front-to-back with an offset, is not a shared wet wall (the v3 shortcut counted both)."""
    baths = [(u.id, b.geom) for u in lay.units for b in u.rooms_of("bath")]
    out = []
    for u in lay.units:
        best = 0.0
        for b in u.rooms_of("bath"):
            for uid, g in baths:
                if uid == u.id:
                    continue
                shared = b.geom.exterior.intersection(g.buffer(0.01))   # 1 cm snap: coordinates are rounded
                best = max(best, _straight_length(shared))
        ok = best >= LIMITS["pair_wall_m"] - 1e-6
        out.append(CheckResult("paired_wet_rooms", u.id, "pass" if ok else "fail", _r(best), LIMITS["pair_wall_m"]))
    return out


def _straight_length(g) -> float:
    """Longest connected run of shared wall (corner touches and points count zero)."""
    lines = [p for p in getattr(g, "geoms", [g]) if p.geom_type in ("LineString", "MultiLineString") and not p.is_empty]
    if not lines:
        return 0.0
    merged = shapely.line_merge(shapely.union_all(lines))
    return max(p.length for p in getattr(merged, "geoms", [merged]))


# ----------------------------------------------------------------- egress
def stair_separation(floor: Floor, lay: Layout) -> list[CheckResult]:
    doors = [tuple(s["door"]) for s in lay.stairs if s.get("door")]
    need = LIMITS["stair_sep_frac"] * floor.diagonal_m
    if len(doors) < 2:
        return [CheckResult("stair_separation", "floor", "fail", len(doors), need, "fewer than two stair doors", hard=True)]
    sep = max(math.dist(a, b) for a in doors for b in doors)
    return [CheckResult("stair_separation", "floor", "pass" if sep >= need - 1e-6 else "fail", _r(sep), _r(need),
                        "1/3 of the diagonal (sprinklered)")]


def travel_to_stair(floor: Floor, lay: Layout, res: float = 0.2) -> list[CheckResult]:
    """Walk inside the unit (Manhattan, door to its farthest corner) plus the shortest path through circulation to
    the nearest stair door. Storage and amenity space is not a path."""
    walk = lay.circulation
    doors = [tuple(s["door"]) for s in lay.stairs if s.get("door")]
    if walk.is_empty or not doors:
        return [CheckResult("travel_to_stair", u.id, "unknown", None, _r(LIMITS["travel_m"]), "no circulation or stairs")
                for u in lay.units]
    x0, y0, x1, y1 = floor.rect
    xs = np.arange(x0, x1, res) + res / 2
    ys = np.arange(y0, y1, res) + res / 2
    XX, YY = np.meshgrid(xs, ys)
    mask = shapely.contains_xy(walk.buffer(0.05), XX, YY)
    dist = _field(mask, [_cell(mask, d, floor.rect, res) for d in doors], res)
    out = []
    for u in lay.units:
        if u.door is None:
            out.append(CheckResult("travel_to_stair", u.id, "fail", None, _r(LIMITS["travel_m"]), "no door"))
            continue
        c = _cell(mask, u.door, floor.rect, res)
        inside = max(abs(px - u.door[0]) + abs(py - u.door[1]) for px, py in list(u.poly.exterior.coords))
        total = (float(dist[c]) if c is not None else math.inf) + inside
        ok = total <= LIMITS["travel_m"] + 1e-6
        out.append(CheckResult("travel_to_stair", u.id, "pass" if ok else "fail", _r(total, 1), _r(LIMITS["travel_m"], 1),
                               hard=not ok))
    return out


def _cell(mask, p, rect, res, reach=5):
    i, j = int((p[1] - rect[1]) / res), int((p[0] - rect[0]) / res)
    best, bd = None, 1e9
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            ii, jj = i + di, j + dj
            if 0 <= ii < mask.shape[0] and 0 <= jj < mask.shape[1] and mask[ii, jj] and abs(di) + abs(dj) < bd:
                best, bd = (ii, jj), abs(di) + abs(dj)
    return best


def _field(mask, sources, res):
    dist = np.full(mask.shape, np.inf)
    pq = []
    for s in sources:
        if s is not None:
            dist[s] = 0.0
            heapq.heappush(pq, (0.0, s))
    nb = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    while pq:
        d, (i, j) = heapq.heappop(pq)
        if d > dist[i, j]:
            continue
        for di, dj, w in nb:
            ii, jj = i + di, j + dj
            if 0 <= ii < mask.shape[0] and 0 <= jj < mask.shape[1] and mask[ii, jj] and d + w * res < dist[ii, jj]:
                dist[ii, jj] = d + w * res
                heapq.heappush(pq, (d + w * res, (ii, jj)))
    return dist


def stair_links(floor: Floor, lay: Layout) -> list[CheckResult]:
    """Every stair door opens onto circulation, and every link is an enclosed rated passage at least 1.12 m wide."""
    out = []
    circ = lay.circulation
    for s in lay.stairs:
        if not s.get("door"):
            continue
        d = Point(s["door"]).distance(circ) if not circ.is_empty else math.inf
        out.append(CheckResult("stair_links", str(s.get("name") or "stair"), "pass" if d <= LIMITS["door_corridor_tol_m"] else "fail",
                               _r(d), LIMITS["door_corridor_tol_m"], "stair door reaches circulation", hard=d > 1.0))
    for i, s in enumerate(lay.stair_links):
        x0, y0, x1, y1 = s["rect"]
        w = min(x1 - x0, y1 - y0)
        rated = "enclosed" in str(s.get("rating") or "")
        ok = w >= LIMITS["link_width_m"] - 1e-6 and rated
        out.append(CheckResult("stair_links", f"link{i + 1}", "pass" if ok else "fail", _r(w), LIMITS["link_width_m"],
                               f"rating: {s.get('rating') or 'none'}"))
    return out or [CheckResult("stair_links", "floor", "unknown", None, None, "no stairs drawn")]


def circulation_clear_of_core(floor: Floor, lay: Layout) -> list[CheckResult]:
    a = lay.circulation.intersection(floor.core).area if not lay.circulation.is_empty else 0.0
    units_in_core = sum(u.poly.intersection(floor.core).area for u in lay.units)
    ok = a <= 0.02 and units_in_core <= 0.02
    return [CheckResult("circulation_clear_of_core", "floor", "pass" if ok else "fail", _r(a + units_in_core, 3), 0.02,
                        f"circulation {a:.2f} m2, units {units_in_core:.2f} m2 inside the core", hard=units_in_core > 0.02)]


def chases(floor: Floor, lay: Layout) -> list[CheckResult]:
    out = []
    for u in lay.units:
        for i, ch in enumerate(u.chases):
            cb = box(*ch)
            near = min((cb.distance(c.square) for c in floor.columns), default=math.inf)
            size_ok = max(ch[2] - ch[0], ch[3] - ch[1]) <= LIMITS["chase_max_m"] + 1e-6
            ok = size_ok and near >= LIMITS["chase_clear_m"] - 1e-6
            out.append(CheckResult("chases", f"{u.id}/ch{i + 1}", "pass" if ok else "fail", _r(near), LIMITS["chase_clear_m"],
                                   "" if size_ok else "opening over 0.6 m"))
    return out


CHECKS = {
    "column_footprint": column_footprint, "room_minimums": room_minimums, "rooms_on_glass": rooms_on_glass,
    "entry_width": entry_width, "door_on_corridor": door_on_corridor, "drain_runs": drain_runs,
    "turning_circle": turning_circle_check, "paired_wet_rooms": paired_wet_rooms, "stair_separation": stair_separation,
    "travel_to_stair": travel_to_stair, "onebed_size": onebed_size, "kitchen_run": kitchen_run, "chases": chases,
    "stair_links": stair_links, "circulation_clear_of_core": circulation_clear_of_core,
}


def run_checks(floor: Floor, lay: Layout, rules: list[str] | None = None) -> list[CheckResult]:
    out: list[CheckResult] = []
    for name in rules or RULES:
        out += CHECKS[name](floor, lay)
    return out
