"""Bake a scan's MatterPak mesh into the floor walkthrough's mesh files (web/walkthrough/index.html reads them).

    python -m pipeline.bake.mesh <scanId>

Reads raw/pak/ (OBJ, MTL, textures) and raw/plan.png from pipeline/bake/source.py. Writes data/:
    pos.bin    Float32 xyz per vertex, in three.js world coordinates: (x, z, -y) of the scan's z-up metres
    uv.bin     Float32 uv per vertex, into the vertex's texture atlas (v = 0 at the bottom, three's flipY default)
    idx.bin    Uint32 triangle indices, sorted by atlas so each atlas is one contiguous run
    drop.bin   Uint8 class per vertex: 1 = interior walls and furniture (sink into the floor when the walls go),
               2 = the scan's floor, ceiling and outer shell (dissolve). Vertices shared by two classes are split.
    atlas{i}.jpg   the textures packed into 8192 px atlases (each texture downscaled to one tile)
    floorfill.png  a clean floor in the floor's own colour over bandRect, transparent outside the floor plate, the
                   unscanned core painted rgb(52, 58, 66); row 0 is the north edge
    mesh.json  {atlases, groups: [[start, count, atlas]], floorY, ceilY, bandRect: [x, y, w, h], stats: {areaSf, tris}}
               groups index idx.bin (start and count in indices); bandRect is in scan metres (x east, y north)

Recipe (web/walkthrough/HANDOFF.md section 3): weld by rounded position; drop faces outside the solid footprint
(the plan's alpha, closed and opened: pipeline/daylight.py floor_plate); drop connected pieces under 1.5 m2; classify
floor (facing up, within 0.12 m of the floor), ceiling (facing down, over 2.2 m up), and deep interior (over 0.4 m
inside the outer wall and clear of the core) as droppable.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from pipeline.bake import source
from pipeline.daylight import floor_plate

SF_PER_M2 = 10.7639
ATLAS = 8192
TILE = 512                 # each texture's size in the atlas: 256 textures per atlas
PAD = 2                    # pixels kept inside each tile edge, so mipmaps do not bleed between textures
MIN_PIECE_M2 = 1.5
FLOOR_BAND = 0.12
CEILING_MIN = 2.2
DEEP_M = 0.4
GRID = 20.0                # pixels per metre for the footprint lookups and floorfill
CORE_COLOUR = (52, 58, 66)
INTERIOR, SHELL = 1, 2


# ---------- read ----------

def read_obj(path):
    """(V scan metres [n,3], T uv [m,2], F vertex indices [k,3], FT uv indices [k,3], FM material index [k], materials)."""
    v, t, f, ft, fm, mats = [], [], [], [], [], []
    current = -1
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            c = line[:2]
            if c == "v ":
                v.append(line[2:])
            elif c == "vt":
                t.append(line[3:])
            elif c == "f ":
                a, b, cc = line[2:].split()[:3]
                a, b, cc = a.split("/"), b.split("/"), cc.split("/")
                f.append((a[0], b[0], cc[0]))
                ft.append((a[1] if len(a) > 1 and a[1] else 0, b[1] if len(b) > 1 and b[1] else 0, cc[1] if len(cc) > 1 and cc[1] else 0))
                fm.append(current)
            elif line.startswith("usemtl"):
                name = line.split(None, 1)[1].strip()
                if name not in mats:
                    mats.append(name)
                current = mats.index(name)
    V = np.array(" ".join(v).split(), dtype=np.float64).reshape(-1, 3)
    T = np.array(" ".join(t).split(), dtype=np.float64).reshape(-1, 2) if t else np.zeros((1, 2))
    F = np.array(f, dtype=np.int64) - 1
    FT = np.array(ft, dtype=np.int64) - 1
    FT[FT < 0] = 0
    return V, T, F, FT, np.array(fm, dtype=np.int64), mats


def texture_files(pak, mtl_names):
    """material name -> texture path (map_Kd in the MTL; the material name is the file name in MatterPaks)."""
    mtl = next(pak.glob("*.mtl"), None)
    out, name = {}, None
    if mtl:
        for line in mtl.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("newmtl"):
                name = line.split(None, 1)[1].strip()
            elif line.strip().startswith("map_Kd") and name:
                out[name] = pak / line.split(None, 1)[1].strip()
    return [out.get(n, pak / n) for n in mtl_names]


# ---------- footprint and classes ----------

class Frame:
    """Raster frame over the scan in metres at GRID px/m; row 0 is the north (max y) edge, like an image."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = x0, y0
        self.w, self.h = int(np.ceil((x1 - x0) * GRID)), int(np.ceil((y1 - y0) * GRID))

    def px(self, x, y):
        c = np.clip(((x - self.x0) * GRID).astype(int), 0, self.w - 1)
        r = np.clip(((self.y0 + self.h / GRID - y) * GRID).astype(int), 0, self.h - 1)
        return r, c


