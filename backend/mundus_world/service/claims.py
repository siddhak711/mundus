"""Claims: evidence-linked facts written by agents. Deterministic merge, conflict and staleness rules (no model calls)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from mundus_world.repo.db import Database
from mundus_world.service import evidence as ev
from mundus_world.service import graph
from mundus_world.types.ctx import CLAIM_SCOPE
from mundus_world.types.errors import ApiError
from mundus_world.types.ids import claim_id, node_kind, normalize_value, now_iso, sha256_hex

FREE_NAMESPACES = ("note.", "synthesis.")
MARKET_TTL = timedelta(days=7)
DISPUTE_WINDOW = timedelta(hours=24)
_VOCAB_CACHE: dict[str, dict[str, Any]] = {}


def load_vocab(path: Path) -> dict[str, Any]:
    key = str(path)
    if key not in _VOCAB_CACHE:
        _VOCAB_CACHE[key] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _VOCAB_CACHE[key]


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def to_public(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["claim_id"], "subject_id": r["subject_id"], "place_id": r["place_id"], "predicate": r["predicate"],
            "value": json.loads(r["value_json"]), "unit": r["unit"], "statement": r["statement"],
            "evidence_ids": json.loads(r["evidence_ids"]), "derived_from": json.loads(r["derived_from"]),
            "confidence": r["confidence"], "status": r["status"], "confirmations": r["confirmations"],
            "created_by": r["created_by"], "run_id": r["run_id"], "created_at": r["created_at"],
            "updated_at": r["updated_at"]}


def _differs(a: Any, b: Any, exact: bool = False) -> bool:
    """Numbers within 5% count as the same fact, except for predicates flagged exact (years, counts)."""
    num = (int, float)
    if not exact and isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        big = max(abs(a), abs(b))
        return big > 0 and abs(a - b) / big > 0.05
    return normalize_value(a) != normalize_value(b)


class Claims:
    def __init__(self, db: Database, vocab_path: Path):
        self.db = db
        self.vocab_path = vocab_path

    @property
    def vocab(self) -> dict[str, Any]:
        return load_vocab(self.vocab_path)

    def _is_free(self, predicate: str) -> bool:
        return predicate.startswith(FREE_NAMESPACES)

    def _is_multi(self, predicate: str) -> bool:
        return self._is_free(predicate) or bool((self.vocab.get(predicate) or {}).get("multi"))

    def _rank(self, evidence_ids: list[str], derived_from: list[str]) -> int:
        if evidence_ids:
            return ev.rank_of(self.db, evidence_ids)
        ranks = [r["rank"] for r in self.db.q(
            f"SELECT rank FROM claim WHERE claim_id IN ({','.join('?' * len(derived_from))})", derived_from)]
        return min(ranks) if ranks else 0

    # ---- write -----------------------------------------------------------
    def put(self, subject_id: str, predicate: str, value: Any, statement: str, evidence_ids: list[str] | None = None,
            confidence: float = 0.5, unit: str | None = None, derived_from: list[str] | None = None,
            created_by: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        evidence_ids = sorted(set(evidence_ids or []))
        derived_from = sorted(set(derived_from or []))
        if not isinstance(statement, str) or not (3 <= len(statement.strip()) <= 1000):
            raise ApiError("invalid_argument", "statement must be 3 to 1000 characters")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            raise ApiError("invalid_argument", "confidence must be a number between 0 and 1") from None
        if not 0 <= confidence <= 1:
            raise ApiError("invalid_argument", "confidence must be between 0 and 1")
        if value is None:
            raise ApiError("invalid_argument", "value is required")
        if not self._is_free(predicate) and predicate not in self.vocab:
            raise ApiError("invalid_argument", f"Unknown predicate '{predicate}'. Use one from the claims vocabulary, "
                           "or a free-form note.* or synthesis.* predicate.",
                           {"allowed_namespaces": sorted({p.split('.')[0] for p in self.vocab}) + ["note", "synthesis"]})
        if not graph.node_exists(self.db, subject_id):
            raise ApiError("invalid_argument", f"subject_id {subject_id} is not a known node")
        if not evidence_ids and not derived_from:
            raise ApiError("invalid_argument", "A claim needs at least one evidence_id you received from a tool, "
                           "or derived_from claim ids.")
        if evidence_ids:
            found = {r[0]: r[1] for r in self.db.q(
                f"SELECT evidence_id, content_sha256 FROM evidence WHERE evidence_id IN ({','.join('?' * len(evidence_ids))})",
                evidence_ids)}
            unknown = [e for e in evidence_ids if e not in found]
            if unknown:
                raise ApiError("invalid_argument", "Unknown evidence ids. Cite only ids returned by a tool.",
                               {"unknown_evidence_ids": unknown})
        else:
            found = {}
        if derived_from:
            have = {r[0] for r in self.db.q(
                f"SELECT claim_id FROM claim WHERE scope=? AND claim_id IN ({','.join('?' * len(derived_from))})",
                [CLAIM_SCOPE.get(), *derived_from])}
            unknown = [c for c in derived_from if c not in have]
            if unknown:
                raise ApiError("invalid_argument", "Unknown derived_from claim ids.", {"unknown_claim_ids": unknown})

        scope = CLAIM_SCOPE.get()
        cid = claim_id(subject_id, predicate, value)
        if scope:                      # a private memory gets its own ids, so the same fact in two runs never merges
            cid = "claim:" + sha256_hex(f"{cid}|{scope}")[:16]
        now = now_iso()
        place = graph.place_of(self.db, subject_id)
        rank = self._rank(evidence_ids, derived_from)
        with self.db.write() as c:
            existing = c.execute("SELECT * FROM claim WHERE claim_id=?", (cid,)).fetchone()
            if existing:
                return self._merge(c, dict(existing), evidence_ids, found, now)
            conflicts: list[str] = []
            outcome, status = "created", "active"
            if not self._is_multi(predicate):
                others = [dict(r) for r in c.execute(
                    "SELECT * FROM claim WHERE subject_id=? AND predicate=? AND scope=? AND status IN ('active','disputed')",
                    (subject_id, predicate, scope))]
                exact = bool((self.vocab.get(predicate) or {}).get("exact"))
                close = [o for o in others if not _differs(json.loads(o["value_json"]), value, exact)]
                if close:
                    return self._merge(c, close[0], evidence_ids, found, now)
                for old in others:
                    conflicts.append(old["claim_id"])
                    age = _parse(now) - _parse(old["created_at"])
                    if rank > old["rank"] or (rank == old["rank"] and age > DISPUTE_WINDOW):
                        c.execute("UPDATE claim SET status='superseded', updated_at=? WHERE claim_id=?", (now, old["claim_id"]))
                        self._edge(c, cid, "supersedes", old["claim_id"], "rule", now)
                        if outcome == "created":
                            outcome = "superseded_old"
                    elif rank < old["rank"]:
                        outcome, status = "rejected_lower_rank", "superseded"
                        self._edge(c, old["claim_id"], "supersedes", cid, "rule", now)
                    else:
                        outcome, status = "disputed", "disputed"
                        c.execute("UPDATE claim SET status='disputed', updated_at=? WHERE claim_id=?", (now, old["claim_id"]))
                        self._edge(c, cid, "contradicts", old["claim_id"], "rule", now)
            c.execute(
                """INSERT INTO claim(claim_id,subject_id,place_id,predicate,value_json,unit,statement,evidence_ids,evidence_sha,
                     derived_from,confidence,status,confirmations,rank,created_by,run_id,created_at,updated_at,scope)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, subject_id, place, predicate, json.dumps(value, ensure_ascii=False), unit, statement.strip(),
                 json.dumps(evidence_ids), json.dumps(found), json.dumps(derived_from), confidence, status, 1, rank,
                 created_by, run_id, now, now, scope))
            self._edge(c, cid, "about", subject_id, "agent", now)
            for e in evidence_ids:
                self._edge(c, cid, "supported_by", e, "agent", now)
            for d in derived_from:
                self._edge(c, cid, "derived_from", d, "agent", now)
            if node_kind(subject_id) in ("pano", "room", "space") and status == "active":
                space = subject_id if node_kind(subject_id) == "space" else c.execute(
                    "SELECT space_id FROM room WHERE room_id=? UNION SELECT space_id FROM pano WHERE pano_id=?",
                    (subject_id, subject_id)).fetchone()
                space_id = space if isinstance(space, str) else (space[0] if space else None)
                c.execute("INSERT OR REPLACE INTO embedding(doc_id,doc_type,place_id,space_id,title,text,text_sha256,model,dim,"
                          "vector,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (cid, "claim", place, space_id, f"Claim on {subject_id}", statement.strip(), "", None, None, None,
                           evidence_ids[0] if evidence_ids else None))
                c.execute("DELETE FROM doc_fts WHERE doc_id=?", (cid,))
                c.execute("INSERT INTO doc_fts(doc_id,doc_type,text) VALUES(?,?,?)", (cid, "claim", statement.strip()))
            row = dict(c.execute("SELECT * FROM claim WHERE claim_id=?", (cid,)).fetchone())
        return {"claim": to_public(row), "outcome": outcome, "created": outcome != "rejected_lower_rank", "conflicts": conflicts}

    def _merge(self, c, existing: dict[str, Any], evidence_ids: list[str], found: dict[str, str], now: str) -> dict[str, Any]:
        ids = sorted(set(json.loads(existing["evidence_ids"])) | set(evidence_ids))
        sha = {**json.loads(existing["evidence_sha"]), **found}
        status = "active" if existing["status"] == "stale" else existing["status"]
        c.execute("UPDATE claim SET evidence_ids=?, evidence_sha=?, confirmations=confirmations+1, status=?, updated_at=?, "
                  "rank=MAX(rank, ?) WHERE claim_id=?",
                  (json.dumps(ids), json.dumps(sha), status, now, ev.rank_of(self.db, evidence_ids), existing["claim_id"]))
        for e in evidence_ids:
            self._edge(c, existing["claim_id"], "supported_by", e, "agent", now)
        row = dict(c.execute("SELECT * FROM claim WHERE claim_id=?", (existing["claim_id"],)).fetchone())
        return {"claim": to_public(row), "outcome": "merged", "created": False, "conflicts": []}

    @staticmethod
    def _edge(c, src: str, rel: str, dst: str, source: str, now: str) -> None:
        c.execute("INSERT OR REPLACE INTO edges(src,rel,dst,source,weight,created_at) VALUES(?,?,?,?,?,?)",
                  (src, rel, dst, source, None, now))

    # ---- staleness ---------------------------------------------------------
    def refresh_stale(self, place_id: str | None = None) -> int:
        where, params = ("WHERE status='active'", [])
        if place_id:
            where += " AND place_id=?"
            params.append(place_id)
        rows = [dict(r) for r in self.db.q(f"SELECT * FROM claim {where}", params)]
        now = datetime.now(timezone.utc)
        stale: list[str] = []
        status = {r["claim_id"]: r["status"] for r in rows}
        for r in rows:
            if r["predicate"].startswith("market.") and now - _parse(r["created_at"]) > MARKET_TTL:
                stale.append(r["claim_id"])
                continue
            shas = json.loads(r["evidence_sha"])
            if shas:
                cur = {x[0]: x[1] for x in self.db.q(
                    f"SELECT evidence_id, content_sha256 FROM evidence WHERE evidence_id IN ({','.join('?' * len(shas))})",
                    list(shas))}
                if all(cur.get(e) != s for e, s in shas.items()):
                    stale.append(r["claim_id"])
                    continue
            if r["predicate"].startswith("synthesis."):
                parents = json.loads(r["derived_from"])
                for p in parents:
                    st = status.get(p) or self.db.scalar("SELECT status FROM claim WHERE claim_id=?", (p,))
                    if st != "active":
                        stale.append(r["claim_id"])
                        break
        if stale:
            self.db.executemany("UPDATE claim SET status='stale', updated_at=? WHERE claim_id=?",
                                [(now_iso(), cid) for cid in stale])
        return len(stale)

    # ---- read --------------------------------------------------------------
    def get(self, subject_id: str, predicate_prefix: str | None = None, status: str = "active",
            count_read: bool = True) -> dict[str, Any]:
        if not graph.node_exists(self.db, subject_id):
            raise ApiError("not_found", f"No node with id {subject_id}")
        is_place = node_kind(subject_id) == "place"
        self.refresh_stale(subject_id if is_place else graph.place_of(self.db, subject_id))
        sql = f"SELECT * FROM claim WHERE {'place_id' if is_place else 'subject_id'}=? AND scope=?"
        params: list[Any] = [subject_id, CLAIM_SCOPE.get()]
        if status and status != "all":
            sql += " AND status=?"
            params.append(status)
        if predicate_prefix:
            sql += " AND predicate LIKE ?"
            params.append(predicate_prefix.replace("%", "") + "%")
        sql += " ORDER BY predicate, created_at"
        rows = [dict(r) for r in self.db.q(sql, params)]
        if rows and count_read:
            self.db.executemany("UPDATE claim SET read_count=read_count+1 WHERE claim_id=?", [(r["claim_id"],) for r in rows])
        return {"subject_id": subject_id, "claims": [to_public(r) for r in rows], "count": len(rows)}

    def one(self, cid: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM claim WHERE claim_id=?", (cid,))
        if not r:
            raise ApiError("not_found", f"No claim with id {cid}")
        return to_public(dict(r))

    def invalidate(self, cid: str, reason: str, superseded_by: str | None = None) -> dict[str, Any]:
        if not self.db.one("SELECT 1 FROM claim WHERE claim_id=?", (cid,)):
            raise ApiError("not_found", f"No claim with id {cid}")
        now = now_iso()
        with self.db.write() as c:
            c.execute("UPDATE claim SET status='superseded', updated_at=? WHERE claim_id=?", (now, cid))
            c.execute("DELETE FROM doc_fts WHERE doc_id=?", (cid,))
            c.execute("DELETE FROM embedding WHERE doc_id=?", (cid,))
            if superseded_by:
                self._edge(c, superseded_by, "supersedes", cid, "rule", now)
        return {"claim": self.one(cid), "reason": reason}

    def places_with_claims(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.q(
            """SELECT c.place_id, p.name, count(*) AS claims, sum(c.status='active') AS active FROM claim c
               JOIN place p ON p.place_id=c.place_id WHERE c.scope=? GROUP BY c.place_id ORDER BY claims DESC""",
            (CLAIM_SCOPE.get(),))]

    # ---- reset and snapshots -------------------------------------------------
    def _clear(self, c) -> None:
        c.execute("DELETE FROM claim")
        c.execute("DELETE FROM edges WHERE source IN ('agent','rule')")
        c.execute("DELETE FROM doc_fts WHERE doc_type='claim'")
        c.execute("DELETE FROM embedding WHERE doc_type='claim'")

    def purge_scoped(self) -> dict[str, Any]:
        """Deletes every private (run-scoped) claim. The shared memory is not touched."""
        with self.db.write() as c:
            ids = [r[0] for r in c.execute("SELECT claim_id FROM claim WHERE scope!=''")]
            for cid in ids:
                c.execute("DELETE FROM edges WHERE src=? OR dst=?", (cid, cid))
                c.execute("DELETE FROM doc_fts WHERE doc_id=?", (cid,))
                c.execute("DELETE FROM embedding WHERE doc_id=?", (cid,))
            c.execute("DELETE FROM claim WHERE scope!=''")
        return {"purged": len(ids)}

    def snapshot(self, name: str) -> dict[str, Any]:
        now = now_iso()
        with self.db.write() as c:
            c.execute("DELETE FROM claim_snapshot WHERE name=?", (name,))
            rows = [dict(r) for r in c.execute("SELECT * FROM claim")]
            c.executemany("INSERT INTO claim_snapshot(name,created_at,claim_json) VALUES(?,?,?)",
                          [(name, now, json.dumps(r)) for r in rows])
        return {"name": name, "claims": len(rows)}

    def list_snapshots(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.q(
            "SELECT name, min(created_at) AS created_at, count(*) AS claims FROM claim_snapshot GROUP BY name ORDER BY name")]

    def reset(self, mode: str = "empty", name: str | None = None, clear_caches: bool = False) -> dict[str, Any]:
        if mode not in ("empty", "restore"):
            raise ApiError("invalid_argument", "mode must be 'empty' or 'restore'")
        if mode == "restore" and not name:
            raise ApiError("invalid_argument", "restore needs a snapshot name")
        reset_id = uuid.uuid4().hex[:12]
        now = now_iso()
        restored = 0
        with self.db.write() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM claim")]
            if mode == "restore":
                snap = [json.loads(r[0]) for r in c.execute("SELECT claim_json FROM claim_snapshot WHERE name=?", (name,))]
                if not snap and not c.execute("SELECT 1 FROM claim_snapshot WHERE name=?", (name,)).fetchone():
                    raise ApiError("not_found", f"No snapshot named {name}")
            c.executemany("INSERT INTO claim_archive(reset_id,archived_at,claim_json) VALUES(?,?,?)",
                          [(reset_id, now, json.dumps(r)) for r in rows])
            self._clear(c)
            if mode == "restore":
                for r in snap:
                    r["read_count"] = 0
                    cols = list(r.keys())
                    c.execute(f"INSERT INTO claim({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [r[k] for k in cols])
                    self._edge(c, r["claim_id"], "about", r["subject_id"], "agent", now)
                    for e in json.loads(r["evidence_ids"]):
                        self._edge(c, r["claim_id"], "supported_by", e, "agent", now)
                    for d in json.loads(r["derived_from"]):
                        self._edge(c, r["claim_id"], "derived_from", d, "agent", now)
                    if node_kind(r["subject_id"]) in ("pano", "room", "space") and r["status"] == "active":
                        c.execute("INSERT INTO doc_fts(doc_id,doc_type,text) VALUES(?,?,?)", (r["claim_id"], "claim", r["statement"]))
                        c.execute("INSERT OR REPLACE INTO embedding(doc_id,doc_type,place_id,title,text) VALUES(?,?,?,?,?)",
                                  (r["claim_id"], "claim", r["place_id"], f"Claim on {r['subject_id']}", r["statement"]))
                restored = len(snap)
            c.execute("DELETE FROM api_log")
            if clear_caches:
                c.execute("DELETE FROM query_embed_cache")
                c.execute("DELETE FROM aerial_search_cache")
        return {"reset_id": reset_id, "archived": len(rows), "restored": restored, "caches_cleared": bool(clear_caches)}


FACETS = ("market", "interior", "aerial", "surroundings")


def _facet_of(c: dict[str, Any]) -> str:
    """Facet a claim counts toward. A free-form note about a room, space or pano is interior knowledge: without this,
    an agent that files what it saw under note.* leaves the interior facet looking empty and the work is redone."""
    ns = c["predicate"].split(".")[0]
    if ns == "pano" or (ns == "note" and str(c.get("subject_id") or "").startswith(("room:", "space:", "pano:"))):
        return "interior"
    return ns


def coverage(claims: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {f: {"fresh": 0, "stale": 0} for f in FACETS}
    for c in claims:
        ns = _facet_of(c)
        if ns in out:
            if c["status"] == "active":
                out[ns]["fresh"] += 1
            elif c["status"] == "stale":
                out[ns]["stale"] += 1
    for v in out.values():
        v["state"] = "fresh" if v["fresh"] >= 3 else ("partial" if v["fresh"] else ("stale" if v["stale"] else "none"))
    return out


def _age(ts: str) -> str:
    d = datetime.now(timezone.utc) - _parse(ts)
    if d < timedelta(hours=1):
        return f"{max(1, int(d.total_seconds() // 60))}m"
    if d < timedelta(days=1):
        return f"{int(d.total_seconds() // 3600)}h"
    return f"{d.days}d"


def render_card(db: Database, claims_svc: Claims, place_id: str) -> str:
    """card.md for a place: generated from claims, never written by a model."""
    pl = db.one("SELECT * FROM place WHERE place_id=?", (place_id,))
    if not pl:
        raise ApiError("not_found", f"No place with id {place_id}")
    allc = claims_svc.get(place_id, status="all", count_read=False)["claims"]
    active = [c for c in allc if c["status"] == "active"]
    disputed = [c for c in allc if c["status"] == "disputed"]
    cov = coverage(allc)
    size = f"{pl['building_sqft']:.0f} sq ft" if pl["building_sqft"] else "size unknown"
    lines = [f"# {pl['name']} ({place_id})", f"{pl['address'] or 'address unknown'} · {pl['property_type'] or 'type unknown'} · {size}",
             "coverage: " + " ".join(
                 f"{f}={v['state']}" + (f"({v['fresh']})" if v["fresh"] else (f"({v['stale']})" if v["stale"] else ""))
                 for f, v in cov.items()),
             f"updated: {max((c['updated_at'] for c in allc), default=now_iso())} · claims: {len(active)} active, {len(disputed)} disputed", ""]
    ev_types = {r[0]: r[1] for r in db.q("SELECT evidence_id, type FROM evidence WHERE place_id=?", (place_id,))}
    for facet in (*FACETS, "synthesis", "note"):
        rows = [c for c in active if _facet_of(c) == facet]
        if not rows:
            continue
        lines.append(f"## {facet}")
        for c in rows:
            kind = ev_types.get(c["evidence_ids"][0], "evidence") if c["evidence_ids"] else "derived"
            lines.append(f"- {c['statement']} [{c['id']}] ({c['confidence']:.1f}, {kind}, {_age(c['created_at'])})")
    if disputed:
        lines.append("## disputed")
        by: dict[tuple, list] = {}
        for c in disputed:
            by.setdefault((c["subject_id"], c["predicate"]), []).append(c)
        for (subj, pred), cs in by.items():
            lines.append(f"- {pred} on {subj}: " + " vs ".join(f"{json.dumps(c['value'])} [{c['id']}]" for c in cs))
    if not allc:
        lines.append("No claims yet. Nothing has been established about this place.")
    return "\n".join(lines) + "\n"
