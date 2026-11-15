"""The empty floor: photo-baked exterior walls, core, columns and walkable area for one scanned floor.

    python -m pipeline.bake.shell <scanId> [...]

Writes web/walkthrough/floors/<scanId>/data/:
    shell.json   rect [x0, x1, y0, y1], z0, z1, eye, pieces (exterior wall quads into walls.jpg), core [{outer, holes}],
                 columns [{x, y, size, grade}], plus a summary
    walls.jpg    the exterior walls, baked from the 360-degree photos
    walk.png     where the empty floor can be walked, 8 px per metre over scene.json's bandRect (row 0 = north)

Pranava's floor 16 recipe (web/walkthrough/HANDOFF.md, section 3), generalised from a rectangle to any outline:
- the outer wall is scene.json's outline (pipeline/bake/scene.py) when that is a clean polygon that agrees with the scanned
  floor; otherwise (window reflections bulging it out, as on The Tower) the scanned floor's own edge, squared up, which
  is where the rooms meet the glass. Each wall is baked at 160 px/m
- the walls run from the floor to the ceiling the scan shows: scene.json's ceilY, or the exposed deck above it when
  most of the ceiling mesh is there (3415 Sepulveda)
- each 5 cm run of wall is coloured from the capture point that sees it best: near, facing it, and with a clear line of
  sight past the office partitions (the mesh cut at eye height); choices are majority-smoothed along the wall and the
  joins between photos feathered
- below the sill the wall is drawn (plain wall and baseboard), as the photos there show desks and radiators
- stretches no photo sees clearly, or where the glass is washed out, are mirrored from the nearest good stretch
- core: the large unscanned regions inside the floor; columns: small solid spots running floor to ceiling
  (pipeline/floorprep.py find_core / find_columns)

The photo sampling uses exactly the walkthrough's own mapping (index.html: FACE_ORDER, T_M, SWAP, YAW0 = 90 degrees,
inverted capture-point rotation), so the walls show the same pixels the walk mode does.
"""
import argparse
import glob
import json
import math
from collections import OrderedDict

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

from pipeline import floorprep
from pipeline.bake import scene as scene_mod
from pipeline.bake import source

PX_PER_M = 160            # wall texture resolution
RUN_M = 0.05              # each run of wall picks one photo
SMOOTH_RUNS = 9           # majority smoothing of the photo choice along the wall
FEATHER_PX = 14           # joins between photos are blended over this many pixels
ATLAS_W = 8192            # walls.jpg width; long walls are split into pieces that fit
SILL_M = 0.6              # below this the wall is drawn, not photographed
MAX_VIEW_M = 22.0         # capture points farther than this are not used for a wall
MIN_STANDOFF_M = 1.5      # ... nor ones closer to it than this: the wall is then seen at a grazing angle, and a
                          #     camera right at the glass sees past the drawn wall line into the room
MIN_FACING = 0.3          # ... nor ones looking along it (cosine of the angle off the wall's normal)
WALK_PX_PER_M = 8
EYE_M = 1.6
YAW0 = math.radians(90)
FACE_ORDER = [2, 4, 0, 5, 1, 3]   # cube +x, -x, +y, -y, +z, -z <- scan faces (0 up, 1-4 sides turning right, 5 down)
WALL_RGB = np.array([0.93, 0.915, 0.875]) * 255
BASE_RGB = np.array([0.40, 0.23, 0.10]) * 255
BASE_LINE_RGB = np.array([0.25, 0.14, 0.06]) * 255


# ---------- photo sampling, as the walkthrough does it ----------

def quat_matrix(x, y, z, w):
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


SWAP = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], float)       # scan-local (x, y, z) -> cube (x, z, y)
RZ = np.array([[math.cos(YAW0), -math.sin(YAW0), 0], [math.sin(YAW0), math.cos(YAW0), 0], [0, 0, 1]])


def cube_matrix(q):
    """Scan-space direction -> cube direction, as index.html builds it (rotation inverted, then Rz(YAW0), then SWAP).
    T_M there turns three.js world directions into scan directions; here directions are already in scan space."""
    r_inv = quat_matrix(*q).T
    return SWAP @ RZ @ r_inv


