"""Measured daylight depth for a building's floors, from its Matterport scans' floor plans.

    python -m pipeline.daylight 246826 [more property ids]      # writes data/daylight/<id>.json
    python -m pipeline.daylight --walkthroughs                  # every building in pipeline/walkthroughs.json

Apartments need daylight: conversion studies put the limit at 25 to 35 ft from a window. For each scan linked to the
property, the transparent top-down floor plan is turned into a mask of the floor, cleaned of specks and of the rays that
window reflections leave outside the facade, and filled to the outline of the floor plate. The distance from every point
of the plate to the plate's edge is the distance to the facade.

Only a scan that covers a whole floor measures daylight. A suite's outline is mostly corridor and neighbour walls, not
windows, so for suites only the scanned area is recorded. A scan counts as a whole floor when its plate is at least 80%
of the floor size CoStar records for that floor.

Needs MATTERPORT_API_KEY and MATTERPORT_API_TOKEN in .env, and scipy.
"""
import io
import json
import re
import sys

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

from pipeline import config, matterport

FT_PER_M = 3.2808
SF_PER_M2 = 10.7639
FULL_FLOOR_SHARE = 0.8
THRESHOLDS_FT = (25, 30, 35)

_PLAN_QUERY = """query($id: ID!) { model(id: $id) {
  id name
  assets { floorplans(provider: "matterport") { format flags url width height resolution origin { x y } } }
} }"""


def _disk(metres, res):
    r = max(1, round(metres * res))
    return np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) <= r


def floor_plate(mask, res):
    """Scanned-floor mask (True = floor) at `res` pixels per metre -> filled outline of the floor plate."""
    joined = ndimage.binary_closing(mask, structure=_disk(1.0, res))     # across walls and furniture shadows
    joined = ndimage.binary_opening(joined, structure=_disk(0.8, res))   # off specks and reflection rays
    labels, n = ndimage.label(joined)
    if n == 0:
        return joined
    largest = np.bincount(labels.ravel())[1:].argmax() + 1
    return ndimage.binary_fill_holes(labels == largest)


WORK_RES = 20.0   # pixels per metre for the measurement: 5 cm is ample for distances in feet, and keeps it fast


def resample(mask, res, to=WORK_RES):
    """Mask at `res` px/m -> (mask at `to` px/m, `to`). A pixel stays floor if any floor falls in it."""
    if res <= to:
        return mask, res
    h, w = mask.shape
    size = (max(1, round(w * to / res)), max(1, round(h * to / res)))
    img = Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.BOX)
    return np.array(img) > 0, to


def measure(mask, res):
    """Daylight figures for one floor plan mask at `res` pixels per metre."""
    mask, res = resample(mask, res)
    px = 1.0 / res
    plate = floor_plate(mask, res)
    dist_ft = ndimage.distance_transform_edt(plate) * px * FT_PER_M
    inside = dist_ft[plate]
    ys, xs = np.nonzero(plate)
    out = {
        "scannedSf": round(float(mask.sum()) * px * px * SF_PER_M2),
        "plateSf": round(float(plate.sum()) * px * px * SF_PER_M2),
        "plateFt": [round(float(xs.max() - xs.min()) * px * FT_PER_M), round(float(ys.max() - ys.min()) * px * FT_PER_M)] if xs.size else None,
        "deepestFt": round(float(inside.max()), 1) if inside.size else None,
    }
    for ft in THRESHOLDS_FT:
        out[f"within{ft}ft"] = round(float(np.mean(inside <= ft)), 3) if inside.size else None
    out["beyond30ftSf"] = round(float((inside > 30).sum()) * px * px * SF_PER_M2)
    return out


def best_plan(model):
    plans = [f for f in (model.get("assets") or {}).get("floorplans") or []
             if f.get("format") == "png" and "alpha" in (f.get("flags") or []) and f.get("resolution") and f.get("width")]
    return max(plans, key=lambda f: f["resolution"]) if plans else None


def measure_scan(scan_id, detail):
    model = matterport._query(_PLAN_QUERY, scan_id)
    name = (model.get("name") or "").strip()
    floor = matterport.floor_from_name(name, detail.get("stories"))
    row = {"scanId": scan_id, "name": name, "floor": floor}
    plan = best_plan(model)
    if not plan:
        return {**row, "error": "no floor plan image"}
    image = Image.open(io.BytesIO(requests.get(plan["url"], timeout=120).content)).convert("RGBA")
    mask = np.array(image)[..., 3] > 0
    row.update(measure(mask, plan["resolution"]))
    sizes = detail.get("floorSf") or {}
    floor_sf = sizes.get(str(floor)) or detail.get("typicalFloorSf")
    row["floorSf"] = floor_sf
    row["fullFloor"] = bool(floor_sf and row["plateSf"] >= FULL_FLOOR_SHARE * floor_sf)
    if not row["fullFloor"]:      # a suite: its edges are not the facade
        for k in [k for k in row if k.startswith("within")] + ["deepestFt", "beyond30ftSf"]:
            row[k] = None
    return row


def run(property_id):
    detail = json.loads((config.DATA / "property" / f"{property_id}.json").read_text(encoding="utf-8"))
    scans = []
    for scan_id in detail.get("scanIds") or []:
        try:
            scans.append(measure_scan(scan_id, detail))
        except Exception as error:  # one bad scan should not lose the others
            scans.append({"scanId": scan_id, "error": str(error)[:200]})
    full = [s for s in scans if s.get("fullFloor")]
    # the full-floor scan with the most floor captured stands for the building's typical plate
    plate = max(full, key=lambda s: s["scannedSf"]) if full else None
    out = {"id": property_id, "name": detail.get("name"), "scans": scans,
           "plate": {k: plate[k] for k in ("floor", "name", "plateSf", "plateFt", "deepestFt", "beyond30ftSf",
                                           *(f"within{ft}ft" for ft in THRESHOLDS_FT))} if plate else None}
    folder = config.DATA / "daylight"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{property_id}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def walkthrough_buildings():
    """Property ids of the buildings listed in walkthroughs.json, matched by street address in the LA index."""
    norm = lambda t: " ".join(re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).split())
    wanted = {norm(w["address"]) for w in json.loads((config.ROOT / "pipeline" / "walkthroughs.json").read_text(encoding="utf-8"))["floors"]}
    index = json.loads((config.DATA / "index" / "los-angeles.json").read_text(encoding="utf-8"))
    return sorted({it["id"] for it in index if it.get("kind") == "commercial" and norm(it.get("address")) in wanted})


def main():
    ids = walkthrough_buildings() if sys.argv[1:] == ["--walkthroughs"] else sys.argv[1:]
    if not ids:
        sys.exit("usage: python -m pipeline.daylight <property id> [...]  |  --walkthroughs")
    for pid in ids:
        out = run(int(pid))
        p = out["plate"]
        print(f"{out['name']}: {len(out['scans'])} scans;",
              f"plate from floor {p['floor']}: {p['within30ft']:.0%} within 30 ft, deepest {p['deepestFt']} ft" if p else "no full-floor scan")
        for s in out["scans"]:
            print("  ", s.get("floor"), s.get("name") or s["scanId"], "full floor" if s.get("fullFloor") else "suite",
                  s.get("scannedSf"), s.get("error", ""))


if __name__ == "__main__":
    main()
