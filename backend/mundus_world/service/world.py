"""Read services behind the World API: places, spaces, rooms, panos, aerial, evidence, stats."""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

from mundus_world.config.settings import Settings
from mundus_world.providers.http import Http
from mundus_world.providers.vexcel import Vexcel
from mundus_world.repo.db import Database
from mundus_world.service import graph
from mundus_world.service.claims import Claims, coverage
from mundus_world.types.errors import ApiError
from mundus_world.types.ids import haversine_m, now_iso, sha256_hex

MARKET_ITEMS = 10
RECORD_FIELDS = {
    "costar_listing": ["listing_kind", "listing_status_label", "listing_type_label", "created_date",
                       "for_lease_summary_total_available_square_feet", "for_lease_summary_space_count",
                       "for_lease_summary_min_divisible_square_feet", "for_lease_summary_max_contiguous_square_feet",
                       "for_sale_summary_asking_price_low", "for_sale_summary_asking_price_high",
                       "for_sale_summary_sale_status_label", "brokerage_company_name"],
    "costar_occupancy": ["tenant_name", "square_feet_occupied", "from_date", "move_in_date", "lease_type_label",
                         "industry_type_label", "lease_deal_commencement_date", "lease_deal_expiration_date",
                         "lease_deal_lease_term", "lease_deal_effective_rate"],
    "costar_sale_entity": ["sale_id", "sold_date", "sold_for_price"],
    "costar_apartment_listing": ["building_name", "min_rent", "max_rent", "num_units_available", "total_num_units",
                                 "min_square_feet", "max_square_feet", "year_built", "property_management_company_name"],
    "costar_res_listing": ["current_price", "original_price", "listing_status_label", "list_date", "off_market_date",
                           "property_beds_max", "property_baths_max", "property_sqft_max", "property_year_built",
                           "property_mls_property_type", "dom", "remarks", "mls_id", "permission_levels_homes"],
}
ORDER = {"costar_listing": ["created_date"], "costar_occupancy": ["from_date", "move_in_date"],
         "costar_sale_entity": ["sold_date"], "costar_apartment_listing": [], "costar_res_listing": ["list_date"]}


class LRU:
    def __init__(self, size: int = 512):
        self.size, self.d = size, OrderedDict()

    def get(self, k: str) -> Any:
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def put(self, k: str, v: Any) -> None:
        self.d[k] = v
        self.d.move_to_end(k)
        while len(self.d) > self.size:
            self.d.popitem(last=False)

    def clear(self) -> None:
        self.d.clear()


