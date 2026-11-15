"""The walkthrough's scene file for one scanned floor: capture points, outer wall, daylight band.

    python -m pipeline.bake.scene <scanId>

Writes web/walkthrough/floors/<scanId>/data/scene.json and data/band.png. Everything is in the scan's own metres
(x east, y north, z up); index.html turns them into three.js world coordinates (x, z, -y).

Fields index.html reads:
    panos      [{id, label, p: [x, y, z], q: [x, y, z, w]}]   q is Matterport's rotation as given (the viewer inverts it)
    outline    [[x1, y1, x2, y2], ...]   the outer wall, as straight segments round the floor plate
    floorY, ceilY                        floor and ceiling heights (scan z)
    bandRect   [x, y, w, h]              the rectangle the floor images (band.png, floorfill.png, walk.png) cover;
                                         y is its south edge, and an image's top row is its north edge
    share      fraction of the scanned floor within 30 ft of the outer wall (the daylight legend)
    stats      {areaSf, plateSf, capturePoints}
    atlases, groups                      from the mesh bake (pipeline/bake/mesh.py, data/mesh.json); empty until it
                                         has run. When mesh.json is there, its floorY, ceilY and bandRect are used, so
                                         band.png lies exactly over the mesh bake's floorfill.png

The outer wall comes from the floor plate (pipeline/daylight.py floor_plate): the transparent floor plan, closed and
filled, traced and simplified to straight walls. Pranava fitted a rectangle for floor 16; this handles any shape.
"""
import argparse
import glob
import json

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from pipeline import daylight
from pipeline.bake import source

DAYLIGHT_M = 30 / 3.2808              # 30 ft
CAMERA_HEIGHT_M = 1.42                # Matterport tripod: capture points sit about this far above the floor
DEFAULT_CEILING_M = 2.7
BAND_MARGIN_M = 1.0                   # the floor images reach this far past the plate
SIMPLIFY_M = 0.5                      # outline vertices closer than this to a straight wall are dropped
MIN_WALL_M = 0.8                      # shorter jogs are folded into their neighbours
AMBER, BLUE = (255, 176, 46), (46, 86, 140)   # index.html's legend colours
BAND_ALPHA = 150


class Plate:
    """The floor plate on a raster, with the mapping from its pixels to scan metres."""

    def __init__(self, scan):
        png, meta = source.plan(scan)
        alpha = np.array(Image.open(png).convert("RGBA"))[..., 3] > 0
        self.scanned, res = daylight.resample(alpha, meta["resolution"])
        self.plate = daylight.floor_plate(self.scanned, res)
        h, w = self.plate.shape
        self.mx = meta["width"] / meta["resolution"] / w                # metres per pixel, x and y
        self.my = meta["height"] / meta["resolution"] / h
        self.ox, self.oy = meta["origin"]["x"], meta["origin"]["y"]    # the plan's lower-left corner
        self.top = self.oy + h * self.my                                # y of row 0's top edge

    def to_m(self, col, row):
        return self.ox + col * self.mx, self.top - row * self.my

    def distance_m(self):
        """Distance from each plate pixel to the plate's edge (the outer wall), in metres."""
        return ndimage.distance_transform_edt(self.plate, sampling=(self.my, self.mx))


def outline(scan, plate=None):
    """The outer wall as straight segments [[x1, y1, x2, y2], ...] in scan metres, going round the plate."""
    p = plate or Plate(scan)
    contours, _ = cv2.findContours(p.plate.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    ring = max(contours, key=cv2.contourArea)
    eps = SIMPLIFY_M / ((p.mx + p.my) / 2)
    pts = cv2.approxPolyDP(ring, eps, True)[:, 0, :].astype(float)
    pts = _fold_short(pts, MIN_WALL_M / ((p.mx + p.my) / 2))
    xy = [p.to_m(c + 0.5, r + 0.5) for c, r in pts]
    xy = _square_up(xy, cv2.minAreaRect(ring)[2])
    return [[round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)]
            for a, b in zip(xy, xy[1:] + xy[:1])]


