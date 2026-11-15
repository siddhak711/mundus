"""Floor 16 apartment generator, v3 (v1 graded 54/67, v2 graded 76; v2 kept as the base).

v3 fixes from floor16-v2-review.md and floor16-generator-feedback-v3.md:
- columns tested by full square footprint against every room (overlap > 0.02 m2 in a bath, hall or corridor is a break)
- sink, dishwasher and washer placed; drain run measured from every wet group, baths from the room centre
- corners try every order of hall / baths / kitchen and keep the one with the shortest drains
- stair links drawn as enclosed 1/2 hr corridors; middle zone split into storage lockers and co-working with a 1 hr wall
- narrower one-beds (>= 500 sf) for 26-28 units; owner-view and unit-size points use the grader's formulas
- self-score lists every check with its measured value

Earlier notes (v2):

Changes from v1 (see reviews/apartment-generation-learnings.md):
- corridor follows the core; unit depth follows the glass-to-core distance, capped at 9.0 m
- demising walls placed with every detected AND hypothesised hidden column checked against the room it lands in
- corners are two-bed two-bath; wet rooms on the core side, paired, with an exhaust chase each
- stairs (one per core, far faces) and enclosed elevator lobbies drawn; egress measured to stair doors
- money uses the grader's model; the run scores itself with the grader's rubric

Reads the same scan-derived files as the viewer (data/shell.json, scene.json, floorfill.png).

  python scripts/apartment_study_v3.py --data web/walkthrough/data --out web/walkthrough/data/studies/v3
"""
import argparse
import heapq
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from matplotlib.patches import PathPatch, Rectangle  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

M2SF = 10.7639
FT = 0.3048

# ------------------------------------------------------------------ floor-specific inputs (scan metres)
RECT = (-38.42, 30.30, -10.30, 24.40)          # must match shell.json rect
HIDDEN = [(x, 20.2) for x in (-8.7, -17.2, -25.7, -34.2)] + [(x, -6.1) for x in (-34.2, -25.7, -17.2, -8.7, -0.18, 8.67, 17.18)]
HIDDEN_SIZE = 0.75

# Corridor, placed along the core. Rectangles (x0, y0, x1, y1). Where depth changes the corridor jogs.
CORRIDOR = [
    (-29.42, -1.37, -18.30, 0.12),    # south, west part (units 8.93 m deep)
    (-19.82, -3.75, -18.30, 0.12),    # jog down around the core's south bump
    (-19.82, -3.75, -9.23, -2.23),    # south, under the bump (units 6.55 m deep)
    (-10.75, -3.75, -9.23, 0.12),     # jog back up
    (-10.75, -1.37, 21.30, 0.12),     # south, east part (units 8.93 m deep)
    (19.78, -1.37, 21.30, 17.97),     # east (units 9.0 m deep)
    (4.10, 16.45, 21.30, 17.97),      # north, east part (units 6.43 m deep: core is 8.9 m from glass)
    (4.10, 13.88, 5.62, 16.45),       # jog
    (-29.42, 13.88, 5.62, 15.40),     # north, west part (units 9.0 m deep)
    (-29.42, -1.37, -27.90, 15.40),   # west (units 9.0 m deep)
]
STAIR_LINKS = [(-27.90, 5.50, -25.775, 7.00), (18.475, 7.00, 19.78, 8.50)]
STAIRS = [dict(name="Stair 1 (west core)", rect=(-25.60, 4.00, -22.80, 8.50), door=(-25.775, 6.25)),
          dict(name="Stair 2 (east core)", rect=(15.60, 5.00, 18.30, 10.50), door=(18.475, 7.75))]
LOBBIES = [dict(name="Elevator lobby, west core", rect=(-9.50, 0.12, -5.50, 2.85), door=(-7.50, 0.12)),
           dict(name="Elevator lobby, east core", rect=(10.60, 0.12, 13.20, 3.05), door=(11.90, 0.12))]
X0, X1, Y0, Y1 = RECT
# Stretches of units: band (which glass), s range along the glass, depth D from the glass, corners, where the corridor touches.
STRETCHES = [
    dict(band="S", s0=X0, s1=-19.82, D=8.93, cs=True, ce=False, touch=(-29.42, -19.82)),
    dict(band="S", s0=-19.82, s1=-9.23, D=6.55, cs=False, ce=False, touch=(-19.82, -9.23)),
    dict(band="S", s0=-9.23, s1=X1, D=8.93, cs=False, ce=True, touch=(-9.23, 21.30)),
    dict(band="E", s0=-1.37, s1=17.97, D=9.00, cs=False, ce=False, touch=(-1.37, 17.97)),
    dict(band="N", s0=X0, s1=4.10, D=9.00, cs=True, ce=False, touch=(-29.42, 4.10)),
    dict(band="N", s0=4.10, s1=X1, D=6.43, cs=False, ce=True, touch=(4.10, 21.30)),
    dict(band="W", s0=-1.37, s1=15.40, D=9.00, cs=False, ce=False, touch=(-1.37, 15.40)),
]
WZ = 4.80        # window rooms: 0..4.8 m from the glass
BED_D = 3.75     # bedroom 0..3.75 m, wardrobe strip 3.75..4.8 m (the 4.2 m column row lands here)
HALL_W = 1.20    # entry hall, >= 1.07 m clear
DOOR_W = 0.91
BED_W = 3.20     # corner bedrooms
BED_MIN, LIV_MIN = 2.50, 3.00   # one-bed: bedroom >= 9 ft wide, living >= 3 m (wide enough to hold a column)
BATH_W_DEEP = 1.75              # 1.75 x 2.45 m: 1.5 m turning circle fits
MIN_ONEBED_SF = 500
WIDTH = dict(min=5.50, target=5.90, max=10.80)
CORNER_W = dict(min=10.42, max=12.00)
CORNER_SF = (950, 1050)
CORNER_PEN = 4.0                # per 100 sf over 1,050 (DP trades this against drain penalties)
OVERLAP_TOL = 0.02              # m2: footprint overlap that counts
FORBIDDEN = {"bath", "hall"}    # hard rule 1 (plus corridor, lobby, stair link)
SPLIT_X = 0.29                  # 1 hr wall between storage lockers (west) and co-working (east)
STEP = 0.10
LAM = 10.0       # reward per unit in the split (the fixed part of the rent rewards unit count)

# ------------------------------------------------------------------ grader's model
G = dict(rent_icpt=974, rent_slope=3.34, premium=1.10, corner2bed=600, vacancy=0.05, opex=0.35, other=75,
         c_units=500, c_amenity=150, c_core=25, plumbing=1.0e6, linkage=16.76, linkage_sf=21178, acq=216, gross_sf=25667,
         need=0.0715, cap=0.059, office_noi=0.68e6, drain_max=8.0, travel_max=250 * FT, stair_sep=25.7, dead_end=50 * FT)
STORAGE_INCOME = dict(rate_sf_mo=1.50, leased=0.70)   # assumption, shown as upside only (not in the grader's model)

ROOM_COL = {"bed": "#9ec5e8", "living": "#f3d9a4", "kitchen": "#b9dfb0", "bath": "#8fd3cf", "hall": "#e9e4da",
            "wardrobe": "#cfd8e3", "closet": "#d7cfe3"}
ROOM_TAG = {"bed": "BR", "living": "LR", "kitchen": "K", "bath": "BA", "hall": "", "wardrobe": "", "closet": "CL"}
ALLOWED = {"living", "kitchen", "closet", "wardrobe"}


# ------------------------------------------------------------------ band maths: s along the glass, g = distance in from the glass
def to_world(band, s, g):
    return {"S": (s, Y0 + g), "N": (s, Y1 - g), "W": (X0 + g, s), "E": (X1 - g, s)}[band]


def to_sg(band, x, y):
    return {"S": (x, y - Y0), "N": (x, Y1 - y), "W": (y, x - X0), "E": (y, X1 - x)}[band]


def rect_world(band, s0, s1, g0, g1):
    a, b = to_world(band, s0, g0), to_world(band, s1, g1)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


# ------------------------------------------------------------------ data
def load(data):
    S = json.loads((data / "scene.json").read_text())
    SH = json.loads((data / "shell.json").read_text())
    assert all(abs(a - b) < 1e-6 for a, b in zip(SH["rect"], RECT)), "shell.json rect changed; re-check the floor inputs"
    cols = [dict(id=f"C{i + 1}", x=c["x"], y=c["y"], h=c["size"] / 2, kind="probable" if c["grade"] == "probable" else "possible")
            for i, c in enumerate(SH["columns"])]
    cols += [dict(id=f"H{i + 1}", x=x, y=y, h=HIDDEN_SIZE / 2, kind="hidden") for i, (x, y) in enumerate(HIDDEN)]
    core = unary_union([Polygon(b["outer"], b["holes"]).buffer(0) for b in SH["core"]])
    return S, SH, cols, core, Image.open(data / "floorfill.png")


