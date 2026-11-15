"""CoStar data kit: download, unzip (password), iterate records."""
from __future__ import annotations

import csv
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Iterator

from mundus_world.config.settings import Settings
from mundus_world.providers.http import Http

DATASETS = {
    "commercial-property": 3339,
    "commercial-listing-summary": 1022,
    "location-occupancy": 74093,
    "company-detail": 49575,
    "commercial-sale-comp": 6120,
    "apartment-listing": 1747,
    "residential-listings": 2120,
    "residential-listing-features": 1899,
}


def ensure_kit(settings: Settings, http: Http) -> Path:
    """Download and unzip the kit into data/kit if it is not there yet. Returns the kit folder."""
    kit = settings.kit_dir
    if (kit / "data" / "commercial-property.jsonl").exists():
        return kit
    if not settings.kit_url or not settings.kit_password:
        raise RuntimeError("COSTAR_KIT_URL and COSTAR_ZIP_PASSWORD are required to load the CoStar kit")
    kit.mkdir(parents=True, exist_ok=True)
    zpath = settings.data_dir / "kit.zip"
    if not zpath.exists():
        zpath.write_bytes(http.get_bytes(settings.kit_url, auth_fatal=False))
    dest = os.path.realpath(kit)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            target = os.path.realpath(os.path.join(dest, info.filename))
            if not (target == dest or target.startswith(dest + os.sep)):
                raise RuntimeError(f"unsafe path in kit zip: {info.filename}")
            z.extract(info, dest, pwd=settings.kit_password.encode())
    return kit


def iter_records(kit: Path, dataset: str) -> Iterator[dict[str, Any]]:
    with open(kit / "data" / f"{dataset}.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def load_enums(kit: Path) -> dict[str, dict[str, str]]:
    p = kit / "schemas" / "enums.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
