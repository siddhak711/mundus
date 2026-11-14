"""Thin client for the Vexcel API 2.0 (aerial imagery, height model, parcels, object detection)."""
import io
import math
import random
import time

import numpy as np
import requests
import tifffile
from shapely import wkt as shapely_wkt
from shapely.geometry import shape

from . import config

API = "https://api.vexcelgroup.com/v2"
LAYERS = "urban,urban-r,wide-area,urban-g"
METERS_PER_DEGREE = 111_320.0


class VexcelError(RuntimeError):
    pass


def _send(method, path, **kwargs):
    """Call the API, backing off on 429."""
    for attempt in range(6):
        r = requests.request(method, f"{API}/{path}", headers={"X-API-KEY": config.VEXCEL_API_KEY}, timeout=180, **kwargs)
        if r.status_code != 429:
            return r
        time.sleep(min(2 ** attempt, 30) + random.random())
    return r


def square(lat, lon, half_m):
    """WKT square centred on a point; half_m is centre-to-edge in metres."""
    dlat = half_m / METERS_PER_DEGREE
    dlon = half_m / (METERS_PER_DEGREE * math.cos(math.radians(lat)))
    w, e, s, n = lon - dlon, lon + dlon, lat - dlat, lat + dlat
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


def to_geometry(geom):
    """The API returns geometry as GeoJSON or WKT depending on the endpoint."""
    return shapely_wkt.loads(geom) if isinstance(geom, str) else shape(geom)


def property_at(lat, lon):
    """Parcel record at a point, or None when there is no parcel there."""
    r = _send("GET", "property/extract", params={
        "wkt": f"POINT({lon} {lat})", "srid": 4326, "layer": LAYERS, "latest": "true",
        "include": "precomputed", "unit-system": "metric"})
    if r.status_code == 404:
        return None
    if not r.ok:
        raise VexcelError(f"property/extract {r.status_code}: {r.text[:200]}")
    features = r.json().get("features") or []
    return features[0] if features else None


def structures_in(area_wkt):
    r = _send("GET", "structure/extract", params={
        "wkt": area_wkt, "srid": 4326, "layer": LAYERS, "latest": "true",
        "include": "precomputed", "unit-system": "metric", "page-size": 500})
    if r.status_code == 404:
        return []
    if not r.ok:
        raise VexcelError(f"structure/extract {r.status_code}: {r.text[:200]}")
    return r.json().get("features") or []


def ortho(area_wkt, pixels, drawing=None):
    """Top-down aerial image (JPEG bytes) of an area."""
    body = {"wkt": area_wkt, "srid": 4326, "layer": LAYERS, "crop": "bounding_box", "image-format": "jpeg",
            "destination-dimensions": f"{pixels},{pixels}", "attribution": False}
    if drawing:
        body["drawing"] = drawing
    r = _send("POST", "ortho/extract", json=body)
    if not r.ok:
        raise VexcelError(f"ortho/extract {r.status_code}: {r.text[:200]}")
    return r.content


def oblique(area_wkt, direction, buffer_m=30):
    """Angled aerial photo looking north/south/east/west, or None when not captured."""
    r = _send("POST", "oriented/extract", json={
        "wkt": area_wkt, "srid": 4326, "layer": "urban", "product-type": f"oblique-{direction}",
        "rotation": "natural", "buffer-meter": buffer_m, "crop": "bbox", "image-format": "jpeg", "attribution": False})
    return r.content if r.ok else None


def surface_heights(area_wkt, pixels=900):
    """Digital surface model for an area: (heights in metres as a 2-D array, row 0 = north)."""
    r = _send("POST", "dsm/extract", json={
        "wkt": area_wkt, "srid": 4326, "layer": LAYERS, "crop": "bounding_box", "image-format": "tiff",
        "destination-dimensions": f"{pixels},{pixels}"})
    if not r.ok:
        raise VexcelError(f"dsm/extract {r.status_code}: {r.text[:200]}")
    heights = tifffile.imread(io.BytesIO(r.content)).astype(np.float32)
    heights[heights < -100] = np.nan  # nodata
    return heights


def detect(area_wkt, labels, threshold=0.45):
    """Open-vocabulary object detection on the aerial image. Returns {label: [confidence, ...]}."""
    r = _send("POST", "elements/detect", json={
        "wkt": area_wkt, "srid": 4326, "buffer-meter": 0,
        "images": [{"endpoint": "ortho/extract", "request": {"layer": LAYERS, "srid": 4326, "wkt": area_wkt, "crop": "bounding_box"}}],
        "model-input": {"elements": [{"label": l, "model": "sam3", "detection-threshold": threshold} for l in labels],
                        "include": ["bbox", "confidence"]}})
    if not r.ok:
        raise VexcelError(f"elements/detect {r.status_code}: {r.text[:200]}")
    found = {l: [] for l in labels}
    for feature in r.json().get("features") or []:
        props = feature["properties"]
        found.setdefault(props["label"], []).extend(round(d["confidence"], 2) for d in props.get("detections") or [])
    return found


def search_similar(area_wkt, text, limit=8):
    """Semantic search over pre-computed image tiles. Returns [{lat, lon, score}]."""
    r = _send("POST", "embedding/extract", json={
        "wkt": area_wkt, "srid": 4326, "search-text": text, "include": "score,geometry",
        "total-records": limit, "page-size": limit})
    if not r.ok:
        raise VexcelError(f"embedding/extract {r.status_code}: {r.text[:200]}")
    out = []
    for feature in r.json().get("features") or []:
        c = to_geometry(feature["geometry"]).centroid
        out.append({"lat": round(c.y, 6), "lon": round(c.x, 6), "score": round(feature["properties"]["score"], 3)})
    return out
