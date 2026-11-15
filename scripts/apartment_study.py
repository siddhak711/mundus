"""Apartment layout study for one scanned office floor (10880 Wilshire, Suite 1600).

Reads the same scan-derived files the walkthrough viewer loads (data/shell.json, data/scene.json,
data/floorfill.png), lays out one-bed apartments around the detected columns, checks each unit
against the rules in RULES, and prices the conversion. Writes PNGs, layout JSON and a notes file.

No licensed data lives in this file; it reads the scan data and the CoStar kit from paths given
on the command line. Outputs are written next to the data (gitignored).

  python scripts/apartment_study.py all --data web/walkthrough/data \
      --kit ~/Downloads/hackprinceton/costar-hackathon-kit --out web/walkthrough/data/studies
"""
import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False   # dollar signs are money, not maths
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import PathPatch, Polygon as MPoly, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

M2SF = 10.7639
FT = 0.3048

# ---------------------------------------------------------------- rules (sources in study.md)
RULES = {
    "room_min_dim_m": 7 * FT,        # CBC 2025 §1208.1: 7 ft min plan dimension, habitable rooms
    "big_room_sf": 120,              # CBC 2025 §1208.4: one habitable room >= 120 sq ft
    "room_min_sf": 70,               # CBC 2025 §1208.4: other habitable rooms >= 70 sq ft
    "unit_habitable_min_sf": 190,    # CBC 2025 §1208.3
    "glazing_frac": 0.08,            # CBC §1204.2 natural light
    "corridor_min_m": 44 * 0.0254,   # CBC §1020.2 (we draw 5 ft for wheelchair turning)
    "dead_end_max_m": 50 * FT,       # CBC §1020.5 sprinklered R-2
    "travel_max_m": 250 * FT,        # CBC Table 1017.2 sprinklered R-2
    "common_path_max_m": 125 * FT,   # CBC Table 1006.2.1 sprinklered R-2
    "min_units": 5,                  # LA ARO §12.22 A.26(d)(4)
}

# ---------------------------------------------------------------- floor-specific layout inputs
# The corridor is placed by hand for this floor: a 5 ft loop whose inner wall runs along the
# outer faces of the detected column rows (south y~-1.9, north y~16.0, east x~22, west possibles
# x~-30.2), so every probable column sits in the corridor's inner wall, not inside an apartment.
CW = 1.52                                   # corridor width, 5 ft
RING_IN = (-30.60, 22.60, -2.33, 16.45)     # inner edges of the loop (x0, x1, y0, y1), scan metres
# Short corridors from the loop to the core, where stairs and lifts are assumed to be.
CONNECTORS = [(-0.65, -2.33, 0.87, 16.45),      # spine through the gap between the two core blocks
              (-30.60, 4.50, -25.775, 6.00),    # west
              (18.475, 6.50, 22.60, 8.00)]      # east
# Wall between kitchen/bath zone and window rooms, measured from the corridor. North is 2.43 m so the
# wall runs through the second north column row (y~20.2).
SERVICE_DEPTH = {"S": 2.25, "N": 2.43, "W": 2.25, "E": 2.25}
BATH_W, ENTRY_W, KITCHEN_MIN, BED_MIN, LIVING_MIN, DOOR_FRONT = 1.65, 1.05, 2.10, 2.75, 3.00, 1.20
SILL_M, HEAD_M = 0.55, 2.55                 # glass band on the exterior wall (photo walls: sill row 347/435)

SCHEMES = {
    "A": dict(title="Scheme A: code-minimum one-beds", wmin=5.90, w0=5.90, wmax=7.00, cmax=9.0, lam=100.0),
    "B": dict(title="Scheme B: market-size one-beds", wmin=7.60, w0=8.40, wmax=9.40, cmax=10.5, lam=0.0),
}

ROOM_COL = {"bed": "#9ec5e8", "living": "#f3d9a4", "kitchen": "#b9dfb0", "bath": "#8fd3cf", "entry": "#e4e0d8"}
ROOM_TAG = {"bed": "BR", "living": "LR", "kitchen": "K", "bath": "BA", "entry": ""}


# ---------------------------------------------------------------- data
def load(data):
    S = json.loads((data / "scene.json").read_text())
    SH = json.loads((data / "shell.json").read_text())
    fill = Image.open(data / "floorfill.png")
    return S, SH, fill


def core_geom(SH):
    return unary_union([Polygon(b["outer"], b["holes"]).buffer(0) for b in SH["core"]])


# ---------------------------------------------------------------- bands
def bands(SH):
    x0, x1, y0, y1 = SH["rect"]
    ix0, ix1, iy0, iy1 = RING_IN
    ox0, ox1, oy0, oy1 = ix0 - CW, ix1 + CW, iy0 - CW, iy1 + CW
    # (s, v) -> world, v = distance from the corridor face toward the glass
    return {
        "S": dict(s0=x0, s1=x1, D=oy0 - y0, touch=(ox0, ox1), corners=True, f=lambda s, v: (s, oy0 - v)),
        "N": dict(s0=x0, s1=x1, D=y1 - oy1, touch=(ox0, ox1), corners=True, f=lambda s, v: (s, oy1 + v)),
        "W": dict(s0=oy0, s1=oy1, D=ox0 - x0, touch=(oy0, oy1), corners=False, f=lambda s, v: (ox0 - v, s)),
        "E": dict(s0=oy0, s1=oy1, D=x1 - ox1, touch=(oy0, oy1), corners=False, f=lambda s, v: (ox1 + v, s)),
    }


