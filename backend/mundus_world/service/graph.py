"""Knowledge graph: typed edges built by code from join keys and geometry, and neighbour walks."""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from mundus_world.repo.db import Database
from mundus_world.types.ctx import CLAIM_SCOPE
from mundus_world.types.errors import ApiError
from mundus_world.types.ids import node_kind, now_iso

RECORD_TABLE = {"listing": "costar_listing", "tenancy": "costar_occupancy", "sale": "costar_sale",
                "company": "costar_company", "aptlisting": "costar_apartment_listing",
                "homelisting": "costar_res_listing", "homefeatures": "costar_listing_features",
                "property": "costar_property"}


def build_edges(db: Database) -> dict[str, int]:
    """Rebuild every edge that comes from a join or from geometry. Agent and rule edges are left alone."""
    now = now_iso()
    counts: dict[str, int] = {}

    def put(c, rows: list[tuple], rel: str, source: str) -> None:
        c.executemany("INSERT OR REPLACE INTO edges(src,rel,dst,source,weight,created_at) VALUES(?,?,?,?,?,?)",
                      [(s, rel, d, source, w, now) for s, d, w in rows])
        counts[rel] = counts.get(rel, 0) + len(rows)

    tables = set(db.tables())
    with db.write() as c:
        c.execute("DELETE FROM edges WHERE source IN ('join','geometry')")
        put(c, [(r["space_id"], r["place_id"], None) for r in c.execute(
            "SELECT space_id, place_id FROM space WHERE place_id IS NOT NULL")], "part_of", "join")
        put(c, [(r["room_id"], r["space_id"], None) for r in c.execute("SELECT room_id, space_id FROM room")], "part_of", "join")
        put(c, [(r["pano_id"], r["room_id"] or r["space_id"], None) for r in c.execute(
            "SELECT pano_id, room_id, space_id FROM pano")], "part_of", "join")
        for table, rel in (("costar_listing", "has_listing"), ("costar_occupancy", "has_tenancy"),
                           ("costar_apartment_listing", "has_apartment_listing"), ("costar_res_listing", "has_home_listing")):
            if table in tables:
                put(c, [(r["place_id"], r["node_id"], None) for r in c.execute(
                    f"SELECT t.place_id, t.node_id FROM {table} t JOIN place p ON p.place_id=t.place_id")], rel, "join")
        if "costar_sale_entity" in tables:
            put(c, [(r["place_id"], r["node_id"], None) for r in c.execute(
                "SELECT place_id, node_id FROM costar_sale_entity WHERE place_id IS NOT NULL")], "has_sale", "join")
        if "costar_occupancy" in tables:
            put(c, [(r["node_id"], f"company:{r['tenant_location_id']}", None) for r in c.execute(
                "SELECT node_id, tenant_location_id FROM costar_occupancy WHERE place_id IS NOT NULL AND tenant_location_id IS NOT NULL")],
                "tenant_is", "join")
        put(c, [(r["room_a"], r["room_b"], r["shared_length_m"]) for r in c.execute(
            "SELECT room_a, room_b, shared_length_m FROM room_adjacency")], "adjacent_to", "geometry")
        places = c.execute("SELECT place_id, lat, lon FROM place WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
        if len(places) > 1:
            ids = [p["place_id"] for p in places]
            lat = np.radians(np.array([p["lat"] for p in places]))
            lon = np.radians(np.array([p["lon"] for p in places]))
            near = []
            for i in range(len(ids)):
                dlat, dlon = lat[i + 1:] - lat[i], lon[i + 1:] - lon[i]
                a = np.sin(dlat / 2) ** 2 + np.cos(lat[i]) * np.cos(lat[i + 1:]) * np.sin(dlon / 2) ** 2
                d = 2 * 6371000.0 * np.arcsin(np.sqrt(a))
                for j in np.nonzero(d <= 250.0)[0]:
                    near.append((ids[i], ids[i + 1 + int(j)], round(float(d[j]), 1)))
            put(c, near, "near", "geometry")
    return counts


def node_exists(db: Database, node_id: str) -> bool:
    return node_summary(db, node_id, strict=True) is not None


def node_summary(db: Database, node_id: str, strict: bool = False) -> dict[str, Any] | None:
    kind = node_kind(node_id)
    r = None
    if kind == "place":
        r = db.one("SELECT place_id AS id, name, property_type, address, is_deep FROM place WHERE place_id=?", (node_id,))
    elif kind == "space":
        r = db.one("SELECT space_id AS id, name, space_kind, place_id, depth FROM space WHERE space_id=?", (node_id,))
    elif kind == "room":
        r = db.one("SELECT room_id AS id, label AS name, area_m2, space_id FROM room WHERE room_id=?", (node_id,))
    elif kind == "pano":
        r = db.one("SELECT pano_id AS id, label AS name, room_id, space_id, is_selected FROM pano WHERE pano_id=?", (node_id,))
    elif kind == "claim":
        r = db.one("SELECT claim_id AS id, statement AS name, predicate, status FROM claim WHERE claim_id=?", (node_id,))
    elif kind == "ev":
        r = db.one("SELECT evidence_id AS id, type, excerpt AS name FROM evidence WHERE evidence_id=?", (node_id,))
    elif kind in RECORD_TABLE:
        table = RECORD_TABLE[kind]
        if table in db.tables():
            r = db.one(f"SELECT t.node_id AS id, t.place_id, t.evidence_id, e.excerpt AS name FROM {table} t "
                       "LEFT JOIN evidence e ON e.evidence_id=t.evidence_id WHERE t.node_id=?", (node_id,))
    if r is None:
        return None if strict else {"id": node_id, "kind": kind}
    d = {k: v for k, v in dict(r).items() if v is not None}
    d["kind"] = kind
    return d


def place_of(db: Database, node_id: str) -> str | None:
    """The place a node belongs to (None when it belongs to none, for example a company)."""
    kind = node_kind(node_id)
    if kind == "place":
        return node_id
    if kind == "space":
        return db.scalar("SELECT place_id FROM space WHERE space_id=?", (node_id,))
    if kind == "room":
        return db.scalar("SELECT s.place_id FROM room r JOIN space s ON s.space_id=r.space_id WHERE r.room_id=?", (node_id,))
    if kind == "pano":
        return db.scalar("SELECT s.place_id FROM pano p JOIN space s ON s.space_id=p.space_id WHERE p.pano_id=?", (node_id,))
    if kind == "claim":
        return db.scalar("SELECT place_id FROM claim WHERE claim_id=?", (node_id,))
    if kind in RECORD_TABLE and RECORD_TABLE[kind] in db.tables():
        return db.scalar(f"SELECT place_id FROM {RECORD_TABLE[kind]} WHERE node_id=?", (node_id,))
    return None


def neighbors(db: Database, node_id: str, rel: str | None = None, depth: int = 1, limit: int = 50) -> dict[str, Any]:
    if not node_exists(db, node_id):
        raise ApiError("not_found", f"No node with id {node_id}")
    depth = max(1, min(int(depth), 2))
    limit = max(1, min(int(limit), 200))
    seen = {node_id}
    frontier = [node_id]
    edges: list[dict[str, Any]] = []
    truncated = False
    for _ in range(depth):
        nxt: list[str] = []
        for n in frontier:
            sql = "SELECT src, rel, dst, source, weight FROM edges WHERE (src=? OR dst=?)"
            params: list[Any] = [n, n]
            if rel:
                sql += " AND rel=?"
                params.append(rel)
            sql += " ORDER BY CASE rel WHEN 'near' THEN weight ELSE 0 END, rel, src, dst LIMIT ?"
            params.append(limit + 1)
            for r in db.q(sql, params):
                if len(edges) >= limit:
                    truncated = True
                    break
                e = dict(r)
                key = (e["src"], e["rel"], e["dst"])
                if any((x["src"], x["rel"], x["dst"]) == key for x in edges):
                    continue
                other = e["dst"] if e["src"] == n else e["src"]
                if node_kind(other) == "claim" and db.scalar("SELECT scope FROM claim WHERE claim_id=?", (other,)) != CLAIM_SCOPE.get():
                    continue              # another run's private memory
                edges.append({k: v for k, v in e.items() if v is not None})
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    nodes = {n: node_summary(db, n) for n in seen}
    by_rel: dict[str, int] = {}
    for e in edges:
        by_rel[e["rel"]] = by_rel.get(e["rel"], 0) + 1
    total = db.scalar("SELECT count(*) FROM edges WHERE src=? OR dst=?", (node_id, node_id))
    return {"node": nodes[node_id], "edges": edges, "nodes": nodes, "counts_by_rel": by_rel,
            "total_edges_at_node": total, "truncated": truncated}


def edge_types_report(db: Database) -> dict[str, int]:
    return {r[0] or "null": r[1] for r in db.q("SELECT type, count(*) FROM wall_edge GROUP BY 1")}


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)
