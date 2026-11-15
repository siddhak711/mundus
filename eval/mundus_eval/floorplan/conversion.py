"""Grade the merged conversion agent (harness/mundus_harness/conversion) on its own output.

The agent draws units as strips from the facade to a corridor along the core, with bedroom rectangles against the
glass, demising and corridor walls, and an entry point. It has no baths, kitchens or fixtures yet, so the profile
here (conversion-v0) scores only what that output supports. Every value is recomputed; the agent's own check report
and summary are kept only to measure how far its claims are from the grade.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from mundus_eval.floorplan import checks as C
from mundus_eval.floorplan.floor import FLOOR16_HIDDEN, HIDDEN_SIZE, Column, Floor
from mundus_eval.floorplan.layout import M2SF
from mundus_eval.floorplan.rubric import MONEY

PROFILE = "conversion-v2"   # v2 (frozen): 0.9 m passage, door reach 0.5 m, unscanned facade = unknown, bedroom-column > 0.1 m2. Change => new name, rescore
WALL_T = 0.15            # wall thickness used to test walls against columns
WINDOW_TOL = 0.5         # a bedroom edge within this of a detected window segment counts as on the glass
BED_COL_TOL = 0.10       # m2 of a column inside a bedroom that counts (a few cm graze is within the column guess)
DOOR_REACH = 0.5         # a door may open across up to this much leftover floor (same as the agent's checker)

CRITERIA = [  # name, max
    ("Walls clear of detected columns", 15),
    ("Walls clear of hidden columns", 10),
    ("Bedrooms clear of columns", 10),
    ("Bedrooms on windows", 15),
    ("Units inside the plate, clear of core and each other", 10),
    ("Unit size vs market", 10),
    ("Exit travel", 10),
    ("Buyer yield", 10),
    ("Owner view vs office", 5),
    ("Share of floor rented", 5),
]
assert sum(m for _, m in CRITERIA) == 100
NOT_SCORED = ["baths, kitchens and fixtures (drains, turning circle, paired wet rooms)", "entry and door widths",
              "stair separation and links", "fire, sound and ventilation", "chases"]


# ----------------------------------------------------------------- loading
def load_conversion_floor(folder: Path, hidden: bool = True) -> Floor:
    """Floor from floorprep output (geometry.json, structure.json). Columns are the mesh candidates, low confidence."""
    g = json.loads((folder / "geometry.json").read_text(encoding="utf-8"))
    s = json.loads((folder / "structure.json").read_text(encoding="utf-8"))
    x0, y0, x1, y1 = g["bbox_m"]
    core = unary_union([Polygon(b["polygon"]).buffer(0) for b in s.get("core") or []])
    cols = [Column(f"C{i + 1}", c["x"], c["y"], max(c.get("w_m", 0.6), c.get("d_m", 0.6)), "probable",
                   c.get("w_m"), c.get("d_m")) for i, c in enumerate(s.get("columns") or [])]
    if hidden:
        cols += [Column(f"H{i + 1}", x, y, HIDDEN_SIZE, "hidden") for i, (x, y) in enumerate(FLOOR16_HIDDEN)]
    f = Floor((x0, y0, x1, y1), core, cols, name=str(folder))
    f.windows = [LineString(w) for w in g.get("windows") or []]          # type: ignore[attr-defined]
    f.exits = [(e["x"], e["y"]) for e in s.get("exits") or []]           # type: ignore[attr-defined]
    f.plate = Polygon(g["outline"])                                       # type: ignore[attr-defined]
    f.unscanned = _unscanned(folder)                                      # type: ignore[attr-defined]
    return f


def _unscanned(folder: Path) -> Any:
    """Facade the scanner never saw (offices it did not enter), as geometry. Scan coverage is data, so this reuses the
    agent package's derivation of it; the checks themselves stay independent."""
    try:
        from mundus_harness.conversion.geometry import Floor as AgentFloor
        af = AgentFloor(folder.name, folder.parent)
        mask = af.unscanned_facade()
    except Exception:  # noqa: BLE001
        return Polygon()
    rr, cc = np.nonzero(mask)
    pts = [Point(*af.to_m(c, r)).buffer(1.0 / af.res) for r, c in zip(rr, cc, strict=True)]
    return unary_union(pts).buffer(0.1) if pts else Polygon()


