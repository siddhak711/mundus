"""Fixture library and the turning-circle test with fixtures placed.

The v4 generator fitted the 1.5 m circle into the empty bath rectangle. That passes rooms that fail once a toilet and a
shower are in them. Here the grader places the fixtures itself, tries every reasonable arrangement against the walls,
and takes the best one: a bath passes only if some real arrangement leaves the circle clear.

Dimensions (metres) are the CBC 11B minimums, rounded up to real products. Confidence: moderate; check against the
11B-603/604/608 figures before treating a marginal result as final.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product

import shapely
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

TURN_D = 1.524          # 60 in turning circle (11B-304.3.1)
WC_CL = (1.525, 1.42)   # clearance around the water closet: 60 in along the wall, 56 in out from it (11B-604.3.1)
WC_CENTRE = 0.43        # toilet centreline 16-18 in from the side wall (11B-604.2): use 17 in


@dataclass(frozen=True)
class FixtureSpec:
    kind: str
    w: float            # along the wall
    d: float            # out from the wall
    obstructs: bool     # False: the turning space may overlap it (knee and toe space under a lavatory, 11B-304.3)


TOILET = FixtureSpec("toilet", 0.50, 0.72, True)
LAVATORY = FixtureSpec("lavatory", 0.55, 0.48, False)
SHOWER_TRANSFER = FixtureSpec("shower", 0.92, 0.92, True)   # 36 x 36 in transfer shower
TUB = FixtureSpec("tub", 1.524, 0.76, True)                  # 60 x 30 in
LIBRARY = {f.kind: f for f in (TOILET, LAVATORY, SHOWER_TRANSFER, TUB)}


def _against(r: tuple[float, float, float, float], wall: str, t: float, spec: FixtureSpec) -> Polygon:
    """Fixture rectangle with its back on `wall` (S, N, W, E), starting at offset t along the wall."""
    x0, y0, x1, y1 = r
    if wall == "S":
        return box(x0 + t, y0, x0 + t + spec.w, y0 + spec.d)
    if wall == "N":
        return box(x0 + t, y1 - spec.d, x0 + t + spec.w, y1)
    if wall == "W":
        return box(x0, y0 + t, x0 + spec.d, y0 + t + spec.w)
    return box(x1 - spec.d, y0 + t, x1, y0 + t + spec.w)


def _wall_len(r, wall):
    return (r[2] - r[0]) if wall in "SN" else (r[3] - r[1])


def arrangements(rect: tuple[float, float, float, float], bathing: FixtureSpec = SHOWER_TRANSFER, strict: bool = True):
    """Yield fixture placements: bathing fixture at a wall end, toilet with its centreline 17 in from a side wall,
    lavatory at a wall end or centre. Fixtures must fit and not overlap. strict (11B): the 60 x 56 in clearance around
    the toilet must fit in the room and overlap no other fixture."""
    room = box(*rect).buffer(1e-6)
    walls = "SNWE"
    for wb, wt, wl in product(walls, walls, walls):
        for tb, tt, tl in product(("lo", "hi"), ("lo", "hi"), ("lo", "mid", "hi")):
            def at(wall, where, spec, off=0.0):
                n = _wall_len(rect, wall) - spec.w
                if n < -1e-9:
                    return None
                return _against(rect, wall, {"lo": off, "mid": n / 2, "hi": n - off}[where], spec)
            off = WC_CENTRE - TOILET.w / 2
            b, t, lav = at(wb, tb, bathing), at(wt, tt, TOILET, off), at(wl, tl, LAVATORY)
            if b is None or t is None or lav is None:
                continue
            shapes = [b, t, lav]
            if any(not room.contains(s) for s in shapes):
                continue
            if any(shapes[i].intersection(shapes[j]).area > 1e-6 for i in range(3) for j in range(i + 1, 3)):
                continue
            out = {"shower" if bathing.kind == "shower" else bathing.kind: b, "toilet": t, "lavatory": lav}
            if strict:
                spec = FixtureSpec("wc_clearance", WC_CL[0], WC_CL[1], False)
                cl = at(wt, tt, spec)               # starts at the same side wall as the toilet
                if cl is None or not room.contains(cl) or cl.intersection(b).area > 1e-6 or cl.intersection(lav).area > 1e-6:
                    continue
                out["wc_clearance"] = cl
            yield out


def turning_circle(rect: tuple[float, float, float, float], with_fixtures: bool = True,
                   obstacles: list[Polygon] | None = None, strict: bool = True) -> dict:
    """Largest clear circle in the bath. with_fixtures=False reproduces the generator's empty-rectangle test.
    strict=True applies the 11B toilet clearance (mobility units); strict=False is the 11A adaptable case."""
    if not obstacles:
        w, d = round(rect[2] - rect[0], 3), round(rect[3] - rect[1], 3)
        res = dict(_cached(w, d, with_fixtures, strict))
        if res.get("arrangement"):
            res["arrangement"] = {k: [round(v + (rect[0] if i % 2 == 0 else rect[1]), 3) for i, v in enumerate(b)]
                                  for k, b in res["arrangement"].items()}
        return res
    return _turning(rect, with_fixtures, obstacles, strict)


@lru_cache(maxsize=512)
def _cached(w: float, d: float, with_fixtures: bool, strict: bool) -> tuple:
    return tuple(_turning((0.0, 0.0, w, d), with_fixtures, None, strict).items())


def _turning(rect, with_fixtures, obstacles, strict) -> dict:
    room = box(*rect)
    extra = unary_union(obstacles) if obstacles else None
    if not with_fixtures:
        free = room.difference(extra) if extra is not None else room
        d = _inscribed_d(free)
        return {"diameter_m": round(d, 3), "pass": d >= TURN_D - 1e-6, "mode": "empty", "arrangement": None}
    best = (0.0, None)
    for bathing in (SHOWER_TRANSFER, TUB):
        for arr in arrangements(rect, bathing, strict):
            blocked = [g for k, g in arr.items() if k in LIBRARY and LIBRARY[k].obstructs]
            if extra is not None:
                blocked.append(extra)
            free = room.difference(unary_union(blocked))
            d = _inscribed_d(free)
            if d > best[0]:
                best = (d, {k: [round(v, 3) for v in g.bounds] for k, g in arr.items()})
    d, arr = best
    return {"diameter_m": round(d, 3), "pass": d >= TURN_D - 1e-6, "mode": "fixtures", "arrangement": arr}


def _inscribed_d(geom) -> float:
    if geom.is_empty:
        return 0.0
    parts = list(getattr(geom, "geoms", [geom]))
    best = 0.0
    for p in parts:
        if p.area < 1e-6:
            continue
        line = shapely.maximum_inscribed_circle(p, tolerance=0.005)
        best = max(best, 2 * line.length)
    return best
