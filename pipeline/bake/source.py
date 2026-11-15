"""Everything the bake reads from Matterport for one scan, downloaded once and cached under raw/.

    model(scan)       the model response: capture points (position, rotation), floor plans, dimensions
    matterpak(scan)   the MatterPak's OBJ, MTL and textures, read out of the zip with HTTP range requests so the
                      point cloud inside it (often over 1 GB) is never downloaded
    plan(scan)        the transparent top-down floor plan image and its placement (origin, pixels per metre)
    skybox_urls(scan, res)   fresh signed links to every capture point's six faces (they expire in about 30 min)

Matterport's limit is about 10 requests a second; signed links expire, so nothing here stores one for later.
"""
import io
import json
import zipfile
from pathlib import Path

import requests

from pipeline import config, matterport

ROOT = config.ROOT / "web" / "walkthrough" / "floors"

_MODEL = """query($id: ID!) { model(id: $id) {
  id name
  dimensions(units: metric) { areaFloor height }
  floors { id label }
  panoLocations { id label position { x y z } rotation { x y z w } }
  assets { floorplans(provider: "matterport") { format flags url width height resolution origin { x y } } }
} }"""
_BUNDLE = """query($id: ID!) { model(id: $id) { bundle(id: "mp:matterpak") { availability assets { url } } } }"""
_SKYBOX = """query($id: ID!) { model(id: $id) { panoLocations { id skybox(resolution: "%s") { children } } } }"""


def floor_dir(scan):
    return ROOT / scan


def raw_dir(scan):
    d = floor_dir(scan) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def model(scan, refresh=False):
    """The model response, cached as raw/model.json (it holds no signed links worth keeping)."""
    path = raw_dir(scan) / "model.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    m = matterport._query(_MODEL, scan)
    path.write_text(json.dumps(m), encoding="utf-8")
    return m


def plan(scan):
    """(path to the transparent floor plan PNG, its meta {origin {x,y}, resolution px/m, width, height})."""
    raw = raw_dir(scan)
    png, meta_path = raw / "plan.png", raw / "plan.json"
    if png.exists() and meta_path.exists():
        return png, json.loads(meta_path.read_text(encoding="utf-8"))
    plans = [f for f in model(scan, refresh=True)["assets"]["floorplans"]
             if f["format"] == "png" and "alpha" in (f.get("flags") or []) and f.get("resolution") and f.get("width")]
    best = max(plans, key=lambda f: f["resolution"])
    png.write_bytes(requests.get(best["url"], timeout=300).content)
    meta = {k: best[k] for k in ("origin", "resolution", "width", "height")}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return png, meta


class RangeFile(io.RawIOBase):
    """A read-only, seekable file over an HTTP URL, fetched in ranges: lets zipfile read one member of a big zip."""

    def __init__(self, url, block=1 << 20):
        super().__init__()
        self.url, self.block, self.pos = url, block, 0
        r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=60)
        r.raise_for_status()
        self.size = int(r.headers["Content-Range"].split("/")[-1])
        self.cache = {}

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else (self.pos + offset if whence == 1 else self.size + offset)
        return self.pos

    def _chunk(self, i):
        if i not in self.cache:
            start = i * self.block
            end = min(self.size, start + self.block) - 1
            r = requests.get(self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=300)
            r.raise_for_status()
            self.cache = {i: r.content}                       # keep one block: members are read in order
        return self.cache[i]

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        i, off = divmod(self.pos, self.block)
        data = self._chunk(i)[off:off + len(b)]
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def matterpak(scan):
    """Extract the MatterPak's mesh (.obj, .mtl) and its textures into raw/pak/. Returns that folder."""
    out = raw_dir(scan) / "pak"
    done = out / ".complete"
    if done.exists():
        return out
    out.mkdir(parents=True, exist_ok=True)
    b = (matterport._query(_BUNDLE, scan).get("bundle") or {})
    if b.get("availability") != "unlocked" or not b.get("assets"):
        raise RuntimeError(f"MatterPak not available for {scan}: {b.get('availability')}")
    with zipfile.ZipFile(RangeFile(b["assets"][0]["url"])) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if not name or not name.lower().endswith((".obj", ".mtl", ".jpg", ".jpeg", ".png")):
                continue                                       # skips the point cloud (.xyz) and anything else
            with z.open(info) as src, open(out / name, "wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    done.write_text("ok")
    return out


def skybox_urls(scan, res="2k"):
    """{panoId: [six signed face URLs, in Matterport's face order 0 up, 1-4 sides turning right, 5 down]}."""
    m = matterport._query(_SKYBOX % res, scan)
    return {p["id"]: ((p.get("skybox") or {}).get("children") or []) for p in m["panoLocations"]}
