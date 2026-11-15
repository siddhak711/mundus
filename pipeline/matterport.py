"""Thin client for the Matterport Model API (GraphQL) plus the on-disk cache of scan assets."""
import json
import re
import threading

import requests
from PIL import Image

from . import config, storage

GRAPH_URL = "https://api.matterport.com/api/models/graph"
SQFT_PER_M2 = 10.7639

_SUMMARY_QUERY = """query($id: ID!) { model(id: $id) {
  id name
  publication { url address }
  dimensions(units: metric) { areaFloor volume }
  floors { id }
  rooms { id label classifications { label } dimensions(units: metric) { areaFloor } }
  panoLocations { id }
} }"""

_ASSET_QUERY = """query($id: ID!) { model(id: $id) {
  panoLocations { position { x y z } }
  assets {
    meshes { format resolution url }
    floorplans { url format width height resolution flags origin { x y } }
    photos { url label width }
  }
} }"""

_locks = {}
_locks_guard = threading.Lock()


def _query(query, model_id):
    r = requests.post(GRAPH_URL, auth=(config.MATTERPORT_API_KEY, config.MATTERPORT_API_TOKEN),
                      json={"query": query, "variables": {"id": model_id}}, timeout=90)
    r.raise_for_status()
    payload = r.json()
    model = (payload.get("data") or {}).get("model")
    if model is None:
        raise RuntimeError(f"Matterport model {model_id}: {json.dumps(payload.get('errors'))[:200]}")
    return model


def floor_from_name(name, stories):
    """Scan names often carry the suite ('Suite 3610', '1500 - Wells Fargo Plaza', 'Level 53')."""
    if not stories or stories < 2:
        return None
    level = re.search(r"\b(?:level|floor)\s+(\d{1,3})\b", name or "", re.I)
    if level and 1 <= int(level.group(1)) <= stories:
        return int(level.group(1))
    # an explicit suite wins; a bare leading number counts only in the "1500 - Building" style,
    # because otherwise it is usually the street number
    suite = (re.search(r"\b(?:suite|ste|unit)\.?\s*#?(\d{3,4})\b", name or "", re.I)
             or re.match(r"\s*(\d{3,4})\s+-", name or ""))
    if suite:
        floor = int(suite.group(1)) // 100
        if 1 <= floor <= stories:
            return floor
    return None


def summary(model_id, stories=None):
    """Small record for the scan list: name, size, rooms, tour link, best-guess floor."""
    m = _query(_SUMMARY_QUERY, model_id)
    rooms = [c["label"] for r in m.get("rooms") or [] for c in r.get("classifications") or [] if c["label"] not in ("Void", "Other")]
    area = (m.get("dimensions") or {}).get("areaFloor") or 0
    return {
        "id": m["id"], "name": (m.get("name") or "Untitled scan").strip(),
        "tourUrl": (m.get("publication") or {}).get("url") or f"https://my.matterport.com/show/?m={m['id']}",
        "areaSf": round(area * SQFT_PER_M2), "volumeCuFt": round(((m.get("dimensions") or {}).get("volume") or 0) * 35.3147),
        "levels": len(m.get("floors") or []), "roomTypes": sorted(set(rooms)),
        "capturePoints": len(m.get("panoLocations") or []),
        "floor": floor_from_name(m.get("name"), stories),
    }


def assets(model_id):
    """Download the mesh and the photo-textured floor plan once; return what the viewer needs.

    Photo links are signed and expire, so they are fetched fresh on every call.
    """
    with _locks_guard:
        lock = _locks.setdefault(model_id, threading.Lock())
    with lock:
        folder = config.CACHE / "scan" / model_id
        m = _query(_ASSET_QUERY, model_id)
        photos = [{"url": p["url"], "label": p.get("label") or ""} for p in m["assets"].get("photos") or [] if (p.get("width") or 0) >= 800][:9]
        meta = storage.get_json(f"scan/{model_id}/scan.json")
        if meta:
            meta["photos"] = photos
            return meta

        folder.mkdir(parents=True, exist_ok=True)
        mesh = next((x for x in m["assets"]["meshes"] if x["format"] == "obj" and x["resolution"] == "50k"), None)
        if mesh is None:
            raise RuntimeError(f"Matterport model {model_id} has no mesh")
        (folder / "mesh.obj").write_bytes(requests.get(mesh["url"], timeout=300).content)
        storage.put(f"scan/{model_id}/mesh.obj", folder / "mesh.obj", "text/plain")

        plan = next((f for f in m["assets"]["floorplans"]
                     if f["format"] == "png" and set(f["flags"]) == {"photogramy", "alpha"} and f.get("resolution")), None)
        plan_meta = None
        if plan:
            raw = folder / "plan.png"
            raw.write_bytes(requests.get(plan["url"], timeout=300).content)
            image = Image.open(raw).convert("RGBA")
            width_px, height_px = image.size
            image.thumbnail((2048, 2048))
            image.save(folder / "plan.webp", quality=88)
            raw.unlink()
            storage.put(f"scan/{model_id}/plan.webp", folder / "plan.webp", "image/webp")
            # origin is the plan's lower-left corner in model metres; resolution is pixels per metre
            plan_meta = {"x": plan["origin"]["x"], "y": plan["origin"]["y"],
                         "width": width_px / plan["resolution"], "height": height_px / plan["resolution"]}

        meta = {
            "id": model_id,
            "mesh": storage.url(f"scan/{model_id}/mesh.obj"),
            "plan": storage.url(f"scan/{model_id}/plan.webp") if plan_meta else None,
            "planRect": plan_meta,
            "capturePoints": [[round(p["position"][k], 2) for k in "xyz"] for p in m.get("panoLocations") or [] if p.get("position")],
        }
        storage.put_json(f"scan/{model_id}/scan.json", meta)
        meta["photos"] = photos
        return meta
