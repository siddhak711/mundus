"""The World API operations, defined once. REST routes and MCP tools both call these."""
from __future__ import annotations

from typing import Any

from mundus_world.runtime.container import Container
from mundus_world.service import graph, market
from mundus_world.service.claims import render_card
from mundus_world.types.errors import ApiError

MAX_TEXT = 6000


class Ops:
    def __init__(self, c: Container):
        self.c = c

    def search_places(self, query: str | None = None, near: dict | None = None, filters: dict | None = None,
                      limit: int = 10, cursor: str | None = None) -> dict[str, Any]:
        return self.c.search.places(query, near, filters, limit, cursor)

    def get_place(self, place_id: str) -> dict[str, Any]:
        return self.c.world.get_place(place_id)

    def get_space(self, space_id: str) -> dict[str, Any]:
        return self.c.world.get_space(space_id)

    def get_room(self, room_id: str) -> dict[str, Any]:
        return self.c.world.get_room(room_id)

    def get_pano(self, pano_id: str) -> dict[str, Any]:
        return self.c.world.get_pano(pano_id)

    def search_interiors(self, text: str, place_id: str | None = None, near: dict | None = None,
                         kinds: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        return self.c.search.interiors(text, place_id, near, kinds, limit)

    def get_aerial_facts(self, place_id: str) -> dict[str, Any]:
        return self.c.world.aerial_facts(place_id)

    def aerial_semantic_search(self, text: str, near: dict | None = None, radius_m: int = 1000, limit: int = 10,
                               lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
        if near:
            lat, lon = near.get("lat", lat), near.get("lon", lon)
            radius_m = near.get("radius_m", radius_m)
        if lat is None or lon is None:
            raise ApiError("invalid_argument", "aerial_semantic_search needs a point: near={lat, lon}")
        return self.c.world.aerial_search(text, float(lat), float(lon), radius_m, limit)

    def describe_market(self, table: str | None = None) -> dict[str, Any]:
        return market.describe_compact(self.c.db, table)

    def query_market(self, sql: str, limit: int = 50) -> dict[str, Any]:
        return market.query(self.c.db, sql, limit)

    def get_neighbors(self, node_id: str, rel: str | None = None, depth: int = 1, limit: int = 50) -> dict[str, Any]:
        return graph.neighbors(self.c.db, node_id, rel, depth, limit)

    def get_claims(self, subject_id: str, predicate_prefix: str | None = None, status: str = "active") -> dict[str, Any]:
        return self.c.claims.get(subject_id, predicate_prefix, status)

    def put_claim(self, subject_id: str, predicate: str, value: Any, statement: str, evidence_ids: list[str] | None = None,
                  confidence: float = 0.5, unit: str | None = None, derived_from: list[str] | None = None,
                  created_by: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        out = self.c.claims.put(subject_id, predicate, value, statement, evidence_ids, confidence, unit, derived_from,
                                created_by, run_id)
        self.c.world.invalidate()
        return out

    def invalidate_claim(self, claim_id: str, reason: str, superseded_by: str | None = None) -> dict[str, Any]:
        out = self.c.claims.invalidate(claim_id, reason, superseded_by)
        self.c.world.invalidate()
        return out

    def get_evidence(self, ev_id: str) -> dict[str, Any]:
        return self.c.world.get_evidence(ev_id)

    def card(self, place_id: str) -> str:
        return render_card(self.c.db, self.c.claims, place_id)