def cube_lookup(d):
    """Cube directions (N, 3) -> (face index into the cube's +x..-z order, s, t), WebGL's cube map rules."""
    ax, ay, az = np.abs(d[:, 0]), np.abs(d[:, 1]), np.abs(d[:, 2])
    face = np.where((ax >= ay) & (ax >= az), np.where(d[:, 0] > 0, 0, 1),
                    np.where(ay >= az, np.where(d[:, 1] > 0, 2, 3), np.where(d[:, 2] > 0, 4, 5)))
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    sc = np.select([face == 0, face == 1, face == 2, face == 3, face == 4], [-z, z, x, x, x], -x)
    tc = np.select([face == 0, face == 1, face == 2, face == 3, face == 4], [-y, -y, z, -z, -y], -y)
    ma = np.select([face < 2, face < 4], [ax, ay], az)
    return face, (sc / ma + 1) / 2, (tc / ma + 1) / 2


class Panos:
    """The capture points and their 2k faces, loaded on demand (a handful kept in memory)."""

    def __init__(self, scan, scene, keep=10):
        self.dir = source.floor_dir(scan) / "pano" / "2k"
        self.pts = scene["panos"]
        self.pos = np.array([p["p"] for p in self.pts], float)
        self.mats = [cube_matrix(p["q"]) for p in self.pts]
        self.cache, self.keep = OrderedDict(), keep

    def faces(self, i):
        if i in self.cache:
            self.cache.move_to_end(i)
            return self.cache[i]
        pid = self.pts[i]["id"]
        imgs = [np.asarray(Image.open(self.dir / f"{pid}_{FACE_ORDER[k]}.jpg").convert("RGB")) for k in range(6)]
        self.cache[i] = imgs
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)
        return imgs

    def sample(self, i, pts):
        """Colours (N, 3) seen from capture point i towards scan-space points (N, 3)."""
        d = (pts - self.pos[i]) @ self.mats[i].T
        face, s, t = cube_lookup(d)
        imgs = self.faces(i)
        out = np.zeros((len(pts), 3), np.float32)
        for k in range(6):
            m = face == k
            if not m.any():
                continue
            img = imgs[k]
            h, w = img.shape[:2]
            col = np.clip(s[m] * w, 0, w - 1.001)
            row = np.clip(t[m] * h, 0, h - 1.001)
            c0, r0 = col.astype(int), row.astype(int)
            fc, fr = (col - c0)[:, None], (row - r0)[:, None]
            p00, p01 = img[r0, c0].astype(np.float32), img[r0, c0 + 1].astype(np.float32)
            p10, p11 = img[r0 + 1, c0].astype(np.float32), img[r0 + 1, c0 + 1].astype(np.float32)
            out[m] = (p00 * (1 - fc) + p01 * fc) * (1 - fr) + (p10 * (1 - fc) + p11 * fc) * fr
        return out


# ---------- the floor on a raster ----------

CLEAN_SEGMENTS = 8        # scene.json's outline is used as is when it has at most this many walls ...
AGREE_IOU = 0.9           # ... and covers the same floor as the scanned edge
FOLD_M = 1.0              # window-line walls shorter than this are mullion noise
EXPOSED_M = 0.4           # a ceiling mesh this far above ceilY is an exposed deck, not a fitting


def polygon_from_outline(outline):
    return [(s[0], s[1]) for s in outline]


def polygon_area(poly):
    p = np.asarray(poly, float)
    return 0.5 * abs(float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))))


def main_axis_deg(poly, min_len=6.0):
    """The building's main axis (0-90 degrees) from the directions of its long walls, weighted by length."""
    p = np.asarray(poly, float)
    e = np.roll(p, -1, 0) - p
    L = np.hypot(e[:, 0], e[:, 1])
    a = np.degrees(np.arctan2(e[:, 1], e[:, 0])) % 90
    w = L * (L > min_len) if (L > min_len).any() else L
    h = np.bincount(np.round(a).astype(int) % 90, weights=w, minlength=90)
    h = h + np.roll(h, 1) + np.roll(h, -1)
    return float(h.argmax())