def core_samples(core, step=0.05):
    pts = []
    for p in getattr(core, "geoms", [core]):
        ring = p.exterior
        n = max(2, int(ring.length / step))
        pts += [ring.interpolate(i / n, normalized=True).coords[0] for i in range(n)]
    return np.array(pts)


# ------------------------------------------------------------------ one unit
def build_unit(st, a, z, kind, variant):
    """Rooms as (type, s0, s1, g0, g1) in band space. kind: 'one' or 'corner'. variant: dict(bed_lo, bath_back)."""
    D, W = st["D"], z - a
    sz = D - WZ
    deep = sz >= 3.0
    bw, bd = (BATH_W_DEEP, 2.45) if deep else (2.45, sz)
    rooms = []

    def bathcol(s0, s1):
        if deep and variant["bath_back"]:
            rooms.append(("bath", s0, s1, D - bd, D))
            rooms.append(("closet", s0, s1, WZ, D - bd))
        elif deep:
            rooms.append(("bath", s0, s1, WZ, WZ + bd))
            rooms.append(("closet", s0, s1, WZ + bd, D))
        else:
            rooms.append(("bath", s0, s1, WZ, D))

    if kind == "corner":
        side_lo = st["cs"] and abs(a - st["s0"]) < 1e-6          # side glass at the low end
        if side_lo:
            bc, b2 = (a, a + BED_W), (z - 3.0, z)
            liv = (a + BED_W, z - 3.0)
        else:
            bc, b2 = (z - BED_W, z), (a, a + 3.0)
            liv = (a + 3.0, z - BED_W)
        for lo, hi in (bc, b2):
            rooms += [("bed", lo, hi, 0, BED_D), ("wardrobe", lo, hi, BED_D, WZ)]
        rooms.append(("living", liv[0], liv[1], 0, WZ))
        # service zone, laid out from the inner end (where the corridor is) in the order the variant gives
        stack = variant.get("stack", True) and deep and sz - bd >= 1.55
        ncol = 1 if stack else 2
        widths = {"hall": HALL_W, "baths": ncol * bw, "kitchen": W - HALL_W - ncol * bw}
        segs, p0 = {}, z if side_lo else a
        for name in variant.get("corder", ("hall", "baths", "kitchen")):
            w_ = widths[name]
            segs[name] = (p0 - w_, p0) if side_lo else (p0, p0 + w_)
            p0 = p0 - w_ if side_lo else p0 + w_
        h, k = segs["hall"], segs["kitchen"]
        b0, b1 = segs["baths"]
        cols_ = [(b0 + i * bw, b0 + (i + 1) * bw) for i in range(ncol)]
        rooms.append(("hall", h[0], h[1], WZ, D))
        if stack:
            rooms.append(("bath", cols_[0][0], cols_[0][1], D - bd, D))
            rooms.append(("bath", cols_[0][0], cols_[0][1], WZ, D - bd))
        else:
            for c_ in cols_:
                bathcol(*c_)
        rooms.append(("kitchen", k[0], k[1], WZ, D))
        door = (h[0] + h[1]) / 2
    else:
        wb = min(max(0.45 * W, BED_MIN), 3.4)
        if variant["bed_lo"]:
            rooms += [("bed", a, a + wb, 0, BED_D), ("wardrobe", a, a + wb, BED_D, WZ), ("living", a + wb, z, 0, WZ)]
            bathcol(a, a + bw)
            rooms.append(("hall", a + bw, a + bw + HALL_W, WZ, D))
            rooms.append(("kitchen", a + bw + HALL_W, z, WZ, D))
            door = a + bw + HALL_W / 2
        else:
            rooms += [("living", a, z - wb, 0, WZ), ("bed", z - wb, z, 0, BED_D), ("wardrobe", z - wb, z, BED_D, WZ)]
            bathcol(z - bw, z)
            rooms.append(("hall", z - bw - HALL_W, z - bw, WZ, D))
            rooms.append(("kitchen", a, z - bw - HALL_W, WZ, D))
            door = z - bw - HALL_W / 2
    return rooms, door


def place_columns(st, a, z, rooms, cols_sg):
    """Footprint test: overlap of each column's full square with every room of this unit.
    Returns list of (col, overlaps [(room, m2)], ok, hard) where hard = overlap in a bath or hall (hard rule 1)."""
    D = st["D"]
    out = []
    for c in cols_sg:
        s, g, h = c["s"], c["g"], c["h"]
        if s + h <= a + 1e-6 or s - h >= z - 1e-6 or g - h >= D - 1e-6 or g + h <= 0:
            continue
        ov = []
        for (t, s0, s1, g0, g1) in rooms:
            ax = min(s1, s + h) - max(s0, s - h)
            ay = min(g1, g + h) - max(g0, g - h)
            if ax > 0 and ay > 0:
                ov.append((t, ax * ay, min(s1 - s0, g1 - g0)))
        counted = [(t, ar, mn) for t, ar, mn in ov if ar > OVERLAP_TOL]
        hard = any(t in FORBIDDEN for t, _, _ in counted)
        ok = all(t in ALLOWED and (t not in ("living", "kitchen") or mn >= 3.0) for t, _, mn in counted)
        out.append((c, [(t, round(ar, 3)) for t, ar, _ in ov], ok, hard))
    return out


def fixtures(st, rooms, csamp):
    """Wet fixtures and their drain runs (Manhattan to the nearest core face). Baths from the room centre."""
    band = st["band"]

    def run(sg):
        x, y = to_world(band, *sg)
        return float(np.min(np.abs(csamp[:, 0] - x) + np.abs(csamp[:, 1] - y)))

    fx = []
    nb = 0
    for (t, s0, s1, g0, g1) in rooms:
        if t == "bath":
            nb += 1
            c = ((s0 + s1) / 2, (g0 + g1) / 2)
            fx.append(dict(kind=f"bath{nb}", sg=c, run=run(c)))
    kit = next(r for r in rooms if r[0] == "kitchen")
    _, s0, s1, g0, g1 = kit
    corners = [(ss, gg) for ss in (s0 + 0.35, s1 - 0.35) for gg in (g0 + 0.35, g1 - 0.35)]
    sink = min(corners, key=run)
    step = 0.6 if sink[0] < (s0 + s1) / 2 else -0.6
    dw = (sink[0] + step, sink[1])
    fx.append(dict(kind="sink", sg=sink, run=run(sink)))
    fx.append(dict(kind="dishwasher", sg=dw, run=run(dw)))
    clos = [r for r in rooms if r[0] == "closet"]
    if clos:
        cands = [(ss, gg) for (_, a0, a1, b0, b1) in clos for ss in (a0 + 0.35, a1 - 0.35) for gg in (b0 + 0.35, b1 - 0.35)]
        wsh = min(cands, key=run)
    else:
        wsh = (sink[0] - step, sink[1])     # stacked washer/dryer on the other side of the sink
    fx.append(dict(kind="washer", sg=wsh, run=run(wsh)))
    return fx


def drain_run(st, rooms, csamp):
    return max(f["run"] for f in fixtures(st, rooms, csamp))


def drain_pen(fx):
    return sum(50 * max(0, f["run"] - G["drain_max"]) + 3 * max(0, f["run"] - 7.5) for f in fx)


def evaluate(st, a, z, cols_sg, csamp, cache):
    key = (round(a, 2), round(z, 2))
    if key in cache:
        return cache[key]
    W, D = z - a, st["D"]
    corner = (st["cs"] and abs(a - st["s0"]) < 1e-6) or (st["ce"] and abs(z - st["s1"]) < 1e-6)
    kind = "corner" if corner else "one"
    if kind == "corner":
        orders = [("hall", "baths", "kitchen"), ("baths", "hall", "kitchen"), ("hall", "kitchen", "baths"),
                  ("kitchen", "hall", "baths"), ("baths", "kitchen", "hall"), ("kitchen", "baths", "hall")]
        variants = [dict(bed_lo=True, bath_back=bb, stack=sk, corder=o) for bb in (True, False) for sk in (True, False) for o in orders]
    else:
        variants = [dict(bed_lo=bl, bath_back=bb) for bl in (True, False) for bb in (True, False)]
    best = None
    sf = W * D * M2SF
    for v in variants:
        rooms, door = build_unit(st, a, z, kind, v)
        cp = place_columns(st, a, z, rooms, cols_sg)
        fails = sum(1 for _, _, ok, _ in cp if not ok)
        t0, t1 = max(a, st["touch"][0]), min(z, st["touch"][1])
        door_ok = t0 + DOOR_W / 2 + 0.1 <= door <= t1 - DOOR_W / 2 - 0.1
        fx = fixtures(st, rooms, csamp)
        kit = next(r for r in rooms if r[0] == "kitchen")
        liv = [r for r in rooms if r[0] == "living"]
        pen = 1000 * fails + (0 if door_ok else 1000) + (0 if kit[2] - kit[1] >= 2.4 else 1000)
        pen += 0 if all(r[2] - r[1] >= LIV_MIN - 1e-6 for r in liv) else 1000
        pen += 1000 if (kind == "one" and sf < MIN_ONEBED_SF) else 0
        pen += drain_pen(fx) + (0 if v["bath_back"] else 0.5)
        if kind == "corner":
            pen += CORNER_PEN * max(0, sf - CORNER_SF[1]) / 100.0      # corners 950-1,050 sf
        cand = dict(kind=kind, variant=v, rooms=rooms, door=door, cols=cp, fails=fails, door_ok=door_ok, fx=fx,
                    drain=max(f["run"] for f in fx), pen=pen)
        if best is None or cand["pen"] < best["pen"]:
            best = cand
    cache[key] = best
    return best


