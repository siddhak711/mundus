"""Where built site models and scan assets live.

Locally they are files under cache/, served by server.py at /cache/<path>. On Vercel, function instances share
no disk and responses are capped at 4.5 MB (a tall building's aerial photo is about 8 MB), so when
BLOB_READ_WRITE_TOKEN is set the files go to Vercel Blob instead and the browser loads them from its CDN.
A model is built once and then reused by every instance and every later deploy.

The Blob calls follow the @vercel/blob SDK (2.9.0): PUT https://vercel.com/api/blob/?pathname=..., API version 13.
"""
import json
import os

import requests

from . import config

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API = os.environ.get("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")
PREFIX = "atlas"
ONE_YEAR = 31_536_000


def blob_enabled():
    return bool(BLOB_TOKEN)


def _store_id():
    return BLOB_TOKEN.split("_")[3]  # vercel_blob_rw_<storeId>_<secret>


def url(rel):
    """Public URL of a stored file; rel is e.g. 'twin/commercial-27120/ortho.jpg'."""
    if blob_enabled():
        return f"https://{_store_id()}.public.blob.vercel-storage.com/{PREFIX}/{rel}"
    return f"/cache/{rel}"


def put(rel, path, content_type):
    """Publish a file written under config.CACHE. Locally the file already is the published copy."""
    if not blob_enabled():
        return
    r = requests.put(f"{BLOB_API}/", params={"pathname": f"{PREFIX}/{rel}"}, data=path.read_bytes(), timeout=120,
                     headers={"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "13",
                              "x-vercel-blob-access": "public", "x-add-random-suffix": "0",
                              "x-allow-overwrite": "1", "x-content-type": content_type,
                              "x-cache-control-max-age": str(ONE_YEAR)})
    r.raise_for_status()


def get_json(rel):
    """A stored JSON file, or None when it has not been built yet."""
    local = config.CACHE / rel
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    if not blob_enabled():
        return None
    # head() first: the CDN could hold on to a 404 for a file that was built a moment later
    r = requests.get(f"{BLOB_API}/", params={"url": url(rel)}, timeout=20,
                     headers={"authorization": f"Bearer {BLOB_TOKEN}", "x-api-version": "13"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = requests.get(r.json()["url"], timeout=30)
    data.raise_for_status()
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data.content)  # this instance skips the round trip next time
    return data.json()


def put_json(rel, payload):
    local = config.CACHE / rel
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(payload), encoding="utf-8")
    put(rel, local, "application/json")