class World:
    def __init__(self, settings: Settings, db: Database, claims: Claims, http: Http | None = None):
        self.s, self.db, self.claims = settings, db, claims
        self.cache = LRU()
        self.vx = Vexcel(settings, http or Http(limits={"api.vexcelgroup.com": 2.0}, max_attempts=2))

    def invalidate(self) -> None:
        self.cache.clear()

    # ---- places ------------------------------------------------------------
    def _place(self, place_id: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM place WHERE place_id=?", (place_id,))
        if not r:
            raise ApiError("not_found", f"No place with id {place_id}")
        return dict(r)

    def _records(self, table: str, where: str, params: tuple) -> dict[str, Any]:
        if table not in self.db.tables():
            return {"count": 0, "items": []}
        cols = set(self.db.table_columns(table))
        fields = [f for f in RECORD_FIELDS[table] if f in cols]
        n = self.db.scalar(f"SELECT count(*) FROM {table} WHERE {where}", params)
        keys = [k for k in ORDER[table] if k in cols]
        order = (f"COALESCE({', '.join(keys)}) DESC" if len(keys) > 1 else f"{keys[0]} DESC") if keys else "row_id"
        rows = self.db.q(f"SELECT node_id, evidence_id{''.join(', ' + f for f in fields)} FROM {table} WHERE {where} "
                         f"ORDER BY {order} LIMIT {MARKET_ITEMS}", params)
        return {"count": n, "items": [{"id": r["node_id"], "evidence_id": r["evidence_id"],
                                       "fields": {f: r[f] for f in fields if r[f] is not None}} for r in rows]}

    def get_place(self, place_id: str) -> dict[str, Any]:
        pl = self._place(place_id)
        out: dict[str, Any] = {
            "place_id": place_id, "kind": pl["kind"], "name": pl["name"], "address": pl["address"], "city": pl["city"],
            "lat": pl["lat"], "lon": pl["lon"], "property_type": pl["property_type"], "building_sqft": pl["building_sqft"],
            "year_built": pl["year_built"], "stories": pl["stories"], "is_deep": bool(pl["is_deep"]),
            "evidence_id": pl["evidence_id"], "card_text": pl["card_text"]}
        spaces = [dict(r) for r in self.db.q("SELECT * FROM space WHERE place_id=? ORDER BY name, sid", (place_id,))]
        out["spaces"] = [space_brief(s) for s in spaces]
        out["candidate_spaces"] = []
        if pl["kind"] == "home":
            out["market"] = {"home_listings": self._records("costar_res_listing", "place_id=?", (place_id,))}
            if "costar_listing_features" in self.db.tables():
                feats = self.db.q("SELECT node_id, evidence_id, highlights_text, derived_values_total_bedrooms, "
                                  "derived_values_total_bathrooms, derived_values_home_square_feet, derived_values_year_built "
                                  "FROM costar_listing_features WHERE place_id=?", (place_id,))
                out["market"]["home_features"] = {"count": len(feats), "items": [
                    {"id": r["node_id"], "evidence_id": r["evidence_id"],
                     "fields": {k: r[k] for k in r.keys() if k not in ("node_id", "evidence_id") and r[k] is not None}}
                    for r in feats]}
        else:
            out["market"] = {
                "listings": self._records("costar_listing", "place_id=?", (place_id,)),
                "tenancies": self._records("costar_occupancy", "place_id=?", (place_id,)),
                "sales": self._records("costar_sale_entity", "place_id=?", (place_id,)),
                "apartment_listings": self._records("costar_apartment_listing", "place_id=?", (place_id,)),
                "note": f"Each list shows at most {MARKET_ITEMS} items, newest first; count is the true total. "
                        "Use query_market for the rest.",
            }
        out["aerial"] = self.aerial_facts(place_id, strict=False)
        allc = self.claims.get(place_id, status="all")["claims"]
        out["claims"] = [c for c in allc if c["status"] in ("active", "disputed")]
        out["claim_coverage"] = coverage(allc)
        near = self.db.q("SELECT src, dst, weight FROM edges WHERE rel='near' AND (src=? OR dst=?) ORDER BY weight LIMIT 10",
                         (place_id, place_id))
        out["nearby_places"] = []
        for e in near:
            other = e["dst"] if e["src"] == place_id else e["src"]
            o = self.db.one("SELECT name, property_type, is_deep FROM place WHERE place_id=?", (other,))
            if o:
                out["nearby_places"].append({"place_id": other, "name": o["name"], "property_type": o["property_type"],
                                             "is_deep": bool(o["is_deep"]), "distance_m": e["weight"]})
        if not pl["is_deep"]:
            out["hint"] = "This place is not in the deep set: it has market records only, no rooms, photos or aerial facts."
        return out

    # ---- spaces, rooms, panos ---------------------------------------------
    def _space(self, space_id: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM space WHERE space_id=?", (space_id,))
        if not r:
            raise ApiError("not_found", f"No space with id {space_id}")
        return dict(r)

    def get_space(self, space_id: str) -> dict[str, Any]:
        sp = self._space(space_id)
        out = space_brief(sp)
        out.update(place_id=sp["place_id"], segment=sp["segment"], original_created=sp["original_created"],
                   has_defurnished=bool(sp["has_defurnished"]), has_splat=bool(sp["has_splat"]),
                   drone_photos=sp["drone_photos"], visibility=sp["visibility"], lat=sp["lat"], lon=sp["lon"],
                   summary_evidence_id=sp["summary_evidence_id"], card_text=sp["card_text"])
        if sp["depth"] < 3:
            out["hint"] = "This space is index-only: no rooms, photos or captions were ingested."
            out.update(floors=[], rooms=[], panos=[], room_adjacency=[], floorplans=[])
            return out
        out["floors"] = [dict(r) for r in self.db.q("SELECT floor_id, label, seq FROM floor WHERE space_id=? ORDER BY seq", (space_id,))]
        out["rooms"] = [room_brief(dict(r)) for r in self.db.q("SELECT * FROM room WHERE space_id=? ORDER BY area_m2 DESC", (space_id,))]
        panos = self.db.q("""SELECT p.*, c.caption_json, c.evidence_id AS caption_evidence_id FROM pano p
                             LEFT JOIN pano_caption c ON c.pano_id=p.pano_id AND c.variant='furnished'
                             WHERE p.space_id=? ORDER BY p.is_selected DESC, p.label""", (space_id,))
        out["panos"] = []
        for p in panos:
            cap = json.loads(p["caption_json"]) if p["caption_json"] else None
            out["panos"].append({"pano_id": p["pano_id"], "label": p["label"], "room_id": p["room_id"],
                                 "room_match": p["room_match"], "position": {"x": p["x"], "y": p["y"], "z": p["z"]},
                                 "is_selected": bool(p["is_selected"]), "has_image": bool(p["has_faces"]),
                                 "has_defurnished_image": bool(p["has_defurnished_faces"]),
                                 "caption_summary": (cap or {}).get("summary"), "room_type": (cap or {}).get("room_type"),
                                 "evidence_id": p["caption_evidence_id"]})
        out["room_adjacency"] = [[r["room_a"], r["room_b"], r["shared_length_m"]] for r in self.db.q(
            "SELECT room_a, room_b, shared_length_m FROM room_adjacency WHERE space_id=? AND involves_void=0", (space_id,))]
        out["floorplans"] = [dict(r) | {"url": f"/v1/floorplans/{r['plan_id']}/image"} for r in self.db.q(
            "SELECT plan_id, format, width, height, px_per_m, origin_x, origin_y, evidence_id FROM floorplan "
            "WHERE space_id=? AND format='jpg'", (space_id,))]
        sel = sum(1 for p in out["panos"] if p["is_selected"])
        out["pano_note"] = (f"{sel} of {len(out['panos'])} camera positions have photos and captions "
                            f"(cap of {self.s.max_panos_per_space} per space).")
        return out

    def get_room(self, room_id: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM room WHERE room_id=?", (room_id,))
        if not r:
            raise ApiError("not_found", f"No room with id {room_id}")
        r = dict(r)
        out = room_brief(r)
        out.update(space_id=r["space_id"], floor_id=r["floor_id"], polygon=json.loads(r["polygon_json"] or "[]"),
                   polygon_quality=r["polygon_quality"], place_id=graph.place_of(self.db, room_id))
        out["panos"] = [self._pano_out(dict(p)) for p in self.db.q(
            "SELECT * FROM pano WHERE room_id=? ORDER BY is_selected DESC, label", (room_id,))]
        adj = self.db.q("SELECT * FROM room_adjacency WHERE room_a=? OR room_b=?", (room_id, room_id))
        out["adjacent_rooms"] = []
        for a in adj:
            other = a["room_b"] if a["room_a"] == room_id else a["room_a"]
            o = self.db.one("SELECT label, area_m2 FROM room WHERE room_id=?", (other,))
            out["adjacent_rooms"].append({"room_id": other, "label": o["label"] if o else None,
                                          "shared_length_m": a["shared_length_m"], "involves_void": bool(a["involves_void"])})
        out["adjacency_note"] = "adjacent_rooms share a wall. The data has no doors: sharing a wall does not mean you can walk between them."
        if r["pano_selected"] == 0:
            out["hint"] = "No photo of this room was ingested. Its dimensions are known; its appearance is not."
        return out

    def _pano_row(self, pano_id: str) -> dict[str, Any]:
        p = self.db.one("SELECT * FROM pano WHERE pano_id=?", (pano_id,))
        if not p:
            raise ApiError("not_found", f"No pano with id {pano_id}")
        return dict(p)

    def _pano_out(self, p: dict[str, Any]) -> dict[str, Any]:
        cap = self.db.one("SELECT caption_json, caption_text, evidence_id, model FROM pano_caption WHERE pano_id=? AND variant='furnished'",
                          (p["pano_id"],))
        out = {"pano_id": p["pano_id"], "label": p["label"], "space_id": p["space_id"], "room_id": p["room_id"],
               "room_match": p["room_match"], "position": {"x": p["x"], "y": p["y"], "z": p["z"]},
               "is_selected": bool(p["is_selected"]), "has_image": bool(p["has_faces"]),
               "has_defurnished_image": bool(p["has_defurnished_faces"])}
        if cap:
            out.update(caption=json.loads(cap["caption_json"]), caption_text=cap["caption_text"],
                       evidence_id=cap["evidence_id"], caption_model=cap["model"])
        if p["has_faces"]:
            out["faces"] = [{"face": f["face"], "url": f"/v1/panos/{p['pano_id']}/faces/{f['face']}", "evidence_id": f["evidence_id"]}
                            for f in self.db.q("SELECT face, evidence_id FROM pano_face WHERE pano_id=? AND variant='furn' ORDER BY face",
                                               (p["pano_id"],))]
            out["face_note"] = "Faces 1 to 4 are the four horizontal directions; 0 is up, 5 is down."
        return out

    def get_pano(self, pano_id: str) -> dict[str, Any]:
        return self._pano_out(self._pano_row(pano_id))

    def pano_image(self, pano_id: str, face: int = 1, defurnished: bool = False, size: str = "2k") -> tuple[Path, str, str]:
        p = self._pano_row(pano_id)
        if face not in range(6):
            raise ApiError("invalid_argument", "face must be 0 to 5")
        variant = "defurn" if defurnished else "furn"
        f = self.db.one("SELECT * FROM pano_face WHERE pano_id=? AND variant=? AND face=?", (pano_id, variant, face))
        if not f:
            why = ("not selected within the pano cap" if not p["is_selected"] else
                   "no defurnished view for this space" if defurnished else "image not ingested")
            raise ApiError("not_ingested", f"No {'defurnished ' if defurnished else ''}image for {pano_id}: {why}",
                           {"is_selected": bool(p["is_selected"]), "depth": "positions_only"})
        path = self.s.data_dir / (f["thumb_path"] if size == "thumb" and f["thumb_path"] else f["path"])
        return path, f["evidence_id"], f["content_sha256"]

    def floorplan_image(self, plan_id: str) -> tuple[Path, str]:
        r = self.db.one("SELECT path, evidence_id FROM floorplan WHERE plan_id=?", (plan_id,))
        if not r:
            raise ApiError("not_found", f"No floor plan with id {plan_id}")
        return self.s.data_dir / r["path"], r["evidence_id"]

    def preview_image(self, space_id: str) -> Path:
        sp = self._space(space_id)
        if not sp["preview_path"]:
            raise ApiError("not_ingested", f"No preview image for {space_id}", {"depth": sp["depth"]})
        return self.s.data_dir / sp["preview_path"]

    # ---- aerial ------------------------------------------------------------
    def aerial_facts(self, place_id: str, strict: bool = True) -> dict[str, Any] | None:
        pl = self._place(place_id)
        a = self.db.one("SELECT * FROM aerial_facts WHERE place_id=?", (place_id,))
        if not a:
            if strict:
                raise ApiError("not_ingested", f"No aerial facts for {place_id}", {"is_deep": bool(pl["is_deep"])})
            return None
        imgs = self.db.q("SELECT kind, size_m, width, height, evidence_id FROM aerial_image WHERE place_id=? ORDER BY kind, size_m", (place_id,))
        return {"aerial_id": a["aerial_id"], "place_id": place_id, "evidence_id": a["evidence_id"],
                "match_method": a["match_method"], "match_distance_m": a["match_distance_m"],
                "structure_count": a["structure_count"], "parcel_count": a["parcel_count"],
                "footprint_area_m2": a["footprint_area_m2"], "footprint_wkt": a["footprint_wkt"],
                "parcel_wkt": a["parcel_wkt"], "attributes": json.loads(a["attributes_json"] or "{}"),
                "fetched_at": a["fetched_at"],
                "images": [{"kind": i["kind"], "size_m": i["size_m"], "width": i["width"], "height": i["height"],
                            "url": f"/v1/places/{place_id}/aerial?kind={i['kind']}&size_m={i['size_m']}",
                            "evidence_id": i["evidence_id"]} for i in imgs],
                "note": "match_method parcel_only means Vexcel returned a parcel with no building footprint."
                if a["match_method"] == "parcel_only" else None}

    def aerial_image(self, place_id: str, kind: str = "ortho", size_m: int | None = None) -> tuple[Path, str, str]:
        self._place(place_id)
        rows = self.db.q("SELECT * FROM aerial_image WHERE place_id=? AND kind=? ORDER BY size_m", (place_id, kind))
        if not rows:
            raise ApiError("not_ingested", f"No {kind} image for {place_id}",
                           {"kinds": [r[0] for r in self.db.q("SELECT DISTINCT kind FROM aerial_image WHERE place_id=?", (place_id,))]})
        r = next((x for x in rows if size_m is not None and x["size_m"] == int(size_m)), rows[0])
        return self.s.data_dir / r["path"], r["evidence_id"], r["content_sha256"]

    def aerial_search(self, text: str, lat: float, lon: float, radius_m: int = 1000, limit: int = 10) -> dict[str, Any]:
        if not text or not text.strip():
            raise ApiError("invalid_argument", "text is required")
        radius_m, limit = max(50, min(int(radius_m), 5000)), max(1, min(int(limit), 25))
        key = sha256_hex(f"{text.strip().lower()}|{lat:.3f}|{lon:.3f}|{radius_m}|{limit}")
        hit = self.db.one("SELECT response_json FROM aerial_search_cache WHERE cache_key=?", (key,))
        if hit:
            return json.loads(hit["response_json"]) | {"cache": "hit"}
        try:
            fc = self.vx.semantic_search(text, lat, lon, radius_m, limit)
        except Exception as e:  # noqa: BLE001
            raise ApiError("upstream_unavailable", f"Vexcel search failed: {type(e).__name__}. Do not retry; record this as a gap.") from None
        feats = []
        with self.db.write() as c:
            from mundus_world.service import evidence as ev
            for f in (fc.get("features") or [])[:limit]:
                props = f.get("properties") or {}
                cen = _centroid(f.get("geometry"))
                item = {"score": props.get("score"), "product_type": props.get("source.product-type"),
                        "lat": cen[1] if cen else None, "lon": cen[0] if cen else None,
                        "distance_m": round(haversine_m(lat, lon, cen[1], cen[0]), 1) if cen else None}
                item["evidence_id"] = ev.register(c, "aerial_facts", "vexcel", f"aerial_search:{key[:12]}:{len(feats)}",
                                                  content={"q": text, **item},
                                                  excerpt=f"Aerial semantic search hit for '{text}', score {item['score']}")
                feats.append(item)
            out = {"query": text, "center": {"lat": lat, "lon": lon}, "radius_m": radius_m, "features": feats,
                   "note": "Scores are similarity, not probability. Features carry no label: inspect with an aerial image."}
            c.execute("INSERT OR REPLACE INTO aerial_search_cache(cache_key,request_json,response_json,fetched_at) VALUES(?,?,?,?)",
                      (key, json.dumps({"text": text, "lat": lat, "lon": lon, "radius_m": radius_m}), json.dumps(out), now_iso()))
        return out | {"cache": "miss"}

    # ---- evidence, records, map, stats --------------------------------------
    def get_evidence(self, ev_id: str) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM evidence WHERE evidence_id=?", (ev_id,))
        if not r:
            raise ApiError("not_found", f"No evidence with id {ev_id}")
        return dict(r)

    def get_record(self, node_id: str) -> dict[str, Any]:
        kind = node_id.split(":", 1)[0]
        table = graph.RECORD_TABLE.get(kind)
        if not table or table not in self.db.tables():
            raise ApiError("not_found", f"No record with id {node_id}")
        r = self.db.one(f"SELECT * FROM {table} WHERE node_id=?", (node_id,))
        if not r:
            raise ApiError("not_found", f"No record with id {node_id}")
        d = dict(r)
        raw = d.pop("raw_json", None)
        return {"id": node_id, "table": table, "place_id": d.get("place_id"), "evidence_id": d.get("evidence_id"),
                "fields": {k: v for k, v in d.items() if v is not None}, "record": json.loads(raw) if raw else None}

    def map_spaces(self, bbox: str | None = None, deep_only: bool = False) -> dict[str, Any]:
        sql = ("SELECT s.space_id, s.place_id, s.name, s.space_kind, s.depth, s.lat, s.lon, s.pano_count, "
               "COALESCE(p.is_deep,0) AS is_deep FROM space s LEFT JOIN place p ON p.place_id=s.place_id "
               "WHERE s.is_la=1 AND s.lat IS NOT NULL")
        params: list[Any] = []
        if deep_only:
            sql += " AND p.is_deep=1"
        if bbox:
            try:
                w, s_, e, n = (float(x) for x in bbox.split(","))
            except ValueError:
                raise ApiError("invalid_argument", "bbox must be west,south,east,north") from None
            sql += " AND s.lon BETWEEN ? AND ? AND s.lat BETWEEN ? AND ?"
            params += [w, e, s_, n]
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                  "properties": {"space_id": r["space_id"], "place_id": r["place_id"], "name": r["name"],
                                 "space_kind": r["space_kind"], "depth": r["depth"], "is_deep": bool(r["is_deep"]),
                                 "pano_count": r["pano_count"]}} for r in self.db.q(sql, params)]
        return {"type": "FeatureCollection", "features": feats}

    def map_places(self, deep_only: bool = True) -> dict[str, Any]:
        rows = self.db.q("SELECT place_id, name, property_type, lat, lon, is_deep FROM place WHERE lat IS NOT NULL"
                         + (" AND is_deep=1" if deep_only else ""))
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
             "properties": {"place_id": r["place_id"], "name": r["name"], "property_type": r["property_type"],
                            "is_deep": bool(r["is_deep"])}} for r in rows]}

    def stats(self, run_id: str | None = None) -> dict[str, Any]:
        counts = {t: self.db.scalar(f"SELECT count(*) FROM {t}") for t in
                  ("place", "space", "room", "pano", "pano_caption", "pano_face", "aerial_facts", "evidence", "claim",
                   "edges", "embedding")}
        counts["deep_places"] = self.db.scalar("SELECT count(*) FROM place WHERE is_deep=1")
        counts["selected_panos"] = self.db.scalar("SELECT count(*) FROM pano WHERE is_selected=1")
        where, params = ("WHERE run_id=?", (run_id,)) if run_id else ("", ())
        ops = [dict(r) for r in self.db.q(
            f"SELECT op, count(*) AS calls, round(avg(ms),1) AS avg_ms, round(max(ms),1) AS max_ms, sum(bytes_out) AS bytes_out "
            f"FROM api_log {where} GROUP BY op ORDER BY calls DESC", params)]
        claims = [dict(r) for r in self.db.q(
            "SELECT place_id, count(*) AS claims, sum(status='active') AS active, sum(read_count) AS reads FROM claim "
            + ("WHERE run_id=? " if run_id else "") + "GROUP BY place_id", params)]
        usage = [dict(r) for r in self.db.q(
            "SELECT purpose, model, count(*) AS calls, sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, "
            "sum(tokens_thought) AS tokens_thought, max(estimated) AS estimated, round(avg(ms),1) AS avg_ms "
            f"FROM model_usage {where} GROUP BY purpose, model ORDER BY purpose, model", params)]
        return {"counts": counts, "run_id": run_id, "api_calls": ops,
                "model_usage": usage,
                "model_tokens_total": {k: sum(u[k] or 0 for u in usage) for k in ("tokens_in", "tokens_out", "tokens_thought")}, "total_calls": sum(o["calls"] for o in ops),
                "claims_by_place": claims,
                "expensive_calls": sum(o["calls"] for o in ops if o["op"] in ("pano_image", "aerial_image", "aerial_semantic_search", "query_market"))}

    def log(self, op: str, ms: float, caller: str | None, run_id: str | None, status: int, bytes_out: int = 0,
            cache: str | None = None, place_id: str | None = None) -> None:
        try:
            self.db.execute("INSERT INTO api_log(ts,op,caller,run_id,ms,cache,place_id,bytes_out,status) VALUES(?,?,?,?,?,?,?,?,?)",
                            (now_iso(), op, caller, run_id, round(ms, 2), cache, place_id, bytes_out, status))
        except Exception:  # noqa: BLE001 - logging must never break a request
            pass


