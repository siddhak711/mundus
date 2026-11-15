"""Turn a floor-16 layout study (studies/floor16/v4/layout-v4.json) into the walkthrough's apartment file.

    python3 scripts/layout_v4_to_viewer.py [study.json] [out.json]

The study lists units, the rooms inside them, the corridor, stairs and columns, all in scan metres (x, y). The viewer
needs wall segments as well, so they are found here: every room is painted onto a 5 cm grid, and a wall goes wherever
two neighbouring cells belong to different units, or to different rooms of one unit that are not open to each other
(living, kitchen and hall stay open). Door gaps are cut at each unit's entry and between each bedroom, bath and closet
and the room it opens onto. The exterior glass line is left alone: the viewer already draws the photo walls there.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "studies/floor16/v4/layout-v4.json"
OUT = ROOT / "web/walkthrough/layouts/cEvQ8q5GKZd.json"
SHELL_RECT = (-38.42, 30.3, -10.3, 24.4)   # x0, x1, y0, y1 of the outer wall (shell.json "rect")
CELL = 0.05

SLOTS = 32   # grid value = 100 + unit index * SLOTS + (room index + 1); slot 0 is unit floor no room covers
OPEN = {frozenset(p) for p in [("living", "kitchen"), ("living", "hall"), ("kitchen", "hall"), ("other", "hall"),
                                ("other", "living"), ("other", "kitchen"), ("bed", "wardrobe")]}
DOOR_PARTNERS = {"bed": ["hall", "living", "other", "kitchen"], "bath": ["hall", "bed", "living", "other"],
                 "closet": ["hall", "living", "other", "bed", "kitchen"]}
OUTSIDE, OPEN_FLOOR, CORRIDOR, CORE_ROOM = 0, 1, 2, 3


def build(study: dict) -> dict:
    x0, x1, y0, y1 = SHELL_RECT
    nx, ny = round((x1 - x0) / CELL), round((y1 - y0) / CELL)
    grid = [[OPEN_FLOOR] * ny for _ in range(nx)]

    def cells(rect):
        ax, ay, bx, by = rect
        i0, i1 = sorted((round((ax - x0) / CELL), round((bx - x0) / CELL)))
        j0, j1 = sorted((round((ay - y0) / CELL), round((by - y0) / CELL)))
        for i in range(max(i0, 0), min(i1, nx)):
            for j in range(max(j0, 0), min(j1, ny)):
                yield i, j

    def paint(rect, value):
        for i, j in cells(rect):
            grid[i][j] = value

    def inside(poly, x, y):
        hit = False
        for k in range(len(poly)):
            (ax, ay), (bx, by) = poly[k], poly[k - 1]
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                hit = not hit
        return hit

    for rect in study["corridor"]:
        paint(rect, CORRIDOR)
    for group in ("stairs", "lobbies", "stair_links"):
        for s in study.get(group, []):
            paint(s["rect"], CORE_ROOM)
    units = study["units"]
    for u_i, u in enumerate(units):
        poly = u["poly"]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        for i, j in cells((min(xs), min(ys), max(xs), max(ys))):
            if inside(poly, x0 + (i + 0.5) * CELL, y0 + (j + 0.5) * CELL):
                grid[i][j] = 100 + u_i * SLOTS
        for r_i, r in enumerate(u["rooms"]):
            paint(r["rect"], 100 + u_i * SLOTS + r_i + 1)

    unit_of = lambda v: (v - 100) // SLOTS if v >= 100 else None

    def room_of(v):
        if v < 100:
            return None
        slot = (v - 100) % SLOTS
        return "other" if slot == 0 else units[unit_of(v)]["rooms"][slot - 1]["type"]

    def kind(a, b):
        ua, ub = unit_of(a), unit_of(b)
        if ua is None and ub is None:
            return None
        if ua != ub:
            other = b if ua is not None else a
            if ua is not None and ub is not None:
                return "demising"
            return {OUTSIDE: None, CORRIDOR: "corridor"}.get(other, "demising")
        ra, rb = room_of(a), room_of(b)
        if a == b or frozenset((ra, rb)) in OPEN or (ra == rb and ra not in ("bed", "bath")):
            return None
        return "interior"

    # every wall edge on the grid: key (orientation, line index, cell index) -> (kind, label a, label b)
    # 'v' edges sit on x = x0 + i*CELL between cells (i-1, j) and (i, j); 'h' edges on y = y0 + j*CELL.
    edges = {}
    for i in range(nx + 1):
        for j in range(ny):
            a = grid[i - 1][j] if i > 0 else OUTSIDE
            b = grid[i][j] if i < nx else OUTSIDE
            k = kind(a, b)
            if k:
                edges[("v", i, j)] = (k, a, b)
    for i in range(nx):
        for j in range(ny + 1):
            a = grid[i][j - 1] if j > 0 else OUTSIDE
            b = grid[i][j] if j < ny else OUTSIDE
            k = kind(a, b)
            if k:
                edges[("h", j, i)] = (k, a, b)

    def edge_mid(key):
        o, line, t = key
        return (x0 + line * CELL, y0 + (t + 0.5) * CELL) if o == "v" else (x0 + (t + 0.5) * CELL, y0 + line * CELL)

    # entry doors: 0.95 m opening centred on the study's door point
    for u_i, u in enumerate(units):
        dx, dy = u["door"]
        for key in [k for k, (kd, a, b) in edges.items() if kd in ("corridor", "demising") and u_i in (unit_of(a), unit_of(b))]:
            mx, my = edge_mid(key)
            along, across = (abs(my - dy), abs(mx - dx)) if key[0] == "v" else (abs(mx - dx), abs(my - dy))
            if across < 0.08 and along < 0.475:
                del edges[key]

    # room doors: one 0.85 m opening per bedroom, bath and closet, on the wall it shares with its best partner room
    doors = []
    for u_i, u in enumerate(units):
        base = 100 + u_i * SLOTS
        codes = [(base + r_i + 1, r["type"]) for r_i, r in enumerate(u["rooms"])] + [(base, "other")]
        for code, r_type in codes:
            if r_type not in DOOR_PARTNERS:
                continue
            for partner in DOOR_PARTNERS[r_type]:
                run = sorted(k for k, (kd, a, b) in edges.items() if code in (a, b) and room_of(b if a == code else a) == partner
                             and unit_of(b if a == code else a) == u_i)
                if not run:
                    continue
                # the longest straight contiguous run gets the door
                runs, cur = [], [run[0]]
                for k in run[1:]:
                    p = cur[-1]
                    if (k[0], k[1]) == (p[0], p[1]) and k[2] == p[2] + 1:
                        cur.append(k)
                    else:
                        runs.append(cur)
                        cur = [k]
                runs.append(cur)
                for seg in [max(runs, key=len)]:
                    n_gap = round(0.85 / CELL)
                    if len(seg) <= n_gap + 4:
                        gap = seg
                    else:
                        # hinge 15 cm from the end nearer the unit's entry door, as a real door would be
                        ends = [edge_mid(seg[0]), edge_mid(seg[-1])]
                        near0 = (ends[0][0] - u["door"][0]) ** 2 + (ends[0][1] - u["door"][1]) ** 2 <= \
                                (ends[1][0] - u["door"][0]) ** 2 + (ends[1][1] - u["door"][1]) ** 2
                        gap = seg[3:3 + n_gap] if near0 else seg[-3 - n_gap:-3]
                    for k in gap:
                        edges.pop(k, None)
                    a, b = edge_mid(gap[0]), edge_mid(gap[-1])
                    doors.append({"unit": u["id"], "room": r_type, "to": partner, "a": [round(v, 3) for v in a], "b": [round(v, 3) for v in b]})
                break

    # merge cell edges into straight segments of one kind
    walls = []
    for o in ("v", "h"):
        keys = sorted(k for k in edges if k[0] == o)
        start = prev = None
        for k in keys + [None]:
            if prev is not None and k is not None and k[1] == prev[1] and k[2] == prev[2] + 1 and edges[k][0] == edges[prev][0]:
                prev = k
                continue
            if start is not None:
                line, t0, t1 = start[1], start[2], prev[2] + 1
                if o == "v":
                    a, b = [x0 + line * CELL, y0 + t0 * CELL], [x0 + line * CELL, y0 + t1 * CELL]
                else:
                    a, b = [x0 + t0 * CELL, y0 + line * CELL], [x0 + t1 * CELL, y0 + line * CELL]
                if (t1 - t0) * CELL >= 0.1:   # slivers from rounding are not walls
                    walls.append({"a": [round(v, 3) for v in a], "b": [round(v, 3) for v in b], "kind": edges[start][0]})
            start = prev = k

    keep = ("id", "type", "sf", "rent_mo", "poly", "door", "fixtures", "access", "egress_to_stair_m", "entry_clear_m",
            "door_clear_m", "drain_run_m", "drain_runs_m", "chases", "column_overlaps", "wet_rooms_paired", "checks")
    out_units = []
    for u in units:
        o = {k: u[k] for k in keep if k in u}
        o["rooms"] = [{"type": r["type"], "rect": [round(v, 3) for v in r["rect"]], "sf": r["sf"]} for r in u["rooms"]]
        o["poly"] = [[round(x, 3), round(y, 3)] for x, y in u["poly"]]
        out_units.append(o)
    checks = [c["ok"] for u in units for c in u.get("checks", {}).values()]
    mix = {}
    for u in units:
        mix[u["type"]] = mix.get(u["type"], 0) + 1
    return {
        "scan": "cEvQ8q5GKZd", "floor": 16, "format": "rooms-v1",
        "source": "studies/floor16/v4/layout-v4.json (scripts/apartment_study_v4.py)",
        "generated_by": "scripts/layout_v4_to_viewer.py",
        "coords": study.get("coords", "scan metres (x, y)"),
        "summary": {
            "units": len(units), "rentable_sf": sum(u["sf"] for u in units), "unit_mix": mix,
            "monthly_rent_usd": round(sum(u.get("rent_mo", 0) for u in units)),
            "check_counts": {"pass": sum(checks), "fail": len(checks) - sum(checks)},
            "score": study.get("self_score", {}).get("total"),
        },
        "units": out_units, "walls": walls, "doors": doors,
        "corridor": study["corridor"], "stairs": study.get("stairs", []), "lobbies": study.get("lobbies", []),
        "stair_links": study.get("stair_links", []), "storage": study.get("storage"),
        "columns": study.get("columns", []), "areas": study.get("areas"), "unit_mix": study.get("unit_mix"),
        "money": study.get("money"), "self_score": study.get("self_score"),
        "egress": {"stair_separation_m": study.get("stair_separation_m"), "worst_travel_to_stair_m": study.get("worst_travel_to_stair_m"),
                   "corridor_loop": study.get("corridor_loop")},
        "geometry_errors": study.get("geometry_errors", []),
    }


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else OUT
    lay = build(json.loads(src.read_text(encoding="utf-8")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(lay, separators=(",", ":")), encoding="utf-8")
    kinds = {}
    for w in lay["walls"]:
        kinds[w["kind"]] = kinds.get(w["kind"], 0) + 1
    print(f"{out}: {lay['summary']['units']} units, {sum(len(u['rooms']) for u in lay['units'])} rooms, "
          f"{lay['summary']['rentable_sf']:,} sf, {len(lay['walls'])} walls {kinds}, {len(lay['doors'])} doors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