def to_sv(name, b, x, y):
    ix0, ix1, iy0, iy1 = RING_IN
    ox0, ox1, oy0, oy1 = ix0 - CW, ix1 + CW, iy0 - CW, iy1 + CW
    return {"S": (x, oy0 - y), "N": (x, y - oy1), "W": (y, ox0 - x), "E": (y, x - ox1)}[name]


def band_columns(name, b, SH):
    out = []
    for i, c in enumerate(SH["columns"]):
        s, v = to_sv(name, b, c["x"], c["y"])
        if b["s0"] < s < b["s1"] and 0 < v < b["D"]:
            out.append(dict(i=i, s=s, v=v, h=c["size"] / 2, grade=c["grade"]))
    return out


# ---------------------------------------------------------------- split a band into units (dynamic programming)
def split_band(name, b, cols, sc, step=0.05):
    Sd = SERVICE_DEPTH[name]
    n = int(round((b["s1"] - b["s0"]) / step))
    pos = [b["s0"] + i * step for i in range(n + 1)]
    corner_w = (b["touch"][0] - b["s0"]) if b["corners"] else 0

    def unit_cost(a, z, first, last):
        w = z - a
        if b["corners"] and (first or last):
            lo = corner_w + DOOR_FRONT if first else (b["s1"] - b["touch"][1]) + DOOR_FRONT
            if not (lo <= w <= sc["cmax"]):
                return None
            target = lo + 0.6
        else:
            if not (sc["wmin"] - 1e-6 <= w <= sc["wmax"] + 1e-6):
                return None
            target = sc["w0"]
        pen = (w - target) ** 2
        for c in cols:
            if not (a - c["h"] < c["s"] < z + c["h"]):
                continue
            on_cut = abs(c["s"] - a) <= c["h"] - 0.04 or abs(c["s"] - z) <= c["h"] - 0.04
            if on_cut or abs(c["v"] - Sd) <= c["h"]:
                continue                                   # absorbed in a demising or partition wall
            if a + 0.02 < c["s"] < z - 0.02:
                pen += 30 if c["v"] < Sd else 1000         # loose in kitchen/bath zone vs in a window room
        return pen - sc["lam"]

    INF = float("inf")
    best = [INF] * (n + 1)
    prev = [-1] * (n + 1)
    best[0] = 0.0
    wmax = max(sc["wmax"], sc["cmax"])
    for i in range(1, n + 1):
        for j in range(max(0, i - int(wmax / step) - 1), i):
            if best[j] == INF:
                continue
            cst = unit_cost(pos[j], pos[i], j == 0, i == n)
            if cst is None:
                continue
            if best[j] + cst < best[i]:
                best[i], prev[i] = best[j] + cst, j
    if best[n] == INF:
        return None
    cuts, i = [n], n
    while i > 0:
        i = prev[i]
        cuts.append(i)
    return [pos[k] for k in reversed(cuts)]


# ---------------------------------------------------------------- rooms inside one unit
def unit_rooms(name, b, a, z, k, nunits):
    W, D, Sd = z - a, b["D"], SERVICE_DEPTH[name]
    t0, t1 = max(a, b["touch"][0]), min(z, b["touch"][1])
    start_corner = b["corners"] and k == 0
    end_corner = b["corners"] and k == nunits - 1
    kit = W - BATH_W - ENTRY_W
    if start_corner:
        order = [("kitchen", kit), ("bath", BATH_W), ("entry", ENTRY_W)]
    elif end_corner:
        order = [("entry", ENTRY_W), ("bath", BATH_W), ("kitchen", kit)]
    elif k % 2 == 0:
        order = [("bath", BATH_W), ("entry", ENTRY_W), ("kitchen", kit)]
    else:
        order = [("kitchen", kit), ("entry", ENTRY_W), ("bath", BATH_W)]
    rooms, s = [], a
    for t, w in order:
        rooms.append(dict(type=t, s=(s, s + w), v=(0, Sd)))
        s += w
    bath = next(r for r in rooms if r["type"] == "bath")
    bed_lo = (bath["s"][0] - a) < (z - bath["s"][1])
    if start_corner:
        bed_lo = True      # bedroom on the corner, two walls of glass
    if end_corner:
        bed_lo = False
    wb = min(max(0.44 * W, BED_MIN), 4.2)
    if bed_lo:
        rooms += [dict(type="bed", s=(a, a + wb), v=(Sd, D)), dict(type="living", s=(a + wb, z), v=(Sd, D))]
    else:
        rooms += [dict(type="living", s=(a, z - wb), v=(Sd, D)), dict(type="bed", s=(z - wb, z), v=(Sd, D))]
    entry = next(r for r in rooms if r["type"] == "entry")
    door_s = (entry["s"][0] + entry["s"][1]) / 2
    return rooms, door_s, (t0, t1)


def poly_world(b, s, v):
    f = b["f"]
    return [f(s[0], v[0]), f(s[1], v[0]), f(s[1], v[1]), f(s[0], v[1])]


