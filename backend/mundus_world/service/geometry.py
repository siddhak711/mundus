"""Room polygons, pano-to-room matching, room adjacency and the pano cap. Pure functions."""
from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import MultiPoint, Point, Polygon

Pt = tuple[float, float]


def build_polygon(edge_ids: list[str], edges: dict[str, tuple[str, str]], vpos: dict[str, Pt]) -> tuple[list[Pt], str]:
    """Chain unordered wall edges into a closed loop. Falls back to a convex hull."""
    segs = [edges[e] for e in edge_ids if e in edges and edges[e][0] in vpos and edges[e][1] in vpos]
    if len(segs) < 3:
        pts = list({v for s in segs for v in s})
        return ([vpos[v] for v in pts], "none")
    adj: dict[str, list[str]] = {}
    for a, b in segs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if all(len(n) == 2 for n in adj.values()):
        start = next(iter(adj))
        loop, prev, cur = [start], None, start
        for _ in range(len(adj)):
            nxt = [n for n in adj[cur] if n != prev] or adj[cur]
            prev, cur = cur, nxt[0]
            if cur == start:
                break
            loop.append(cur)
        if len(loop) == len(adj):
            return ([vpos[v] for v in loop], "loop")
    try:  # rooms with inner loops (columns, shafts): take the outline of everything the edges enclose
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union

        polys = list(polygonize([LineString([vpos[a], vpos[b]]) for a, b in segs]))
        if polys:
            u = unary_union(polys)
            if u.geom_type == "MultiPolygon":
                u = max(u.geoms, key=lambda g: g.area)
            if u.geom_type == "Polygon" and u.area > 0:
                return ([(float(x), float(y)) for x, y in list(u.exterior.coords)[:-1]], "loop")
    except Exception:  # noqa: BLE001 - fall through to the hull
        pass
    hull = MultiPoint([vpos[v] for v in adj]).convex_hull
    if hull.geom_type == "Polygon":
        return ([(float(x), float(y)) for x, y in list(hull.exterior.coords)[:-1]], "hull")
    return ([vpos[v] for v in adj], "none")


def polygon_centroid(pts: list[Pt]) -> Pt | None:
    if len(pts) < 3:
        if pts:
            return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty:
        return None
    c = poly.centroid
    return (float(c.x), float(c.y))


def match_pano_to_room(x: float, y: float, rooms: list[dict[str, Any]]) -> tuple[str | None, str]:
    """rooms: [{room_id, polygon, centroid, is_void}]. Returns (room_id, inside|nearest|none)."""
    p = Point(x, y)
    hits = []
    for r in rooms:
        if len(r["polygon"]) >= 3:
            poly = Polygon(r["polygon"])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if not poly.is_empty and poly.covers(p):
                hits.append((r.get("is_void", False), poly.area, r["room_id"]))
    if hits:
        hits.sort()
        return hits[0][2], "inside"
    best, bd = None, 3.0
    for r in rooms:
        c = r.get("centroid")
        if c and not r.get("is_void"):
            d = math.dist((x, y), c)
            if d < bd:
                best, bd = r["room_id"], d
    return (best, "nearest") if best else (None, "none")


def adjacency(rooms: list[dict[str, Any]], edges: dict[str, tuple[str, str]], vpos: dict[str, Pt],
              edge_types: dict[str, str]) -> list[dict[str, Any]]:
    """rooms: [{room_id, floor_id, edge_ids, is_void}]. Two rooms are adjacent when they share a wall edge id."""
    out = []
    rs = sorted(rooms, key=lambda r: r["room_id"])
    for i, a in enumerate(rs):
        ea = set(a["edge_ids"])
        for b in rs[i + 1:]:
            if a.get("floor_id") != b.get("floor_id"):
                continue
            shared = sorted(ea & set(b["edge_ids"]))
            if not shared:
                continue
            length = sum(math.dist(vpos[edges[e][0]], vpos[edges[e][1]]) for e in shared
                         if e in edges and edges[e][0] in vpos and edges[e][1] in vpos)
            out.append({"room_a": a["room_id"], "room_b": b["room_id"], "shared_edge_ids": shared,
                        "shared_length_m": round(length, 2),
                        "edge_types": sorted({edge_types.get(e) or "unknown" for e in shared}),
                        "involves_void": int(bool(a.get("is_void") or b.get("is_void")))})
    return out


def select_panos(panos: list[dict[str, Any]], rooms: list[dict[str, Any]], cap: int) -> list[str]:
    """Deterministic choice of at most `cap` panos. panos: [{pano_id, x, y, floor_key, room_id}],
    rooms: [{room_id, area, centroid}]. Rule: all if within cap; else one per room (largest first, nearest the
    centroid), then farthest-point sampling. Ties break on pano id."""
    ordered = sorted(panos, key=lambda p: p["pano_id"])
    if len(ordered) <= cap:
        return [p["pano_id"] for p in ordered]
    chosen: list[dict[str, Any]] = []
    taken: set[str] = set()
    for r in sorted(rooms, key=lambda r: (-(r.get("area") or 0.0), r["room_id"])):
        if len(chosen) >= cap:
            break
        cands = [p for p in ordered if p.get("room_id") == r["room_id"] and p["pano_id"] not in taken]
        if not cands:
            continue
        c = r.get("centroid")
        best = min(cands, key=lambda p: (math.dist((p["x"], p["y"]), c) if c else 0.0, p["pano_id"]))
        chosen.append(best)
        taken.add(best["pano_id"])

    def pos(p: dict[str, Any]) -> tuple[float, float, float]:
        return (p["x"], p["y"], 1000.0 * (p.get("floor_key") or 0))

    if not chosen:
        chosen.append(ordered[0])
        taken.add(ordered[0]["pano_id"])
    while len(chosen) < cap:
        rest = [p for p in ordered if p["pano_id"] not in taken]
        if not rest:
            break
        nxt = max(rest, key=lambda p: (min(math.dist(pos(p), pos(c)) for c in chosen), [-ord(ch) for ch in p["pano_id"]]))
        chosen.append(nxt)
        taken.add(nxt["pano_id"])
    return sorted(p["pano_id"] for p in chosen)


_KIND_RULES: list[tuple[str, str]] = [
    ("unit", r"\d\s*(br|bd|bed)|\bstudio\b|\d(\.\d)?\s*ba\b|\bplan [a-z0-9]+\b|live/work|townhouse|\bunit\b|\bbedroom\b|penthouse|\bloft\b"),
    ("office", r"suite|office|cowork|conference|executive"),
    ("retail", r"retail|store|shop|restaurant|vacant"),
    ("industrial", r"warehouse|industrial|dock"),
    ("amenity", r"fitness|gym|pool|spa\b|lounge|club|roof|deck|theater|screening|game|yoga|bbq|barbecue|grill|pet|business center|courtyard|sundeck|terrace|garden|cafe"),
    ("common", r"lobby|entrance|entry|hall|mail|laundry|package|parking|elevator|foyer|leasing|exterior|common area"),
]


def space_kind(name: str, segment: str) -> str:
    if segment == "residential":
        return "home"
    n = (name or "").lower()
    for kind, pat in _KIND_RULES:
        if re.search(pat, n):
            return kind
    return "other"
