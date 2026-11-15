"""Build the 3-D site model for one property: terrain heights, aerial texture, footprints, scans.

Everything is cached under twin/<kind>-<id>/ (pipeline/storage.py: cache/ locally, Vercel Blob when deployed),
so a property is only fetched once.
"""
import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw
from shapely import transform
from shapely.geometry import Point, box

from . import config, matterport, storage, vexcel

GRID = 450                 # terrain vertices per side sent to the browser
RASTER = GRID * 2          # working resolution for height sampling
MAX_SCANS = 16
METERS_PER_STORY = 3.6
VERSION = 2                 # bump when the model's contents change: cached models of an older version are rebuilt
TREE_MIN_M = 2.5            # canopy taller than this, outside every building footprint, counts as a tree
TREE_CELL_M = 6.0           # one tree per cell of this size at most (the tallest point in it)
MAX_TREES = 3000

_locks = {}
_locks_guard = threading.Lock()


def load_detail(kind, item_id):
    folder = "home" if kind == "home" else "property"
    path = config.DATA / folder / f"{item_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No {kind} with id {item_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def site_half_extent(detail):
    """How much city to show around the building, centre to edge, in metres."""
    stories = detail.get("stories") or 1
    if detail["kind"] == "home":
        return 110
    if stories >= 25:
        return 450
    if stories >= 8:
        return 320
    return 200


class LocalFrame:
    """Converts lon/lat to metres east/north of the property, and to raster pixels."""

    def __init__(self, lat, lon, half):
        self.lat, self.lon, self.half = lat, lon, half
        self.m_per_deg_lat = vexcel.METERS_PER_DEGREE
        self.m_per_deg_lon = vexcel.METERS_PER_DEGREE * math.cos(math.radians(lat))
        self.pixel = (2 * half) / RASTER

    def to_local(self, geometry):
        def convert(coords):
            out = np.empty((len(coords), 2))
            out[:, 0] = (coords[:, 0] - self.lon) * self.m_per_deg_lon
            out[:, 1] = (coords[:, 1] - self.lat) * self.m_per_deg_lat
            return out
        return transform(geometry, convert)

    def mask(self, polygon):
        """Boolean raster of the cells a polygon (local metres) covers."""
        image = Image.new("L", (RASTER, RASTER), 0)
        draw = ImageDraw.Draw(image)
        parts = polygon.geoms if polygon.geom_type == "MultiPolygon" else [polygon]
        for part in parts:
            draw.polygon([(x / self.pixel + RASTER / 2, RASTER / 2 - y / self.pixel) for x, y in part.exterior.coords], fill=255)
        return np.array(image) > 0


def green_mask(ortho_bytes):
    """Cells of the aerial photo, at RASTER resolution, that look like vegetation (green dominates red and blue)."""
    import io
    rgb = np.asarray(Image.open(io.BytesIO(ortho_bytes)).convert("RGB").resize((RASTER, RASTER), Image.BILINEAR), dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (g > r * 1.04) & (g > b * 1.04) & (g > 35)


def trees_from_surface(surface, built_up, frame, green):
    """Tree crowns from the surface model: the tallest point in each TREE_CELL_M cell that rises above TREE_MIN_M, is
    green in the aerial photo, and is clear of every building footprint (a roof missing from the footprint list must not
    become a tree). Returns float32 rows of (x, y, height) in local metres, tallest first, at most MAX_TREES."""
    clear = ~_dilate(built_up, max(1, int(round(2.0 / frame.pixel))))
    canopy = np.where((surface > TREE_MIN_M) & clear & green, surface, 0.0)
    step = max(1, int(round(TREE_CELL_M / frame.pixel)))
    rows = []
    for r0 in range(0, RASTER, step):
        for c0 in range(0, RASTER, step):
            block = canopy[r0:r0 + step, c0:c0 + step]
            k = int(block.argmax())
            h = float(block.flat[k])
            if h <= TREE_MIN_M:
                continue
            r, c = r0 + k // block.shape[1], c0 + k % block.shape[1]
            rows.append(((c + 0.5 - RASTER / 2) * frame.pixel, (RASTER / 2 - r - 0.5) * frame.pixel, min(h, 30.0)))
    rows.sort(key=lambda t: -t[2])
    return np.array(rows[:MAX_TREES], dtype=np.float32).reshape(-1, 3)


def _dilate(mask, steps):
    """Grow a boolean raster by `steps` cells in every direction."""
    out = mask.copy()
    for _ in range(steps):
        grown = out.copy()
        grown[1:] |= out[:-1]; grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]; grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def _largest(polygon):
    return max(polygon.geoms, key=lambda g: g.area) if polygon.geom_type == "MultiPolygon" else polygon