# ---------------------------------------------------------------- layout + checks
def layout(SH, scheme):
    sc = SCHEMES[scheme]
    B = bands(SH)
    units, problems = [], []
    for name in ["S", "E", "N", "W"]:
        b = B[name]
        cols = band_columns(name, b, SH)
        cuts, sc2 = None, dict(sc)
        for _ in range(20):        # short bands may not divide evenly: widen the width range a little at a time
            cuts = split_band(name, b, cols, sc2)
            if cuts:
                break
            sc2["wmin"] -= 0.1
            sc2["wmax"] += 0.1
        if not cuts:
            raise SystemExit(f"band {name}: no valid split for {sc['title']}")
        nun = len(cuts) - 1
        for k in range(nun):
            a, z = cuts[k], cuts[k + 1]
            rooms, door_s, (t0, t1) = unit_rooms(name, b, a, z, k, nun)
            uid = f"{name}{k + 1}"
            W, D = z - a, b["D"]
            u = dict(id=uid, band=name, s=(a, z), width_m=round(W, 2), depth_m=round(D, 2),
                     sf=round(W * D * M2SF), poly=poly_world(b, (a, z), (0, D)),
                     door=b["f"](door_s, 0), corner=b["corners"] and (k == 0 or k == nun - 1), rooms=[], checks={})
            for r in rooms:
                w, d = r["s"][1] - r["s"][0], r["v"][1] - r["v"][0]
                u["rooms"].append(dict(type=r["type"], poly=poly_world(b, r["s"], r["v"]), w=round(w, 2), d=round(d, 2),
                                       sf=round(w * d * M2SF)))
            bed = next(r for r in u["rooms"] if r["type"] == "bed")
            liv = next(r for r in u["rooms"] if r["type"] == "living")
            kit = next(r for r in u["rooms"] if r["type"] == "kitchen")
            glass_bed = (bed["w"] if True else 0) * (HEAD_M - SILL_M)
            ck = {
                "bedroom >= 70 sf and 7 ft": bed["sf"] >= RULES["room_min_sf"] and min(bed["w"], bed["d"]) >= RULES["room_min_dim_m"],
                "living >= 120 sf and 7 ft": liv["sf"] >= RULES["big_room_sf"] and min(liv["w"], liv["d"]) >= RULES["room_min_dim_m"],
                "habitable >= 190 sf": bed["sf"] + liv["sf"] >= RULES["unit_habitable_min_sf"],
                "kitchen run >= 2.1 m": kit["w"] >= KITCHEN_MIN - 1e-6,
                "bedroom on glass, >= 8% glazing": glass_bed >= RULES["glazing_frac"] * bed["w"] * bed["d"],
                "door on corridor": t0 + 0.45 <= door_s <= t1 - 0.45,
            }
            # columns inside this unit
            loose = []
            for c in cols:
                if a < c["s"] < z:
                    on_wall = (abs(c["s"] - a) <= c["h"] - 0.04 or abs(c["s"] - z) <= c["h"] - 0.04
                               or abs(c["v"] - SERVICE_DEPTH[name]) <= c["h"])
                    if not on_wall:
                        loose.append((c["i"], "service zone" if c["v"] < SERVICE_DEPTH[name] else "window room", c["grade"]))
            ck["no column loose in a window room"] = not any(z_ == "window room" for _, z_, _g in loose)
            u["checks"] = ck
            u["columns_in_unit"] = loose
            for kname, ok in ck.items():
                if not ok:
                    problems.append(f"{uid}: {kname}")
            units.append(u)
    return units, problems


def column_report(SH, units):
    ix0, ix1, iy0, iy1 = RING_IN
    ring_out = box(ix0 - CW, iy0 - CW, ix1 + CW, iy1 + CW)
    ring_in = box(ix0, iy0, ix1, iy1)
    corridor = ring_out.difference(ring_in)
    rows = []
    for i, c in enumerate(SH["columns"]):
        sq = box(c["x"] - c["size"] / 2, c["y"] - c["size"] / 2, c["x"] + c["size"] / 2, c["y"] + c["size"] / 2)
        if sq.intersection(corridor).area > 0.01:
            where, ok = "inside corridor", False
        elif sq.intersection(unary_union([box(*cn) for cn in CONNECTORS])).area > 0.01:
            where, ok = "inside core connector", False
        elif ring_in.contains(sq.centroid):
            d = sq.distance(corridor)
            where, ok = ("in corridor inner wall" if d < 0.12 else "amenity / back-of-house zone"), True
        else:
            u = next((u for u in units if Polygon(u["poly"]).contains(sq.centroid)), None)
            if u is None:
                where, ok = "outside units", True
            else:
                hit = next((x for x in u["columns_in_unit"] if x[0] == i), None)
                if hit is None:
                    where, ok = f"in a wall of {u['id']}", True
                else:
                    where, ok = f"loose in {u['id']} {hit[1]}", hit[1] != "window room"
        rows.append(dict(i=i + 1, x=c["x"], y=c["y"], size=c["size"], grade=c["grade"], where=where, ok=ok))
    return rows


def areas(SH, units):
    x0, x1, y0, y1 = SH["rect"]
    ix0, ix1, iy0, iy1 = RING_IN
    gross = (x1 - x0) * (y1 - y0)
    core = core_geom(SH)
    ring_out = box(ix0 - CW, iy0 - CW, ix1 + CW, iy1 + CW)
    ring_in = box(ix0, iy0, ix1, iy1)
    corridor = ring_out.difference(ring_in)
    conn = unary_union([box(*c) for c in CONNECTORS]).difference(core)
    amenity = ring_in.difference(core).difference(conn)
    unit_m2 = sum(u["width_m"] * u["depth_m"] for u in units)
    return dict(gross_sf=round(gross * M2SF), core_sf=round(core.area * M2SF), corridor_sf=round((corridor.area + conn.area) * M2SF),
                amenity_sf=round(amenity.area * M2SF), units_sf=round(unit_m2 * M2SF),
                efficiency=unit_m2 / (gross - core.area), amenity_geom=amenity, corridor_geom=corridor, conn_geom=conn)