def space_brief(s: dict[str, Any]) -> dict[str, Any]:
    return {"space_id": s["space_id"], "name": s["name"], "space_kind": s["space_kind"], "pano_count": s["pano_count"],
            "room_count": s["room_count"], "floor_count": s["floor_count"], "depth": s["depth"],
            "ai_summary": s["ai_summary"], "has_defurnished": bool(s["has_defurnished"]),
            "preview_url": f"/v1/spaces/{s['space_id']}/preview" if s["preview_path"] else None,
            "showcase_url": s["showcase_url"], "evidence_id": s["summary_evidence_id"] or s["evidence_id"]}


def room_brief(r: dict[str, Any]) -> dict[str, Any]:
    return {"room_id": r["room_id"], "label": r["label"], "label_confidence": r["label_confidence"],
            "area_m2": r["area_m2"], "area_sqft": round(r["area_m2"] * 10.7639, 1) if r["area_m2"] else None,
            "width_m": r["width_m"], "depth_m": r["depth_m"], "height_m": r["height_m"],
            "pano_total": r["pano_total"], "pano_selected": r["pano_selected"], "evidence_id": r["evidence_id"]}


def _centroid(geom: dict[str, Any] | None) -> tuple[float, float] | None:
    if not geom:
        return None
    try:
        from shapely.geometry import shape
        c = shape(geom).centroid
        return (float(c.x), float(c.y))
    except Exception:  # noqa: BLE001
        return None