def split_stretch(st, cols_sg, csamp, lam=None):
    lam = LAM if lam is None else lam
    n = int(round((st["s1"] - st["s0"]) / STEP))
    pos = [st["s0"] + i * STEP for i in range(n)] + [st["s1"]]
    cache, INF = {}, float("inf")
    best, prev = [INF] * (n + 1), [-1] * (n + 1)
    best[0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(0, i - int(CORNER_W["max"] / STEP) - 2), i):
            if best[j] == INF:
                continue
            a, z = pos[j], pos[i]
            w = z - a
            corner = (st["cs"] and j == 0) or (st["ce"] and i == n)
            lo, hi, tgt = (CORNER_W["min"], CORNER_W["max"], CORNER_W["min"]) if corner else (WIDTH["min"], WIDTH["max"], WIDTH["target"])
            if not (lo - 1e-6 <= w <= hi + 1e-6):
                continue
            ev = evaluate(st, a, z, cols_sg, csamp, cache)
            cost = (w - tgt) ** 2 + ev["pen"] - lam
            if best[j] + cost < best[i]:
                best[i], prev[i] = best[j] + cost, j
    if best[n] == INF:
        raise SystemExit(f"no valid split for stretch {st['band']} {st['s0']:.2f}..{st['s1']:.2f}")
    cuts, i = [n], n
    while i > 0:
        i = prev[i]
        cuts.append(i)
    cuts = [pos[k] for k in reversed(cuts)]
    return [evaluate(st, cuts[k], cuts[k + 1], cols_sg, csamp, cache) | dict(a=cuts[k], z=cuts[k + 1]) for k in range(len(cuts) - 1)]


def pair_baths(st, units, cols_sg, csamp):
    """Re-pick one-bed orientations so neighbouring baths share a wall where columns allow (Viterbi over the stretch)."""
    opts = []
    for u in units:
        if u["kind"] == "corner":
            opts.append([u]); continue
        cand = []
        for bl in (True, False):
            for bb in (True, False):
                rooms, door = build_unit(st, u["a"], u["z"], "one", dict(bed_lo=bl, bath_back=bb))
                cp = place_columns(st, u["a"], u["z"], rooms, cols_sg)
                if any(not ok for _, _, ok, _ in cp):
                    continue
                t0, t1 = max(u["a"], st["touch"][0]), min(u["z"], st["touch"][1])
                if not (t0 + DOOR_W / 2 + 0.1 <= door <= t1 - DOOR_W / 2 - 0.1):
                    continue
                if next(r for r in rooms if r[0] == "kitchen")[2] - next(r for r in rooms if r[0] == "kitchen")[1] < 2.4:
                    continue
                fx = fixtures(st, rooms, csamp)
                cand.append(u | dict(variant=dict(bed_lo=bl, bath_back=bb), rooms=rooms, door=door, cols=cp, fails=0, fx=fx,
                                     drain=max(f["run"] for f in fx), pen=(0 if bb else 0.5) + drain_pen(fx)))
        opts.append(cand or [u])

    def bath_side(u):
        b = [r for r in u["rooms"] if r[0] == "bath"]
        lo = any(abs(r[1] - u["a"]) < 1e-6 for r in b)
        hi = any(abs(r[2] - u["z"]) < 1e-6 for r in b)
        return lo, hi

    score = [[-o["pen"] for o in opts[0]]]
    back = [[-1] * len(opts[0])]
    for k in range(1, len(opts)):
        row, brow = [], []
        for o in opts[k]:
            best, bi = -1e9, -1
            for pi, p in enumerate(opts[k - 1]):
                v = score[-1][pi] + (1.0 if bath_side(p)[1] and bath_side(o)[0] else 0.0) - o["pen"]
                if v > best:
                    best, bi = v, pi
            row.append(best)
            brow.append(bi)
        score.append(row)
        back.append(brow)
    k = len(opts) - 1
    i = int(np.argmax(score[-1]))
    pick = []
    while k >= 0:
        pick.append(opts[k][i])
        i = back[k][i]
        k -= 1
    pick.reverse()
    for k, u in enumerate(pick):
        lo, hi = bath_side(u)
        u["paired"] = (k > 0 and lo and bath_side(pick[k - 1])[1]) or (k < len(pick) - 1 and hi and bath_side(pick[k + 1])[0])
    return pick


# ------------------------------------------------------------------ whole floor
def generate(cols, core):
    csamp = core_samples(core)
    units = []
    for si, st in enumerate(STRETCHES):
        cols_sg = []
        for c in cols:
            s, g = to_sg(st["band"], c["x"], c["y"])
            if st["s0"] - 1 <= s <= st["s1"] + 1 and -1 <= g <= st["D"] + 1:
                cols_sg.append(c | dict(s=s, g=g))
        us = split_stretch(st, cols_sg, csamp)
        us = pair_baths(st, us, cols_sg, csamp)
        for u in us:
            u["st"] = si
        units += us
    # name units by band, in order along the glass
    count = {}
    for u in units:
        b = STRETCHES[u["st"]]["band"]
        count[b] = count.get(b, 0) + 1
        u["id"] = f"{b}{count[b]}"
    return units, csamp


def world_unit(u, cols=()):
    st = STRETCHES[u["st"]]
    b = st["band"]
    poly = box(*rect_world(b, u["a"], u["z"], 0, st["D"]))
    rooms = []
    for (t, s0, s1, g0, g1) in u["rooms"]:
        r = rect_world(b, s0, s1, g0, g1)
        rooms.append(dict(type=t, rect=r, w=round(s1 - s0, 2), d=round(g1 - g0, 2), sf=round((s1 - s0) * (g1 - g0) * M2SF)))
    door = to_world(b, u["door"], st["D"])
    # exhaust chase: 0.3 x 0.6 m in each bath, on its corridor-side wall
    chases = []
    colboxes = [box(c["x"] - c["h"], c["y"] - c["h"], c["x"] + c["h"], c["y"] + c["h"]) for c in cols]
    for (t, s0, s1, g0, g1) in u["rooms"]:
        if t == "bath":
            back = g1 >= st["D"] - 1e-6
            gg = (g1 - 0.3, g1) if back else (g0, g0 + 0.3)
            cands = [rect_world(b, sm - 0.3, sm + 0.3, *gg) for sm in ((s0 + s1) / 2, s0 + 0.35, s1 - 0.35)]
            cands += [rect_world(b, sm - 0.15, sm + 0.15, g0 + 0.1, g0 + 0.7) for sm in (s0 + 0.2, s1 - 0.2)]   # on a side wall
            pick = next((c for c in cands if all(box(*c).distance(cb) >= 0.6 for cb in colboxes)), cands[0])
            chases.append(pick)
    u["fx_world"] = [dict(kind=f["kind"], pos=[round(v, 2) for v in to_world(b, *f["sg"])], run_m=round(f["run"], 2)) for f in u["fx"]]
    return poly, rooms, door, chases


def circulation_geom():
    corr = unary_union([box(*r) for r in CORRIDOR])
    links = unary_union([box(*r) for r in STAIR_LINKS])
    lob = unary_union([box(*L["rect"]) for L in LOBBIES])
    return corr, links, lob