def egress(SH, units):
    """Walking distance from each unit's far corner to the nearest core connector, along the loop corridor."""
    ix0, ix1, iy0, iy1 = RING_IN
    cx0, cx1, cy0, cy1 = ix0 - CW / 2, ix1 + CW / 2, iy0 - CW / 2, iy1 + CW / 2   # corridor centreline loop
    L = 2 * (cx1 - cx0) + 2 * (cy1 - cy0)

    def param(x, y):   # project to the loop, return distance along it
        x, y = min(max(x, cx0), cx1), min(max(y, cy0), cy1)
        d = [abs(y - cy0), abs(x - cx1), abs(y - cy1), abs(x - cx0)]
        side = int(np.argmin(d))
        if side == 0:
            return x - cx0
        if side == 1:
            return (cx1 - cx0) + (y - cy0)
        if side == 2:
            return (cx1 - cx0) + (cy1 - cy0) + (cx1 - x)
        return 2 * (cx1 - cx0) + (cy1 - cy0) + (cy1 - y)

    taps = [(param(0.11, cy0), 2.5), (param(0.11, cy1), 4.5), (param(cx0, 5.25), 4.8), (param(cx1, 7.25), 4.1)]
    worst = 0
    for u in units:
        p = param(*u["door"])
        along = min(min(abs(p - t), L - abs(p - t)) + extra for t, extra in taps)
        inside = u["width_m"] + u["depth_m"]          # far corner of the unit to its door, walking around furniture
        u["egress_m"] = round(along + inside + CW / 2, 1)
        worst = max(worst, u["egress_m"])
    return worst


# ---------------------------------------------------------------- rent comps and money
def comps(kit, lat0, lon0, radius_km=2.0):
    rows = []
    for line in (kit / "data" / "apartment-listing.jsonl").open():
        r = json.loads(line)
        a = r.get("address") or {}
        if not a.get("latitude"):
            continue
        d = 6371 * math.hypot(math.radians(a["latitude"] - lat0), math.radians(a["longitude"] - lon0) * math.cos(math.radians(lat0)))
        if d > radius_km:
            continue
        for m in r.get("apartmentModels") or []:
            if m.get("numBeds") != 1:
                continue
            rents = [x for x in (m.get("minRent"), m.get("maxRent")) if x]
            sfs = [x for x in (m.get("minSquareFeet"), m.get("maxSquareFeet")) if x]
            if not rents or not sfs:
                continue
            rows.append(dict(bldg=r.get("buildingName") or "", km=round(d, 2), rent=sum(rents) / len(rents), sf=sum(sfs) / len(sfs)))
    rent = np.array([r["rent"] for r in rows])
    sf = np.array([r["sf"] for r in rows])
    slope, icpt = np.polyfit(sf, rent, 1)
    return dict(n=len(rows), buildings=len({r["bldg"] for r in rows}), rent_med=float(np.median(rent)),
                rent_q1=float(np.percentile(rent, 25)), rent_q3=float(np.percentile(rent, 75)), sf_med=float(np.median(sf)),
                psf_med=float(np.median(rent / sf)), fit=(float(icpt), float(slope)), rows=rows)


# Every money input: (value, low, high, source)
MONEY = {
    "all_in_cost_psf": (500, 400, 600, "AECOM ARO Economic Analysis, Jul 2024, Table 5 (high-rise, hard+soft+contingency, per gross sf); range per Cooperative LA Jan 2026"),
    "acq_psf": (216, 93, 539, "AECOM 2024: LA County vacant office sales 2020-24 avg $216 (range $93-349); 10900 Wilshire next door $539/sf (Bisnow Jan 2025) as high"),
    "linkage_net_psf": (16.76, 16.76, 23.20, "LA AHLF memo Apr 2026: $23.20/sf high-market residential less $6.44 non-residential credit (derived); exempt with >=20% low-income units"),
    "opex_ratio": (0.30, 0.30, 0.35, "AECOM 2024 assumption (30%); 35% as a stress case (assumption)"),
    "vacancy": (0.05, 0.05, 0.07, "assumption"),
    "exit_cap": (0.059, 0.045, 0.059, "Kidder Mathews LA multifamily 3Q26: 5.9%; AECOM 2024 used 4.5%"),
    "spread_needed": (0.0125, 0.01, 0.015, "assumption: developers usually need yield on cost ~100-150 bp above the exit cap"),
    "rent_aff_60": (1874, 1874, 1874, "LAHD 2026 schedules (eff. 1 Jul 2026), TCAC 1-bed at 60% AMI"),
    "rent_aff_80": (2499, 2499, 2665, "LAHD 2026 schedules, TCAC 1-bed at 80% AMI ($2,665 LAHD Schedule I)"),
    "other_income_mo": (75, 50, 100, "assumption: parking, storage, fees per unit per month"),
}


def unit_rent(u, C):
    icpt, slope = C["fit"]
    return max(C["rent_q1"] * 0.85, icpt + slope * u["sf"])


