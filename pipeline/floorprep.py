"""Preprocess one scanned office floor for the apartment-conversion agent.

    python -m pipeline.floorprep cEvQ8q5GKZd --property 246826 --floor 16

Writes data/conversion/<scan>/:
  geometry.json   floor outline, windows, daylight depth, ceiling height (metres, the scan's own coordinates)
  structure.json  core, column candidates, stair candidates, assumed exits, each with a confidence
  grid.npz        rasters the agent's geometry tool measures against (floor plate, windows, core, columns)
  overlay.png     everything drawn on Matterport's floor plan image, to check by eye
  raw/            the Matterport response, mesh and floor plan image (signed links expire)

All positions are in the scan's metres. The floor plan image maps onto them with its origin (lower-left corner) and
resolution (pixels per metre); the mesh and the camera positions already use them.
Agents never read raw data: they read geometry.json and structure.json, and measure through grid.npz.
"""
import argparse
import io
import json

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw
from scipy import ndimage

from pipeline import config, matterport
from pipeline.daylight import floor_plate

FT_PER_M = 3.2808
SF_PER_M2 = 10.7639
RES = 20.0          # working grid: pixels per metre (5 cm)

_QUERY = """query($id: ID!) { model(id: $id) {
  id name
  floors { id label }
  rooms { id dimensions(units: metric) { areaFloor height } }
  panoLocations { id label position { x y z } skybox(resolution: "high") { children } }
  assets {
    meshes { format resolution url }
    floorplans(provider: "matterport") { format flags url width height resolution origin { x y } }
  }
} }"""


def out_dir(scan_id):
    return config.DATA / "conversion" / scan_id


# ---------- fetch ----------

def fetch(scan_id):
    """Matterport response, mesh and transparent floor plan, cached under raw/. Returns (model, plan meta)."""
    raw = out_dir(scan_id) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    model = matterport._query(_QUERY, scan_id)
    (raw / "model.json").write_text(json.dumps(model), encoding="utf-8")   # pano links inside expire; refetch to use
    if not (raw / "mesh.obj").exists():
        mesh = next(m for m in model["assets"]["meshes"] if m["format"] == "obj")
        (raw / "mesh.obj").write_bytes(requests.get(mesh["url"], timeout=300).content)
    plans = [f for f in model["assets"]["floorplans"] if f["format"] == "png" and "alpha" in f["flags"] and f.get("resolution")]
    plan = max(plans, key=lambda f: f["resolution"])
    if not (raw / "plan.png").exists():
        (raw / "plan.png").write_bytes(requests.get(plan["url"], timeout=300).content)
    color = [f for f in model["assets"]["floorplans"] if f["format"] == "jpg" and f["flags"] == ["photogramy"]]
    if color and not (raw / "plan_color.jpg").exists():
        (raw / "plan_color.jpg").write_bytes(requests.get(color[0]["url"], timeout=300).content)
    meta = {"origin": plan["origin"], "resolution": plan["resolution"], "width": plan["width"], "height": plan["height"]}
    if color:
        meta["color"] = {"origin": color[0]["origin"], "resolution": color[0]["resolution"]}
    (raw / "plan.json").write_text(json.dumps(meta), encoding="utf-8")
    return model, meta


def load_mesh(path):
    v, f = [], []
    for line in open(path, encoding="utf-8", errors="ignore"):
        if line.startswith("v "):
            v.append([float(t) for t in line.split()[1:4]])
        elif line.startswith("f "):
            f.append([int(t.split("/")[0]) - 1 for t in line.split()[1:4]])
    return np.array(v), np.array(f)


# ---------- grid: one raster frame in metres ----------

class Grid:
    """Raster frame at RES px/m. Row 0 is the north (max y) edge, like an image."""

    def __init__(self, x0, y0, w, h):
        self.x0, self.y0, self.w, self.h = x0, y0, w, h

    def to_px(self, x, y):
        return (np.asarray(x) - self.x0) * RES, (self.y0 + self.h / RES - np.asarray(y)) * RES

    def to_m(self, col, row):
        return self.x0 + np.asarray(col) / RES, self.y0 + self.h / RES - np.asarray(row) / RES

    def polygon_m(self, contour, eps_m):
        approx = cv2.approxPolyDP(contour, eps_m * RES, True)[:, 0, :]
        xs, ys = self.to_m(approx[:, 0], approx[:, 1])
        return [[round(float(a), 2), round(float(b), 2)] for a, b in zip(xs, ys)]