ALIGN_DEG = 15          # walls within this of the building's main axes are made exactly parallel to them
CHAMFER_M = 3.0         # shorter walls off those axes are corner noise: the two neighbouring walls meet instead


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _square_up(xy, rect_angle_deg):
    """Make near-axis walls exactly parallel to the building's main axes and drop short diagonal corner cuts, so a
    rectangular floor gets square corners; genuinely angled walls (longer than CHAMFER_M) are kept as they are."""
    axis = np.radians(rect_angle_deg)
    dirs = [np.array([np.cos(axis), np.sin(axis)]), np.array([-np.sin(axis), np.cos(axis)])]

    def edges(points):
        return [(np.array(points[i]), np.array(points[(i + 1) % len(points)])) for i in range(len(points))]

    def aligned(a, b):
        d = (b - a) / (np.linalg.norm(b - a) or 1)
        for u in dirs:
            if abs(d @ u) >= np.cos(np.radians(ALIGN_DEG)):
                return u if d @ u > 0 else -u
        return None

    # 1. each wall as a line through its midpoint, along the main axis it nearly follows (or its own direction);
    #    short off-axis walls are corner noise and get no line, so their neighbours meet instead
    pts = [np.array(q, float) for q in xy]
    lines = []
    for a, b in edges(pts):
        d = aligned(a, b)
        if d is None and np.linalg.norm(b - a) < CHAMFER_M:
            continue
        lines.append(((a + b) / 2, d if d is not None else (b - a) / (np.linalg.norm(b - a) or 1)))
    if len(lines) < 3:
        return xy
    # 2. merge consecutive parallel lines (a wall split by a dropped chamfer) and intersect the rest
    merged = []
    for ln in lines:
        if merged and abs(_cross(merged[-1][1], ln[1])) < 1e-6:
            merged[-1] = ((merged[-1][0] + ln[0]) / 2, merged[-1][1])
        else:
            merged.append(ln)
    if len(merged) > 1 and abs(_cross(merged[0][1], merged[-1][1])) < 1e-6:
        merged[0] = ((merged[0][0] + merged[-1][0]) / 2, merged[0][1])
        merged.pop()
    out = []
    for i in range(len(merged)):
        (p1, d1), (p2, d2) = merged[i - 1], merged[i]
        t = np.linalg.solve(np.array([d1, -d2]).T, p2 - p1)[0]
        out.append(p1 + t * d1)
    return [(float(q[0]), float(q[1])) for q in out]


def _fold_short(pts, min_len):
    """Drop vertices that make walls shorter than min_len (scan noise at window mullions), keeping at least 4."""
    pts = list(pts)
    changed = True
    while changed and len(pts) > 4:
        changed = False
        for i in range(len(pts)):
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % len(pts)])
            if np.hypot(*(b - a)) < min_len:
                del pts[(i + 1) % len(pts)]
                changed = True
                break
    return pts


def band(scan, plate=None, rect=None):
    """(bandRect [x, y, w, h], share within 30 ft, RGBA band image). The image covers bandRect, top row north.
    rect: draw over this rectangle instead (the mesh bake's, so band.png and floorfill.png line up)."""
    p = plate or Plate(scan)
    if rect is not None:
        return _band_over(p, [float(v) for v in rect])
    rows, cols = np.nonzero(p.plate)
    pad_c, pad_r = int(round(BAND_MARGIN_M / p.mx)), int(round(BAND_MARGIN_M / p.my))
    h, w = p.plate.shape
    r0, r1 = max(0, rows.min() - pad_r), min(h, rows.max() + 1 + pad_r)
    c0, c1 = max(0, cols.min() - pad_c), min(w, cols.max() + 1 + pad_c)
    x0, ytop = p.to_m(c0, r0)
    x1, ybot = p.to_m(c1, r1)
    rect = [round(float(x0), 3), round(float(ybot), 3), round(float(x1 - x0), 3), round(float(ytop - ybot), 3)]

    dist = p.distance_m()
    floor = ndimage.binary_closing(p.scanned, structure=np.ones((5, 5))) & p.plate   # scanned floor, pinholes closed
    near = dist <= DAYLIGHT_M
    share = float((near & floor).sum() / max(1, floor.sum()))
    img = np.zeros((h, w, 4), np.uint8)
    img[floor & near, :3] = AMBER
    img[floor & ~near, :3] = BLUE
    img[floor, 3] = BAND_ALPHA
    return rect, round(share, 3), Image.fromarray(img[r0:r1, c0:c1], "RGBA")