def finance(units, A, C, scenario, cost_case="mid"):
    pick = {"mid": 0, "low": 1, "high": 2}[cost_case]
    m = {k: v[pick] for k, v in MONEY.items()}
    n = len(units)
    floor_sf = A["gross_sf"]
    if scenario == "market":
        rents = [unit_rent(u, C) for u in units]
        linkage = MONEY["linkage_net_psf"][0] * floor_sf
    elif scenario == "mixed":
        k = math.ceil(0.20 * n)
        order = sorted(range(n), key=lambda i: units[i]["sf"])        # smallest units go affordable
        aff = set(order[:k])
        rents = [MONEY["rent_aff_80"][0] if i in aff else unit_rent(u, C) for i, u in enumerate(units)]
        linkage = 0.0                                                   # >=20% low-income: exempt
    else:
        rents = [MONEY["rent_aff_60"][0]] * n
        linkage = 0.0
    gpr = 12 * (sum(rents) + n * m["other_income_mo"])
    egi = gpr * (1 - m["vacancy"])
    noi = egi * (1 - m["opex_ratio"])
    conv = m["all_in_cost_psf"] * floor_sf
    acq = m["acq_psf"] * floor_sf
    total = conv + acq + linkage
    yoc = noi / total
    value = noi / m["exit_cap"]
    hurdle = m["exit_cap"] + m["spread_needed"]
    verdict = "worth it" if yoc >= hurdle else ("marginal" if yoc >= m["exit_cap"] else "not worth it")
    return dict(scenario=scenario, case=cost_case, n=n, rents=rents, avg_rent=sum(rents) / n, gpr=gpr, noi=noi, conv=conv, acq=acq,
                linkage=linkage, total=total, per_unit=total / n, yoc=yoc, value=value, profit=value - total, hurdle=hurdle,
                exit_cap=m["exit_cap"], verdict=verdict, breakeven_cost_psf=(noi / hurdle - acq - linkage) / floor_sf)


# ---------------------------------------------------------------- drawing
def add_geom(ax, g, **kw):
    """Draw a shapely (Multi)Polygon, holes included."""
    for p in getattr(g, "geoms", [g]):
        if p.area < 0.05:
            continue
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            verts += c
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MPath(verts, codes), **kw))


def setup_ax(ax, SH, S, fill, alpha=0.55):
    bx, by, bw, bh = S["bandRect"]
    ax.imshow(fill, extent=[bx, bx + bw, by, by + bh], alpha=alpha, zorder=0)
    x0, x1, y0, y1 = SH["rect"]
    ax.set_xlim(x0 - 3, x1 + 3)
    ax.set_ylim(y0 - 4.5, y1 + 2.5)
    ax.set_aspect("equal")
    ax.axis("off")


def draw_shell(ax, SH, core_label=True):
    x0, x1, y0, y1 = SH["rect"]
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec="#2a5d8f", lw=3.2, zorder=6))
    for blk in SH["core"]:
        ax.add_patch(MPoly(blk["outer"], closed=True, fc="#4a4f57", ec="#24272c", lw=1, hatch="///", zorder=5))
    if core_label:
        ax.text(-13.5, 6.3, "EXISTING CORE\n(not scanned: stairs, lifts,\nshafts assumed)", ha="center", va="center", fontsize=8, color="white", zorder=7)
        ax.text(10.5, 8.5, "EXISTING CORE", ha="center", va="center", fontsize=8, color="white", zorder=7)


def draw_columns(ax, SH, bad=(), labels=False):
    for i, c in enumerate(SH["columns"]):
        h = c["size"] / 2
        prob = c["grade"] == "probable"
        col = "#d62728" if i in bad else "#111111"
        ax.add_patch(Rectangle((c["x"] - h, c["y"] - h), 2 * h, 2 * h, fc=col if prob else "white", ec=col, lw=1.6, zorder=9))
        if labels:
            ax.text(c["x"] + h + 0.15, c["y"] + h + 0.1, f"C{i + 1}", fontsize=6.5, color="#111", zorder=10)


def scale_bar(ax, SH):
    x0, x1, y0, y1 = SH["rect"]
    sx, sy = x0, y0 - 3.2
    for k in range(4):
        ax.add_patch(Rectangle((sx + k * 2.5, sy), 2.5, 0.35, fc="#222" if k % 2 == 0 else "white", ec="#222", lw=0.8, zorder=8))
    ax.text(sx, sy - 0.25, "0", fontsize=7, va="top")
    ax.text(sx + 10, sy - 0.25, "10 m  (32.8 ft)", fontsize=7, va="top")
    ax.text(x1, sy, "Scan coordinates, metres. Up = scan +Y (not verified as true north).", fontsize=7, ha="right", color="#555")


