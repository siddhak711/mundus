"""Ingestion steps 1 to 3: models index, CoStar kit, selection of the deep places."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from typing import Any

from mundus_world.config.settings import BASEMAP_URL, INDEX_URL, LA_MARKET_ID, Settings
from mundus_world.providers import kit as kitp
from mundus_world.providers.http import Http
from mundus_world.repo.db import Database
from mundus_world.service import evidence as ev
from mundus_world.service.geometry import space_kind
from mundus_world.types.ids import (
    canonical_json,
    haversine_m,
    place_id_for_home,
    place_id_for_property,
    sha256_hex,
    snake,
    space_id,
)

log = logging.getLogger("mundus.ingest")

# Never extracted and never stored: people's contact details and bulky media lists.
EXCLUDED_KEYS = {
    "contacts", "listingContacts", "propertyContacts", "agents", "offices", "locationPhone", "locationPhoneCountryCode",
    "siteEmailAddress", "sitePhoneNumber", "sitePhoneCountryCode", "brandProfiles", "attachments", "media", "history",
    "primaryPhoto", "openHouses", "emailAddress", "email", "phone", "compOwners",
}
TABLES = {
    "commercial-property": "costar_property",
    "commercial-listing-summary": "costar_listing",
    "location-occupancy": "costar_occupancy",
    "company-detail": "costar_company",
    "commercial-sale-comp": "costar_sale",
    "apartment-listing": "costar_apartment_listing",
    "residential-listings": "costar_res_listing",
    "residential-listing-features": "costar_listing_features",
}
NODE_PREFIX = {
    "costar_property": "property", "costar_listing": "listing", "costar_occupancy": "tenancy",
    "costar_company": "company", "costar_sale": "sale", "costar_apartment_listing": "aptlisting",
    "costar_res_listing": "homelisting", "costar_listing_features": "homefeatures",
}
FIXED = ["row_id", "node_id", "property_id", "place_id", "evidence_id", "raw_json"]


def _f(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def strip_private(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: strip_private(v) for k, v in o.items() if k not in EXCLUDED_KEYS}
    if isinstance(o, list):
        return [strip_private(v) for v in o]
    return o


def flatten(rec: dict[str, Any], enums: dict[str, dict[str, str]], prefix: str = "", depth: int = 0,
            out: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scalars become columns (snake case, nested names joined by _). Lists become <name>_count."""
    out = {} if out is None else out
    for k, v in rec.items():
        if k in EXCLUDED_KEYS:
            continue
        col = f"{prefix}{snake(k)}"
        if isinstance(v, dict):
            if depth < 2:
                flatten(v, enums, col + "_", depth + 1, out)
        elif isinstance(v, list):
            out[col + "_count"] = len(v)
            if k == "notes":
                out["notes_text"] = " ".join(str(n.get("value") or "") for n in v if isinstance(n, dict))[:4000]
            elif k == "highlights":
                out["highlights_text"] = "; ".join(str(n.get("text") or "") for n in v if isinstance(n, dict))[:4000]
            elif v and all(isinstance(x, (str, int, float)) for x in v) and len(v) <= 12:
                out[col] = ", ".join(str(x) for x in v)
        elif v is not None:
            out[col] = int(v) if isinstance(v, bool) else v
            if isinstance(v, int) and not isinstance(v, bool):
                ename = k[0].upper() + k[1:]
                label = (enums.get(ename) or {}).get(str(v))
                if label is not None:
                    out[col + "_label"] = label
    return out


def _sql_type(values: list[Any]) -> str:
    kinds = {type(v) for v in values if v is not None}
    if kinds <= {int}:
        return "INTEGER"
    if kinds <= {int, float}:
        return "REAL"
    return "TEXT"