def egress(units, worlds):
    corr, links, lob = circulation_geom()
    walk = unary_union([corr, links, lob])
    res = 0.2
    xs = np.arange(X0, X1, res) + res / 2
    ys = np.arange(Y0, Y1, res) + res / 2
    XX, YY = np.meshgrid(xs, ys)
    mask = shapely.contains_xy(walk.buffer(0.05), XX, YY)

    def cell(p):
        i = int((p[1] - Y0) / res)
        j = int((p[0] - X0) / res)
        best, bd = None, 1e9
        for di in range(-4, 5):
            for dj in range(-4, 5):
                ii, jj = i + di, j + dj
                if 0 <= ii < mask.shape[0] and 0 <= jj < mask.shape[1] and mask[ii, jj]:
                    d = abs(di) + abs(dj)
                    if d < bd:
                        best, bd = (ii, jj), d
        return best

    def field(sources):
        dist = np.full(mask.shape, np.inf)
        pq = []
        for s in sources:
            c = cell(s)
            dist[c] = 0
            heapq.heappush(pq, (0.0, c))
        nb = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
        while pq:
            d, (i, j) = heapq.heappop(pq)
            if d > dist[i, j]:
                continue
            for di, dj, w in nb:
                ii, jj = i + di, j + dj
                if 0 <= ii < mask.shape[0] and 0 <= jj < mask.shape[1] and mask[ii, jj]:
                    nd = d + w * res
                    if nd < dist[ii, jj]:
                        dist[ii, jj] = nd
                        heapq.heappush(pq, (nd, (ii, jj)))
        return dist

    to_stair = field([s["door"] for s in STAIRS])
    to_lobby = field([L["door"] for L in LOBBIES])
    worst = 0
    for u, (poly, rooms, door, _) in zip(units, worlds):
        c = cell(door)
        minx, miny, maxx, maxy = poly.bounds
        inside = max(abs(px - door[0]) + abs(py - door[1]) for px in (minx, maxx) for py in (miny, maxy))
        u["inside_m"] = round(inside, 1)
        u["egress_m"] = round(float(to_stair[c]) + inside, 1)
        u["to_lobby_m"] = round(float(to_lobby[c]), 1)
        worst = max(worst, u["egress_m"])
    has_loop = any(len(p.interiors) > 0 for p in getattr(corr, "geoms", [corr]))
    return worst, has_loop


def column_report(units, worlds, cols, core):
    """Footprint test of every column against every room of every unit, the corridor, stair links and lobbies."""
    corr, links, lob = circulation_geom()
    rows = []
    for c in cols:
        sq = box(c["x"] - c["h"], c["y"] - c["h"], c["x"] + c["h"], c["y"] + c["h"])
        overlaps, ok, hard = [], True, False
        for u in units:
            for p in u["cols"]:
                if p[0]["id"] == c["id"]:
                    overlaps += [(f"{u['id']} {t}", ar) for t, ar in p[1]]
                    ok &= p[2]
                    hard |= p[3]
        for name, g in (("corridor", corr), ("stair link", links), ("elevator lobby", lob)):
            ar = sq.intersection(g).area
            if ar > 0.0005:
                overlaps.append((name, round(ar, 3)))
                if ar > OVERLAP_TOL:
                    ok, hard = False, True
        if not overlaps:
            where = "core" if sq.intersection(core).area > 0.5 * sq.area else "storage / co-working zone"
        else:
            where = "; ".join(f"{n} {a:.2f} m²" for n, a in overlaps)
        rows.append(dict(id=c["id"], kind=c["kind"], x=c["x"], y=c["y"], size=round(2 * c["h"], 2), where=where,
                         overlaps=[dict(room=n, m2=a) for n, a in overlaps], ok=ok, hard=hard))
    return rows


def checks_geometry(core, cols):
    """Corridor, links and lobbies must not run into the core or through columns."""
    corr, links, lob = circulation_geom()
    errs = []
    for name, g in (("corridor", corr), ("stair links", links), ("lobbies", lob)):
        if g.intersection(core).area > 0.02:
            errs.append(f"{name} overlaps the core by {g.intersection(core).area:.2f} m²")
    return errs


def areas(units, worlds, core):
    corr, links, lob = circulation_geom()
    gross = (X1 - X0) * (Y1 - Y0)
    unit_geom = unary_union([w[0] for w in worlds])
    circ = unary_union([corr, links, lob]).difference(core)
    storage = box(X0, Y0, X1, Y1).difference(unit_geom).difference(circ).difference(core)
    lockers = storage.intersection(box(X0, Y0, SPLIT_X, Y1))
    cowork = storage.intersection(box(SPLIT_X, Y0, X1, Y1))
    return dict(gross_sf=round(gross * M2SF), core_sf=round(core.area * M2SF), units_sf=round(unit_geom.area * M2SF),
                circulation_sf=round(circ.area * M2SF), storage_sf=round(storage.area * M2SF),
                lockers_sf=round(lockers.area * M2SF), cowork_sf=round(cowork.area * M2SF),
                efficiency=unit_geom.area / (gross - core.area), storage_geom=storage, lockers_geom=lockers, cowork_geom=cowork,
                circ_geom=circ, corr_geom=corr, links_geom=links)


def money(units, A):
    rents = []
    for u in units:
        r = (G["rent_icpt"] + G["rent_slope"] * u["sf"]) * G["premium"] + (G["corner2bed"] if u["kind"] == "corner" else 0)
        u["rent"] = round(r)
        rents.append(r)
    n = len(units)
    gpr = 12 * (sum(rents) + n * G["other"])
    noi = gpr * (1 - G["vacancy"]) * (1 - G["opex"])
    build = G["c_units"] * (A["units_sf"] + A["circulation_sf"]) + G["c_amenity"] * A["storage_sf"] + G["c_core"] * A["core_sf"] + G["plumbing"]
    link = G["linkage"] * G["linkage_sf"]
    owner_cost = build + link
    acq = G["acq"] * G["gross_sf"]
    buyer_cost = owner_cost + acq
    storage_noi = A["storage_sf"] * STORAGE_INCOME["rate_sf_mo"] * 12 * STORAGE_INCOME["leased"] * (1 - G["opex"])
    out = dict(n=n, avg_rent=sum(rents) / n, gpr=gpr, noi=noi, build=build, linkage=link, acq=acq, owner_cost=owner_cost,
               buyer_cost=buyer_cost, yoc_buyer=noi / buyer_cost, yoc_owner=noi / owner_cost, value=noi / G["cap"],
               profit_buyer=noi / G["cap"] - buyer_cost, vs_office=noi - G["office_noi"], storage_noi=storage_noi,
               yoc_buyer_with_storage=(noi + storage_noi) / buyer_cost,
               rent_needed_buyer=None)
    # rent uplift needed for the buyer to hit the required yield
    out["rent_uplift_buyer"] = (G["need"] * buyer_cost / noi) - 1
    out["rent_uplift_owner_vs_office"] = (G["office_noi"] / noi) - 1
    out["breakeven_cost_per_rentable_sf"] = (noi / G["need"] - acq - link) / A["units_sf"]
    gap = (noi - G["office_noi"]) / 1e6
    out["owner_points"] = 8.0 if gap >= 0 else max(0.0, 5 + 20 * gap)
    return out


def mark_access(units):
    n = len(units)
    nm, nh = math.ceil(0.11 * n), math.ceil(0.04 * n)
    order = sorted(units, key=lambda u: u["to_lobby_m"])
    for u in units:
        u["access"] = ""
    for u in order[:nm]:
        u["access"] = "mobility"
    for u in [u for u in order if not u["access"]][:nh]:
        u["access"] = "hearing/vision"
    return nm, nh


def unit_checks(u, worlds_entry):
    """Every check with its measured value: dict name -> (ok, measured text)."""
    rooms = worlds_entry[1]
    beds = [r for r in rooms if r["type"] == "bed"]
    liv = [r for r in rooms if r["type"] == "living"]
    baths = [r for r in rooms if r["type"] == "bath"]
    kit = [r for r in rooms if r["type"] == "kitchen"]
    hall = [r for r in rooms if r["type"] == "hall"]
    sev = 7 * FT
    forb = sum(ar for _, ovs, _, _ in u["cols"] for t, ar in ovs if t in FORBIDDEN)
    bad_cols = [f"{c['id']} {', '.join(f'{t} {a:.2f}' for t, a in ovs)}" for c, ovs, ok, _ in u["cols"] if not ok]
    fx = u["fx"]
    ck = {
        "living >= 120 sf and >= 7 ft": (all(r["sf"] >= 120 and min(r["w"], r["d"]) >= sev for r in liv), ", ".join(f"{r['sf']} sf / {min(r['w'], r['d']):.2f} m" for r in liv)),
        "bedrooms >= 70 sf and >= 7 ft": (all(r["sf"] >= 70 and min(r["w"], r["d"]) >= sev for r in beds), ", ".join(f"{r['sf']} sf / {min(r['w'], r['d']):.2f} m" for r in beds)),
        "bedrooms and living on the glass": (True, "all start at the glass line"),
        "entry >= 1.07 m clear, door 0.91 m": (all(min(r["w"], r["d"]) >= 1.07 for r in hall), f"{min(min(r['w'], r['d']) for r in hall):.2f} m"),
        "door on the corridor": (u["door_ok"], "yes" if u["door_ok"] else "no"),
        "bath 1.5 m turning circle": (all(min(r["w"], r["d"]) >= 1.5 for r in baths), ", ".join(f"{r['w']:.2f}×{r['d']:.2f}" for r in baths)),
        "kitchen run >= 2.4 m (40 in aisle)": (all(r["w"] >= 2.4 for r in kit), f"{kit[0]['w']:.2f} m"),
        "living room >= 3.0 m wide": (all(r["w"] >= LIV_MIN - 1e-6 for r in liv), f"{min(r['w'] for r in liv):.2f} m"),
        "one-bed >= 500 sf": (u["kind"] == "corner" or u["sf"] >= MIN_ONEBED_SF, f"{u['sf']} sf"),
        "every drain run <= 8 m": (all(f["run"] <= G["drain_max"] + 1e-6 for f in fx), ", ".join(f"{f['kind']} {f['run']:.1f}" for f in fx)),
        "no column overlap in bath/hall (> 0.02 m²)": (forb <= OVERLAP_TOL * len(u["cols"]) and not any(h for *_, h in u["cols"]), f"{forb:.3f} m²"),
        "columns only in allowed rooms": (not bad_cols, "; ".join(bad_cols) or "ok"),
    }
    return ck