def window_line(mask, grid):
    """The scanned floor's outer edge (scan metres, counter-clockwise ring), where the rooms meet the glass: thin
    reflection streaks dropped, unscanned rooms along the edge bridged, near-axis walls squared up."""
    R = floorprep.RES
    m = ndimage.binary_opening(mask, structure=floorprep.disk(0.6))           # reflection streaks are thin
    lab, n = ndimage.label(m)
    if n == 0:
        return None
    m = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)
    pad = int(4 * R)
    m = ndimage.binary_closing(np.pad(m, pad), structure=floorprep.disk(3.0))[pad:-pad, pad:-pad]
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, structure=floorprep.disk(2.0))               # blobs of glare outside the glass
    lab, n = ndimage.label(m)
    if n == 0:
        return None
    m = lab == (np.bincount(lab.ravel())[1:].argmax() + 1)
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    ring = max(cs, key=cv2.contourArea)
    fine = cv2.approxPolyDP(ring, 0.2 * R, True)[:, 0, :].astype(float)
    axis = main_axis_deg(np.c_[grid.to_m(fine[:, 0], fine[:, 1])])
    pts = np.array(scene_mod._fold_short(cv2.approxPolyDP(ring, 0.6 * R, True)[:, 0, :].astype(float), FOLD_M * R), float)
    xs, ys = grid.to_m(pts[:, 0], pts[:, 1])
    xy = scene_mod._square_up([(float(x), float(y)) for x, y in zip(xs, ys)], axis)
    p = np.asarray(xy)
    if float(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))) < 0:
        xy = xy[::-1]
    return [(round(x, 3), round(y, 3)) for x, y in xy]


def choose_outline(scene, mask, grid):
    """(wall polygon, where it came from): scene.json's outline when clean and in agreement with the scanned edge,
    else the scanned edge."""
    poly = polygon_from_outline(scene["outline"])
    wl = window_line(mask, grid)
    if wl is None:
        return poly, "scene"
    a = raster_polygon(poly, grid)
    b = raster_polygon(wl, grid)
    iou = (a & b).sum() / max(1, (a | b).sum())
    if len(poly) <= CLEAN_SEGMENTS and iou >= AGREE_IOU:
        return poly, "scene"
    return wl, "window line"


def ceiling_height(V, scene):
    """z1 for the walls: ceilY, or the exposed deck when most of the ceiling mesh sits more than EXPOSED_M above it."""
    ceil = scene["ceilY"]
    if V is None or not len(V):
        return ceil, "scene"
    up = V[:, 2][V[:, 2] > ceil - 0.3]
    if len(up) < 100 or np.percentile(up, 90) <= ceil + EXPOSED_M:
        return ceil, "scene"
    hi = up[up > ceil + EXPOSED_M]
    hist, edges = np.histogram(hi, bins=np.arange(hi.min(), hi.max() + 0.04, 0.02))
    return round(float(edges[hist.argmax()] + 0.01), 3), "exposed deck"


def raster_polygon(poly, grid):
    img = np.zeros((grid.h, grid.w), np.uint8)
    c, r = grid.to_px([p[0] for p in poly], [p[1] for p in poly])
    cv2.fillPoly(img, [np.stack([c, r], 1).round().astype(np.int32)], 1)
    return img.astype(bool)


def inward_normal(a, b, plate, grid):
    """Unit normal of wall a->b pointing into the floor plate."""
    d = np.array(b, float) - np.array(a, float)
    n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) or 1)
    mid = (np.array(a) + np.array(b)) / 2
    probe = mid + n * 0.6
    c, r = grid.to_px(probe[0], probe[1])
    c, r = int(round(float(c))), int(round(float(r)))
    inside = 0 <= r < plate.shape[0] and 0 <= c < plate.shape[1] and plate[r, c]
    return n if inside else -n


def clear_line(obstacles, grid, p0, p1, stop_m=0.6):
    """True when the straight line p0 -> p1 (scan metres) crosses no obstacle pixel, ignoring its last stop_m."""
    d = np.array(p1) - np.array(p0)
    L = np.linalg.norm(d)
    if L <= stop_m:
        return True
    n = int((L - stop_m) * floorprep.RES) + 1
    t = np.linspace(0, (L - stop_m) / L, n)
    pts = np.array(p0) + d * t[:, None]
    c, r = grid.to_px(pts[:, 0], pts[:, 1])
    c, r = np.round(c).astype(int), np.round(r).astype(int)
    ok = (r >= 0) & (r < obstacles.shape[0]) & (c >= 0) & (c < obstacles.shape[1])
    return not obstacles[r[ok], c[ok]].any()


def majority(choice, k):
    """Most common value in a sliding window of k (choice: int array, -1 = none)."""
    out = choice.copy()
    h = k // 2
    for i in range(len(choice)):
        win = choice[max(0, i - h):i + h + 1]
        win = win[win >= 0]
        if len(win):
            vals, counts = np.unique(win, return_counts=True)
            out[i] = vals[counts.argmax()] if choice[i] < 0 or counts.max() > (win == choice[i]).sum() else choice[i]
    return out