def plan_on_frame(png, meta, frame):
    """The plan's alpha (True = scanned floor) resampled onto the frame."""
    alpha = np.array(Image.open(png).convert("RGBA"))[..., 3] > 0
    res, ox, oy = meta["resolution"], meta["origin"]["x"], meta["origin"]["y"]
    H = alpha.shape[0]
    rr, cc = np.mgrid[0:frame.h, 0:frame.w]
    x = frame.x0 + (cc + 0.5) / GRID
    y = frame.y0 + frame.h / GRID - (rr + 0.5) / GRID
    pc = ((x - ox) * res).astype(int)
    pr = (H - (y - oy) * res).astype(int)
    ok = (pc >= 0) & (pc < alpha.shape[1]) & (pr >= 0) & (pr < H)
    out = np.zeros((frame.h, frame.w), bool)
    out[ok] = alpha[pr[ok], pc[ok]]
    return out


def classify(centroids, normals, floor_z, ceil_z, plate, core, frame):
    """Per face: INTERIOR (droppable) or SHELL. centroids/normals in scan metres (z up)."""
    nz = normals[:, 2]
    z = centroids[:, 2]
    is_floor = (nz > 0.85) & (z < floor_z + FLOOR_BAND)
    is_ceiling = (nz < -0.85) & (z > floor_z + CEILING_MIN)
    # metres to the outer wall (padded, so a plate touching the frame edge still has an outside)
    to_outside = ndimage.distance_transform_edt(np.pad(plate, 1))[1:-1, 1:-1] / GRID
    to_core = ndimage.distance_transform_edt(~core) / GRID if core.any() else np.full(plate.shape, 99.0)
    r, c = frame.px(centroids[:, 0], centroids[:, 1])
    deep = (to_outside[r, c] > DEEP_M) & (to_core[r, c] > DEEP_M)
    cls = np.where(deep & ~is_floor & ~is_ceiling, INTERIOR, SHELL).astype(np.uint8)
    return cls


def find_core(plate, scanned):
    """Unscanned holes inside the floor plate larger than 4 m2: the building core (lifts, stairs, risers)."""
    holes = plate & ~ndimage.binary_closing(scanned, structure=np.ones((5, 5)))
    labels, n = ndimage.label(holes)
    if not n:
        return np.zeros_like(plate)
    sizes = ndimage.sum(holes, labels, range(1, n + 1)) / GRID ** 2
    keep = np.isin(labels, 1 + np.nonzero(sizes > 4.0)[0])
    return ndimage.binary_opening(keep, structure=np.ones((3, 3)))


# ---------- atlases ----------

def build_atlases(tex_paths, out):
    """Pack textures (one TILE each) into ATLAS-sized JPEGs. Returns per material (atlas, col, row)."""
    per = ATLAS // TILE
    per_atlas = per * per
    n_atlas = max(1, int(np.ceil(len(tex_paths) / per_atlas)))
    slots = []
    for a in range(n_atlas):
        count = min(per_atlas, len(tex_paths) - a * per_atlas)
        rows = int(np.ceil(count / per))
        img = Image.new("RGB", (ATLAS, rows * TILE if a == n_atlas - 1 else ATLAS), (128, 128, 128))
        for k in range(count):
            i = a * per_atlas + k
            col, row = k % per, k // per
            try:
                t = Image.open(tex_paths[i]).convert("RGB").resize((TILE, TILE), Image.LANCZOS)
            except (OSError, FileNotFoundError):
                t = Image.new("RGB", (TILE, TILE), (128, 128, 128))
            img.paste(t, (col * TILE, row * TILE))
            slots.append((a, col, row, img.size[1]))
        img.save(out / f"atlas{a}.jpg", quality=88, optimize=True)
    return slots, n_atlas


def atlas_uv(uv, slot):
    """Texture uv (v up) -> atlas uv (v up, three's flipY), inset by PAD pixels inside the tile."""
    _, col, row, height = slot
    inner = TILE - 2 * PAD
    px = col * TILE + PAD + uv[:, 0] * inner
    py_top = row * TILE + PAD + (1 - uv[:, 1]) * inner
    return np.stack([px / ATLAS, 1 - py_top / height], axis=1)


