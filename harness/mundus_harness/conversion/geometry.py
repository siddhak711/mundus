"""Deterministic geometry for the office-to-apartment conversion agent.

The agent proposes; this module draws and measures. It reads the per-floor files that pipeline/floorprep.py writes
(geometry.json, structure.json, grid.npz) and never calls a model.

Coordinates are the scan's metres. grid.npz holds rasters at RES pixels per metre with row 0 at the top (max y):
    col = (x - x0) * RES,   row = (y0 + h / RES - y) * RES
"""
from __future__ import annotations

import heapq
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

FT_PER_M = 3.2808
SF_PER_M2 = 10.7639

# Thresholds. Code values are unconfirmed until the compliance subagent confirms them (see the compliance skill).
MIN_UNIT_SF = 220            # efficiency dwelling unit, CBC/IBC 1208.4 (unconfirmed)
MIN_BEDROOM_SF = 70          # habitable room other than the main room, CBC/IBC 1208.3 (unconfirmed)
MIN_ROOM_DIM_FT = 7          # CBC/IBC 1208.1 (unconfirmed)
MIN_CEILING_FT = 7.5         # CBC/IBC 1208.2 (unconfirmed)
MAX_TRAVEL_FT = 250          # exit access travel distance, sprinklered R-2, CBC/IBC Table 1017.2 (unconfirmed)
DAYLIGHT_FT = 35             # rule of thumb from conversion studies, not code: 25 to 35 ft from a window
MIN_CORRIDOR_M = 1.12        # 44 in, CBC/IBC 1020.3 (unconfirmed)
BEDROOM_W_M = 3.2            # drawn bedroom width along the facade (10.5 ft)
BEDROOM_D_M = 3.6            # drawn bedroom depth from the facade (11.8 ft)
LIVING_MIN_W_M = 3.0         # facade frontage kept for the living room next to the bedrooms
TYPE_BEDROOMS = {"studio": 0, "1BR": 1, "2BR": 2, "3BR": 3}


