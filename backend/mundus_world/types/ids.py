"""Id helpers and hashing shared by every layer. No internal imports."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def evidence_id(ev_type: str, source_id: str, content_sha: str) -> str:
    return "ev:" + sha256_hex(f"{ev_type}|{source_id}|{content_sha}")[:16]


def place_id_for_property(pid: str | int) -> str:
    return f"place:costar:{pid}"


def place_id_for_home(res_listing_id: str | int) -> str:
    return f"place:home:{res_listing_id}"


def space_id(sid: str) -> str:
    return f"space:{sid}"


def room_id(sid: str, rid: str) -> str:
    return f"room:{sid}:{rid}"


def pano_id(sid: str, pid: str) -> str:
    return f"pano:{sid}:{pid}"


def floor_id(sid: str, fid: str) -> str:
    return f"floor:{sid}:{fid}"


def node_kind(node_id: str) -> str:
    return node_id.split(":", 1)[0] if ":" in node_id else "unknown"


def round_sig(x: float, sig: int = 3) -> float:
    if x == 0 or not math.isfinite(x):
        return 0.0 if x == 0 else x
    return round(x, sig - int(math.floor(math.log10(abs(x)))) - 1)


def normalize_value(value: Any) -> str:
    """Normal form used in claim ids: numbers to 3 significant figures, strings lower-cased and collapsed."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        v = round_sig(float(value), 3)
        return repr(int(v)) if float(v).is_integer() else repr(v)
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip().lower())
    return canonical_json(value)


def claim_id(subject_id: str, predicate: str, value: Any) -> str:
    return "claim:" + sha256_hex(f"{subject_id}|{predicate}|{normalize_value(value)}")[:16]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_SNAKE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")


def snake(name: str) -> str:
    s = _SNAKE_2.sub(r"\1_\2", _SNAKE_1.sub(r"\1_\2", name))
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