def plan_mask_on_grid(meta, png_path):
    """Matterport's transparent floor plan -> scanned-floor mask resampled onto a Grid at RES px/m."""
    alpha = np.array(Image.open(png_path).convert("RGBA"))[..., 3] > 0
    r = meta["resolution"]
    h, w = alpha.shape
    gw, gh = round(w * RES / r), round(h * RES / r)
    small = np.array(Image.fromarray(alpha.astype(np.uint8) * 255).resize((gw, gh), Image.BOX)) > 0
    return Grid(meta["origin"]["x"], meta["origin"]["y"], gw, gh), small


def slice_raster(V, F, z, grid):
    """Where the mesh crosses height z: True pixels are surfaces (walls, columns, glass frames)."""
    T = V[F]
    d = T[:, :, 2] - z
    hit = (d.min(1) < 0) & (d.max(1) > 0)
    img = Image.new("L", (grid.w, grid.h), 0)
    draw = ImageDraw.Draw(img)
    for tri, dd in zip(T[hit], d[hit]):
        pts = [tri[i] + dd[i] / (dd[i] - dd[j]) * (tri[j] - tri[i]) for i, j in ((0, 1), (1, 2), (2, 0)) if dd[i] * dd[j] < 0]
        if len(pts) == 2:
            (c1, r1), (c2, r2) = [grid.to_px(p[0], p[1]) for p in pts]
            draw.line([(float(c1), float(r1)), (float(c2), float(r2))], fill=1)
    return np.array(img) > 0


def disk(m):
    r = max(1, round(m * RES))
    return np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r