def _ring(polygon, tolerance=0.3):
    return [[round(x, 2), round(y, 2)] for x, y in _largest(polygon).simplify(tolerance).exterior.coords]


def _pick_building(parcel, structures, frame):
    """The footprint this record is about: the parcel's primary structure, else the nearest one."""
    candidates = []
    if parcel:
        for s in parcel["properties"].get("structures") or []:
            if s.get("footprint.wkt"):
                candidates.append((not s.get("primary-structure"), -(s.get("footprint.area") or 0),
                                   frame.to_local(vexcel.to_geometry(s["footprint.wkt"])), s))
    if candidates:
        candidates.sort(key=lambda c: c[:2])
        return candidates[0][2], candidates[0][3]
    origin = Point(0, 0)
    nearby = [(g.distance(origin), g) for g in structures if g.distance(origin) < 60]
    if nearby:
        return min(nearby, key=lambda c: c[0])[1], {}
    return box(-12, -12, 12, 12), {}


def _aerial_facts(parcel, building_attrs):
    """The Vexcel attributes worth showing, already phrased for the panel."""
    p = (parcel or {}).get("properties") or {}
    facts = []

    def add(label, value, suffix=""):
        if value not in (None, "", False):
            facts.append([label, f"{value}{suffix}"])

    add("Roof material", (building_attrs.get("roof-characteristics.material.class") or "").replace("_", " ") or None)
    add("Roof shape", building_attrs.get("roof-characteristics.shape.value"))
    condition = building_attrs.get("roof-characteristics.condition")
    add("Roof condition", f"{condition} of 5" if condition else None)
    area = building_attrs.get("footprint.area")
    add("Footprint", f"{round(area * 10.7639):,} sq ft" if area else None)
    add("Tree cover on parcel", p.get("parcel-tree-cover.percent"), "%")
    add("Pool", "Yes" if p.get("pool.detected") else None)
    add("Solar panels", "Yes" if building_attrs.get("roof-objects.solar-panel.detected") else None)
    add("Imagery collection", p.get("metadata.collection"))
    gsd = p.get("metadata.gsd")
    add("Image resolution", f"{gsd * 100:.1f} cm per pixel" if gsd else None)
    return facts