def _create_and_fill(db: Database, table: str, rows: list[dict[str, Any]]) -> None:
    cols: dict[str, list[Any]] = {}
    for r in rows:
        for k, v in r.items():
            cols.setdefault(k, []).append(v)
    dyn = sorted(c for c in cols if c not in FIXED and c != "id")
    ddl = ["row_id TEXT PRIMARY KEY", "node_id TEXT", "property_id TEXT", "place_id TEXT", "evidence_id TEXT"]
    ddl += [f'"{c}" {_sql_type(cols[c])}' for c in dyn] + ["raw_json TEXT"]
    names = ["row_id", "node_id", "property_id", "place_id", "evidence_id", *dyn, "raw_json"]
    with db.write() as c:
        c.execute(f"DROP TABLE IF EXISTS {table}")
        c.execute(f"CREATE TABLE {table} ({', '.join(ddl)})")
        sql = f"INSERT INTO {table} ({','.join(chr(34) + n + chr(34) for n in names)}) VALUES ({','.join('?' * len(names))})"
        c.executemany(sql, ([r.get(n) for n in names] for r in rows))
        for ix in ("property_id", "place_id", "node_id"):
            c.execute(f"CREATE INDEX IF NOT EXISTS {table}_{ix} ON {table}({ix})")


class KitIngest:
    def __init__(self, settings: Settings, db: Database, http: Http):
        self.s, self.db, self.http = settings, db, http

    # ---- step 1 ----------------------------------------------------------
    def index(self, force: bool = False) -> dict[str, int]:
        raw = self.s.raw_dir / "models_index.csv"
        if force or not raw.exists():
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(self.http.get_bytes(INDEX_URL, auth_fatal=False))
        bm = self.s.data_dir / "basemap.json"
        if force or not bm.exists():
            try:
                bm.write_bytes(self.http.get_bytes(BASEMAP_URL, auth_fatal=False))
            except Exception as e:  # noqa: BLE001 - the basemap is optional
                log.warning("basemap not downloaded: %s", e)
        rows = list(csv.DictReader(io.StringIO(raw.read_text(encoding="utf-8"))))
        n_la = 0
        with self.db.write() as c:
            for r in rows:
                lat, lon = _f(r["lat"]), _f(r["lon"])
                is_la = int(lon is not None and lon < -110)
                n_la += is_la
                sp = space_id(r["sid"])
                evid = ev.register(c, "record", "matterport", sp, content=r, url=f"/v1/spaces/{sp}",
                                   excerpt=f"Matterport index row: {r['name']} ({r['segment']}), {r['pano_count']} panos, "
                                           f"{r['room_count']} rooms, scanned {r['original_created']}")
                c.execute(
                    """INSERT INTO space(space_id,sid,name,segment,space_kind,lat,lon,latlon_source,address,internal_id,
                         index_costar_property_id,index_homes_listing_id,pano_count,room_count,floor_count,has_summary,
                         has_defurnished,has_splat,drone_photos,original_created,showcase_url,is_la,evidence_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(space_id) DO UPDATE SET name=excluded.name, segment=excluded.segment,
                         space_kind=excluded.space_kind, lat=excluded.lat, lon=excluded.lon,
                         pano_count=excluded.pano_count, room_count=excluded.room_count,
                         has_summary=excluded.has_summary, has_defurnished=excluded.has_defurnished,
                         has_splat=excluded.has_splat, is_la=max(space.is_la, excluded.is_la),
                         evidence_id=excluded.evidence_id""",
                    (sp, r["sid"], r["name"], r["segment"], space_kind(r["name"], r["segment"]), lat, lon,
                     r["latlon_source"], r["address"], r["internal_id"], r["costar_property_id"] or None,
                     r["homes_listing_id"] or None, int(r["pano_count"] or 0), int(r["room_count"] or 0),
                     int(r["floor_count"] or 0), int(r["ai_summary"] == "yes"), int(r["defurnished"] == "yes"),
                     int(r["splat"] == "yes"), int(r["drone_photos"] or 0) if (r["drone_photos"] or "").isdigit() else 0,
                     r["original_created"], f"https://my.matterport.com/show/?m={r['sid']}", is_la, evid))
        return {"spaces": len(rows), "la": n_la}

    # ---- step 2 ----------------------------------------------------------
    def costar(self) -> dict[str, Any]:
        kit = kitp.ensure_kit(self.s, self.http)
        enums = kitp.load_enums(kit)
        report: dict[str, Any] = {"counts": {}, "warnings": []}
        la_props: dict[str, dict[str, Any]] = {}
        company_names: dict[str, str] = {}

        def base(table: str, rec: dict[str, Any], pid: str | None, place: str | None, c, excerpt: str) -> dict[str, Any]:
            rid = str(rec["id"])
            node = f"{NODE_PREFIX[table]}:{rid}"
            clean = strip_private(rec)
            evid = ev.register(c, "record", "costar", node, content=clean, place_id=place,
                               url=f"/v1/market/records/{node}", excerpt=excerpt)
            row = flatten(rec, enums)
            row.pop("id", None)
            row.update(row_id=rid, node_id=node, property_id=pid, place_id=place, evidence_id=evid,
                       raw_json=canonical_json(clean))
            return row

        # properties first: they define places
        rows = []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "commercial-property"):
                pid = str(rec["id"])
                a = rec.get("primaryAddress") or {}
                is_la = a.get("researchMarketId") == LA_MARKET_ID
                place = place_id_for_property(pid) if is_la else None
                years = [e.get("year") for e in rec.get("constructionEvents") or [] if e.get("year")]
                addr = " ".join(str(a.get(k)) for k in ("streetNumber", "streetDirection", "streetName", "streetType",
                                                         "streetSuffix") if a.get(k))
                ptype = (enums.get("PropertyType") or {}).get(str(rec.get("propertyType")), str(rec.get("propertyType")))
                sqft = rec.get("rentableBuildingAreaSquareFeet") or rec.get("grossBuildingAreaSquareFeet")
                row = base("costar_property", rec, pid, place, c,
                           f"{rec.get('buildingName') or addr}: {ptype}, {sqft or 'unknown'} sq ft, "
                           f"{rec.get('numStoriesAboveGrade') or 'unknown'} storeys, {addr}, {a.get('city')}")
                row.update(year_built=min(years) if years else None, year_last_event=max(years) if years else None,
                           parking_spaces_total=sum(p.get("totalSpaces") or 0 for p in rec.get("parking") or []) or None,
                           street_address=addr)
                rows.append(row)
                if is_la:
                    la_props[pid] = {"place_id": place, "name": rec.get("buildingName") or addr, "address": addr,
                                     "city": a.get("city"), "postal_code": str(a.get("postcode") or "")[:5],
                                     "lat": a.get("latitude"), "lon": a.get("longitude"), "property_type": ptype,
                                     "building_sqft": sqft, "year_built": min(years) if years else None,
                                     "stories": rec.get("numStoriesAboveGrade"), "evidence_id": row["evidence_id"]}
        _create_and_fill(self.db, "costar_property", rows)
        report["counts"]["commercial-property"] = len(rows)
        all_props = {r["row_id"] for r in rows}

        with self.db.write() as c:
            c.execute("DELETE FROM place_fts WHERE place_id LIKE 'place:costar:%'")
            for pid, p in la_props.items():
                c.execute(
                    """INSERT INTO place(place_id,kind,costar_property_id,name,address,city,postal_code,lat,lon,
                         property_type,building_sqft,year_built,stories,evidence_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(place_id) DO UPDATE SET name=excluded.name, address=excluded.address,
                         lat=excluded.lat, lon=excluded.lon, property_type=excluded.property_type,
                         building_sqft=excluded.building_sqft, year_built=excluded.year_built,
                         stories=excluded.stories, evidence_id=excluded.evidence_id""",
                    (p["place_id"], "commercial", pid, p["name"], p["address"], p["city"], p["postal_code"], p["lat"],
                     p["lon"], p["property_type"], p["building_sqft"], p["year_built"], p["stories"], p["evidence_id"]))
                c.execute("INSERT INTO place_fts(place_id,text) VALUES(?,?)",
                          (p["place_id"], f"{p['name']} {p['address']} {p['property_type']} {pid}"))

        def place_of(pid: str | None) -> str | None:
            return la_props[pid]["place_id"] if pid in la_props else None

        # companies (needed for tenant names)
        rows = []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "company-detail"):
                company_names[str(rec["id"])] = rec.get("name") or ""
                rows.append(base("costar_company", rec, None, None, c,
                                 f"Company location: {rec.get('name')}, {rec.get('numEmployees') or 'unknown'} employees"))
        _create_and_fill(self.db, "costar_company", rows)
        report["counts"]["company-detail"] = len(rows)

        rows = []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "location-occupancy"):
                pid = str(rec.get("propertyId"))
                tname = company_names.get(str(rec.get("tenantLocationId")), "") if rec.get("tenantLocationId") else ""
                sqft = sum((s.get("squareFeetOccupied") or 0) for s in rec.get("spaces") or []) or None
                row = base("costar_occupancy", rec, pid, place_of(pid), c,
                           f"Tenancy: {tname or 'unknown tenant'}, {sqft or 'unknown'} sq ft, "
                           f"from {str(rec.get('fromDate') or rec.get('moveInDate') or '')[:10] or 'unknown'}")
                row.update(tenant_name=tname or None, square_feet_occupied=sqft,
                           tenant_location_id=str(rec["tenantLocationId"]) if rec.get("tenantLocationId") else None)
                rows.append(row)
        _create_and_fill(self.db, "costar_occupancy", rows)
        report["counts"]["location-occupancy"] = len(rows)

        rows, spaces = [], []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "commercial-listing-summary"):
                pid = str(rec.get("propertyId"))
                fl, fs = rec.get("forLeaseSummary") or {}, rec.get("forSaleSummary") or {}
                kind = "lease" if fl else "sale"
                row = base("costar_listing", rec, pid, place_of(pid), c,
                           f"{kind.capitalize()} listing at {rec.get('buildingName') or pid}: "
                           + (f"{fl.get('totalAvailableSquareFeet')} sq ft available in {fl.get('spaceCount')} spaces"
                              if fl else f"asking {fs.get('askingPriceLow')} to {fs.get('askingPriceHigh')}"))
                row.update(listing_kind=kind)
                rows.append(row)
                for sp in fl.get("spaces") or []:
                    srow = flatten(sp, enums)
                    srow.pop("id", None)
                    srow.update(row_id=f"{rec['id']}:{sp.get('id')}", node_id=row["node_id"], property_id=pid,
                                place_id=place_of(pid), evidence_id=row["evidence_id"], raw_json=None,
                                listing_id=str(rec["id"]))
                    spaces.append(srow)
        _create_and_fill(self.db, "costar_listing", rows)
        _create_and_fill(self.db, "costar_listing_space", spaces or [{"row_id": "_", "node_id": None, "property_id": None,
                                                                      "place_id": None, "evidence_id": None,
                                                                      "raw_json": None}])
        report["counts"]["commercial-listing-summary"] = len(rows)

        rows, ents = [], []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "commercial-sale-comp"):
                pids = sorted({str(e.get("propertyId")) for e in rec.get("entities") or [] if e.get("propertyId")})
                in_kit = [p for p in pids if p in all_props]
                first = next((p for p in in_kit if p in la_props), in_kit[0] if in_kit else None)
                row = base("costar_sale", rec, first, place_of(first), c,
                           f"Sale on {str(rec.get('soldDate') or '')[:10]} for {rec.get('soldForPrice')} "
                           f"covering {len(pids)} propert{'y' if len(pids) == 1 else 'ies'}")
                row.update(entity_property_count=len(pids))
                rows.append(row)
                for p in pids:
                    ents.append({"row_id": f"{rec['id']}:{p}", "node_id": row["node_id"], "property_id": p,
                                 "place_id": place_of(p), "evidence_id": row["evidence_id"], "raw_json": None,
                                 "sale_id": str(rec["id"]), "in_kit": int(p in all_props),
                                 "sold_date": rec.get("soldDate"), "sold_for_price": rec.get("soldForPrice")})
        _create_and_fill(self.db, "costar_sale", rows)
        _create_and_fill(self.db, "costar_sale_entity", ents)
        report["counts"]["commercial-sale-comp"] = len(rows)

        rows, models = [], []
        with self.db.write() as c:
            for rec in kitp.iter_records(kit, "apartment-listing"):
                pid = str(rec.get("propertyId"))
                row = base("costar_apartment_listing", rec, pid, place_of(pid), c,
                           f"Apartment listing {rec.get('buildingName')}: rents {rec.get('minRent')} to {rec.get('maxRent')}, "
                           f"{rec.get('numUnitsAvailable')} of {rec.get('totalNumUnits')} units available")
                rows.append(row)
                for m in rec.get("apartmentModels") or []:
                    mrow = flatten(m, enums)
                    mrow.pop("id", None)
                    mrow.update(row_id=f"{rec['id']}:{m.get('id')}", node_id=row["node_id"], property_id=pid,
                                place_id=place_of(pid), evidence_id=row["evidence_id"], raw_json=None)
                    models.append(mrow)
        _create_and_fill(self.db, "costar_apartment_listing", rows)
        _create_and_fill(self.db, "costar_apartment_model", models)
        report["counts"]["apartment-listing"] = len(rows)

        for ds, table, label in (("residential-listings", "costar_res_listing", "Home listing"),
                                 ("residential-listing-features", "costar_listing_features", "Home features")):
            rows = []
            with self.db.write() as c:
                for rec in kitp.iter_records(kit, ds):
                    place = place_id_for_home(rec["residentialListingId"]) if rec.get("residentialListingId") else None
                    pr = rec.get("property") or {}
                    row = base(table, rec, None, place, c,
                               f"{label} {rec['id']}: price {rec.get('currentPrice')}, {pr.get('bedsMax')} beds, "
                               f"{pr.get('bathsMax')} baths" if ds == "residential-listings" else f"{label} {rec['id']}")
                    a = pr.get("address") or {}
                    if a:
                        row.update(home_lat=a.get("latitude"), home_lon=a.get("longitude"),
                                   home_address=" ".join(str(a.get(k)) for k in ("streetNumber", "streetDirection",
                                                         "streetName", "streetType", "unitNumber") if a.get(k)),
                                   home_city=a.get("city"))
                    rows.append(row)
            _create_and_fill(self.db, table, rows)
            report["counts"][ds] = len(rows)

        for ds, n in kitp.DATASETS.items():
            if report["counts"].get(ds) != n:
                report["warnings"].append(f"{ds}: expected {n}, loaded {report['counts'].get(ds)}")

        report.update(self._links(kit, la_props))
        (self.s.data_dir / "reports").mkdir(parents=True, exist_ok=True)
        (self.s.data_dir / "reports" / "costar.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        return report

    def _links(self, kit, la_props: dict[str, dict[str, Any]]) -> dict[str, Any]:
        pairs = [(r["PropertyId"], r["MatterportModelId"]) for r in kitp.read_csv(kit / "commercial-properties.csv")
                 if r["MatterportModelId"]]
        res = [(r["ListingId"], r["ResidentialListingId"], r["MatterportModelId"])
               for r in kitp.read_csv(kit / "residential-listings.csv") if r["MatterportModelId"]]
        idx = {r["sid"]: r for r in self.db.q("SELECT sid, lat, lon, latlon_source, index_costar_property_id FROM space")}
        mismatch, far, missing = [], 0, 0
        with self.db.write() as c:
            c.execute("DELETE FROM kit_model_link")
            c.execute("DELETE FROM kit_res_model_link")
            c.execute("DELETE FROM link WHERE relation='space_at_place'")
            c.executemany("INSERT OR IGNORE INTO kit_model_link(property_id,sid) VALUES(?,?)", pairs)
            c.executemany("INSERT OR IGNORE INTO kit_res_model_link(listing_id,residential_listing_id,sid) VALUES(?,?,?)", res)
            first: dict[str, str] = {}
            for pid, sid in sorted(pairs):
                sp = idx.get(sid)
                if sp is None:
                    missing += 1
                    continue
                if pid not in la_props:
                    continue
                p = la_props[pid]
                dist, status, note = None, "accepted", None
                if sp["latlon_source"] == "model" and sp["lat"] is not None and p["lat"] is not None:
                    dist = round(haversine_m(sp["lat"], sp["lon"], p["lat"], p["lon"]), 1)
                    if dist > 150:
                        note, far = "distance_mismatch", far + 1
                if sp["index_costar_property_id"] and sp["index_costar_property_id"] != pid:
                    mismatch.append({"sid": sid, "index_pid": sp["index_costar_property_id"], "kit_pid": pid})
                    note = (note + ",index_pid_mismatch") if note else "index_pid_mismatch"
                c.execute("INSERT OR REPLACE INTO link(src_id,dst_id,relation,method,distance_m,confidence,status,note)"
                          " VALUES(?,?,?,?,?,?,?,?)",
                          (space_id(sid), p["place_id"], "space_at_place", "id_join", dist, 1.0, status, note))
                first.setdefault(sid, p["place_id"])
            c.executemany("UPDATE space SET place_id=?, is_la=1 WHERE sid=?", [(pl, sid) for sid, pl in first.items()])
        return {"kit_pairs": len(pairs), "kit_models": len({s for _, s in pairs}), "la_places": len(la_props),
                "la_spaces_linked": len(first), "models_missing_from_index": missing,
                "index_pid_mismatches": len(mismatch), "distance_over_150m": far, "mismatch_examples": mismatch[:10]}

    # ---- step 3 ----------------------------------------------------------
    def select(self, only: set[str] | None = None) -> dict[str, Any]:
        sel = json.loads(self.s.selection_path.read_text(encoding="utf-8"))
        props = [str(p) for p in sel.get("properties", []) if only is None or str(p) in only]
        homes = [h for h in sel.get("homes", []) if only is None or str(h["residential_listing_id"]) in only]
        missing = [p for p in props if not self.db.one("SELECT 1 FROM place WHERE costar_property_id=?", (p,))]
        if missing:
            raise RuntimeError(f"selected property ids not found in the kit (LA): {missing}")
        with self.db.write() as c:
            c.execute("UPDATE place SET is_deep=0")
            for p in props:
                c.execute("UPDATE place SET is_deep=1 WHERE costar_property_id=?", (p,))
                # a model shared between properties belongs to the deep one
                c.execute("UPDATE space SET place_id=?, is_la=1 WHERE sid IN (SELECT sid FROM kit_model_link WHERE property_id=?)",
                          (place_id_for_property(p), p))
            for h in homes:
                rl = str(h["residential_listing_id"])
                rows = c.execute("SELECT * FROM costar_res_listing WHERE residential_listing_id=? ORDER BY row_id",
                                 (rl,)).fetchall()
                if not rows:
                    raise RuntimeError(f"home {rl} not found in the kit residential listings")
                r = dict(rows[0])
                place = place_id_for_home(rl)
                name = r.get("home_address") or f"Home {rl}"
                c.execute(
                    """INSERT INTO place(place_id,kind,residential_listing_id,name,address,city,lat,lon,property_type,
                         year_built,is_deep,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)
                       ON CONFLICT(place_id) DO UPDATE SET is_deep=1, name=excluded.name, lat=excluded.lat, lon=excluded.lon""",
                    (place, "home", rl, name, name, r.get("home_city"), r.get("home_lat"), r.get("home_lon"), "Residential",
                     r.get("property_year_built"), r["evidence_id"]))
                c.execute("DELETE FROM place_fts WHERE place_id=?", (place,))
                c.execute("INSERT INTO place_fts(place_id,text) VALUES(?,?)", (place, f"{name} home residential {rl}"))
                sids = {x["sid"] for x in c.execute("SELECT sid FROM kit_res_model_link WHERE residential_listing_id=?", (rl,))}
                sids.add(h["sid"])
                for sid in sids:
                    c.execute("UPDATE space SET place_id=?, is_la=1 WHERE sid=?", (place, sid))
                    c.execute("INSERT OR REPLACE INTO link(src_id,dst_id,relation,method,confidence,status)"
                              " VALUES(?,?,?,?,?,?)", (space_id(sid), place, "space_at_place", "id_join", 1.0, "accepted"))
        deep = [r["place_id"] for r in self.db.q("SELECT place_id FROM place WHERE is_deep=1 ORDER BY place_id")]
        return {"deep_places": deep, "count": len(deep)}

    def deep_spaces(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.q(
            "SELECT s.* FROM space s JOIN place p ON p.place_id=s.place_id WHERE p.is_deep=1 ORDER BY s.sid")]


def qhash(text: str) -> str:
    return sha256_hex(re.sub(r"\s+", " ", text.strip().lower()))