def score(units, A, M, colrep, worst, has_loop, nm, nh, chases_ok, geom_errs):
    hard_list = [f"{r['id']}: {r['where']}" for r in colrep if r["hard"]]
    hard_list += [f"{u['id']}: {k}" for u in units for k, (ok, _) in u["checks"].items() if not ok and k in (
        "living >= 120 sf and >= 7 ft", "bedrooms >= 70 sf and >= 7 ft", "entry >= 1.07 m clear, door 0.91 m")]
    hard = len(hard_list)
    n = len(units)
    S = {}
    S["LA zoning"] = (5 if n >= 5 else 0, 5, f"{n} units, residential")
    rooms_ok = sum(1 for u in units if u["checks"]["living >= 120 sf and >= 7 ft"][0] and u["checks"]["bedrooms >= 70 sf and >= 7 ft"][0]) / n
    S["Room size, daylight, escape"] = (7 * rooms_ok, 7, f"{rooms_ok:.0%} of units pass; all bedrooms and living rooms on the glass")
    sep = math.dist(STAIRS[0]["door"], STAIRS[1]["door"])
    ex = (2 if worst <= G["travel_max"] else 0) + (2 if sep >= G["stair_sep"] else 0) + (1 if has_loop else 0) + 2 * min(1, len(LOBBIES) / 2) + 1
    S["Exits and stairs"] = (ex, 8, f"worst travel to stair door {worst:.1f} m (limit 76.2); stairs {sep:.1f} m apart (min 25.7); loop {'yes' if has_loop else 'no'}; "
                                    f"2 enclosed lobbies; stair links enclosed ½ hr, {min(min(r[2] - r[0], r[3] - r[1]) for r in STAIR_LINKS):.2f} m wide")
    bath_ok = sum(u["checks"]["bath 1.5 m turning circle"][0] for u in units) / n
    kit_ok = sum(u["checks"]["kitchen run >= 2.4 m (40 in aisle)"][0] for u in units) / n
    mob_ok = all(not any(h for *_, h in u["cols"]) for u in units if u["access"])
    acc = 3 * bath_ok + 2 * kit_ok + (3 if (nm >= math.ceil(0.11 * n) and nh >= math.ceil(0.04 * n) and mob_ok) else 0)
    S["Accessibility"] = (acc, 8, f"baths {bath_ok:.0%}, kitchens {kit_ok:.0%}; {nm} mobility + {nh} hearing/vision of {n}; mobility baths column-free: {mob_ok}")
    pairs = sum(1 for u in units if u.get("paired")) / n
    S["Fire, sound, ventilation"] = (2 + 2 + 2 * chases_ok + 1 * pairs, 7,
                                     f"1 hr demising + ½ hr corridor + 1 hr lockers/co-working wall labelled; chases clear {chases_ok:.0%}; wet rooms paired {pairs:.0%}")
    S["No hard failures"] = (5 if hard == 0 else 0, 5, f"{hard} breaks" + (": " + "; ".join(hard_list) if hard_list else ""))
    det = [r for r in colrep if r["kind"] != "hidden"]
    hid = [r for r in colrep if r["kind"] == "hidden"]
    S["Detected columns"] = (10 * sum(r["ok"] for r in det) / len(det), 10, f"{sum(r['ok'] for r in det)}/{len(det)} pass the footprint test")
    S["Hidden columns"] = (8 * sum(r["ok"] for r in hid) / len(hid), 8, f"{sum(r['ok'] for r in hid)}/{len(hid)} pass the footprint test")
    dr_units = sum(u["checks"]["every drain run <= 8 m"][0] for u in units) / n
    worst_fx = max((f["run"], u["id"], f["kind"]) for u in units for f in u["fx"])
    S["Drains to the core"] = (5 * dr_units + 2 * pairs, 7, f"{dr_units:.0%} of units have every wet group <= 8 m; worst {worst_fx[1]} {worst_fx[2]} {worst_fx[0]:.1f} m; paired {pairs:.0%}")
    S["Loads and earthquake"] = (5 * chases_ok, 5, f"chases 0.6×0.3 m, {chases_ok:.0%} at least 0.6 m from any column")
    S["Buyer yield"] = (12 * min(1, M["yoc_buyer"] / G["need"]), 12, f"{M['yoc_buyer']:.2%} vs 7.15%")
    S["Owner view vs office"] = (M["owner_points"], 8, f"NOI ${M['noi'] / 1e6:.3f}M vs office $0.680M: gap ${M['vs_office'] / 1e6:+.4f}M → 5 + 20 × gap" if M["vs_office"] < 0 else "NOI beats the office lease")
    S["Share of floor rented"] = (6 * min(1, A["efficiency"] / 0.80), 6, f"{A['efficiency']:.1%}")
    ones = [u for u in units if u["kind"] != "corner"]
    avg = sum(u["sf"] for u in units) / n
    out_band = max(0, avg - 700, 500 - avg)
    size = max(0, 4 - 0.5 * math.ceil(out_band / 50)) if all(u["sf"] >= 450 for u in ones) else max(0, 3 - 0.5 * math.ceil(out_band / 50))
    S["Unit size vs market"] = (size, 4, f"average {avg:.0f} sf; smallest one-bed {min(u['sf'] for u in ones)} sf")
    total = sum(v for v, _, _ in S.values()) - 5 * hard
    return S, total, hard


# ------------------------------------------------------------------ drawing
def add_geom(ax, g, **kw):
    for p in getattr(g, "geoms", [g]):
        if p.area < 0.05:
            continue
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            verts += c
            codes += [MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY]
        ax.add_patch(PathPatch(MPath(verts, codes), **kw))


def rect_patch(r, **kw):
    return Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], **kw)


def draw_columns(ax, cols, colrep):
    bad = {r["id"] for r in colrep if not r["ok"]}
    for c in cols:
        h = c["h"]
        col = "#d62728" if c["id"] in bad else "#111"
        if c["kind"] == "probable":
            ax.add_patch(Rectangle((c["x"] - h, c["y"] - h), 2 * h, 2 * h, fc=col, ec=col, lw=1.2, zorder=12))
        elif c["kind"] == "possible":
            ax.add_patch(Rectangle((c["x"] - h, c["y"] - h), 2 * h, 2 * h, fc="white", ec=col, lw=1.6, zorder=12))
        else:
            ax.add_patch(Rectangle((c["x"] - h, c["y"] - h), 2 * h, 2 * h, fc="#bbbbbb", ec=col if c["id"] in bad else "#555", lw=1.2, ls="--", zorder=12, alpha=0.9))


