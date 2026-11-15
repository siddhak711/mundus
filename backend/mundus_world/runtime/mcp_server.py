"""MCP server: the World API as tools for the deepagents harness. Descriptions are written for a model."""
from __future__ import annotations

import contextvars
import json
import time
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer

from mundus_world.runtime.container import Container
from mundus_world.runtime.tools import Ops
from mundus_world.types.errors import ApiError

MAX_CHARS = 24000


def _dump(obj: Any) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS] + '... [truncated: result too large. Narrow the request or use a more specific tool.]'
    return s


def agent_place(d: dict[str, Any]) -> dict[str, Any]:
    """get_place for an agent: the claims are on the card already, and the space list gets a count."""
    out = {k: v for k, v in d.items() if k not in ("claims", "claim_coverage")}
    spaces = d.get("spaces") or []
    out["spaces"] = [{k: s.get(k) for k in ("space_id", "name", "space_kind", "room_count", "pano_count", "has_defurnished",
                                             "evidence_id")} for s in spaces]
    out["space_count"] = len(spaces)
    out["space_note"] = "Each space is one Matterport scan. Cite the place's evidence_id for the number of scans."
    return out


def agent_space(d: dict[str, Any]) -> dict[str, Any]:
    """get_space for an agent: every room on one line with its photo count, and only the positions that have photos.
    The full record is far larger than a model should read, and cutting it mid-list hid rooms from the agent."""
    rooms = d.get("rooms") or []
    real = [r for r in rooms if (r.get("label") or "").lower() != "void"]
    out = {k: d.get(k) for k in ("space_id", "name", "space_kind", "place_id", "evidence_id", "ai_summary", "room_count",
                                 "pano_count", "floor_count", "has_defurnished", "original_created", "hint") if d.get(k) is not None}
    out["room_counts"] = {"rooms_excluding_void": len(real), "void_rooms": len(rooms) - len(real),
                          "rooms_with_photo": sum(1 for r in real if (r.get("pano_selected") or 0) > 0),
                          "rooms_without_photo": sum(1 for r in real if (r.get("pano_selected") or 0) == 0)}
    out["rooms"] = [{"room_id": r["room_id"], "label": r.get("label"),
                     "area_m2": round(r["area_m2"], 1) if r.get("area_m2") else None, "area_sqft": r.get("area_sqft"),
                     "width_m": round(r["width_m"], 2) if r.get("width_m") else None,
                     "depth_m": round(r["depth_m"], 2) if r.get("depth_m") else None,
                     "height_m": round(r["height_m"], 2) if r.get("height_m") else None,
                     "photos": r.get("pano_selected") or 0, "evidence_id": r.get("evidence_id")} for r in rooms]
    shown = [p for p in d.get("panos") or [] if p.get("is_selected") and p.get("has_image")]
    out["photo_positions"] = [{"pano_id": p["pano_id"], "label": p.get("label"), "room_id": p.get("room_id"),
                               "room_type": p.get("room_type"), "caption_summary": (p.get("caption_summary") or "")[:220],
                               "has_defurnished_image": p.get("has_defurnished_image"), "evidence_id": p.get("evidence_id")}
                              for p in shown]
    out["note"] = (f"{len(shown)} camera positions have photos and captions. photos is the number of photographed positions "
                   "in a room: 0 means its size and label are known and its appearance is not. Use get_room for the full "
                   "captions of one room. Rooms that share a wall are listed by get_room.")
    return out


def agent_room(d: dict[str, Any], max_panos: int = 8, max_caption: int = 1800) -> dict[str, Any]:
    """get_room for an agent: one caption text per photographed position, without the duplicate structured caption,
    the face list or the floor polygon."""
    out = {k: v for k, v in d.items() if k not in ("panos", "polygon", "polygon_quality", "label_confidence")}
    shown = [p for p in d.get("panos") or [] if p.get("is_selected") and p.get("caption_text")]
    out["photo_positions"] = [{"pano_id": p["pano_id"], "label": p.get("label"), "evidence_id": p.get("evidence_id"),
                               "has_defurnished_image": p.get("has_defurnished_image"),
                               "caption": p["caption_text"][:max_caption] + (" ..." if len(p["caption_text"]) > max_caption else "")}
                              for p in shown[:max_panos]]
    if len(shown) > max_panos:
        out["more_positions"] = [p["pano_id"] for p in shown[max_panos:]]
        out["more_note"] = "More photographed positions exist in this room: use search_interiors or look_at_pano for them."
    out["caption_note"] = ("Captions were written by a model from the photos and can contain mistakes. For a question about "
                           "what a room contains or looks like, check the photo with look_at_pano before stating details.")
    return out