def data_root() -> Path:
    env = os.environ.get("CONVERSION_DATA_DIR", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data" / "conversion"


def r2(v: float) -> float:
    return round(float(v), 2)


class Floor:
    """One preprocessed floor: summaries plus rasters, with metre/pixel conversion."""

    def __init__(self, scan: str, root: Path | None = None):
        self.scan = scan
        self.dir = (root or data_root()) / scan
        if not (self.dir / "geometry.json").exists():
            raise FileNotFoundError(f"no preprocessed floor for scan {scan}: run python -m pipeline.floorprep {scan}")
        self.geo = json.loads((self.dir / "geometry.json").read_text(encoding="utf-8"))
        self.struct = json.loads((self.dir / "structure.json").read_text(encoding="utf-8"))
        z = np.load(self.dir / "grid.npz")
        self.plate, self.window, self.core, self.columns = (z[k].astype(bool) for k in ("plate", "window", "core", "columns"))
        x0, y0, w, h, res = (float(v) for v in z["frame"])
        self.x0, self.y0, self.w, self.h, self.res = x0, y0, int(w), int(h), res
        self.top = y0 + self.h / res
        self._win_dist = None
        self._walk = None
        self._unscanned = None
        self._open_dist = None

    def unscanned_facade(self) -> np.ndarray:
        """Facade pixels more than 5 m from every camera position: offices the scanner never entered, seen at most
        through interior glass. Whether they have windows is unknown, not 'no'."""
        if self._unscanned is None:
            edge = self.plate & ~ndimage.binary_erosion(self.plate)
            cams = np.zeros_like(self.plate)
            pf = self.dir / "panos.json"
            if pf.exists():
                for p in json.loads(pf.read_text(encoding="utf-8")):
                    c, r = self.to_px(p["x"], p["y"])
                    if 0 <= int(r) < self.h and 0 <= int(c) < self.w:
                        cams[int(r), int(c)] = True
            far = ndimage.distance_transform_edt(~cams) / self.res > 5.0 if cams.any() else np.zeros_like(self.plate)
            self._unscanned = ndimage.binary_dilation(edge & far, iterations=1) & ~ndimage.binary_dilation(self.window, iterations=3)
        return self._unscanned

    def open_facade_distance_m(self) -> np.ndarray:
        """Distance to the nearest window or unscanned facade (where a window is possible but unseen)."""
        if self._open_dist is None:
            self._open_dist = ndimage.distance_transform_edt(~(self.window | self.unscanned_facade())) / self.res
        return self._open_dist

    # ---------- frame ----------
    def to_px(self, x, y):
        return (np.asarray(x, float) - self.x0) * self.res, (self.top - np.asarray(y, float)) * self.res

    def to_m(self, col, row):
        return self.x0 + np.asarray(col, float) / self.res, self.top - np.asarray(row, float) / self.res

    def raster(self, poly: list[list[float]]) -> np.ndarray:
        import cv2
        c, r = self.to_px([p[0] for p in poly], [p[1] for p in poly])
        m = np.zeros((self.h, self.w), np.uint8)
        cv2.fillPoly(m, [np.round(np.stack([c, r], 1)).astype(np.int32)], 1)
        return m.astype(bool)

    def sample(self, mask: np.ndarray, x: float, y: float) -> bool:
        c, r = self.to_px(x, y)
        c, r = int(c), int(r)
        return 0 <= r < self.h and 0 <= c < self.w and bool(mask[r, c])

    def disk(self, m: float) -> np.ndarray:
        k = max(1, round(m * self.res))
        return np.hypot(*np.mgrid[-k:k + 1, -k:k + 1]) <= k

    # ---------- derived maps ----------
    def window_distance_m(self) -> np.ndarray:
        if self._win_dist is None:
            self._win_dist = ndimage.distance_transform_edt(~self.window) / self.res
        return self._win_dist

    def walk_distance_m(self) -> np.ndarray:
        """Shortest walking distance (metres) to the nearest exit across the plate, around the core. Computed on a
        25 cm grid; walls inside the plate are ignored (they come down in a conversion)."""
        if self._walk is None:
            step = max(1, int(round(self.res / 4)))
            walk = (self.plate & ~self.core)[::step, ::step]
            h, w = walk.shape
            dist = np.full((h, w), np.inf)
            heap = []
            cell = step / self.res
            for e in self.struct.get("exits") or []:
                c, r = self.to_px(e["x"], e["y"])
                c, r = int(c / step), int(r / step)
                rad = int(1.5 / cell)
                for rr in range(max(0, r - rad), min(h, r + rad + 1)):
                    for cc in range(max(0, c - rad), min(w, c + rad + 1)):
                        if walk[rr, cc]:
                            d0 = math.hypot(rr - r, cc - c) * cell
                            if d0 < dist[rr, cc]:
                                dist[rr, cc] = d0
                                heapq.heappush(heap, (d0, rr, cc))
            nb = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
            while heap:
                d, r, c = heapq.heappop(heap)
                if d > dist[r, c]:
                    continue
                for dr, dc, k in nb:
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < h and 0 <= cc < w and walk[rr, cc]:
                        nd = d + k * cell
                        if nd < dist[rr, cc]:
                            dist[rr, cc] = nd
                            heapq.heappush(heap, (nd, rr, cc))
            full = np.repeat(np.repeat(dist, step, 0), step, 1)[: self.h, : self.w]
            self._walk = full
        return self._walk

    # ---------- facade sides ----------
    def sides(self) -> list[dict[str, Any]]:
        """The facade as straight sides, each with a compass name, length and inward direction. The two longest
        sides run the full length; the shorter sides fit between the units of the long sides."""
        pts = np.array(self.geo["outline"], float)
        centre = pts.mean(0)
        out = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            v = b - a
            length = float(np.hypot(*v))
            if length < 2:
                continue
            u = v / length
            n = np.array([-u[1], u[0]])
            if np.dot(centre - (a + b) / 2, n) < 0:
                n = -n
            ang = math.degrees(math.atan2(-n[1], -n[0])) % 360   # outward direction
            name = ["east", "north", "west", "south"][int(((ang + 45) % 360) // 90)]
            out.append({"name": name, "a": a, "b": b, "u": u, "n": n, "length_m": length})
        longest = sorted(out, key=lambda s: -s["length_m"])[:2]
        for s in out:
            s["full"] = s in longest
        return out

    def side(self, name: str) -> dict[str, Any]:
        for s in self.sides():
            if s["name"] == name:
                return s
        raise ValueError(f"no facade side named {name!r}; sides are {[s['name'] for s in self.sides()]}")

    def clearance(self, s: dict[str, Any], t0: float, t1: float, step: float = 0.5) -> list[float]:
        """Distance inward from the facade to the first core pixel or the plate's far edge, sampled along a side."""
        out = []
        for t in np.arange(t0 + step / 2, t1, step):
            p = s["a"] + s["u"] * t
            d = 0.0
            while d < 25:
                q = p + s["n"] * (d + 0.25)
                if not self.sample(self.plate, *q) or self.sample(self.core, *q):
                    break
                d += 0.25
            out.append(d)
        return out


# ---------- summaries for the agent ----------

def floor_summary(scan: str, root: Path | None = None) -> dict[str, Any]:
    f = Floor(scan, root)
    g, st = f.geo, f.struct
    sides = []
    for s in f.sides():
        cl = f.clearance(s, 0, s["length_m"])
        cols = []
        for c in st.get("columns") or []:
            rel = np.array([c["x"], c["y"]]) - s["a"]
            t, d = float(rel @ s["u"]), float(rel @ s["n"])
            if -0.5 <= t <= s["length_m"] + 0.5 and 0 <= d <= 12:
                cols.append({"along_m": r2(t), "from_facade_m": r2(d)})
        ts = np.arange(0.25, s["length_m"], 0.5)
        flags = []
        for t in ts:
            p = s["a"] + s["u"] * t + s["n"] * 0.05
            c, r = f.to_px(*p)
            rr, cc = int(r), int(c)
            flags.append(bool(0 <= rr < f.h and 0 <= cc < f.w and f.window[max(0, rr - 3):rr + 4, max(0, cc - 3):cc + 4].any()))
        win = sum(flags)
        uns = f.unscanned_facade()
        uflags = []
        for t in ts:
            p = s["a"] + s["u"] * t + s["n"] * 0.05
            c, r = f.to_px(*p)
            rr, cc = int(r), int(c)
            uflags.append(bool(0 <= rr < f.h and 0 <= cc < f.w and uns[max(0, rr - 3):rr + 4, max(0, cc - 3):cc + 4].any()))
        ugaps, ustart = [], None
        for t, fl in zip(list(ts) + [s["length_m"] + 1], uflags + [False], strict=True):
            if fl and ustart is None:
                ustart = t
            elif not fl and ustart is not None:
                if t - ustart >= 1.0:
                    ugaps.append([r2(ustart - 0.25), r2(min(t - 0.25, s["length_m"]))])
                ustart = None
        flags = [a or b for a, b in zip(flags, uflags, strict=True)]   # unscanned is not "no window"
        gaps, start = [], None
        for t, fl in zip(list(ts) + [s["length_m"] + 1], flags + [True], strict=True):
            if not fl and start is None:
                start = t
            elif fl and start is not None:
                if t - start >= 1.0:
                    gaps.append([r2(start - 0.25), r2(min(t - 0.25, s["length_m"]))])
                start = None
        sides.append({"side": s["name"], "length_m": r2(s["length_m"]), "length_ft": round(s["length_m"] * FT_PER_M),
                      "runs_full_length": s["full"],
                      "facade_to_core_m": {"min": r2(min(cl)), "p10": r2(np.percentile(cl, 10)), "median": r2(np.median(cl))} if cl else None,
                      "window_share": round(win / max(1, len(ts)), 2),
                      "no_window_stretches_along_m": gaps,
                      "unscanned_facade_along_m": ugaps,
                      "column_candidates": cols})
    return {
        "scan": scan, "name": g.get("name"), "floor": g.get("floor"), "property": g.get("property"),
        "plate_sf": g.get("plate_sf"), "usable_sf_outside_core": g.get("usable_sf_outside_core"),
        "ceiling_height_ft": g.get("ceiling_height_ft"), "daylight": g.get("daylight"),
        "facade_sides": sides,
        "core": [{"area_m2": b["area_m2"], "bbox_m": [r2(min(p[0] for p in b["polygon"])), r2(min(p[1] for p in b["polygon"])),
                                                      r2(max(p[0] for p in b["polygon"])), r2(max(p[1] for p in b["polygon"]))]}
                 for b in st.get("core") or []],
        "columns": {"count": len(st.get("columns") or []), "grid": st.get("column_grid"), "confidence": "low"},
        "stairs": [{k: s_[k] for k in ("x", "y", "kind", "confidence", "evidence") if k in s_} for s_ in st.get("stairs") or []],
        "exits": st.get("exits"),
        "notes": st.get("notes", []) + [
            "Corner rule for draft_ring_layout: the two longest sides run full length; shorter sides fit between "
            "them, so their usable length is their length minus the unit depth at each end.",
        ],
    }


# ---------- drawing a draft ----------

def _seg(a, b, kind):
    return {"a": [r2(a[0]), r2(a[1])], "b": [r2(b[0]), r2(b[1])], "kind": kind}


def draft_ring(scan: str, unit_depth_m: float, sides: dict[str, list[dict[str, Any]]], corridor_m: float = 1.6,
               root: Path | None = None) -> dict[str, Any]:
    """Draw a ring of units along the facade. `sides` maps a facade side name to its units in order, each
    {"type": "studio|1BR|2BR|3BR", "width_m": float}. Returns a layout (contract shape) without checks."""
    f = Floor(scan, root)
    all_sides = {s["name"]: s for s in f.sides()}
    long_depth = {n: (unit_depth_m if sides.get(n) else 0.0) for n in all_sides}
    units, walls, problems = [], [], []
    k = 0
    for name, specs in sides.items():
        if name not in all_sides:
            raise ValueError(f"unknown side {name!r}; sides are {sorted(all_sides)}")
        s = all_sides[name]
        if s["full"]:
            t0, t1 = 0.0, s["length_m"]
        else:   # fit between the long sides' units
            ends = [o for o in all_sides.values() if o["full"]]
            t0, t1 = 0.0, s["length_m"]
            starts = [o for o in ends if np.allclose(o["b"], s["a"], atol=0.6) or np.allclose(o["a"], s["a"], atol=0.6)]
            stops = [o for o in ends if np.allclose(o["a"], s["b"], atol=0.6) or np.allclose(o["b"], s["b"], atol=0.6)]
            t0 = max([long_depth[o["name"]] for o in starts] + [0.0])
            t1 = s["length_m"] - max([long_depth[o["name"]] for o in stops] + [0.0])
        avail = t1 - t0
        total = sum(float(u["width_m"]) for u in specs)
        if total > avail + 0.05:
            raise ValueError(f"side {name}: unit widths add up to {total:.1f} m but only {avail:.1f} m is available "
                             f"(from {t0:.1f} to {t1:.1f} m along the side)")
        # centre the run when no gaps are given; with explicit gaps, start at the side's usable start
        t = t0 + (0.0 if any(u.get("type") == "gap" for u in specs) else (avail - total) / 2)
        if avail - total > 0.5:
            problems.append(f"side {name}: {avail - total:.1f} m of facade left unassigned (amenity or storage)")
        run_start = t
        a_, u_, n_ = s["a"], s["u"], s["n"]
        for spec in specs:
            typ = spec["type"]
            if typ == "gap":                     # facade left unassigned here: amenity, storage, no windows
                g = float(spec["width_m"])
                if units and units[-1]["side"] == name and t > run_start:
                    walls.append(_seg(a_ + u_ * t, a_ + u_ * t + n_ * unit_depth_m, "demising"))
                    walls.append(_seg(a_ + u_ * run_start + n_ * unit_depth_m, a_ + u_ * t + n_ * unit_depth_m, "corridor"))
                t += g
                run_start = t
                continue
            if typ not in TYPE_BEDROOMS:
                raise ValueError(f"unit type {typ!r} must be one of {list(TYPE_BEDROOMS) + ['gap']}")
            w = float(spec["width_m"])
            k += 1
            p0, p1 = a_ + u_ * t, a_ + u_ * (t + w)
            poly = [p0, p1, p1 + n_ * unit_depth_m, p0 + n_ * unit_depth_m]
            nb = TYPE_BEDROOMS[typ]
            bedrooms = []
            if nb:
                need = nb * BEDROOM_W_M + LIVING_MIN_W_M
                if w + 1e-6 < need:
                    problems.append(f"U{k} ({typ}) is {w:.1f} m wide; {nb} bedroom(s) plus living need {need:.1f} m of facade")
                bd = min(BEDROOM_D_M, unit_depth_m - 1.0)
                for i in range(nb):
                    b0, b1 = a_ + u_ * (t + i * BEDROOM_W_M), a_ + u_ * (t + (i + 1) * BEDROOM_W_M)
                    bedrooms.append([[r2(c) for c in q] for q in (b0, b1, b1 + n_ * bd, b0 + n_ * bd)])
                    walls.append(_seg(b1, b1 + n_ * bd, "interior"))
                walls.append(_seg(a_ + u_ * t + n_ * bd, a_ + u_ * (t + nb * BEDROOM_W_M) + n_ * bd, "interior"))
            centre = (p0 + p1) / 2 + n_ * unit_depth_m / 2
            entry = (p0 + p1) / 2 + n_ * unit_depth_m
            units.append({"id": f"U{k}", "type": typ, "bedrooms": nb, "side": name,
                          "area_sf": round(w * unit_depth_m * SF_PER_M2),
                          "width_m": r2(w), "depth_m": r2(unit_depth_m),
                          "polygon": [[r2(c) for c in q] for q in poly], "label_at": [r2(centre[0]), r2(centre[1])],
                          "entry": [r2(entry[0]), r2(entry[1])], "bedroom_polygons": bedrooms})
            walls.append(_seg(p0, p0 + n_ * unit_depth_m, "demising"))
            t += w
        if t > run_start + 0.01:
            walls.append(_seg(a_ + u_ * t, a_ + u_ * t + n_ * unit_depth_m, "demising"))
            walls.append(_seg(a_ + u_ * run_start + n_ * unit_depth_m, a_ + u_ * t + n_ * unit_depth_m, "corridor"))
        side_units = [x for x in units if x["side"] == name]
        if side_units:
            cl = f.clearance(s, t0, t)
            if cl and min(cl) < unit_depth_m + max(corridor_m, MIN_CORRIDOR_M):
                problems.append(f"side {name}: the core is {min(cl):.1f} m from the facade in places; units {unit_depth_m:.1f} m "
                                f"deep plus a {corridor_m:.1f} m corridor need {unit_depth_m + corridor_m:.1f} m")
    return {"scan": scan, "floor": f.geo.get("floor"), "unit_depth_m": r2(unit_depth_m), "corridor_m": r2(corridor_m),
            "walls": walls, "units": units, "draft_problems": problems}


# ---------- checking ----------

def _wall_hits(f: Floor, w: dict[str, Any], core_in: np.ndarray, cols: np.ndarray) -> dict[str, bool]:
    a, b = np.array(w["a"], float), np.array(w["b"], float)
    n = max(2, int(np.hypot(*(b - a)) / 0.1))
    hit_core = hit_col = False
    for t in np.linspace(0, 1, n):
        p = a + (b - a) * t
        hit_core = hit_core or f.sample(core_in, *p)
        hit_col = hit_col or f.sample(cols, *p)
    return {"core": hit_core, "column": hit_col}


def check_layout(scan: str, layout: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Every rule we can measure, per unit: pass, fail or unknown, with the number behind it."""
    f = Floor(scan, root)
    core_in = ndimage.binary_erosion(f.core, structure=f.disk(0.2))
    win_zone = ndimage.binary_dilation(f.window, structure=f.disk(0.5))
    win_d = f.window_distance_m()
    open_d = f.open_facade_distance_m()
    uns = f.unscanned_facade()
    uns_zone = ndimage.binary_dilation(uns, structure=f.disk(0.5))
    walk = f.walk_distance_m()
    ceiling = f.geo.get("ceiling_height_ft")
    exits_assumed = all((e.get("confidence") == "assumed") for e in f.struct.get("exits") or [])
    wall_results = []
    for w in layout.get("walls") or []:
        h = _wall_hits(f, w, core_in, f.columns)
        if h["core"] or h["column"]:
            wall_results.append({"wall": w, **h})
    out_units = []
    taken = np.zeros_like(f.plate)
    for u in layout.get("units") or []:
        m = f.raster(u["polygon"])
        px = int(m.sum())
        area_sf = px / f.res ** 2 * SF_PER_M2
        checks: dict[str, dict[str, Any]] = {}

        def put(name, status, value=None, rule=None, checks=checks):
            checks[name] = {"status": status, **({"value": value} if value is not None else {}), **({"rule": rule} if rule else {})}

        inside = float((m & f.plate).sum() / max(1, px))
        put("inside_floor", "pass" if inside >= 0.97 else "fail", f"{inside:.0%} inside the floor plate")
        core_share = float((m & core_in).sum() / max(1, px))
        put("clear_of_core", "pass" if core_share <= 0.01 else "fail", f"{core_share:.1%} overlaps the core",
            "Never build into the core (lifts, stairs, shafts)")
        overlap = float((m & taken).sum() / max(1, px))
        put("no_overlap", "pass" if overlap <= 0.02 else "fail", f"{overlap:.0%} overlaps another unit")
        taken |= m
        put("unit_size", "pass" if area_sf >= MIN_UNIT_SF else "fail", f"{area_sf:.0f} sf",
            f"Unit at least {MIN_UNIT_SF} sf (CBC 1208.4, unconfirmed)")
        grown = ndimage.binary_dilation(m, iterations=2)
        frontage = float((grown & f.window).sum() / f.res)
        unseen = float((grown & uns).sum() / f.res)

        def tri(ok_seen, ok_with_unseen):
            return "pass" if ok_seen else ("unknown" if ok_with_unseen else "fail")
        put("window_frontage", tri(frontage >= 2.0, frontage + unseen >= 2.0),
            f"{frontage:.1f} m of window" + (f", {unseen:.1f} m of facade not scanned" if unseen else ""))
        floor_m2 = px / f.res ** 2
        put("natural_light", tri(frontage * 2.0 >= 0.08 * floor_m2, (frontage + unseen) * 2.0 >= 0.08 * floor_m2),
            f"about {frontage * 2.0:.0f} m2 glass for {floor_m2:.0f} m2 floor (assumes 2 m of glazed height)",
            "Glazing at least 8% of floor area (CBC 1204.2, unconfirmed); glazed height is an estimate")
        deepest = float(win_d[m].max() * FT_PER_M) if px else None
        deepest_open = float(open_d[m].max() * FT_PER_M) if px else None
        put("daylight_depth", tri(deepest is not None and deepest <= DAYLIGHT_FT, deepest_open is not None and deepest_open <= DAYLIGHT_FT),
            f"deepest point {deepest:.0f} ft from a seen window" + (f", {deepest_open:.0f} ft counting unscanned facade" if deepest_open is not None and deepest_open < deepest else "") if deepest is not None else None,
            f"Rule of thumb, not code: within {DAYLIGHT_FT} ft of a window")
        bed_status, bed_notes = "pass", []
        beds = u.get("bedroom_polygons") or []
        if u.get("bedrooms") and not beds:
            bed_status, bed_notes = "unknown", ["bedrooms not drawn; unit window frontage checked instead"]
            if frontage + unseen < 2.0:
                bed_status = "fail"
        for i, bp in enumerate(beds, 1):
            bm = f.raster(bp)
            bsf = bm.sum() / f.res ** 2 * SF_PER_M2
            bx = np.array(bp)
            dims = sorted([float(np.hypot(*(bx[1] - bx[0]))), float(np.hypot(*(bx[2] - bx[1])))])
            touches = bool((bm & win_zone).any())
            maybe = bool((bm & uns_zone).any())
            size_ok = bsf >= MIN_BEDROOM_SF and dims[0] * FT_PER_M >= MIN_ROOM_DIM_FT
            if not size_ok or not (touches or maybe):
                bed_status = "fail"
            elif not touches and bed_status == "pass":
                bed_status = "unknown"
            seen = "touches a window" if touches else ("faces unscanned facade" if maybe else "NO window")
            bed_notes.append(f"bedroom {i}: {bsf:.0f} sf, {seen}, narrowest {dims[0] * FT_PER_M:.1f} ft")
        put("bedroom_windows", bed_status, "; ".join(bed_notes) or "no bedrooms",
            "Every bedroom has an exterior window (CBC 1204/1205, unconfirmed); bedroom at least 70 sf and 7 ft wide (CBC 1208)")
        travel = walk[m & np.isfinite(walk)]
        if travel.size:
            ft = float(travel.max() * FT_PER_M)
            put("exit_travel", "pass" if ft <= MAX_TRAVEL_FT else "fail",
                f"{ft:.0f} ft from the unit's farthest point to the nearest exit" + (" (exits assumed at the core)" if exits_assumed else ""),
                f"Exit access travel at most {MAX_TRAVEL_FT} ft, sprinklered R-2 (CBC Table 1017.2, unconfirmed)")
        else:
            put("exit_travel", "unknown", "no walking route found to an exit")
        if ceiling:
            put("ceiling_height", "pass" if ceiling >= MIN_CEILING_FT else "fail", f"{ceiling} ft as scanned, before new ceilings",
                f"At least {MIN_CEILING_FT} ft (CBC 1208.2, unconfirmed)")
        else:
            put("ceiling_height", "unknown", "no ceiling height in the scan")
        my_walls = [r for r in wall_results if _near_unit(r["wall"], u)]
        col_hits = [r for r in my_walls if r["column"]]
        core_hits = [r for r in my_walls if r["core"]]
        put("walls_clear_of_structure", "fail" if (col_hits or core_hits) else "pass",
            f"{len(core_hits)} wall(s) cross the core, {len(col_hits)} cross a column candidate (low confidence)",
            "Walls must not cut through the core or columns")
        statuses = [c["status"] for c in checks.values()]
        overall = "fail" if "fail" in statuses else ("unknown" if "unknown" in statuses else "pass")
        out_units.append({"id": u["id"], "type": u.get("type"), "area_sf": round(area_sf), "status": overall, "checks": checks})
    counts = {s: sum(1 for u in out_units if u["status"] == s) for s in ("pass", "fail", "unknown")}
    return {"scan": scan, "counts": counts, "units": out_units,
            "walls_crossing_structure": [{"a": r["wall"]["a"], "b": r["wall"]["b"], "kind": r["wall"].get("kind"),
                                          "core": r["core"], "column": r["column"]} for r in wall_results],
            "assumptions": (["Exits are assumed at the ends of the core: fire stairs were not scanned."] if exits_assumed else [])
            + (["Some facade was not scanned (offices never entered); units there are 'unknown' for windows, not failed."] if uns.any() else [])
            + ["Column positions are low-confidence guesses from the mesh.",
               "Code thresholds are unconfirmed until the compliance agent confirms them."]}


def _near_unit(w: dict[str, Any], u: dict[str, Any], tol: float = 0.15) -> bool:
    poly = np.array(u["polygon"], float)
    lo, hi = poly.min(0) - tol, poly.max(0) + tol
    for p in (w["a"], w["b"]):
        if np.all(np.array(p) >= lo) and np.all(np.array(p) <= hi):
            return True
    return False


# ---------- final layout ----------

def finalize(scan: str, layout: dict[str, Any], report: dict[str, Any], summary: dict[str, Any], generated_by: str,
             root: Path | None = None) -> dict[str, Any]:
    f = Floor(scan, root)
    by_id = {u["id"]: u for u in report["units"]}
    units = []
    for u in layout.get("units") or []:
        r = by_id.get(u["id"], {})
        units.append({"id": u["id"], "type": u["type"], "bedrooms": int(u.get("bedrooms", TYPE_BEDROOMS.get(u["type"], 0))),
                      "area_sf": u.get("area_sf") or r.get("area_sf"), "polygon": u["polygon"],
                      "label_at": u.get("label_at") or [r2(np.mean([p[0] for p in u["polygon"]])), r2(np.mean([p[1] for p in u["polygon"]]))],
                      "checks": {"status": r.get("status", "unknown"), **{k: v["status"] for k, v in (r.get("checks") or {}).items()}}})
    walls = [{"a": w["a"], "b": w["b"], "kind": w.get("kind", "demising")} for w in layout.get("walls") or []]
    for w in walls:
        if w["kind"] not in ("demising", "interior", "corridor"):
            raise ValueError(f"wall kind {w['kind']!r} must be demising, interior or corridor")
        if len(w["a"]) != 2 or len(w["b"]) != 2:
            raise ValueError("each wall needs a and b as [x, y]")
    st = f.struct
    out = {
        "scan": scan, "floor": f.geo.get("floor"), "generated_by": generated_by,
        "walls": walls, "units": units,
        "structure": {"core": [b["polygon"] for b in st.get("core") or []],
                      "columns": [{"x": c["x"], "y": c["y"], "confidence": c.get("confidence", "low")} for c in st.get("columns") or []],
                      "exits": [{"x": e["x"], "y": e["y"], "kind": e.get("kind"), "confidence": e.get("confidence")} for e in st.get("exits") or []]},
        "summary": {"units": len(units), "rentable_sf": int(sum(u["area_sf"] or 0 for u in units)),
                    "monthly_rent_usd": summary.get("monthly_rent_usd"),
                    "issues": list(summary.get("issues") or []), "assumptions": list(summary.get("assumptions") or [])},
    }
    for k in ("unit_mix", "annual_rent_usd", "conversion_cost_usd", "simple_yield", "check_counts"):
        if summary.get(k) is not None:
            out["summary"][k] = summary[k]
    (f.dir / "layout.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


@lru_cache(maxsize=8)
def _cached_floor(scan: str, root: str) -> Floor:
    return Floor(scan, Path(root))