# ---------- bake ----------

def bake_mesh(scan):
    pak = source.matterpak(scan)
    png, meta = source.plan(scan)
    out = source.floor_dir(scan) / "data"
    out.mkdir(parents=True, exist_ok=True)

    V, T, F, FT, FM, mats = read_obj(next(pak.glob("*.obj")))

    # floor and ceiling heights: the commonest heights of upward and downward faces
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=1) / 2
    normals = cross / np.maximum(2 * area, 1e-12)[:, None]
    cen = (a + b + c) / 3
    up = normals[:, 2] > 0.85
    hist, edges = np.histogram(cen[up, 2], bins=200, weights=area[up], range=(-1.0, 1.5))
    floor_z = float(edges[hist.argmax()] + (edges[1] - edges[0]) / 2)
    down = normals[:, 2] < -0.85
    hist, edges = np.histogram(cen[down, 2], bins=200, weights=area[down], range=(floor_z + 1.8, floor_z + 5.0))
    ceil_z = float(edges[hist.argmax()] + (edges[1] - edges[0]) / 2)

    # the solid footprint, from the plan's alpha (closed, opened, largest piece, holes filled)
    ox, oy, res = meta["origin"]["x"], meta["origin"]["y"], meta["resolution"]
    frame = Frame(ox - 1, oy - 1, ox + meta["width"] / res + 1, oy + meta["height"] / res + 1)
    scanned = plan_on_frame(png, meta, frame)
    # The plan also picks up what the cameras saw through the glass, which bulges past the window line. Keep only the
    # part of it the mesh has real floor under: faces facing up at floor height, rasterised and closed.
    at_floor = (normals[:, 2] > 0.85) & (np.abs(cen[:, 2] - floor_z) < FLOOR_BAND) & (area > 1e-6)
    cover = np.zeros((frame.h, frame.w), bool)
    fr, fc = frame.px(cen[at_floor, 0], cen[at_floor, 1])
    cover[fr, fc] = True
    for corner in (a, b, c):                                   # the corners too, so large floor triangles fill in
        cr, ccx = frame.px(corner[at_floor, 0], corner[at_floor, 1])
        cover[cr, ccx] = True
    floor_seen = floor_plate(cover, GRID)
    plate = floor_plate(scanned, GRID) & ndimage.binary_dilation(floor_seen, iterations=int(0.3 * GRID))
    core = find_core(plate, scanned)
    keep_zone = ndimage.binary_dilation(plate, iterations=int(0.5 * GRID))   # outer walls and glass sit on the edge

    r, cc = frame.px(cen[:, 0], cen[:, 1])
    keep = keep_zone[r, cc] & (cen[:, 2] > floor_z - 0.3) & (cen[:, 2] < ceil_z + 0.3) & (area > 1e-8)

    # weld by rounded position, then drop connected pieces under MIN_PIECE_M2
    key = np.round(V * 1000).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.ravel()
    Fw = weld[F]
    idx_keep = np.nonzero(keep)[0]
    rows = np.concatenate([Fw[idx_keep, 0], Fw[idx_keep, 1]])
    cols = np.concatenate([Fw[idx_keep, 1], Fw[idx_keep, 2]])
    nW = weld.max() + 1
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nW, nW))
    _, comp = connected_components(g, directed=False)
    piece_area = np.bincount(comp[Fw[idx_keep, 0]], weights=area[idx_keep], minlength=comp.max() + 1)
    keep[idx_keep] &= piece_area[comp[Fw[idx_keep, 0]]] >= MIN_PIECE_M2

    F, FT, FM, cen, normals = F[keep], FT[keep], FM[keep], cen[keep], normals[keep]
    cls = classify(cen, normals, floor_z, ceil_z, plate, core, frame)

    # atlases, then one output vertex per (position, uv, class): split where classes meet
    slots, n_atlas = build_atlases(texture_files(pak, mats), out)
    fm_atlas = np.array([slots[m][0] if m >= 0 else 0 for m in FM])
    order = np.argsort(fm_atlas, kind="stable")
    F, FT, FM, cls, fm_atlas = F[order], FT[order], FM[order], cls[order], fm_atlas[order]

    corner_v = F.ravel()
    corner_t = FT.ravel()
    corner_m = np.repeat(FM, 3)
    corner_c = np.repeat(cls, 3)
    keys = np.stack([corner_v, corner_t, corner_m, corner_c], axis=1)
    uniq, inverse = np.unique(keys, axis=0, return_inverse=True)
    inverse = inverse.ravel()

    P = V[uniq[:, 0]]
    pos = np.stack([P[:, 0], P[:, 2], -P[:, 1]], axis=1).astype(np.float32)   # scan (x, y, z up) -> three (x, z, -y)
    uv = np.zeros((len(uniq), 2))
    for m in np.unique(uniq[:, 2]):
        sel = uniq[:, 2] == m
        uv[sel] = atlas_uv(np.clip(T[uniq[sel, 1]], 0, 1), slots[m] if m >= 0 else slots[0])
    idx = inverse.astype(np.uint32)
    drop = uniq[:, 3].astype(np.uint8)

    groups = []
    for a_i in range(n_atlas):
        faces = np.nonzero(fm_atlas == a_i)[0]
        if len(faces):
            groups.append([int(faces[0] * 3), int(len(faces) * 3), a_i])

    pos.tofile(out / "pos.bin")
    uv.astype(np.float32).tofile(out / "uv.bin")
    idx.tofile(out / "idx.bin")
    drop.tofile(out / "drop.bin")

    # bandRect: the floor plate's bounds with a small margin, in scan metres
    rows_any, cols_any = np.nonzero(plate.any(axis=1))[0], np.nonzero(plate.any(axis=0))[0]
    bx0 = frame.x0 + cols_any[0] / GRID - 0.5
    bx1 = frame.x0 + (cols_any[-1] + 1) / GRID + 0.5
    by1 = frame.y0 + frame.h / GRID - rows_any[0] / GRID + 0.5
    by0 = frame.y0 + frame.h / GRID - (rows_any[-1] + 1) / GRID - 0.5
    band = [round(bx0, 3), round(by0, 3), round(bx1 - bx0, 3), round(by1 - by0, 3)]
    write_floorfill(out, band, frame, plate, core, floor_colour(pak, texture_files(pak, mats), T, F, FT, FM, cls, normals))

    info = {
        "atlases": n_atlas, "groups": groups,
        "floorY": round(floor_z, 4), "ceilY": round(ceil_z, 4), "bandRect": band,
        "stats": {"areaSf": int(round(float((scanned & plate).sum()) / GRID ** 2 * SF_PER_M2)), "tris": int(len(F)),
                  "vertices": int(len(pos)), "interiorTris": int((cls == INTERIOR).sum())},
    }
    (out / "mesh.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def floor_colour(pak, tex_paths, T, F, FT, FM, cls, normals):
    """The floor's typical colour: textures sampled at the centres of up to 400 floor faces."""
    floor_faces = np.nonzero((cls == SHELL) & (normals[:, 2] > 0.85))[0]
    rng = np.random.default_rng(0)
    pick = rng.choice(floor_faces, size=min(400, len(floor_faces)), replace=False) if len(floor_faces) else []
    cache, samples = {}, []
    for f in pick:
        m = FM[f]
        if m < 0:
            continue
        if m not in cache:
            try:
                cache[m] = np.asarray(Image.open(tex_paths[m]).convert("RGB").resize((256, 256)))
            except (OSError, FileNotFoundError):
                continue
        u, v = T[FT[f]].mean(axis=0)
        img = cache[m]
        samples.append(img[int((1 - np.clip(v, 0, 1)) * 255), int(np.clip(u, 0, 1) * 255)])
    if not samples:
        return (150, 146, 138)
    return tuple(int(x) for x in np.median(np.array(samples), axis=0))


def write_floorfill(out, band, frame, plate, core, colour):
    """floorfill.png over bandRect at GRID px/m: the floor colour inside the plate, the core painted, clear elsewhere."""
    bx, by, bw, bh = band
    w, h = int(round(bw * GRID)), int(round(bh * GRID))
    rr, cc = np.mgrid[0:h, 0:w]
    x = bx + (cc + 0.5) / GRID
    y = by + bh - (rr + 0.5) / GRID
    r, c = frame.px(x, y)
    inside, in_core = plate[r, c], core[r, c]
    img = np.zeros((h, w, 4), np.uint8)
    img[inside] = (*colour, 255)
    img[in_core] = (*CORE_COLOUR, 255)
    Image.fromarray(img, "RGBA").save(out / "floorfill.png", optimize=True)


def main():
    for scan in sys.argv[1:]:
        info = bake_mesh(scan)
        print(scan, json.dumps({k: v for k, v in info.items() if k != "groups"}), "groups", info["groups"])


if __name__ == "__main__":
    main()