def build_mcp(c: Container, ops: Ops, run_id: contextvars.ContextVar, caller: contextvars.ContextVar) -> MCPServer:
    mcp = MCPServer("mundus-world", instructions=(
        "World context for 15 places in Los Angeles: CoStar market records, Matterport interiors (rooms, photos, captions), "
        "Vexcel aerial photos, and a shared memory of evidence-linked claims. Every item returned carries an evidence_id. "
        "Cite only evidence ids you received. If the data does not contain something, say so: do not invent it."))

    async def run(op: str, fn, *args, **kw) -> str:
        t0 = time.perf_counter()
        rid, who = run_id.get(), caller.get()
        status = 200
        try:
            return _dump(await anyio.to_thread.run_sync(lambda: fn(*args, **kw)))
        except ApiError as e:
            status = e.status
            return _dump(e.body())
        finally:
            c.world.log(op, (time.perf_counter() - t0) * 1000, who or "mcp", rid, status)

    @mcp.tool(description="Find places in Los Angeles by name, address or location. Returns place summaries with ids. "
                          "Use when you need candidates. Only places with is_deep true have interiors, captions and aerial photos.")
    async def search_places(query: str | None = None, near: dict | None = None, filters: dict | None = None,
                            limit: int = 10) -> str:
        return await run("search_places", ops.search_places, query, near, filters, limit)

    @mcp.tool(description="Record for one place: building basics, its scans (spaces) with a count, listings, tenancies, sales "
                          "and aerial photos. Each item includes an evidence_id you must cite. "
                          "Market lists show the 10 newest items with the true count; use query_market for more.")
    async def get_place(place_id: str) -> str:
        return await run("get_place", lambda p: agent_place(ops.get_place(p)), place_id)

    @mcp.tool(description="One Matterport scan (a space): every room with its size and number of photos, counts of rooms "
                          "with and without photos, and the photographed camera positions with caption summaries. Takes "
                          "a space id (space:...), not a place id. Each item includes an evidence_id.")
    async def get_space(space_id: str) -> str:
        return await run("get_space", lambda sid: agent_space(ops.get_space(sid)), space_id)

    @mcp.tool(description="One room: label, dimensions in metres, the caption of each photographed camera position in "
                          "it, and which rooms share a wall with it. Sharing a wall does not mean there is a door: the "
                          "data has no doors. A room with pano_selected 0 has no photo, so its appearance is unknown.")
    async def get_room(room_id: str) -> str:
        return await run("get_room", lambda rid: agent_room(ops.get_room(rid)), room_id)

    @mcp.tool(description="Search interiors by what they look like or contain, in plain words (for example 'gym with free "
                          "weights and mirrors'). Returns ranked camera positions, rooms and spaces. Pass place_id to "
                          "stay inside one place.")
    async def search_interiors(text: str, place_id: str | None = None, near: dict | None = None, limit: int = 10) -> str:
        return await run("search_interiors", ops.search_interiors, text, place_id, near, None, limit)

    @mcp.tool(description="Search aerial imagery around a point by description (for example 'surface parking lot'). "
                          "near is {lat, lon}. Returns features with similarity scores and locations. Calls a live "
                          "service and can take a few seconds.")
    async def aerial_semantic_search(text: str, near: dict, radius_m: int = 1000, limit: int = 10) -> str:
        return await run("aerial_semantic_search", ops.aerial_semantic_search, text, near, radius_m, limit)

    @mcp.tool(description="List the market data tables and their columns. Call once before writing SQL. Pass table to get "
                          "sample values for one table.")
    async def describe_market(table: str | None = None) -> str:
        return await run("describe_market", ops.describe_market, table)

    @mcp.tool(description="Run one read-only SELECT (SQLite dialect) over the CoStar tables. Max 200 rows. Every table "
                          "has place_id and evidence_id columns: include evidence_id in your SELECT so you can cite rows. "
                          "Use for counts, comparisons and anything across many rows.")
    async def query_market(sql: str, limit: int = 50) -> str:
        return await run("query_market", ops.query_market, sql, limit)

    @mcp.tool(description="Walk the knowledge graph from any node (place, space, room, pano, listing, tenancy, sale, "
                          "company, claim). Returns edges and neighbour summaries. rel filters by edge type: part_of, "
                          "has_listing, has_tenancy, has_sale, tenant_is, near, adjacent_to, about, "
                          "supported_by, derived_from, supersedes, contradicts. depth is 1 or 2.")
    async def get_neighbors(node_id: str, rel: str | None = None, depth: int = 1, limit: int = 50) -> str:
        return await run("get_neighbors", ops.get_neighbors, node_id, rel, depth, limit)

    @mcp.tool(description="Stored facts about a node, with evidence ids, confidence and age. Passing a place id returns "
                          "claims on the place and on its spaces, rooms and panos. Read these before doing new work.")
    async def get_claims(subject_id: str, predicate_prefix: str | None = None, status: str = "active") -> str:
        return await run("get_claims", ops.get_claims, subject_id, predicate_prefix, status)

    @mcp.tool(description="Save one fact to shared memory. Requires at least one evidence_id you received from a tool, or "
                          "derived_from claim ids. predicate must come from the claims vocabulary (or start with note. "
                          "or synthesis.). Returns the claim id and the outcome: created, merged with an identical "
                          "claim, superseded_old, rejected_lower_rank, or disputed.")
    async def put_claim(subject_id: str, predicate: str, value: Any, statement: str, evidence_ids: list[str] | None = None,
                        confidence: float = 0.7, unit: str | None = None, derived_from: list[str] | None = None,
                        created_by: str | None = None) -> str:
        return await run("put_claim", ops.put_claim, subject_id, predicate, value, statement, evidence_ids, confidence,
                         unit, derived_from, created_by or caller.get(), run_id.get())

    @mcp.tool(description="The source behind a claim or a fact: record excerpt or image reference.")
    async def get_evidence(ev_id: str) -> str:
        return await run("get_evidence", ops.get_evidence, ev_id)

    return mcp
