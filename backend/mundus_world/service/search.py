"""Interior search (hybrid: FTS5 + in-memory vectors, reciprocal rank fusion) and place search."""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import numpy as np

from mundus_world.config.settings import Settings
from mundus_world.providers.embedder import Embedder
from mundus_world.repo.db import Database
from mundus_world.types.ctx import CLAIM_SCOPE
from mundus_world.types.errors import ApiError
from mundus_world.types.ids import haversine_m, now_iso, sha256_hex

log = logging.getLogger("mundus.search")
_WORD = re.compile(r"[A-Za-z0-9]{2,}")
STOP = {"the", "and", "with", "for", "that", "this", "from", "are", "has", "have", "what", "which", "where", "there",
        "any", "does", "is", "in", "of", "on", "to", "an", "it", "at", "by", "or", "be", "as",
        "out", "can", "some", "somewhere", "anywhere", "place", "places", "how", "who", "do", "you", "me", "my"}
VECTOR_WEIGHT = 3.0
RRF_K = 10   # small k keeps the top of each list decisive


def fts_query(text: str) -> str | None:
    words = [w.lower() for w in _WORD.findall(text or "") if w.lower() not in STOP]
    if not words:
        return None
    return " OR ".join(f'"{w}"*' for w in dict.fromkeys(words))