def _band_over(p, rect):
    """The band drawn over a given rectangle at the plate's own resolution (nearest plate pixel per image pixel)."""
    x, y, w, h = rect
    dist = p.distance_m()
    floor = ndimage.binary_closing(p.scanned, structure=np.ones((5, 5))) & p.plate
    near = dist <= DAYLIGHT_M
    share = float((near & floor).sum() / max(1, floor.sum()))
    cols, rows = max(1, int(round(w / p.mx))), max(1, int(round(h / p.my)))
    xs = x + (np.arange(cols) + 0.5) * (w / cols)
    ys = y + h - (np.arange(rows) + 0.5) * (h / rows)            # top row is the north edge
    ci = np.floor((xs - p.ox) / p.mx).astype(int)
    ri = np.floor((p.top - ys) / p.my).astype(int)
    H, W = p.plate.shape
    ok = (ri[:, None] >= 0) & (ri[:, None] < H) & (ci[None, :] >= 0) & (ci[None, :] < W)
    rr, cc = np.clip(ri, 0, H - 1)[:, None], np.clip(ci, 0, W - 1)[None, :]
    f, n = floor[rr, cc] & ok, near[rr, cc]
    img = np.zeros((rows, cols, 4), np.uint8)
    img[f & n, :3] = AMBER
    img[f & ~n, :3] = BLUE
    img[f, 3] = BAND_ALPHA
    return [round(v, 3) for v in rect], round(share, 3), Image.fromarray(img, "RGBA")


def floor_and_ceiling(scan):
    """(floorY, ceilY) from the MatterPak mesh's height histogram when it is on disk, else from the capture points."""
    objs = glob.glob(str(source.raw_dir(scan) / "pak" / "*.obj"))
    if objs:
        z = np.array([float(line.split()[3]) for line in open(objs[0], encoding="utf-8", errors="ignore")
                      if line.startswith("v ")])
        hist, edges = np.histogram(z, bins=np.arange(z.min(), z.max() + 0.05, 0.05))
        mid = (edges[:-1] + edges[1:]) / 2
        cam = float(np.median([pt["position"]["z"] for pt in source.model(scan)["panoLocations"]]))
        below, above = mid < cam - 0.5, mid > cam + 0.5          # the floor is under the cameras, the ceiling over
        if below.any() and above.any():
            return round(float(mid[below][hist[below].argmax()]), 3), round(float(mid[above][hist[above].argmax()]), 3)
    cam = float(np.median([pt["position"]["z"] for pt in source.model(scan)["panoLocations"]]))
    return round(cam - CAMERA_HEIGHT_M, 3), round(cam - CAMERA_HEIGHT_M + DEFAULT_CEILING_M, 3)


def write_scene(scan, mesh_info=None):
    """Write data/scene.json and data/band.png. mesh_info (from pipeline/bake/mesh.py) supplies atlases, groups and,
    when it measured them, floorY and ceilY. Returns the scene dict."""
    data = source.floor_dir(scan) / "data"
    if mesh_info is None and (data / "mesh.json").exists():          # the mesh bake ran first: use what it measured
        mesh_info = json.loads((data / "mesh.json").read_text(encoding="utf-8"))
    mesh_info = mesh_info or {}
    model = source.model(scan)
    p = Plate(scan)
    rect, share, band_img = band(scan, p, mesh_info.get("bandRect"))
    floor_y, ceil_y = (mesh_info["floorY"], mesh_info["ceilY"]) if "floorY" in mesh_info and "ceilY" in mesh_info \
        else floor_and_ceiling(scan)
    sf = lambda px, mx, my: round(float(px) * mx * my * daylight.SF_PER_M2)
    scene = {
        "scan": scan, "name": model.get("name"),
        "panos": [{"id": pt["id"], "label": pt.get("label"),
                   "p": [round(pt["position"][k], 4) for k in "xyz"],
                   "q": [round(pt["rotation"][k], 6) for k in "xyzw"]} for pt in model["panoLocations"]],
        "outline": outline(scan, p),
        "floorY": floor_y,
        "ceilY": ceil_y,
        "bandRect": rect,
        "share": share,
        "stats": {"areaSf": sf(p.scanned.sum(), p.mx, p.my), "plateSf": sf(p.plate.sum(), p.mx, p.my),
                  "capturePoints": len(model["panoLocations"])},
        "atlases": mesh_info.get("atlases", 0),
        "groups": mesh_info.get("groups", []),
    }
    data.mkdir(parents=True, exist_ok=True)
    band_img.save(data / "band.png")
    (data / "scene.json").write_text(json.dumps(scene), encoding="utf-8")
    return scene


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    a = ap.parse_args()
    s = write_scene(a.scan)
    print(f"{a.scan}: {len(s['panos'])} capture points, {len(s['outline'])} wall segments, floorY {s['floorY']}, "
          f"ceilY {s['ceilY']}, bandRect {s['bandRect']}, {round(s['share'] * 100)}% within 30 ft, {s['stats']}")


if __name__ == "__main__":
    main()