def dims(ax, SH):
    x0, x1, y0, y1 = SH["rect"]
    ax.annotate("", (x0, y1 + 1.2), (x1, y1 + 1.2), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((x0 + x1) / 2, y1 + 1.45, f"{x1 - x0:.1f} m  ({(x1 - x0) / FT:.0f} ft)", ha="center", fontsize=8)
    ax.annotate("", (x1 + 1.2, y0), (x1 + 1.2, y1), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(x1 + 1.5, (y0 + y1) / 2, f"{y1 - y0:.1f} m\n({(y1 - y0) / FT:.0f} ft)", va="center", fontsize=8)


def render_base(SH, S, fill, out):
    fig, ax = plt.subplots(figsize=(17, 9.6))
    setup_ax(ax, SH, S, fill, alpha=0.9)
    x0, x1, y0, y1 = SH["rect"]
    for g in np.arange(math.ceil(x0), x1, 1.0):
        ax.plot([g, g], [y0, y1], color="#000", lw=0.5 if g % 5 == 0 else 0.15, alpha=0.25, zorder=1)
    for g in np.arange(math.ceil(y0), y1, 1.0):
        ax.plot([x0, x1], [g, g], color="#000", lw=0.5 if g % 5 == 0 else 0.15, alpha=0.25, zorder=1)
    d = 30 * FT
    ax.add_patch(Rectangle((x0 + d, y0 + d), x1 - x0 - 2 * d, y1 - y0 - 2 * d, fill=False, ec="#e08a00", lw=1.4, ls="--", zorder=4))
    ax.text(x0 + d + 0.3, y0 + d + 0.3, "30 ft from the glass (daylight line)", fontsize=7.5, color="#b56d00", zorder=4)
    draw_shell(ax, SH)
    draw_columns(ax, SH, labels=True)
    dims(ax, SH)
    scale_bar(ax, SH)
    gross = (x1 - x0) * (y1 - y0) * M2SF
    ax.set_title("10880 Wilshire, floor 16 (Suite 1600): empty floor with columns, from the Matterport scan", fontsize=13, loc="left")
    leg = (f"Outer wall (fitted to scan): {gross:,.0f} sq ft gross   ·   Core: {core_geom(SH).area * M2SF:,.0f} sq ft   ·   "
           f"Columns: {sum(c['grade'] == 'probable' for c in SH['columns'])} probable (solid), "
           f"{sum(c['grade'] != 'probable' for c in SH['columns'])} possible (hollow)\n"
           "Columns were detected in the scan mesh. Columns hidden inside old partitions were not found (likely several in the west half). Not an official floor plan.")
    fig.text(0.02, 0.02, leg, fontsize=8.5, color="#333")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_layout(SH, S, fill, units, A, colrep, scheme, out, worst_egress, C, fin):
    sc = SCHEMES[scheme]
    fig = plt.figure(figsize=(20, 10.4))
    ax = fig.add_axes([0.0, 0.06, 0.74, 0.88])
    setup_ax(ax, SH, S, fill, alpha=0.35)
    for g, fc in [(A["amenity_geom"], "#ece4f2"), (A["corridor_geom"], "#d9d9d9"), (A["conn_geom"], "#d9d9d9")]:
        add_geom(ax, g, fc=fc, ec="#999", lw=0.6, zorder=2)
    ax.text(-28.3, 12.5, "AMENITY / STORAGE / BACK-OF-HOUSE\n(no daylight, not rentable)", fontsize=7.5, color="#6a4d80", zorder=3)
    ax.text(-8.0, -3.1, "CORRIDOR  5 ft", fontsize=7, color="#555", ha="center", va="center", zorder=3)
    draw_shell(ax, SH)
    for u in units:
        for r in u["rooms"]:
            bad = not all(u["checks"].values())
            ax.add_patch(MPoly(r["poly"], closed=True, fc=ROOM_COL[r["type"]], ec="#333", lw=0.6, zorder=4))
            if ROOM_TAG[r["type"]] and r["w"] > 0.9:
                cx = sum(p[0] for p in r["poly"]) / 4
                cy = sum(p[1] for p in r["poly"]) / 4
                ax.text(cx, cy, ROOM_TAG[r["type"]], fontsize=6, ha="center", va="center", color="#333", zorder=5)
        ax.add_patch(MPoly(u["poly"], closed=True, fill=False, ec="#d62728" if not all(u["checks"].values()) else "#111", lw=1.8, zorder=6))
        xs, ys = [p[0] for p in u["poly"]], [p[1] for p in u["poly"]]
        # label on the window side
        lx, ly = sum(xs) / 4, sum(ys) / 4
        win = {"S": (0, -1), "N": (0, 1), "W": (-1, 0), "E": (1, 0)}[u["band"]]
        lx += win[0] * u["depth_m"] * 0.42
        ly += win[1] * u["depth_m"] * 0.42
        ax.text(lx, ly, f"{u['id']}  {u['sf']} sf", fontsize=6.6, ha="center", va="center", fontweight="bold", zorder=7,
                rotation=90 if u["band"] in "WE" else 0)
        ax.plot(*u["door"], marker="s", ms=4, color="#e07b00", zorder=8)
    bad_cols = {r["i"] - 1 for r in colrep if not r["ok"]}
    draw_columns(ax, SH, bad=bad_cols)
    scale_bar(ax, SH)
    ax.set_title(f"10880 Wilshire, floor 16: {sc['title']}  ·  {len(units)} units", fontsize=14, loc="left")

    # side panel
    sx = fig.add_axes([0.745, 0.06, 0.25, 0.88])
    sx.axis("off")
    fails = [u["id"] for u in units if not all(u["checks"].values())]
    sizes = [u["sf"] for u in units]
    mk = fin["market"]
    lines = [
        ("LAYOUT", True),
        (f"Units: {len(units)} one-bed / one-bath ({sum(u['corner'] for u in units)} corner)", False),
        (f"Unit size: {min(sizes)}–{max(sizes)} sf, avg {sum(sizes) / len(sizes):.0f} sf", False),
        (f"Rentable (units): {A['units_sf']:,} sf of {A['gross_sf']:,} gross", False),
        (f"Corridors: {A['corridor_sf']:,} sf · Amenity/BOH: {A['amenity_sf']:,} sf", False),
        (f"Core: {A['core_sf']:,} sf · Efficiency (units ÷ gross−core): {A['efficiency']:.0%}", False),
        ("", False),
        ("RULE CHECKS", True),
        (f"Rooms: bedroom ≥70 sf, living ≥120 sf, ≥7 ft wide: {'all pass' if not fails else 'FAIL ' + ', '.join(fails)}", False),
        ("Bedroom and living room on the glass in every unit", False),
        (f"Columns: {sum(r['ok'] for r in colrep)}/{len(colrep)} in walls, corridor wall or amenity zone", False),
        (f"Corridor: 5 ft loop, no dead ends (limit 50 ft)", False),
        (f"Worst walk to core: {worst_egress:.0f} m ({worst_egress / FT:.0f} ft) vs 250 ft limit", False),
        (f"≥ {RULES['min_units']} units (LA ARO): yes", False),
        ("", False),
        ("MONEY (mid case, whole floor)", True),
        (f"Rent: CoStar comps, {C['n']} one-bed plans in {C['buildings']} bldgs ≤2 km, median ${C['rent_med']:,.0f}/mo @ {C['sf_med']:.0f} sf", False),
        (f"Market avg rent here: ${mk['avg_rent']:,.0f}/mo  ·  NOI ${mk['noi'] / 1e6:.2f}M/yr", False),
        (f"All-in cost ${mk['total'] / 1e6:.1f}M (${mk['per_unit'] / 1e3:,.0f}k/unit) incl. acquisition", False),
    ]
    for key, label in [("market", "100% market"), ("mixed", "80% market / 20% at 80% AMI"), ("affordable", "100% at 60% AMI")]:
        f = fin[key]
        lines.append((f"{label}: yield {f['yoc']:.1%} vs {f['hurdle']:.1%} needed → {f['verdict'].upper()}", False))
    lines += [("", False), ("Full numbers and sources: 04-cost-benefit.png, study.md", False),
              ("Draft for checking. Not an architect's or code consultant's opinion.", False)]
    y = 0.98
    for text, head in lines:
        sx.text(0.0, y, text, fontsize=9.5 if head else 8.3, fontweight="bold" if head else "normal", va="top", transform=sx.transAxes,
                color="#d62728" if "FAIL" in text or "NOT WORTH" in text else "#222")
        y -= 0.031 if text else 0.014
    # legend
    y -= 0.01
    for t, c in ROOM_COL.items():
        if t == "entry":
            continue
        sx.add_patch(Rectangle((0.0, y - 0.018), 0.05, 0.018, fc=c, ec="#333", lw=0.5, transform=sx.transAxes))
        sx.text(0.07, y - 0.009, transform=sx.transAxes, s={"bed": "Bedroom", "living": "Living / dining", "kitchen": "Kitchen", "bath": "Bath"}[t], fontsize=8, va="center")
        y -= 0.028
    sx.plot([0.025], [y - 0.009], marker="s", ms=5, color="#e07b00", transform=sx.transAxes)
    sx.text(0.07, y - 0.009, "Front door", fontsize=8, va="center", transform=sx.transAxes)
    y -= 0.028
    sx.add_patch(Rectangle((0.0, y - 0.018), 0.05, 0.018, fc="#111", transform=sx.transAxes))
    sx.text(0.07, y - 0.009, "Column (solid probable, hollow possible)", fontsize=8, va="center", transform=sx.transAxes)
    sx.set_xlim(0, 1)
    sx.set_ylim(0, 1)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_money(res, C, out):
    fig = plt.figure(figsize=(17, 11))
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.94])
    ax.axis("off")
    ax.set_title("Cost-benefit: converting floor 16 to one-bed apartments (whole floor, 25,700 sf gross)", fontsize=14, loc="left")
    hdr = ["Scheme", "Rent mix", "Units", "Avg rent/mo", "NOI/yr", "Conversion", "Acquisition", "Linkage fee", "Total cost",
           "Cost/unit", "Yield on cost", "Needed", "Value at exit cap", "Profit", "Verdict"]
    rows = []
    for sch in ["A", "B"]:
        for sc_name, label in [("market", "100% market"), ("mixed", "80/20 mixed"), ("affordable", "100% @ 60% AMI")]:
            f = res[sch]["fin"][sc_name]
            rows.append([sch, label, f"{f['n']}", f"${f['avg_rent']:,.0f}", f"${f['noi'] / 1e6:.2f}M", f"${f['conv'] / 1e6:.1f}M",
                         f"${f['acq'] / 1e6:.1f}M", f"${f['linkage'] / 1e6:.2f}M", f"${f['total'] / 1e6:.1f}M", f"${f['per_unit'] / 1e3:,.0f}k",
                         f"{f['yoc']:.1%}", f"{f['hurdle']:.1%}", f"${f['value'] / 1e6:.1f}M", ("-" if f["profit"] < 0 else "+") + f"${abs(f['profit']) / 1e6:.1f}M", f["verdict"].upper()])
    tb = ax.table(cellText=rows, colLabels=hdr, loc="upper left", bbox=[0, 0.62, 1, 0.33], cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(8)
    for (r, c), cell in tb.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2a5d8f")
            cell.set_text_props(color="white", fontweight="bold")
        elif c == len(hdr) - 1:
            v = rows[r - 1][-1]
            cell.set_facecolor("#cfe8c9" if v == "WORTH IT" else "#f6e3a8" if v == "MARGINAL" else "#f2c0c0")
    # sensitivity
    y = 0.57
    ax.text(0, y, "What it takes (mid case): the all-in conversion cost per sf at which yield on cost reaches the hurdle", fontsize=10, fontweight="bold")
    y -= 0.03
    for sch in ["A", "B"]:
        for sc_name, label in [("market", "100% market"), ("mixed", "80/20"), ("affordable", "100% @ 60% AMI")]:
            f = res[sch]["fin"][sc_name]
            ax.text(0.01, y, f"Scheme {sch}, {label}: break-even conversion cost ${f['breakeven_cost_psf']:,.0f}/sf (vs $500 assumed)", fontsize=9)
            y -= 0.024
    y -= 0.01
    ax.text(0, y, "Range (Scheme A, 100% market). Optimistic = $400/sf, $93/sf land, 4.5% exit cap; pessimistic = $600/sf, $539/sf land, 35% opex", fontsize=10, fontweight="bold")
    y -= 0.03
    for case in ["low", "mid", "high"]:
        f = res["A"]["fin_cases"][case]
        ax.text(0.01, y, f"{dict(low='optimistic', mid='mid', high='pessimistic')[case]}: total ${f['total'] / 1e6:.1f}M, yield {f['yoc']:.1%} vs {f['hurdle']:.1%} → {f['verdict']}", fontsize=9)
        y -= 0.024
    y -= 0.01
    ax.text(0, y, "Inputs and sources", fontsize=10, fontweight="bold")
    y -= 0.028
    ax.text(0.01, y, f"Market rent: CoStar apartment listings, {C['n']} one-bed floor plans in {C['buildings']} buildings within 2 km; "
                     f"median ${C['rent_med']:,.0f}/mo (IQR ${C['rent_q1']:,.0f}–{C['rent_q3']:,.0f}) at median {C['sf_med']:.0f} sf. "
                     f"Unit rent = ${C['fit'][0]:,.0f} + ${C['fit'][1]:.2f} × sf (straight-line fit to the comps).", fontsize=8.3)
    y -= 0.024
    for k, (v, lo, hi, src) in MONEY.items():
        val = f"{v:.2%}" if v < 1 else f"${v:,.2f}" if v < 100 else f"${v:,.0f}"
        ax.text(0.01, y, f"{k}: {val}  (range {lo}–{hi})  —  {src}", fontsize=8)
        y -= 0.022
    ax.text(0.01, y - 0.004, "80/20 mixed = 20% of units (the smallest) at the 80% AMI rent, which also exempts the project from the linkage fee.", fontsize=8, color="#555")
    y -= 0.022
    ax.text(0.01, y - 0.01, "Costs are applied to the whole gross floor (25,700 sf), so space that can't be rented (core, corridor, amenity) still costs money. "
                            "Yield on cost = stabilised NOI ÷ total cost. Draft for checking; not investment advice.", fontsize=8, color="#555")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["base", "layout", "all"])
    ap.add_argument("--data", type=Path, default=Path("web/walkthrough/data"))
    ap.add_argument("--kit", type=Path, default=Path.home() / "Downloads/hackprinceton/costar-hackathon-kit")
    ap.add_argument("--out", type=Path, default=Path("web/walkthrough/data/studies"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    S, SH, fill = load(args.data)

    if args.cmd in ("base", "all"):
        render_base(SH, S, fill, args.out / "01-empty-floor.png")
        print("wrote", args.out / "01-empty-floor.png")
    if args.cmd == "base":
        return

    C = comps(args.kit, 34.058653, -118.443137)   # 10880 Wilshire, CoStar property 246826
    res, ok = {}, True
    for sch in ["A", "B"]:
        units, problems = layout(SH, sch)
        A = areas(SH, units)
        colrep = column_report(SH, units)
        worst = egress(SH, units)
        fin = {s: finance(units, A, C, s) for s in ["market", "mixed", "affordable"]}
        fin_cases = {c: finance(units, A, C, "market", c) for c in ["low", "mid", "high"]}
        for u in units:
            u["rent_market"] = round(unit_rent(u, C))
        res[sch] = dict(units=units, areas=A, colrep=colrep, fin=fin, fin_cases=fin_cases, worst=worst, problems=problems)
        fname = {"A": "02-scheme-A-min.png", "B": "03-scheme-B-market.png"}[sch]
        render_layout(SH, S, fill, units, A, colrep, sch, args.out / fname, worst, C, fin)
        print("wrote", args.out / fname)
        col_bad = [r for r in colrep if not r["ok"]]
        print(f"\nScheme {sch}: {len(units)} units, {A['units_sf']:,} sf, efficiency {A['efficiency']:.0%}, worst egress {worst:.0f} m")
        print("  unit checks:", "all pass" if not problems else problems)
        print("  columns:", "all ok" if not col_bad else [(r["i"], r["where"]) for r in col_bad])
        if worst > RULES["travel_max_m"]:
            problems.append("travel distance")
        ok = ok and not problems and not col_bad
        out = dict(scheme=sch, title=SCHEMES[sch]["title"], coords="scan metres (x, y), same as shell.json",
                   areas={k: v for k, v in A.items() if not k.endswith("_geom")},
                   units=[{k: v for k, v in u.items() if k not in ("s",)} for u in units],
                   corridor=dict(ring_inner=RING_IN, width_m=CW, connectors=CONNECTORS),
                   columns=colrep, finance={k: {kk: vv for kk, vv in f.items() if kk != "rents"} for k, f in fin.items()})
        (args.out / f"layout-{sch}.json").write_text(json.dumps(out, indent=1, default=float))
    render_money(res, C, args.out / "04-cost-benefit.png")
    print("wrote", args.out / "04-cost-benefit.png")
    (args.out / "summary.json").write_text(json.dumps(dict(
        comps={k: v for k, v in C.items() if k != "rows"},
        schemes={s: dict(units=len(r["units"]), areas={k: v for k, v in r["areas"].items() if not k.endswith("_geom")},
                         worst_egress_m=r["worst"], columns=r["colrep"],
                         finance={k: {kk: vv for kk, vv in f.items() if kk != "rents"} for k, f in r["fin"].items()},
                         cost_cases={k: {kk: vv for kk, vv in f.items() if kk != "rents"} for k, f in r["fin_cases"].items()})
                 for s, r in res.items()}), indent=1, default=float))
    print("\nALL CHECKS PASS" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