def mirror_fill(img, bad_cols):
    """Replace runs of bad columns by mirroring the nearest good stretch beside them."""
    W = img.shape[1]
    good = ~bad_cols
    if not good.any():
        return img
    i = 0
    while i < W:
        if not bad_cols[i]:
            i += 1
            continue
        j = i
        while j < W and bad_cols[j]:
            j += 1
        n = j - i
        left = img[:, max(0, i - n):i][:, ::-1] if i > 0 else None
        right = img[:, j:min(W, j + n)][:, ::-1] if j < W else None
        src = left if left is not None and left.shape[1] == n and good[i - n:i].all() else right
        if src is None or src.shape[1] < n:
            src = left if left is not None and left.shape[1] else right
            src = np.resize(src, (img.shape[0], n, 3)) if src is not None else None
        if src is not None:
            img[:, i:j] = src[:, :n]
        i = j
    return img


# ---------- one wall ----------

def bake_wall(a, b, inward, z0, z1, panos, obstacles, grid):
    """Texture (H, W, 3) for the wall a->b seen from inside, plus the share of it a photo saw clearly."""
    a, b = np.array(a, float), np.array(b, float)
    L = float(np.linalg.norm(b - a))
    W = max(2, int(round(L * PX_PER_M)))
    H = max(2, int(round((z1 - z0) * PX_PER_M)))
    along = (b - a) / L
    runs = max(1, int(math.ceil(L / RUN_M)))
    centres = a + along * ((np.arange(runs) + 0.5) * L / runs)[:, None]
    eye_z = z0 + 1.4
    # capture point per run: near, frontal, and with a clear line of sight past the partitions
    choice = np.full(runs, -1)
    pos2 = panos.pos[:, :2]
    for k, c in enumerate(centres):
        v = pos2 - c
        dist = np.linalg.norm(v, axis=1)
        facing = (v @ inward) / np.maximum(dist, 1e-6)                # 1 = straight in front of the wall
        order = np.argsort(dist * (1 + 2.0 * (1 - np.clip(facing, 0, 1))))
        for i in order[:12]:
            if dist[i] > MAX_VIEW_M or facing[i] < MIN_FACING or dist[i] * facing[i] < MIN_STANDOFF_M:
                continue
            if clear_line(obstacles, grid, pos2[i], c + inward * 0.05):
                choice[k] = i
                break
    choice = majority(choice, SMOOTH_RUNS)
    col_run = np.minimum((np.arange(W) + 0.5) / W * runs, runs - 1).astype(int)
    col_choice = choice[col_run]
    # sample each used photo where it (feathered) contributes
    us = (np.arange(W) + 0.5) / W
    zs = z1 - (np.arange(H) + 0.5) / PX_PER_M                          # row 0 is the ceiling end
    xy = a + along * (us * L)[:, None]
    acc = np.zeros((H, W, 3), np.float32)
    wsum = np.zeros((W,), np.float32)
    for i in np.unique(col_choice[col_choice >= 0]):
        wgt = ndimage.gaussian_filter1d((col_choice == i).astype(np.float32), FEATHER_PX / 2.5, mode="nearest")
        cols = np.nonzero(wgt > 0.02)[0]
        if not len(cols):
            continue
        P = np.empty((H, len(cols), 3))
        P[..., 0] = xy[cols, 0][None, :]
        P[..., 1] = xy[cols, 1][None, :]
        P[..., 2] = zs[:, None]
        rgb = panos.sample(i, P.reshape(-1, 3)).reshape(H, len(cols), 3)
        acc[:, cols] += rgb * wgt[cols][None, :, None]
        wsum[cols] += wgt[cols]
    img = np.where(wsum[None, :, None] > 0, acc / np.maximum(wsum, 1e-6)[None, :, None], 0).astype(np.float32)
    # washed-out glass: the window band all but white
    band = img[int(H * 0.2):int(H * 0.7)]
    washed = band.mean(axis=(0, 2)) > 242
    bad = (col_choice < 0) | washed
    clear_share = float(1 - bad.mean())
    img = mirror_fill(img, bad)
    draw_sill(img, z0, z1)
    return np.clip(img, 0, 255).astype(np.uint8), clear_share