def final_draft(run_data: Path, scan: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(final layout.json, the draft it was written from). The draft keeps bedrooms, entries and walls."""
    out = json.loads((run_data / scan / "layout.json").read_text(encoding="utf-8"))
    m = re.search(r"\((draft_\d+)\)", out.get("generated_by", ""))
    if not m:
        raise ValueError("layout.json does not name its draft")
    draft = json.loads((run_data / scan / "drafts" / f"{m.group(1)}.json").read_text(encoding="utf-8"))
    return out, draft


# ----------------------------------------------------------------- geometry
def _corridor(units: list[dict[str, Any]], corridor_m: float) -> Any:
    """Corridor band behind each unit: the unit's back edge pushed corridor_m further from the glass."""
    parts = []
    for u in units:
        q = [np.array(p, float) for p in u["polygon"]]
        if len(q) != 4:
            continue
        n = q[3] - q[0]
        d = float(np.linalg.norm(n))
        if d < 1e-6:
            continue
        n /= d
        parts.append(Polygon([q[3], q[2], q[2] + n * corridor_m, q[3] + n * corridor_m]))
    return unary_union(parts).buffer(0.05).buffer(-0.05) if parts else Polygon()


def _open_floor(floor: Floor, units_geom: Any) -> Any:
    """Open floor a person can walk: gaps narrower than 0.9 m (36 in, the minimum corridor) are removed."""
    plate = getattr(floor, "plate", floor.outline)
    free = plate.difference(units_geom).difference(floor.core).buffer(-0.45).buffer(0.45)     # 36 in minimum corridor
    return unary_union([free] + [Point(e).buffer(1.5) for e in getattr(floor, "exits", [])])


def _travel(floor: Floor, units_geom: Any, starts: list[tuple[float, float]], res: float = 0.25) -> list[float]:
    """Shortest walk over the open floor (the plate outside every unit and the core) to the nearest assumed exit.
    Exits are assumed at the core edge, so the zone reaches 1.5 m into the core around each one."""
    exits = getattr(floor, "exits", [])
    if not exits:
        return [math.inf] * len(starts)
    zone = _open_floor(floor, units_geom)
    x0, y0, x1, y1 = floor.rect
    xs = np.arange(x0, x1, res) + res / 2
    ys = np.arange(y0, y1, res) + res / 2
    XX, YY = np.meshgrid(xs, ys)
    mask = shapely.contains_xy(zone, XX, YY)
    dist = C._field(mask, [C._cell(mask, e, floor.rect, res, reach=8) for e in exits], res)
    out = []
    for p in starts:
        c = C._cell(mask, p, floor.rect, res, reach=4)
        out.append(float(dist[c]) if c is not None else math.inf)
    return out


# ----------------------------------------------------------------- grade
def grade_conversion(floor: Floor, draft: dict[str, Any], final: dict[str, Any] | None = None) -> dict[str, Any]:
    units = draft.get("units") or []
    if not units:
        return {"profile": PROFILE, "total": 0.0, "criteria": {}, "hard_breaks": ["no units"], "units": 0}
    polys = {u["id"]: Polygon(u["polygon"]) for u in units}
    walls = [(w, LineString([w["a"], w["b"]]).buffer(WALL_T / 2, cap_style="flat")) for w in draft.get("walls") or []]
    hard: list[str] = []
    rows: list[dict[str, Any]] = []

    def row(rule, subject, ok, value=None, detail="", is_hard=False):
        rows.append({"rule": rule, "subject": subject, "status": "pass" if ok else "fail", "value": value, "detail": detail})
        if is_hard and not ok:
            hard.append(f"{rule}:{subject}")

    # columns vs walls (priority 1 in the agent's own prompt: never a wall through a column) and vs bedrooms
    col_ok: dict[str, bool] = {}
    for c in floor.columns:
        sq = c.square
        hit = [w["kind"] for w, g in walls if g.intersection(sq).area > C.OVERLAP_TOL]
        # a hard break is a wall that cuts at least 10 cm into the column; a graze on its edge only loses points
        deep = [w["kind"] for w, _ in walls if not sq.buffer(-0.10).is_empty and
                LineString([w["a"], w["b"]]).intersects(sq.buffer(-0.10))]
        col_ok[c.id] = not hit
        row("wall_column", c.id, not hit, len(hit), ", ".join(hit) + (" (cuts in)" if deep else " (grazes edge)" if hit else ""),
            is_hard=bool(deep) and c.kind != "hidden")
    bed_hits = 0
    n_beds = 0
    for u in units:
        for i, b in enumerate(u.get("bedroom_polygons") or []):
            n_beds += 1
            bp = Polygon(b)
            over = [c.id for c in floor.columns if bp.intersection(c.square).area > BED_COL_TOL]
            bed_hits += bool(over)
            row("bedroom_column", f"{u['id']}/bed{i + 1}", not over, ",".join(over))
    # bedrooms on windows
    win = unary_union(getattr(floor, "windows", []) or [LineString()]).buffer(WINDOW_TOL)
    unseen = getattr(floor, "unscanned", Polygon()).buffer(WINDOW_TOL)
    unit_glass_ok = 0.0
    for u in units:
        beds = [Polygon(b) for b in u.get("bedroom_polygons") or []]
        seen = [b.exterior.intersection(win).length >= 1.0 for b in beds]
        maybe = [not s_ and not unseen.is_empty and b.exterior.intersection(unseen).length >= 1.0 for b, s_ in zip(beds, seen, strict=True)]
        if all(seen):
            unit_glass_ok += 1
            row("bedroom_window", u["id"], True, None, f"{len(beds)} bedrooms")
        elif all(s_ or m_ for s_, m_ in zip(seen, maybe, strict=True)):
            unit_glass_ok += 0.5            # unknown: the facade there was never scanned
            rows.append({"rule": "bedroom_window", "subject": u["id"], "status": "unknown", "value": None,
                         "detail": "bedroom faces facade the scan never saw"})
        else:
            row("bedroom_window", u["id"], False, None, "a bedroom has no window", is_hard=True)
    # inside the plate, clear of core and of each other
    plate = getattr(floor, "plate", floor.outline)
    clean = 0
    for u in units:
        p = polys[u["id"]]
        inside = p.intersection(plate).area / max(p.area, 1e-9)
        core = p.intersection(floor.core).area
        overlap = sum(p.intersection(polys[o]).area for o in polys if o != u["id"])
        ok = inside >= 0.97 and core <= 0.5 and overlap <= 0.5
        clean += ok
        row("unit_placement", u["id"], ok, round(core + overlap, 2), f"inside {inside:.0%}, core {core:.1f} m2, overlap {overlap:.1f} m2",
            is_hard=not ok)
    # exit travel: corridor walk from the entry to the nearest assumed exit, plus the walk inside the unit
    walk = _corridor(units, float(draft.get("corridor_m") or 1.6))
    starts = [tuple(u.get("entry") or polys[u["id"]].centroid.coords[0]) for u in units]
    ugeom = unary_union(list(polys.values()))
    tr = _travel(floor, ugeom, starts)
    pieces = list(getattr(z := _open_floor(floor, ugeom), "geoms", [z]))
    exits = [Point(e) for e in getattr(floor, "exits", [])]
    travel_ok = 0
    worst = 0.0
    for u, t, s in zip(units, tr, starts, strict=True):
        inside = max(abs(px - s[0]) + abs(py - s[1]) for px, py in polys[u["id"]].exterior.coords)
        # a door can go on any wall of the unit that faces open floor: pass if >= 1 m of the outline borders open floor
        # that reaches an exit; sealed if no such wall exists
        ring = polys[u["id"]].exterior
        reach = [p for p in pieces if any(p.buffer(0.01).contains(e) for e in exits)]
        sealed = all(ring.intersection(p.buffer(DOOR_REACH)).length < 1.0 for p in reach)
        total = t + inside
        if sealed:
            ok, detail = False, "entry opens onto floor with no route to an exit (only through other units)"
        elif not math.isfinite(total):
            rows.append({"rule": "exit_travel", "subject": u["id"], "status": "unknown", "value": None,
                         "detail": "connected, distance not resolved on the grid"})
            travel_ok += 1
            continue
        else:
            ok, detail = total <= C.LIMITS["travel_m"], ""
        worst = max(worst, total if math.isfinite(total) else worst)
        travel_ok += ok
        row("exit_travel", u["id"], ok, round(total, 1) if math.isfinite(total) else None, detail, is_hard=sealed)

    n = len(units)
    sfs = [polys[u["id"]].area * M2SF for u in units]
    ones = [sf for u, sf in zip(units, sfs, strict=True) if u.get("type") in ("studio", "1BR")]
    avg = sum(sfs) / n
    out_band = max(0, avg - 700, 500 - avg)
    small = sum(sf < 450 for sf in ones)
    size = max(0.0, 10 - 1.25 * math.ceil(out_band / 50) - 1.0 * small)
    gross = plate.area
    eff = sum(p.area for p in polys.values()) / max(1e-9, gross - floor.core.area)
    rents = [(MONEY["rent_icpt"] + MONEY["rent_slope"] * round(sf)) * MONEY["premium"] + (MONEY["corner2bed"] if u.get("type") in ("2BR", "3BR") else 0)
             for u, sf in zip(units, sfs, strict=True)]
    noi = 12 * (sum(rents) + n * MONEY["other"]) * (1 - MONEY["vacancy"]) * (1 - MONEY["opex"])
    units_sf = sum(sfs)
    circ_sf = walk.area * M2SF
    storage_sf = max(0.0, (gross - floor.core.area) * M2SF - units_sf - circ_sf)
    build = MONEY["c_units"] * (units_sf + circ_sf) + MONEY["c_amenity"] * storage_sf + MONEY["c_core"] * floor.core.area * M2SF + MONEY["plumbing"]
    buyer = build + MONEY["linkage"] * MONEY["linkage_sf"] + MONEY["acq"] * MONEY["gross_sf"]
    yoc = noi / buyer
    gap = noi - MONEY["office_noi"]

    det = [c for c in floor.columns if c.kind != "hidden"]
    hid = [c for c in floor.columns if c.kind == "hidden"]
    S = {
        "Walls clear of detected columns": (15 * sum(col_ok[c.id] for c in det) / max(1, len(det)), f"{sum(col_ok[c.id] for c in det)}/{len(det)}"),
        "Walls clear of hidden columns": (10 * sum(col_ok[c.id] for c in hid) / max(1, len(hid)), f"{sum(col_ok[c.id] for c in hid)}/{len(hid)}"),
        "Bedrooms clear of columns": (10 * (1 - bed_hits / max(1, n_beds)), f"{bed_hits}/{n_beds} bedrooms hit a column"),
        "Bedrooms on windows": (15 * unit_glass_ok / n, f"{unit_glass_ok:g}/{n} units (unscanned facade counts half)"),
        "Units inside the plate, clear of core and each other": (10 * clean / n, f"{clean}/{n} units"),
        "Unit size vs market": (size, f"average {avg:.0f} sf; {small} one-beds/studios under 450 sf"),
        "Exit travel": (10 * travel_ok / n, f"{travel_ok}/{n} within 76.2 m; worst {worst:.1f} m"),
        "Buyer yield": (10 * min(1, yoc / MONEY["need"]), f"{yoc:.2%} vs {MONEY['need']:.2%} (frozen model)"),
        "Owner view vs office": (5 / 8 * (8.0 if gap >= 0 else max(0.0, 5 + 20 * gap / 1e6)),
                                 f"NOI ${noi / 1e6:.3f}M vs ${MONEY['office_noi'] / 1e6:.2f}M"),
        "Share of floor rented": (5 * min(1, eff / 0.80), f"{eff:.1%}"),
    }
    crit = {k: {"points": round(S[k][0], 2), "max": mx, "measured": S[k][1]} for k, mx in CRITERIA}
    total = sum(v["points"] for v in crit.values()) - 5 * len(hard)
    res = {"profile": PROFILE, "total": round(total, 2), "criteria": crit, "hard_breaks": hard, "units": n,
           "unit_mix": _mix(units), "rentable_sf": round(units_sf), "efficiency": round(eff, 3), "noi": round(noi),
           "not_scored": NOT_SCORED, "checks": rows}
    if final is not None:
        res["claims"] = claims(final, rows, n)
    return res


def _mix(units):
    m: dict[str, int] = {}
    for u in units:
        m[u.get("type", "?")] = m.get(u.get("type", "?"), 0) + 1
    return m


def claims(final: dict[str, Any], rows: list[dict[str, Any]], n: int) -> dict[str, Any]:
    """What the agent said vs what the grader found: units the agent called passing vs units with no failed check."""
    claimed_pass = sum(1 for u in final.get("units") or [] if (u.get("checks") or {}).get("status") == "pass")
    failing = {r["subject"].split("/")[0] for r in rows if r["status"] == "fail" and r["rule"] != "wall_column"}
    graded_pass = n - len(failing)
    cc = (final.get("summary") or {}).get("check_counts") or {}
    return {"claimed_units_passing": claimed_pass, "graded_units_passing": graded_pass, "gap": claimed_pass - graded_pass,
            "claimed_check_counts": cc, "issues_reported": len((final.get("summary") or {}).get("issues") or [])}
