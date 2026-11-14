"""Evidence registry. Every fact the API returns points at one of these rows."""
from __future__ import annotations

import sqlite3
from typing import Any

from mundus_world.repo.db import Database
from mundus_world.types.ids import canonical_json, evidence_id, now_iso, sha256_hex

EVIDENCE_RANK = {"record": 5, "room": 4, "aerial_facts": 4, "pano_image": 3, "ortho_image": 3, "oblique_image": 3,
                 "floorplan": 3, "caption": 2, "summary": 1, "claim": 0}


def content_hash(content: Any) -> str:
    if isinstance(content, (bytes, bytearray)):
        return sha256_hex(bytes(content))
    if isinstance(content, str):
        return sha256_hex(content)
    return sha256_hex(canonical_json(content))


def register(conn: sqlite3.Connection, ev_type: str, source: str, source_id: str, *, content: Any = None,
             content_sha: str | None = None, place_id: str | None = None, url: str | None = None,
             excerpt: str | None = None) -> str:
    sha = content_sha or content_hash(content)
    ev = evidence_id(ev_type, source_id, sha)
    conn.execute(
        "INSERT OR REPLACE INTO evidence(evidence_id,type,source,source_id,place_id,url,excerpt,content_sha256,fetched_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (ev, ev_type, source, source_id, place_id, url, (excerpt or "")[:500], sha, now_iso()))
    return ev


def get(db: Database, ev_id: str) -> dict[str, Any] | None:
    r = db.one("SELECT * FROM evidence WHERE evidence_id=?", (ev_id,))
    return dict(r) if r else None


def rank_of(db: Database, ev_ids: list[str]) -> int:
    if not ev_ids:
        return 0
    rows = db.q(f"SELECT type FROM evidence WHERE evidence_id IN ({','.join('?' * len(ev_ids))})", ev_ids)
    return max((EVIDENCE_RANK.get(r["type"], 0) for r in rows), default=0)


def usage_logger(db: Database, run_id_getter=None):
    """Callback for Gemini.on_usage that appends one row per model call to model_usage."""
    def log(purpose: str, model: str, tin: int, tout: int, tthought: int, estimated: int, ms: float) -> None:
        try:
            db.execute("INSERT INTO model_usage(ts,purpose,model,run_id,tokens_in,tokens_out,tokens_thought,estimated,ms) "
                       "VALUES(?,?,?,?,?,?,?,?,?)",
                       (now_iso(), purpose, model, run_id_getter() if run_id_getter else None, tin, tout, tthought,
                        estimated, round(ms, 1)))
        except Exception:  # noqa: BLE001 - usage logging must never break a call
            pass
    return log