def draw_sill(img, z0, z1):
    """Below the sill the wall is drawn: plain wall, a baseboard, and a soft edge into the photo above."""
    H = img.shape[0]
    hh = z1 - z0 - (np.arange(H) + 0.5) / PX_PER_M                     # height of each row above the floor
    wall = np.where((hh < 0.10)[:, None], BASE_RGB, np.where((hh < 0.112)[:, None], BASE_LINE_RGB, WALL_RGB))
    shade = (1 - 0.10 * np.exp(-hh * 5.0))[:, None]
    blend = np.clip((SILL_M - hh) / 0.03, 0, 1)[:, None, None]         # 3 cm soft edge at the sill
    img[:] = img * (1 - blend) + (wall * shade)[:, None, :] * blend


# ---------- core, columns, walkable area ----------

def structure(scan, scene, grid, mask, plate):
    """(core blocks [{outer, holes}], core raster, columns [{x, y, size, grade}], partitions at eye height, mesh
    vertices or None)."""
    objs = glob.glob(str(source.raw_dir(scan) / "pak" / "*.obj"))
    blocks, core_px = floorprep.find_core(mask, plate, grid)
    core = [{"outer": b["polygon"], "holes": []} for b in blocks]
    columns = []
    obstacles = np.zeros_like(plate)
    V = None
    if objs:
        V, F = floorprep.load_mesh(objs[0])
        z0 = scene["floorY"]
        slices = [floorprep.slice_raster(V, F, z0 + h, grid) for h in (1.0, 2.0)]
        cands = floorprep.find_columns(mask, plate, core_px, slices, grid)
        columns = grade_columns(cands)
        obstacles = floorprep.slice_raster(V, F, z0 + 1.4, grid)
    return core, core_px, columns, obstacles, V


def grade_columns(cands):
    """Pranava's grading: 'probable' when it shares a row or a line with at least two others, else 'possible'."""
    out = []
    for c in cands:
        size = round(float(min(1.0, max(0.4, max(c["w_m"], c["d_m"])))), 2)
        in_row = sum(1 for o in cands if o is not c and abs(o["y"] - c["y"]) < 0.5)
        in_line = sum(1 for o in cands if o is not c and abs(o["x"] - c["x"]) < 0.5)
        out.append({"x": c["x"], "y": c["y"], "size": size, "grade": "probable" if max(in_row, in_line) >= 2 else "possible"})
    return out


def walk_mask(scene, plate_poly, core, columns):
    """White where the empty floor can be walked, over bandRect at WALK_PX_PER_M, row 0 = north."""
    bx, by, bw, bh = scene["bandRect"]
    W, H = max(1, round(bw * WALK_PX_PER_M)), max(1, round(bh * WALK_PX_PER_M))
    to_px = lambda x, y: ((x - bx) * WALK_PX_PER_M, (by + bh - y) * WALK_PX_PER_M)
    img = np.zeros((H, W), np.uint8)
    ring = lambda pts: np.array([to_px(x, y) for x, y in pts]).round().astype(np.int32)
    cv2.fillPoly(img, [ring(plate_poly)], 255)
    img = cv2.erode(img, np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)                     # keep about 30 cm off the outer wall
    for blk in core:
        cv2.fillPoly(img, [ring(blk["outer"])], 0)
    keep_off = int(round(0.3 * WALK_PX_PER_M))
    for c in columns:
        cx, cy = to_px(c["x"], c["y"])
        r = c["size"] / 2 * WALK_PX_PER_M + keep_off
        cv2.rectangle(img, (int(cx - r), int(cy - r)), (int(cx + r), int(cy + r)), 0, -1)
    return img


# ---------- the whole shell ----------

def pack(pieces_imgs):
    """Shelf-pack wall textures (each at most ATLAS_W wide) into one atlas. Returns (atlas, [(x, y)] per image)."""
    x = y = shelf = 0
    places = []
    for img in pieces_imgs:
        h, w = img.shape[:2]
        if x + w > ATLAS_W:
            x, y, shelf = 0, y + shelf, 0
        places.append((x, y))
        x += w
        shelf = max(shelf, h)
    H = y + shelf
    atlas = np.full((max(1, H), ATLAS_W, 3), 200, np.uint8)
    for img, (px, py) in zip(pieces_imgs, places):
        atlas[py:py + img.shape[0], px:px + img.shape[1]] = img
    return atlas, places