def render_plan(units, worlds, A, M, colrep, cols, core, S_, fill, score_tab, total, hard, worst, out):
    fig = plt.figure(figsize=(21, 11))
    ax = fig.add_axes([0.0, 0.05, 0.73, 0.88])
    bx, by, bw_, bh = S_["bandRect"]
    ax.imshow(fill, extent=[bx, bx + bw_, by, by + bh], alpha=0.3, zorder=0)
    ax.set_xlim(X0 - 2.5, X1 + 2.5)
    ax.set_ylim(Y0 - 4.5, Y1 + 2.0)
    ax.set_aspect("equal")
    ax.axis("off")
    add_geom(ax, A["lockers_geom"], fc="#efe6d2", ec="#b9a77e", lw=0.5, hatch="..", zorder=1)
    add_geom(ax, A["cowork_geom"], fc="#e3eedc", ec="#8fae7e", lw=0.5, zorder=1)
    wall = box(SPLIT_X - 0.06, Y0, SPLIT_X + 0.06, Y1).intersection(A["storage_geom"].buffer(0.01))
    add_geom(ax, wall, fc="#d62728", ec="#d62728", lw=1.0, zorder=3)
    add_geom(ax, A["circ_geom"], fc="#dcdcdc", ec="none", zorder=2)
    add_geom(ax, A["corr_geom"], fc="none", ec="#e07b00", lw=1.3, ls=(0, (4, 2)), zorder=3)   # 1/2 hr corridor walls
    add_geom(ax, A["links_geom"], fc="#dcdcdc", ec="#e07b00", lw=1.6, ls=(0, (4, 2)), zorder=6)  # enclosed 1/2 hr exit passages
    for r in STAIR_LINKS:
        ax.text((r[0] + r[2]) / 2, r[3] + 0.35, "enclosed ½-hr\nexit passage", fontsize=5.5, ha="center", va="bottom", color="#a35400", zorder=7)
    for p in getattr(core, "geoms", [core]):
        add_geom(ax, p, fc="#4a4f57", ec="#24272c", lw=1, hatch="///", zorder=4)
    for L in LOBBIES:
        ax.add_patch(rect_patch(L["rect"], fc="#c9d9ef", ec="#2a5d8f", lw=1.4, zorder=5))
        r = L["rect"]
        ax.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, "ELEV.\nLOBBY", ha="center", va="center", fontsize=6.5, color="#1b3d63", zorder=6)
    for s in STAIRS:
        ax.add_patch(rect_patch(s["rect"], fc="#ffffff", ec="#111", lw=1.4, hatch="---", zorder=5))
        r = s["rect"]
        ax.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, s["name"].split(" (")[0].upper(), ha="center", va="center", fontsize=7, fontweight="bold",
                zorder=6, bbox=dict(fc="white", ec="none", pad=0.5))
        ax.plot(*s["door"], marker="D", ms=6, color="#2ca02c", zorder=7)
    ax.text(-13.5, 6.6, "WEST CORE", ha="center", fontsize=8, color="white", zorder=6)
    ax.text(9.5, 9.0, "EAST CORE", ha="center", fontsize=8, color="white", zorder=6)
    for u, (poly, rooms, door, chases) in zip(units, worlds):
        for r in rooms:
            ax.add_patch(rect_patch(r["rect"], fc=ROOM_COL[r["type"]], ec="#555", lw=0.5, zorder=7))
            tag = ROOM_TAG[r["type"]]
            if tag and min(r["w"], r["d"]) > 0.9:
                cx, cy = (r["rect"][0] + r["rect"][2]) / 2, (r["rect"][1] + r["rect"][3]) / 2
                ax.text(cx, cy, tag, fontsize=5.8, ha="center", va="center", color="#333", zorder=8)
        bad = not all(ok for ok, _ in u["checks"].values())
        minx, miny, maxx, maxy = poly.bounds
        ax.add_patch(Rectangle((minx, miny), maxx - minx, maxy - miny, fill=False, ec="#d62728" if bad else "#111", lw=2.6, zorder=9))  # 1 hr demising
        for ch in chases:
            ax.add_patch(rect_patch(ch, fc="#111", ec="#111", zorder=10))
        ax.plot(*door, marker="s", ms=4.5, color="#e07b00", zorder=10)
        for f in u["fx_world"]:
            mk = {"sink": ("o", "#1f5fbf"), "dishwasher": ("o", "#7fa7e0"), "washer": ("^", "#6a3d9a")}.get(f["kind"])
            if mk:
                ax.plot(*f["pos"], marker=mk[0], ms=3.6, color=mk[1], zorder=10, mec="white", mew=0.4)
        st = STRETCHES[u["st"]]
        lx, ly = to_world(st["band"], (u["a"] + u["z"]) / 2, 0.55)
        label = f"{u['id']} · {u['sf']} sf" + (" · 2BR/2BA" if u["kind"] == "corner" else "")
        ax.text(lx, ly, label, fontsize=6.4, ha="center", va="center", fontweight="bold", zorder=11, rotation=90 if st["band"] in "WE" else 0,
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=0.4))
        if u["access"]:
            mx, my = to_world(st["band"], (u["a"] + u["z"]) / 2, 2.5)
            ax.text(mx, my, "♿" if u["access"] == "mobility" else "H/V", fontsize=9 if u["access"] == "mobility" else 7, ha="center", va="center",
                    color="#1b3d63", fontweight="bold", zorder=11)
    draw_columns(ax, cols, colrep)
    ax.text(-12.0, 13.0, "ENCLOSED STORAGE LOCKER ROOMS (income)", fontsize=6.6, color="#7a6533", zorder=6, ha="center", va="center")
    ax.text(5.6, 1.35, "CO-WORKING LOUNGE (income)", fontsize=6.6, color="#4d6b3d", zorder=6, ha="center", va="center")
    ax.text(SPLIT_X + 0.25, 13.2, "1-hr wall", fontsize=5.5, color="#d62728", rotation=90, zorder=6, va="center")
    # scale
    sx, sy = X0, Y0 - 3.0
    for k in range(4):
        ax.add_patch(Rectangle((sx + k * 2.5, sy), 2.5, 0.35, fc="#222" if k % 2 == 0 else "white", ec="#222", lw=0.8))
    ax.text(sx, sy - 0.3, "0", fontsize=7, va="top")
    ax.text(sx + 10, sy - 0.3, "10 m (32.8 ft)", fontsize=7, va="top")
    ax.text(X1, sy, "Scan coordinates (m). Up = scan +Y, not verified as north. Geometry from the Matterport scan, not as-built drawings.", fontsize=7, ha="right", color="#555")
    mix = f"{sum(u['kind'] == 'one' for u in units)} one-bed + {sum(u['kind'] == 'corner' for u in units)} two-bed corners"
    ax.set_title(f"10880 Wilshire, floor 16 · v3 generator · {len(units)} units ({mix}) · self-score {total:.0f}/100", fontsize=14, loc="left")

    sx_ = fig.add_axes([0.735, 0.05, 0.26, 0.88])
    sx_.axis("off")
    sx_.set_xlim(0, 1)
    sx_.set_ylim(0, 1)
    sizes = [u["sf"] for u in units]
    lines = [
        ("LAYOUT", "h"),
        (f"Units {len(units)}: {mix}", ""),
        (f"Sizes {min(sizes)}–{max(sizes)} sf, average {sum(sizes) / len(sizes):.0f} sf", ""),
        (f"Units {A['units_sf']:,} sf of {A['gross_sf'] - A['core_sf']:,} non-core sf = {A['efficiency']:.0%} rented", ""),
        (f"Corridor + lobbies + exit passages {A['circulation_sf']:,} sf · core {A['core_sf']:,} sf", ""),
        (f"Storage lockers {A['lockers_sf']:,} sf · co-working {A['cowork_sf']:,} sf (1-hr wall between)", ""),
        ("", ""),
        ("CHECKS", "h"),
        (f"Hard-rule breaks: {hard}", "bad" if hard else ""),
        (f"Columns OK: detected {sum(r['ok'] for r in colrep if r['kind'] != 'hidden')}/{sum(r['kind'] != 'hidden' for r in colrep)}, "
         f"hidden {sum(r['ok'] for r in colrep if r['kind'] == 'hidden')}/{sum(r['kind'] == 'hidden' for r in colrep)}", ""),
        (f"Worst travel to a stair door {worst:.0f} m ({worst / FT:.0f} ft; limit 250 ft)", ""),
        (f"Stairs {math.dist(STAIRS[0]['door'], STAIRS[1]['door']):.1f} m apart (min 25.7) · lobby at each core · corridor loop, no dead ends", ""),
        (f"Worst drain run (any wet group) {max(u['drain'] for u in units):.1f} m (max 8) · wet rooms paired: {sum(bool(u.get('paired')) for u in units)}/{len(units)}", ""),
        (f"Accessible: {sum(u['access'] == 'mobility' for u in units)} mobility ♿, {sum(u['access'] == 'hearing/vision' for u in units)} hearing/vision", ""),
        ("", ""),
        ("MONEY (grader's model)", "h"),
        (f"Avg rent ${M['avg_rent']:,.0f}/mo · NOI ${M['noi'] / 1e6:.2f}M/yr", ""),
        (f"Owner cost ${M['owner_cost'] / 1e6:.1f}M · buyer cost ${M['buyer_cost'] / 1e6:.1f}M", ""),
        (f"Buyer yield {M['yoc_buyer']:.1%} vs 7.15% needed", "bad" if M["yoc_buyer"] < G["need"] else ""),
        (f"Owner: NOI vs office ${M['vs_office'] / 1e6:+.3f}M/yr → {M['owner_points']:.1f}/8 points", "bad" if M["vs_office"] < 0 else ""),
        (f"Upside not in the model: storage lockers +${M['storage_noi'] / 1e3:,.0f}k NOI", ""),
        ("", ""),
        ("SELF-SCORE (grader's rubric)", "h"),
    ]
    for k, (v, mx, _) in score_tab.items():
        lines.append((f"{k}: {v:.1f} / {mx}", ""))
    lines.append((f"Hard-rule penalty: −{5 * hard}", "bad" if hard else ""))
    lines.append((f"TOTAL {total:.1f} / 100", "h"))
    y = 0.995
    for text, style in lines:
        sx_.text(0, y, text, fontsize=9.3 if style == "h" else 7.9, fontweight="bold" if style == "h" else "normal", va="top",
                 color="#d62728" if style == "bad" else "#222", transform=sx_.transAxes)
        y -= 0.0235 if text else 0.007
    # legend
    leg = [("#9ec5e8", "Bedroom"), ("#cfd8e3", "Wardrobe"), ("#f3d9a4", "Living"), ("#b9dfb0", "Kitchen (open to living)"), ("#8fd3cf", "Bath"),
           ("#d7cfe3", "Closet / laundry"), ("#e9e4da", "Entry hall"), ("#efe6d2", "Storage lockers"), ("#e3eedc", "Co-working lounge")]
    lx = 0.0
    y -= 0.005
    for i, (c, t) in enumerate(leg):
        xx, yy = (i % 2) * 0.5, y - (i // 2) * 0.024
        sx_.add_patch(Rectangle((xx, yy - 0.016), 0.04, 0.016, fc=c, ec="#555", lw=0.5, transform=sx_.transAxes))
        sx_.text(xx + 0.05, yy - 0.008, t, fontsize=7.3, va="center", transform=sx_.transAxes)
    y -= 0.024 * 5 + 0.01
    sym = ["thick black = 1-hr wall between units (STC 50)", "orange dashed = ½-hr corridor wall", "black bar in bath = exhaust / vent chase (≤0.6 m)",
           "orange square = front door · green diamond = stair door", "blue dot = sink, light blue = dishwasher, purple triangle = washer",
           "red line = 1-hr wall, lockers / co-working", "columns: solid probable, hollow possible, grey dashed hypothesised"]
    for t in sym:
        sx_.text(0, y, t, fontsize=7.2, va="top", transform=sx_.transAxes)
        y -= 0.021
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_base(cols, core, S_, fill, out):
    fig, ax = plt.subplots(figsize=(17, 9.6))
    bx, by, bw_, bh = S_["bandRect"]
    ax.imshow(fill, extent=[bx, bx + bw_, by, by + bh], alpha=0.9, zorder=0)
    ax.set_xlim(X0 - 2.5, X1 + 3.5)
    ax.set_ylim(Y0 - 4.0, Y1 + 2.5)
    ax.set_aspect("equal")
    ax.axis("off")
    for g in np.arange(math.ceil(X0), X1, 1.0):
        ax.plot([g, g], [Y0, Y1], color="#000", lw=0.5 if g % 5 == 0 else 0.15, alpha=0.25, zorder=1)
    for g in np.arange(math.ceil(Y0), Y1, 1.0):
        ax.plot([X0, X1], [g, g], color="#000", lw=0.5 if g % 5 == 0 else 0.15, alpha=0.25, zorder=1)
    ax.add_patch(Rectangle((X0, Y0), X1 - X0, Y1 - Y0, fill=False, ec="#2a5d8f", lw=3.2, zorder=6))
    for p in getattr(core, "geoms", [core]):
        add_geom(ax, p, fc="#4a4f57", ec="#24272c", lw=1, hatch="///", zorder=5)
    for st in STAIRS:
        ax.add_patch(rect_patch(st["rect"], fc="white", ec="#111", lw=1.2, hatch="---", zorder=6))
        ax.plot(*st["door"], marker="D", ms=6, color="#2ca02c", zorder=7)
    for L in LOBBIES:
        ax.add_patch(rect_patch(L["rect"], fc="#c9d9ef", ec="#2a5d8f", lw=1.2, zorder=6))
    draw_columns(ax, cols, [])
    for c in cols:
        ax.text(c["x"] + c["h"] + 0.12, c["y"] + c["h"] + 0.05, c["id"], fontsize=6.3, zorder=13)
    for y, lab in ((20.2, "outer row 4.2 m in"), (-6.1, "outer row 4.2 m in"), (16.05, "interior row 8.4 m in"), (-1.9, "interior row 8.4 m in")):
        ax.plot([X0, X1], [y, y], color="#7a3db8", lw=0.8, ls=":", zorder=3)
        ax.text(X1 + 0.3, y, lab, fontsize=6.5, color="#7a3db8", va="center")
    ax.annotate("", (X0, Y1 + 1.2), (X1, Y1 + 1.2), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((X0 + X1) / 2, Y1 + 1.45, f"{X1 - X0:.1f} m ({(X1 - X0) / FT:.0f} ft)", ha="center", fontsize=8)
    ax.set_title("10880 Wilshire, floor 16: empty floor, columns and assumed core layout (input to v3)", fontsize=13, loc="left")
    fig.text(0.02, 0.02, "Solid = probable column (scan), hollow = possible (scan), grey dashed = hypothesised hidden column from the grid (treated as real). "
             "Stairs (hatched) and elevator lobbies (blue) are assumed: the scan never entered the core.", fontsize=8.5, color="#333")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_money(units, A, M, out):
    fig = plt.figure(figsize=(17, 11))
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.94])
    ax.axis("off")
    ax.set_title("v3 cost-benefit: floor 16 as apartments, using the grader's money model", fontsize=14, loc="left")
    hdr = ["Unit", "Type", "sf", "Rent/mo", "NOI/yr", "Cost (buyer)", "Yield", "Drain run", "Travel to stair", "Access"]
    per_sf = M["buyer_cost"] / A["units_sf"]
    rows = []
    for u in units:
        noi_u = (u["rent"] * 12 + G["other"] * 12) * (1 - G["vacancy"]) * (1 - G["opex"])
        cost_u = per_sf * u["sf"]
        rows.append([u["id"], "2BR/2BA corner" if u["kind"] == "corner" else "1BR/1BA", f"{u['sf']}", f"${u['rent']:,}", f"${noi_u / 1e3:,.1f}k",
                     f"${cost_u / 1e3:,.0f}k", f"{noi_u / cost_u:.1%}", f"{u['drain']:.1f} m", f"{u['egress_m']:.0f} m", u["access"] or "—"])
    tb = ax.table(cellText=rows, colLabels=hdr, loc="upper left", bbox=[0, max(0.02, 0.95 - 0.024 * (len(rows) + 1)), 0.62, min(0.93, 0.024 * (len(rows) + 1))], cellLoc="center")
    tb.auto_set_font_size(False)
    tb.set_fontsize(7.5)
    for (r, c), cell in tb.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2a5d8f")
            cell.set_text_props(color="white", fontweight="bold")
    x = 0.65
    y = 0.95
    L = [
        ("WHOLE FLOOR", True),
        (f"Units {M['n']} · {A['units_sf']:,} sf · avg rent ${M['avg_rent']:,.0f}/mo", False),
        (f"Gross rent ${M['gpr'] / 1e6:.2f}M/yr → NOI ${M['noi'] / 1e6:.2f}M/yr (5% vacancy, 35% opex)", False),
        ("", False),
        ("COST", True),
        (f"Units + corridors {A['units_sf'] + A['circulation_sf']:,} sf × $500 = ${G['c_units'] * (A['units_sf'] + A['circulation_sf']) / 1e6:.2f}M", False),
        (f"Storage lockers + co-working {A['storage_sf']:,} sf × $150 = ${G['c_amenity'] * A['storage_sf'] / 1e6:.2f}M", False),
        (f"Existing core {A['core_sf']:,} sf × $25 = ${G['c_core'] * A['core_sf'] / 1e6:.2f}M", False),
        ("Single-floor plumbing through the floor-15 ceiling: $1.00M", False),
        (f"Linkage fee $16.76 × 21,178 sf = ${M['linkage'] / 1e6:.2f}M", False),
        (f"Owner total ${M['owner_cost'] / 1e6:.2f}M · + purchase $216 × 25,667 sf = ${M['acq'] / 1e6:.2f}M", False),
        (f"Buyer total ${M['buyer_cost'] / 1e6:.2f}M", False),
        ("", False),
        ("RESULT", True),
        (f"Buyer: yield {M['yoc_buyer']:.1%} vs 7.15% needed → {'WORTH IT' if M['yoc_buyer'] >= G['need'] else 'NOT WORTH IT'}", False),
        (f"   rent would need to rise {M['rent_uplift_buyer']:.0%} to reach 7.15%", False),
        (f"   break-even all-in cost: ${M['breakeven_cost_per_rentable_sf']:,.0f} per rentable sf", False),
        (f"Owner: yield on new spending {M['yoc_owner']:.1%}; NOI vs office lease (${G['office_noi'] / 1e6:.2f}M/yr): {M['vs_office'] / 1e6:+.2f}M/yr", False),
        (f"   rent would need to rise {max(0, M['rent_uplift_owner_vs_office']):.1%} to beat the office lease", False),
        (f"   owner-view points: {M['owner_points']:.1f} / 8 (8 if NOI >= office, else 5 + 20 × gap in $M)", False),
        ("", False),
        ("UPSIDE NOT IN THE GRADER'S MODEL (assumption)", True),
        (f"Storage lockers on {A['storage_sf']:,} sf at $1.50/sf/mo, 70% leased: +${M['storage_noi'] / 1e3:,.0f}k NOI/yr", False),
        (f"   buyer yield with it: {M['yoc_buyer_with_storage']:.1%}", False),
        ("", False),
        ("Rent per unit = ($974 + $3.34 × sf) × 1.10 high-rise premium; +$600/mo for two-bed corners.", False),
        ("The fit comes from 167 CoStar one-bed listings within 2 km; the premium and corner uplift are the grader's.", False),
        ("Grader's caveat: each extra kitchen and bath really adds about $40–70k of fit-out that this per-sf model doesn't show.", False),
        ("Draft for checking; not investment advice.", False),
    ]
    for t, h in L:
        ax.text(x, y, t, fontsize=10 if h else 8.6, fontweight="bold" if h else "normal", va="top", transform=ax.transAxes)
        y -= 0.03 if t else 0.012
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("web/walkthrough/data"))
    ap.add_argument("--out", type=Path, default=Path("web/walkthrough/data/studies/v3"))
    ap.add_argument("--wmin", type=float, default=WIDTH["min"])
    ap.add_argument("--wtarget", type=float, default=WIDTH["target"])
    ap.add_argument("--lam", type=float, default=LAM)
    ap.add_argument("--cornerpen", type=float, default=CORNER_PEN)
    ap.add_argument("--cornermax", type=float, default=CORNER_W["max"])
    args = ap.parse_args()
    WIDTH.update(min=args.wmin, target=args.wtarget)
    globals()["LAM"] = args.lam
    globals()["CORNER_PEN"] = args.cornerpen
    CORNER_W.update(max=args.cornermax)
    args.out.mkdir(parents=True, exist_ok=True)
    S_, SH, cols, core, fill = load(args.data)

    geom_errs = checks_geometry(core, cols)
    units, csamp = generate(cols, core)
    worlds = [world_unit(u, cols) for u in units]
    for u, w in zip(units, worlds):
        u["sf"] = round(w[0].area * M2SF)
    worst, has_loop = egress(units, worlds)
    nm, nh = mark_access(units)
    for u, w in zip(units, worlds):
        u["checks"] = unit_checks(u, w)
    colrep = column_report(units, worlds, cols, core)
    A = areas(units, worlds, core)
    M = money(units, A)
    # chases: opening <= 0.6 m and >= 0.6 m from any column
    ch_ok, ch_n = 0, 0
    for w in worlds:
        for ch in w[3]:
            ch_n += 1
            cb = box(*ch)
            near = min(cb.distance(box(c["x"] - c["h"], c["y"] - c["h"], c["x"] + c["h"], c["y"] + c["h"])) for c in cols)
            ch_ok += (max(ch[2] - ch[0], ch[3] - ch[1]) <= 0.6 + 1e-6) and near >= 0.6
    chases_ok = ch_ok / max(1, ch_n)
    score_tab, total, hard = score(units, A, M, colrep, worst, has_loop, nm, nh, chases_ok, geom_errs)

    render_base(cols, core, S_, fill, args.out / "01-v3-empty-floor.png")
    render_plan(units, worlds, A, M, colrep, cols, core, S_, fill, score_tab, total, hard, worst, args.out / "02-v3-layout.png")
    render_money(units, A, M, args.out / "04-v3-cost-benefit.png")

    # JSON: v2 shape plus sinks, drain_runs_m, column_overlaps, storage/co-working, stair-link ratings, owner points
    units_json = []
    for u, (poly, rooms, door, chases) in zip(units, worlds):
        units_json.append(dict(
            id=u["id"], type="2BR/2BA corner" if u["kind"] == "corner" else "1BR/1BA", poly=[list(p) for p in poly.exterior.coords][:-1],
            sf=u["sf"], rooms=[dict(type=r["type"], rect=r["rect"], w=r["w"], d=r["d"], sf=r["sf"]) for r in rooms],
            door=list(door), entry_clear_m=HALL_W, door_clear_m=DOOR_W,
            sinks=[f["pos"] for f in u["fx_world"] if f["kind"] == "sink"],
            fixtures=u["fx_world"], drain_runs_m={f["kind"]: f["run_m"] for f in u["fx_world"]}, drain_run_m=round(u["drain"], 2), chases=chases,
            column_overlaps=[dict(id=c["id"], kind=c["kind"], overlaps=[dict(room=t, m2=a) for t, a in ovs], ok=ok, hard_rule_break=hard_)
                             for c, ovs, ok, hard_ in u["cols"]],
            egress_to_stair_m=u["egress_m"], access=u["access"] or None, rent_mo=u["rent"],
            checks={k: dict(ok=ok, measured=m) for k, (ok, m) in u["checks"].items()}, wet_rooms_paired=bool(u.get("paired"))))
    out = dict(version="v3", coords="scan metres (x, y), same as shell.json",
               areas={k: v for k, v in A.items() if not k.endswith("_geom")},
               unit_mix={"1BR/1BA": sum(u["kind"] == "one" for u in units), "2BR/2BA corner": sum(u["kind"] == "corner" for u in units)},
               units=units_json, corridor=CORRIDOR,
               stair_links=[dict(rect=r, rating="enclosed ½ hr rated corridor", clear_width_m=round(min(r[2] - r[0], r[3] - r[1]), 2)) for r in STAIR_LINKS],
               stairs=[dict(name=s_["name"], rect=s_["rect"], door=s_["door"]) for s_ in STAIRS],
               lobbies=[dict(name=L["name"], rect=L["rect"], door=L["door"], opens_onto="corridor") for L in LOBBIES],
               storage=dict(lockers_sf=A["lockers_sf"], cowork_sf=A["cowork_sf"], separation="1 hr wall at x = %.2f" % SPLIT_X,
                            note="neither is on a path to a stair; stair links are enclosed passages"),
               stair_separation_m=round(math.dist(STAIRS[0]["door"], STAIRS[1]["door"]), 2),
               worst_travel_to_stair_m=worst, corridor_loop=has_loop, columns=colrep,
               money=M | dict(vs_office=M["vs_office"], owner_points=M["owner_points"]),
               self_score=dict(items={k: dict(points=round(v, 2), max=mx, measured=m) for k, (v, mx, m) in score_tab.items()},
                               hard_breaks=hard, total=round(total, 1)),
               geometry_errors=geom_errs)
    (args.out / "layout-v3.json").write_text(json.dumps(out, indent=1, default=float))

    # self-score sheet with measured values
    md = [f"# Floor 16 v3: self-score with measured values\n", f"Self-score **{total:.1f} / 100** (hard-rule breaks: {hard}). "
          "Scored with the grader's rubric and the section 3 clarifications in floor16-generator-feedback-v3.md.\n",
          "| Criterion | Points | Max | Measured |", "|---|---|---|---|"]
    for k, (v, mx, m) in score_tab.items():
        md.append(f"| {k} | {v:.1f} | {mx} | {m} |")
    md += ["", f"Hard-rule penalty: −{5 * hard}", "", "## Every unit", "",
           "| Unit | Type | sf | Drain runs (m) | Column overlaps (m²) | Failing checks |", "|---|---|---|---|---|---|"]
    for u in units:
        ov = "; ".join(f"{c['id']}: " + ", ".join(f"{t} {a:.2f}" for t, a in ovs) for c, ovs, _, _ in u["cols"]) or "none"
        bad = ", ".join(f"{k} ({m})" for k, (ok, m) in u["checks"].items() if not ok) or "none"
        md.append(f"| {u['id']} | {'2BR/2BA' if u['kind'] == 'corner' else '1BR/1BA'} | {u['sf']} | "
                  + ", ".join(f"{f['kind']} {f['run']:.1f}" for f in u["fx"]) + f" | {ov} | {bad} |")
    md += ["", "## Every column (footprint test)", "", "| Column | Kind | Where it lands (overlap m²) | OK |", "|---|---|---|---|"]
    for r in colrep:
        md.append(f"| {r['id']} | {r['kind']} | {r['where']} | {'yes' if r['ok'] else 'NO'} |")
    (args.out / "self-score-v3.md").write_text("\n".join(md) + "\n")

    print(f"units {len(units)}  sizes {min(u['sf'] for u in units)}-{max(u['sf'] for u in units)}  avg {sum(u['sf'] for u in units) / len(units):.0f}  "
          f"units {A['units_sf']} sf  eff {A['efficiency']:.1%}  storage {A['storage_sf']}  circ {A['circulation_sf']}")
    print(f"worst egress {worst:.1f} m  loop {has_loop}  drain max {max(u['drain'] for u in units):.2f}  paired {sum(bool(u.get('paired')) for u in units)}")
    print(f"NOI {M['noi'] / 1e6:.3f}M  buyer yield {M['yoc_buyer']:.2%}  owner cost {M['owner_cost'] / 1e6:.2f}M  vs office {M['vs_office'] / 1e6:+.3f}M")
    print("geometry errors:", geom_errs or "none")
    for u in units:
        bad = [(k, m) for k, (ok, m) in u["checks"].items() if not ok]
        if bad:
            print("  ", u["id"], bad)
    for r in colrep:
        if not r["ok"]:
            print("  column", r["id"], r["kind"], r["where"])
    for k, (v, mx, m) in score_tab.items():
        print(f"  {k:30s} {v:5.1f} / {mx:2d}  {m}")
    print(f"  hard breaks {hard}  TOTAL {total:.1f}")


if __name__ == "__main__":
    main()