def _build(detail, folder):
    lat, lon = detail["lat"], detail["lon"]
    half = site_half_extent(detail)
    frame = LocalFrame(lat, lon, half)
    area = vexcel.square(lat, lon, half)
    ortho_px = 4096 if half >= 400 else 3072

    with ThreadPoolExecutor(max_workers=8) as pool:
        f_heights = pool.submit(vexcel.surface_heights, area)
        f_ortho = pool.submit(vexcel.ortho, area, ortho_px)
        f_parcel = pool.submit(vexcel.property_at, lat, lon)
        f_structures = pool.submit(vexcel.structures_in, area)
        scan_ids = detail.get("scanIds", [])[:MAX_SCANS]
        f_scans = [pool.submit(matterport.summary, sid, detail.get("stories")) for sid in scan_ids]

        heights = f_heights.result()
        ortho_bytes = f_ortho.result()
        (folder / "ortho.jpg").write_bytes(ortho_bytes)
        parcel = f_parcel.result()
        structure_features = f_structures.result()
        scans = []
        for future in f_scans:
            try:
                scans.append(future.result())
            except Exception as error:  # one unreadable scan should not sink the whole model
                print("scan skipped:", error)

    # heights -> RASTER x RASTER, relative to street level
    resized = np.array(Image.fromarray(heights).resize((RASTER, RASTER), Image.NEAREST))
    ground = float(np.nanpercentile(resized, 8))
    resized = np.nan_to_num(resized, nan=ground) - ground

    footprints = [frame.to_local(vexcel.to_geometry(f["geometry"])) for f in structure_features]
    building, building_attrs = _pick_building(parcel, footprints, frame)
    building_mask = frame.mask(building)
    inside = resized[building_mask]
    top = float(inside.max()) if inside.size else 0.0
    roof = float(np.percentile(inside, 85)) if inside.size else 0.0
    stories = detail.get("stories") or max(1, round(roof / METERS_PER_STORY))
    if top < 3:  # height model missed the building; fall back to the record
        top = roof = stories * METERS_PER_STORY

    neighbours = []
    built_up = np.zeros_like(resized, dtype=bool)
    for g in footprints:
        if g.intersection(building).area > 0.5 * min(g.area, building.area):
            continue
        footprint_mask = frame.mask(g.buffer(1.0))
        built_up |= footprint_mask
        cells = resized[footprint_mask]
        if cells.size >= 4:
            roof_height = float(np.percentile(cells, 90))
            neighbours.append({"ring": _ring(g, 0.5), "height": round(roof_height, 1)})
            # trees overhanging a roof would otherwise poke up as spikes
            resized[footprint_mask] = np.minimum(cells, roof_height)

    # Trees, for the 3-D view's planted canopy: everything tall that is not a building or the subject itself.
    subject_area = frame.mask(building.buffer(3))
    trees = trees_from_surface(resized, built_up | subject_area, frame, green_mask(ortho_bytes))
    trees.tofile(folder / "trees.bin")

    # The surface model also contains trees, which read as grey spikes. Where footprints are
    # available, raise only the mapped buildings and leave everything else flat under the photo.
    terrain = np.where(built_up, resized, 0) if neighbours else resized.copy()
    # the building itself is drawn as floors, so flatten it out of the terrain
    terrain[frame.mask(building.buffer(3))] = 0
    pooled = terrain.reshape(GRID, 2, GRID, 2).max(axis=(1, 3)).clip(min=0).astype(np.float32)
    pooled.tofile(folder / "heights.bin")

    rel = f"twin/{folder.name}"
    storage.put(f"{rel}/heights.bin", folder / "heights.bin", "application/octet-stream")
    storage.put(f"{rel}/trees.bin", folder / "trees.bin", "application/octet-stream")
    storage.put(f"{rel}/ortho.jpg", folder / "ortho.jpg", "image/jpeg")
    stamp = int(time.time())  # the files are served with a long cache lifetime; this busts it on rebuild
    twin = {
        "version": VERSION,
        "extent": 2 * half, "grid": GRID, "groundElevation": round(ground, 1),
        "trees": f"{storage.url(rel + '/trees.bin')}?v={stamp}", "treeCount": int(len(trees)),
        "heights": f"{storage.url(rel + '/heights.bin')}?v={stamp}",
        "ortho": f"{storage.url(rel + '/ortho.jpg')}?v={stamp}",
        "building": {"ring": _ring(building), "top": round(top, 1), "roof": round(roof, 1), "stories": stories,
                     "storiesEstimated": not detail.get("stories")},
        "neighbours": neighbours,
        "aerialFacts": _aerial_facts(parcel, building_attrs),
        "scans": sorted(scans, key=lambda s: (s["floor"] is None, s["floor"] or 0, s["name"])),
        "scansOmitted": max(0, len(detail.get("scanIds", [])) - MAX_SCANS),
    }
    storage.put_json(f"{rel}/twin.json", twin)  # written last: its presence means the model is complete
    return twin


def get(kind, item_id):
    """Return the site model for a property, building and caching it on first request."""
    key = f"{kind}-{item_id}"
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        twin = storage.get_json(f"twin/{key}/twin.json")
        if twin and twin.get("version", 1) >= VERSION:
            return twin
        # missing, or an older model (no trees): build it
        folder = config.CACHE / "twin" / key
        folder.mkdir(parents=True, exist_ok=True)
        return _build(load_detail(kind, item_id), folder)