def clip_floor_images(data, band_rect, poly, margin_m=0.15):
    """Clear floorfill.png and band.png outside the outer walls (plus a small margin, so the carpet meets the wall):
    the plate they were drawn from can include window reflections the walls now leave outside."""
    from PIL import ImageDraw
    bx, by, bw, bh = band_rect
    for name in ("floorfill.png", "band.png"):
        path = data / name
        if not path.exists():
            continue
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        sx, sy = w / bw, h / bh                                   # pixels per metre; top row is north
        to_px = lambda x, y: ((x - bx) * sx, (by + bh - y) * sy)
        keep = Image.new("L", (w, h), 0)
        ImageDraw.Draw(keep).polygon([to_px(x, y) for x, y in poly], fill=255)
        grow = max(1, int(round(margin_m * sx)))
        keep = np.asarray(keep) > 0
        keep = ndimage.binary_dilation(keep, iterations=grow)
        px = np.asarray(img).copy()
        px[~keep, 3] = 0
        Image.fromarray(px, "RGBA").save(path, optimize=True)


def bake_shell(scan):
    data = source.floor_dir(scan) / "data"
    scene = json.loads((data / "scene.json").read_text(encoding="utf-8"))
    png, meta = source.plan(scan)
    grid, mask = floorprep.plan_mask_on_grid(meta, png)
    poly, outline_from = choose_outline(scene, mask, grid)
    plate = raster_polygon(poly, grid)
    core, core_px, columns, obstacles, V = structure(scan, scene, grid, mask, plate)
    z0 = scene["floorY"]
    z1, ceiling_from = ceiling_height(V, scene)
    obstacles = (ndimage.binary_dilation(obstacles, iterations=1) | core_px) & plate
    panos = Panos(scan, scene)

    # walls: each outline segment, split into pieces no wider than the atlas
    max_len = ATLAS_W / PX_PER_M - 0.01
    walls, imgs, shares = [], [], []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        a, b = np.array(a, float), np.array(b, float)
        L = float(np.linalg.norm(b - a))
        if L < 0.2:
            continue
        inward = inward_normal(a, b, plate, grid)
        n = max(1, int(math.ceil(L / max_len)))
        for k in range(n):
            pa, pb = a + (b - a) * k / n, a + (b - a) * (k + 1) / n
            img, share = bake_wall(pa, pb, inward, z0, z1, panos, obstacles, grid)
            walls.append((pa, pb, inward, img.shape[1]))
            imgs.append(img)
            shares.append((share, img.shape[1]))
    atlas, places = pack(imgs)
    AH = atlas.shape[0]
    pieces = []
    for (pa, pb, inward, w), (px, py), img in zip(walls, places, imgs):
        h = img.shape[0]
        pieces.append({"a": [round(float(pa[0]), 3), round(float(pa[1]), 3)], "b": [round(float(pb[0]), 3), round(float(pb[1]), 3)],
                       "inward": [round(float(inward[0]), 4), round(float(inward[1]), 4)],
                       "u0": px / ATLAS_W, "u1": (px + w) / ATLAS_W,
                       "v0": 1 - (py + h) / AH, "v1": 1 - py / AH, "kind": "exterior"})
    Image.fromarray(atlas).save(data / "walls.jpg", quality=88)
    Image.fromarray(walk_mask(scene, poly, core, columns)).save(data / "walk.png")
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    clear = sum(s * w for s, w in shares) / max(1, sum(w for _, w in shares))
    shell = {"rect": [round(min(xs), 3), round(max(xs), 3), round(min(ys), 3), round(max(ys), 3)],
             "z0": z0, "z1": z1, "eye": EYE_M, "pieces": pieces, "core": core, "columns": columns,
             "summary": {"pieces": len(pieces), "columns": len(columns),
                         "probableColumns": sum(c["grade"] == "probable" for c in columns),
                         "coreBlocks": len(core), "clearPhotoShare": round(clear, 3), "atlas": [ATLAS_W, AH],
                         "outline": outline_from, "walls": len(poly),
                         "areaSqFt": round(polygon_area(poly) * 10.7639), "ceiling": ceiling_from}}
    (data / "shell.json").write_text(json.dumps(shell), encoding="utf-8")
    clip_floor_images(data, scene["bandRect"], poly)
    return shell


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scans", nargs="+")
    for scan in ap.parse_args().scans:
        print(scan, bake_shell(scan)["summary"], flush=True)


if __name__ == "__main__":
    main()