class Search:
    def __init__(self, settings: Settings, db: Database):
        self.s, self.db = settings, db
        self._lock = threading.Lock()
        self._sig: tuple | None = None
        self._ids: list[str] = []
        self._mat: np.ndarray | None = None
        self._checked = 0.0
        self._emb = Embedder(settings)
        if self._emb.enabled and db.scalar("SELECT count(*) FROM embedding WHERE vector IS NOT NULL"):
            # load the model off the request path so the first search is not slow
            threading.Thread(target=self._emb.available, daemon=True).start()

    def _load(self) -> None:
        if time.monotonic() - self._checked < 5 and self._sig is not None:
            return
        with self._lock:
            sig = tuple(self.db.one("SELECT count(*), coalesce(max(rowid),0), coalesce(sum(length(text_sha256)),0) "
                                    "FROM embedding WHERE vector IS NOT NULL"))
            self._checked = time.monotonic()
            if sig == self._sig:
                return
            rows = self.db.q("SELECT doc_id, vector FROM embedding WHERE vector IS NOT NULL")
            self._ids = [r["doc_id"] for r in rows]
            self._mat = (np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
                         if rows else None)
            self._sig = sig

    def _query_vector(self, text: str) -> tuple[np.ndarray | None, str]:
        key = sha256_hex(re.sub(r"\s+", " ", text.strip().lower()) + "|" + self.s.embed_model)
        r = self.db.one("SELECT vector FROM query_embed_cache WHERE qhash=?", (key,))
        if r:
            return np.frombuffer(r["vector"], dtype=np.float32), "hit"
        if not self._emb.enabled:
            return None, "none"
        try:
            v = self._emb.query(text)
            if v is None:
                return None, "none"
            self.db.execute("INSERT OR REPLACE INTO query_embed_cache(qhash,query,model,vector,created_at) VALUES(?,?,?,?,?)",
                            (key, text[:500], self.s.embed_model, v.tobytes(), now_iso()))
            return v, "miss"
        except Exception as e:  # noqa: BLE001 - fall back to text search
            log.warning("query embedding failed: %s", type(e).__name__)
            return None, "failed"

    def warm(self, queries: list[str]) -> int:
        return sum(1 for q in queries if self._query_vector(q)[0] is not None)

    def interiors(self, text: str, place_id: str | None = None, near: dict[str, Any] | None = None,
                  kinds: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        if not text or not text.strip():
            raise ApiError("invalid_argument", "text is required")
        limit = max(1, min(int(limit or 10), 50))
        kinds = [k for k in (kinds or []) if k in ("pano", "room", "space", "place", "claim")] or None
        place_filter: set[str] | None = None
        if place_id:
            place_filter = {place_id}
        elif near:
            try:
                lat, lon, rad = float(near["lat"]), float(near["lon"]), float(near.get("radius_m", 1000))
            except (KeyError, TypeError, ValueError):
                raise ApiError("invalid_argument", "near needs lat, lon and optional radius_m") from None
            place_filter = {r["place_id"] for r in self.db.q("SELECT place_id, lat, lon FROM place WHERE is_deep=1")
                            if r["lat"] is not None and haversine_m(lat, lon, r["lat"], r["lon"]) <= rad}
        self._load()
        ranks: dict[str, float] = {}
        fq = fts_query(text)
        if fq:
            for i, r in enumerate(self.db.q("SELECT doc_id FROM doc_fts WHERE doc_fts MATCH ? ORDER BY bm25(doc_fts) LIMIT 80", (fq,))):
                ranks[r["doc_id"]] = ranks.get(r["doc_id"], 0.0) + 1.0 / (RRF_K + i + 1)
        vec, cache = self._query_vector(text) if self._mat is not None else (None, "none")
        mode = "text_only"
        if vec is not None and self._mat is not None and vec.shape[0] == self._mat.shape[1]:
            mode = "hybrid"
            sims = self._mat @ vec
            # meaning outranks word overlap: a paraphrase ("somewhere to work out") shares no useful words with a gym caption
            for i, j in enumerate(np.argsort(-sims)[:80]):
                d = self._ids[int(j)]
                ranks[d] = ranks.get(d, 0.0) + VECTOR_WEIGHT / (RRF_K + i + 1)
        hits: list[dict[str, Any]] = []
        for doc_id, score in sorted(ranks.items(), key=lambda kv: (-kv[1], kv[0])):
            d = self.db.one("SELECT doc_id, doc_type, place_id, space_id, title, text, evidence_id FROM embedding WHERE doc_id=?", (doc_id,))
            if not d:
                continue
            if kinds and d["doc_type"] not in kinds:
                continue
            if place_filter is not None and d["place_id"] not in place_filter:
                continue
            h = {"kind": d["doc_type"], "id": d["doc_id"], "score": round(score, 5), "place_id": d["place_id"],
                 "space_id": d["space_id"], "title": d["title"], "snippet": _snippet(d["text"], text),
                 "evidence_id": d["evidence_id"]}
            if d["doc_type"] == "pano":
                p = self.db.one("SELECT room_id FROM pano WHERE pano_id=?", (doc_id,))
                h["room_id"] = p["room_id"] if p else None
                h["thumb_url"] = f"/v1/panos/{doc_id}/faces/1?size=thumb"
            elif d["doc_type"] == "room":
                h["room_id"] = doc_id
            elif d["doc_type"] == "claim":
                cl = self.db.one("SELECT subject_id, scope FROM claim WHERE claim_id=?", (doc_id,))
                if not cl or cl["scope"] != CLAIM_SCOPE.get():
                    continue              # another run's private memory
                h["subject_id"] = cl["subject_id"]
            hits.append(h)
            if len(hits) >= limit:
                break
        return {"mode": mode, "query_embedding": cache, "hits": hits,
                "hint": "Use get_room or get_space on a hit for full captions and dimensions."}

    def places(self, query: str | None = None, near: dict[str, Any] | None = None, filters: dict[str, Any] | None = None,
               limit: int = 10, cursor: str | None = None) -> dict[str, Any]:
        filters = filters or {}
        limit = max(1, min(int(limit or 10), 100))
        offset = int(cursor) if cursor and str(cursor).isdigit() else 0
        cand: dict[str, float] | None = None
        if query and query.strip():
            cand = {}
            fq = fts_query(query)
            if fq:
                for i, r in enumerate(self.db.q("SELECT place_id FROM place_fts WHERE place_fts MATCH ? ORDER BY bm25(place_fts) LIMIT 300", (fq,))):
                    cand.setdefault(r["place_id"], float(i))
            like = f"%{query.strip().lower()}%"
            for r in self.db.q("SELECT place_id FROM place WHERE lower(name) LIKE ? OR lower(address) LIKE ? OR place_id=? LIMIT 50",
                               (like, like, query.strip())):
                cand[r["place_id"]] = min(cand.get(r["place_id"], 1e9), -1.0)
        sql = ("SELECT p.*, (SELECT count(*) FROM space s WHERE s.place_id=p.place_id) AS space_count FROM place p WHERE 1=1")
        params: list[Any] = []
        if filters.get("type"):
            sql += " AND lower(p.property_type)=?"
            params.append(str(filters["type"]).lower())
        if filters.get("deep_only"):
            sql += " AND p.is_deep=1"
        if filters.get("has_interior"):
            sql += " AND EXISTS (SELECT 1 FROM space s WHERE s.place_id=p.place_id)"
        if filters.get("has_listing") and "costar_listing" in self.db.tables():
            sql += " AND EXISTS (SELECT 1 FROM costar_listing l WHERE l.place_id=p.place_id)"
        center = None
        if near:
            try:
                center = (float(near["lat"]), float(near["lon"]), float(near.get("radius_m", 1000)))
            except (KeyError, TypeError, ValueError):
                raise ApiError("invalid_argument", "near needs lat, lon and optional radius_m") from None
            dlat = center[2] / 111320.0
            dlon = center[2] / (111320.0 * 0.83)
            sql += " AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?"
            params += [center[0] - dlat, center[0] + dlat, center[1] - dlon, center[1] + dlon]
        rows = []
        for r in self.db.q(sql, params):
            d = dict(r)
            if cand is not None and d["place_id"] not in cand:
                continue
            if center:
                d["distance_m"] = round(haversine_m(center[0], center[1], d["lat"], d["lon"]), 1)
                if d["distance_m"] > center[2]:
                    continue
            d["_rank"] = cand[d["place_id"]] if cand is not None else 0.0
            rows.append(d)
        rows.sort(key=lambda d: (-d["is_deep"], d.get("distance_m", 0.0) if center else d["_rank"], d["place_id"]))
        page = rows[offset:offset + limit]
        out = {"places": [place_summary(d) for d in page], "total": len(rows)}
        if offset + limit < len(rows):
            out["next_cursor"] = str(offset + limit)
        if not rows:
            out["hint"] = "No place matched. Try a shorter query (street name only) or a larger radius."
        return out


def place_summary(d: dict[str, Any]) -> dict[str, Any]:
    out = {"place_id": d["place_id"], "name": d["name"], "address": d["address"], "property_type": d["property_type"],
           "lat": d["lat"], "lon": d["lon"], "is_deep": bool(d["is_deep"]), "space_count": d.get("space_count", 0),
           "building_sqft": d["building_sqft"], "evidence_id": d["evidence_id"]}
    if "distance_m" in d:
        out["distance_m"] = d["distance_m"]
    return out


def _snippet(text: str, query: str, width: int = 260) -> str:
    low = text.lower()
    pos = min((p for p in (low.find(w.lower()) for w in _WORD.findall(query) if w.lower() not in STOP) if p >= 0), default=0)
    start = max(0, pos - 80)
    s = text[start:start + width].replace("\n", " ")
    return ("…" if start > 0 else "") + s + ("…" if start + width < len(text) else "")