def regularise_plate(plate, mask):
    """Rays the scanner saw through the glass bulge the plate past the facade. Most office towers are rectangles:
    find the plate's orientation, then put each facade where the scanned floor stops being continuous (where fewer
    than half the rows or columns still have floor). If the floor is far from rectangular, keep the opened outline."""
    core = ndimage.binary_opening(plate, structure=disk(2.5))
    labels, n = ndimage.label(core)
    if n:
        core = labels == (np.bincount(labels.ravel())[1:].argmax() + 1)
    cs, _ = cv2.findContours(core.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    (cx, cy), _, ang = cv2.minAreaRect(max(cs, key=cv2.contourArea))
    t = np.deg2rad(ang)
    rows, cols = np.nonzero(plate & mask)
    u = (cols - cx) * np.cos(t) + (rows - cy) * np.sin(t)
    v = -(cols - cx) * np.sin(t) + (rows - cy) * np.cos(t)

    def edges(a):
        lo, hi = int(np.floor(a.min())), int(np.ceil(a.max()))
        hist = np.bincount((a - lo).astype(int), minlength=hi - lo + 1).astype(float)
        hist = ndimage.uniform_filter1d(hist, int(RES))
        keep = np.nonzero(hist >= 0.5 * np.median(hist[hist > 0]))[0]
        return lo + keep.min(), lo + keep.max()
    (u0, u1), (v0, v1) = edges(u), edges(v)
    corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    pts = np.array([[cx + uu * np.cos(t) - vv * np.sin(t), cy + uu * np.sin(t) + vv * np.cos(t)] for uu, vv in corners], np.int32)
    box = np.zeros(plate.shape, np.uint8)
    cv2.fillPoly(box, [pts], 1)
    box = box.astype(bool)
    if (core & box).sum() / max(1, box.sum()) > 0.8:
        return box
    return ndimage.binary_fill_holes(core)


# ---------- features ----------

def find_windows(mask, plate, grid):
    """Glass does not scan: the scanner sees through it and leaves floor outside the facade. Facade stretches with
    scanned floor just outside them are windows."""
    outside = mask & ~ndimage.binary_dilation(plate, iterations=2)
    near = ndimage.binary_dilation(outside, structure=disk(1.5))
    contours, _ = cv2.findContours(plate.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(contours, key=cv2.contourArea)[:, 0, :]
    flags = near[c[:, 1], c[:, 0]]
    flags = ndimage.binary_closing(flags, structure=np.ones(int(2 * RES))) # bridge mullions and columns up to 2 m
    runs, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= RES:                                          # at least about 1 m
                seg = c[start:i]
                xs, ys = grid.to_m(seg[:, 0], seg[:, 1])
                pts = cv2.approxPolyDP(np.stack([xs, ys], 1).astype(np.float32).reshape(-1, 1, 2), 0.3, False)[:, 0, :]
                runs.append([[round(float(a), 2), round(float(b), 2)] for a, b in pts])
            start = None
    window_px = np.zeros_like(plate)
    window_px[c[flags, 1], c[flags, 0]] = True
    perimeter_m = len(c) / RES
    return runs, window_px, round(float(flags.mean()), 3), round(perimeter_m, 1)


def find_core(mask, plate, grid):
    """The building core is the large part of the plate the scanner never entered (lifts, fire stairs, shafts,
    toilets behind closed doors)."""
    scanned = ndimage.binary_closing(mask, structure=disk(0.4))
    unscanned = plate & ~scanned
    unscanned = ndimage.binary_opening(unscanned, structure=disk(1.5))   # drop slivers seen into through doors and glass
    inner = ndimage.binary_erosion(plate, structure=disk(2.0))           # the core does not touch the facade
    labels, n = ndimage.label(unscanned)
    blocks, core_px = [], np.zeros_like(plate)
    for i in range(1, n + 1):
        comp = labels == i
        area = comp.sum() / RES ** 2
        if area < 15 or not (comp & inner).any() or (comp & ~inner).sum() > 0.2 * comp.sum():
            continue
        core_px |= comp
        cs, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        blocks.append({"polygon": grid.polygon_m(max(cs, key=cv2.contourArea), 0.75), "area_m2": round(float(area), 1),
                       "source": "unscanned region inside the floor"})
    return blocks, core_px


def core_from_shell(shell_path, grid, plate):
    """Use the walkthrough bake's core blocks (shell.json: core = list of polygons in scan metres) when available,
    so the agent plans on exactly the cleared floor the viewer shows."""
    sh = json.loads(open(shell_path, encoding="utf-8").read())
    blocks, core_px = [], np.zeros_like(plate)
    for blk in sh.get("core") or []:
        poly = blk.get("polygon", blk) if isinstance(blk, dict) else blk
        pts = np.array([[float(p[0]), float(p[1])] for p in poly])
        if len(pts) < 3:
            continue
        c, r = grid.to_px(pts[:, 0], pts[:, 1])
        m = np.zeros(plate.shape, np.uint8)
        cv2.fillPoly(m, [np.stack([c, r], 1).round().astype(np.int32)], 1)
        core_px |= m.astype(bool)
        blocks.append({"polygon": [[round(float(a), 2), round(float(b), 2)] for a, b in pts],
                       "area_m2": round(float(m.sum() / RES ** 2), 1), "source": "walkthrough bake (shell.json)"})
    return blocks, core_px


def find_columns(mask, plate, core_px, slices, grid):
    """Column candidates: small solid spots the scanner could not see the floor of, with mesh surfaces around them
    at both cut heights (so they run floor to ceiling). Low confidence by construction."""
    holes = plate & ~mask & ~ndimage.binary_dilation(core_px, structure=disk(0.5))
    labels, n = ndimage.label(holes)
    both = ndimage.binary_dilation(slices[0], iterations=2) & ndimage.binary_dilation(slices[1], iterations=2)
    out = []
    for i, sl in enumerate(ndimage.find_objects(labels), 1):
        comp = labels[sl] == i
        hm, wm = comp.shape[0] / RES, comp.shape[1] / RES
        fill = comp.mean()
        if not (0.25 <= wm <= 1.3 and 0.25 <= hm <= 1.3 and fill > 0.55 and max(wm, hm) / min(wm, hm) < 2.2):
            continue
        ring = ndimage.binary_dilation(labels == i, iterations=3) & ~(labels == i)
        if both[ring].mean() < 0.25:
            continue
        rows, cols = np.nonzero(labels == i)
        x, y = grid.to_m(cols.mean(), rows.mean())
        out.append({"x": round(float(x), 2), "y": round(float(y), 2), "w_m": round(wm, 2), "d_m": round(hm, 2),
                    "confidence": "low", "evidence": ["mesh: solid at 1.0 m and 2.0 m, floor not visible under it"]})
    return out


def grid_spacing(cols):
    """Most common spacing between neighbouring column candidates: a real column grid repeats."""
    if len(cols) < 3:
        return None
    pts = np.array([[c["x"], c["y"]] for c in cols])
    d = np.sqrt(((pts[:, None] - pts[None]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    nn = np.round(d.min(1) * 2) / 2
    vals, counts = np.unique(nn, return_counts=True)
    return {"spacing_m": float(vals[counts.argmax()]), "share": round(float(counts.max() / len(cols)), 2)}


def find_stairs(V, floor_z, ceil_z, grid):
    """Mesh geometry well below the floor marks something that passes between storeys: an open stair, a shaft."""
    below = V[V[:, 2] < floor_z - 0.6]
    if not len(below):
        return []
    occ = np.zeros((grid.h, grid.w), bool)
    c, r = grid.to_px(below[:, 0], below[:, 1])
    ok = (c >= 0) & (c < grid.w) & (r >= 0) & (r < grid.h)
    occ[r[ok].astype(int), c[ok].astype(int)] = True
    labels, n = ndimage.label(ndimage.binary_dilation(occ, structure=disk(1.0)))
    out = []
    for i in range(1, n + 1):
        rows, cols = np.nonzero((labels == i) & occ)
        xs, ys = grid.to_m(cols, rows)
        sel = below[(below[:, 0] >= xs.min() - .1) & (below[:, 0] <= xs.max() + .1) & (below[:, 1] >= ys.min() - .1) & (below[:, 1] <= ys.max() + .1)]
        if len(sel) < 40:
            continue
        out.append({"x": round(float(sel[:, 0].mean()), 2), "y": round(float(sel[:, 1].mean()), 2),
                    "bbox": [round(float(sel[:, 0].min()), 2), round(float(sel[:, 1].min()), 2), round(float(sel[:, 0].max()), 2), round(float(sel[:, 1].max()), 2)],
                    "depth_below_floor_m": round(float(floor_z - sel[:, 2].min()), 2), "points": int(len(sel)),
                    "kind": "unknown opening between floors", "confidence": "medium",
                    "evidence": [f"mesh: {len(sel)} points down to {floor_z - sel[:, 2].min():.1f} m below the floor"]})
    return out


def assumed_exits(core_blocks):
    """Fire stairs are behind closed doors and never scanned. Assume one at each end of every core block's long axis."""
    exits = []
    for b in core_blocks:
        p = np.array(b["polygon"])
        centre = p.mean(0)
        u, s, vt = np.linalg.svd(p - centre)
        axis = vt[0]
        proj = (p - centre) @ axis
        for end in (p[proj.argmin()], p[proj.argmax()]):
            exits.append({"x": round(float(end[0]), 2), "y": round(float(end[1]), 2), "kind": "fire stair (assumed)",
                          "confidence": "assumed", "evidence": ["placed at an end of the unscanned core; fire stairs were not scanned"]})
    return exits


# ---------- outputs ----------

def overlay(scan_id, meta, grid, geo, struct):
    folder = out_dir(scan_id)
    path = folder / "raw" / "plan_color.jpg"
    if path.exists() and "color" in meta:
        base = Image.open(path).convert("RGB")
        o, r = meta["color"]["origin"], meta["color"]["resolution"]
    else:
        base = Image.open(folder / "raw" / "plan.png").convert("RGB")
        o, r = meta["origin"], meta["resolution"]
    H = base.size[1]
    px = lambda x, y: ((x - o["x"]) * r, H - (y - o["y"]) * r)
    d = ImageDraw.Draw(base)
    lw = max(3, round(r / 12))
    d.line([px(*p) for p in geo["outline"] + geo["outline"][:1]], fill=(255, 255, 255), width=lw)
    for run in geo["windows"]:
        d.line([px(*p) for p in run], fill=(40, 170, 255), width=lw * 2)
    for b in struct["core"]:
        d.polygon([px(*p) for p in b["polygon"]], outline=(255, 200, 0), width=lw)
    for c in struct["columns"]:
        x, y = px(c["x"], c["y"]); s = r * 0.4
        d.rectangle([x - s, y - s, x + s, y + s], outline=(255, 60, 60), width=lw)
    for s_ in struct["stairs"]:
        a, b_ = px(s_["bbox"][0], s_["bbox"][3]), px(s_["bbox"][2], s_["bbox"][1])
        d.rectangle([a, b_], outline=(255, 0, 255), width=lw)
    for e in struct["exits"]:
        x, y = px(e["x"], e["y"]); s = r * 0.6
        d.ellipse([x - s, y - s, x + s, y + s], outline=(0, 230, 120), width=lw)
    base.thumbnail((2400, 2400))
    base.save(folder / "overlay.png")


def run(scan_id, property_id=None, floor=None, shell=None):
    model, meta = fetch(scan_id)
    folder = out_dir(scan_id)
    grid, mask = plan_mask_on_grid(meta, folder / "raw" / "plan.png")
    plate = regularise_plate(floor_plate(mask, RES), mask)
    V, F = load_mesh(folder / "raw" / "mesh.obj")
    panos = [p for p in model["panoLocations"] if p.get("position")]
    cam_z = float(np.median([p["position"]["z"] for p in panos]))
    heights = [r["dimensions"]["height"] for r in model.get("rooms") or [] if (r.get("dimensions") or {}).get("height")]
    floor_z = float(np.percentile(V[np.abs(V[:, 2] - (cam_z - 1.6)) < 0.5, 2], 10)) if len(V) else cam_z - 1.6
    ceiling = float(np.median(heights)) if heights else None
    slices = [slice_raster(V, F, floor_z + h, grid) for h in (1.0, 2.0)]

    contours, _ = cv2.findContours(plate.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = grid.polygon_m(max(contours, key=cv2.contourArea), 0.3)
    windows, window_px, window_share, perimeter_m = find_windows(mask, plate, grid)
    core, core_px = core_from_shell(shell, grid, plate) if shell else find_core(mask, plate, grid)
    columns = find_columns(mask, plate, core_px, slices, grid)
    stairs = find_stairs(V, floor_z, ceiling, grid)
    exits = assumed_exits(core)

    usable = plate & ~core_px
    dist_window_m = ndimage.distance_transform_edt(~window_px) / RES
    depth = dist_window_m[usable]
    plate_m2 = plate.sum() / RES ** 2
    geo = {
        "scan": scan_id, "property": property_id, "floor": floor, "name": model.get("name"),
        "units": "metres, the scan's own coordinates (x east-ish, y north-ish); 1 m = 3.28 ft",
        "outline": outline,
        "plate_sf": round(float(plate_m2 * SF_PER_M2)), "usable_sf_outside_core": round(float(usable.sum() / RES ** 2 * SF_PER_M2)),
        "bbox_m": [round(float(np.min([p[0] for p in outline])), 2), round(float(np.min([p[1] for p in outline])), 2),
                   round(float(np.max([p[0] for p in outline])), 2), round(float(np.max([p[1] for p in outline])), 2)],
        "perimeter_m": perimeter_m, "window_share_of_facade": window_share, "windows": windows,
        "daylight": {"deepest_ft_from_window": round(float(depth.max() * FT_PER_M), 1),
                     "share_within_25ft": round(float((depth * FT_PER_M <= 25).mean()), 3),
                     "share_within_30ft": round(float((depth * FT_PER_M <= 30).mean()), 3),
                     "note": "Distance to the nearest detected window, not just to the facade."},
        "cleared": ("The office fit-out is removed: interior walls, offices, meeting rooms, the old corridors and all "
                    "furniture are gone. What remains is the facade (with its windows), the core and the columns. "
                    "Everything between the facade and the core is open floor to plan on."),
        "ceiling_height_m": round(ceiling, 2) if ceiling else None,
        "ceiling_height_ft": round(ceiling * FT_PER_M, 1) if ceiling else None,
        "floor_z": round(floor_z, 2),
    }
    struct = {
        "scan": scan_id,
        "core": core, "columns": columns, "column_grid": grid_spacing(columns),
        "stairs": stairs, "exits": exits,
        "notes": ["Core = the large region inside the floor the scanner never entered. Treat it as structural.",
                  "Columns are low-confidence guesses from the mesh. Keep walls off them anyway.",
                  "Fire stairs were not scanned; exits are assumed at the ends of the core."],
    }
    (folder / "geometry.json").write_text(json.dumps(geo, indent=1), encoding="utf-8")
    (folder / "structure.json").write_text(json.dumps(struct, indent=1), encoding="utf-8")
    col_px = np.zeros_like(plate)
    for c in columns:
        cc, rr = grid.to_px(c["x"], c["y"])
        col_px[max(0, int(rr - 0.4 * RES)):int(rr + 0.4 * RES), max(0, int(cc - 0.4 * RES)):int(cc + 0.4 * RES)] = True
    np.savez_compressed(folder / "grid.npz", plate=plate, window=window_px, core=core_px, columns=col_px,
                        frame=np.array([grid.x0, grid.y0, grid.w, grid.h, RES]))
    panos_out = [{"id": p["id"], "label": p["label"], "x": round(p["position"]["x"], 2), "y": round(p["position"]["y"], 2)} for p in panos]
    (folder / "panos.json").write_text(json.dumps(panos_out), encoding="utf-8")
    overlay(scan_id, meta, grid, geo, struct)
    return geo, struct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--property", type=int)
    ap.add_argument("--floor", type=int)
    ap.add_argument("--shell", help="the walkthrough bake's shell.json, to use its core outline")
    a = ap.parse_args()
    geo, struct = run(a.scan, a.property, a.floor, a.shell)
    print(f"{geo['name']}: plate {geo['plate_sf']} sf, windows on {geo['window_share_of_facade']:.0%} of facade, "
          f"deepest point {geo['daylight']['deepest_ft_from_window']} ft from a window, ceiling {geo['ceiling_height_ft']} ft")
    print(f"core blocks {len(struct['core'])}, columns {len(struct['columns'])} {struct['column_grid']}, "
          f"stairs {len(struct['stairs'])}, assumed exits {len(struct['exits'])}")


if __name__ == "__main__":
    main()
