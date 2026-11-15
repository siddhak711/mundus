"""Market summary for one office floor considered for apartment conversion, from the CoStar kit.

    python -m pipeline.market cEvQ8q5GKZd --property 246826 --floor 16 [--kit raw/costar] [--radius-km 3]

Writes data/conversion/<scan>/market.json and market.md: building facts, the floor's size and who occupies it,
tenant history on the floor, and apartment rent comparisons within the radius. Broker and contact details in the
kit are never copied.
"""
import argparse
import json
import math
import statistics as st

from pipeline import config

FLOOR_WORDS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth",
               "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth", "Seventeenth",
               "Eighteenth", "Nineteenth", "Twentieth"]


def rows(kit, dataset):
    with open(kit / "data" / f"{dataset}.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def floor_label(n):
    if n <= 20:
        return FLOOR_WORDS[n - 1] + "Floor"
    tens = {2: "Twenty", 3: "Thirty", 4: "Forty", 5: "Fifty"}[n // 10]
    return tens + ("" if n % 10 == 0 else FLOOR_WORDS[n % 10 - 1]) + "Floor"


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def unit_type(beds):
    return "studio" if beds == 0 else f"{beds}BR" if beds < 3 else "3BR+"


def run(scan, property_id, floor, kit, radius_km=3.0):
    enums = json.loads((kit / "schemas" / "enums.json").read_text(encoding="utf-8"))
    dec = lambda name, v: (enums.get(name) or {}).get(str(v), v)
    props = {}
    target = None
    for r in rows(kit, "commercial-property"):
        a = r.get("primaryAddress") or {}
        props[r["id"]] = (a.get("latitude"), a.get("longitude"))
        if r["id"] == property_id:
            target = r
    if target is None:
        raise SystemExit(f"property {property_id} not in the kit")
    a = target["primaryAddress"]
    here = (a["latitude"], a["longitude"])
    years = {dec("ConstructionEventType", e.get("eventType")): e.get("year") for e in target.get("constructionEvents") or []}
    fmap = {f["propertyFloorId"]: dec("FloorName", f["floorName"]) for f in target.get("floors") or []}
    want = floor_label(floor)
    floor_rec = next((f for f in target.get("floors") or [] if dec("FloorName", f["floorName"]) == want), None)
    floor_id = floor_rec["propertyFloorId"] if floor_rec else None
    floor_sf = (floor_rec or {}).get("floorSize", {}).get("squareFeet")

    # tenancies
    occ = [o for o in rows(kit, "location-occupancy") if o.get("propertyId") == property_id]
    tenant_ids = {o.get("tenantLocationId") for o in occ}
    names = {}
    for c in rows(kit, "company-detail"):
        if c.get("id") in tenant_ids:
            names[c["id"]] = c.get("name")
    gross = target.get("grossBuildingAreaSquareFeet") or 0
    current_sf = sum(s.get("squareFeetOccupied") or 0 for o in occ if not o.get("toDate") for s in o.get("spaces") or [])
    on_floor = []
    for o in occ:
        sp = [s for s in o.get("spaces") or [] if s.get("propertyFloorId") == floor_id]
        if sp:
            on_floor.append({"tenant": names.get(o.get("tenantLocationId"), "unknown"),
                             "from": (o.get("fromDate") or "")[:10], "to": (o.get("toDate") or "")[:10] or None,
                             "sf_on_floor": sum(s.get("squareFeetOccupied") or 0 for s in sp),
                             "other_floors": sorted({fmap.get(s.get("propertyFloorId"), "?") for s in o.get("spaces") or [] if s.get("propertyFloorId") != floor_id})})
    on_floor.sort(key=lambda t: t["from"])
    current = [t for t in on_floor if not t["to"]]

    # space for lease (vacancy signal) from listings
    listed_sf = 0.0
    for l in rows(kit, "commercial-listing-summary"):
        if l.get("propertyId") == property_id:
            listed_sf += (l.get("forLeaseSummary") or {}).get("totalAvailableSquareFeet") or 0

    # apartment comps
    comps = []
    for ap in rows(kit, "apartment-listing"):
        p = props.get(ap.get("propertyId"))
        if not p or p[0] is None:
            continue
        d = km(here, p)
        if d > radius_km:
            continue
        models = []
        for m in ap.get("apartmentModels") or []:
            rent = st.mean([x for x in (m.get("minRent"), m.get("maxRent")) if x]) if (m.get("minRent") or m.get("maxRent")) else None
            sf = st.mean([x for x in (m.get("minSquareFeet"), m.get("maxSquareFeet")) if x]) if (m.get("minSquareFeet") or m.get("maxSquareFeet")) else None
            if rent and m.get("numBeds") is not None:
                models.append({"type": unit_type(m["numBeds"]), "rent": round(rent), "sf": round(sf) if sf else None,
                               "rent_per_sf": round(rent / sf, 2) if sf else None})
        comps.append({"building": ap.get("buildingName"), "distance_km": round(d, 2), "year_built": ap.get("yearBuilt"),
                      "units": ap.get("totalNumUnits"), "min_rent": ap.get("minRent"), "max_rent": ap.get("maxRent"),
                      "min_sf": ap.get("minSquareFeet"), "max_sf": ap.get("maxSquareFeet"), "models": models})
    comps.sort(key=lambda c: c["distance_km"])
    by_type = {}
    for c in comps:
        for m in c["models"]:
            by_type.setdefault(m["type"], []).append(m)
    order = ["studio", "1BR", "2BR", "3BR+"]
    rents = {t: {"plans": len(v), "median_rent": round(st.median([m["rent"] for m in v])),
                 "median_sf": round(st.median([m["sf"] for m in v if m["sf"]])) if any(m["sf"] for m in v) else None,
                 "median_rent_per_sf": round(st.median([m["rent_per_sf"] for m in v if m["rent_per_sf"]]), 2) if any(m["rent_per_sf"] for m in v) else None}
             for t, v in sorted(by_type.items(), key=lambda kv: order.index(kv[0]))}

    out = {
        "scan": scan, "property": property_id, "floor": floor,
        "building": {"name": target.get("buildingName"), "address": f"{a.get('streetNumber')} {a.get('streetName')} {a.get('streetType', '')}, {a.get('city')}".replace("  ", " "),
                     "storeys": target.get("numStoriesAboveGrade"), "gross_sf": gross,
                     "typical_floor_sf": target.get("grossTypicalFloorSquareFeet"),
                     "year_built": years.get("ConstructionComplete"), "year_renovated": years.get("Renovated") or years.get("RenovationComplete"),
                     "construction_events": years, "class": dec("BuildingClass", target.get("buildingClass")),
                     "sprinklers": dec("SprinklerType", target.get("sprinklerType")),
                     "zoning": target.get("zoningDescription"), "lot_acres_or_code": target.get("lotSize")},
        "floor_detail": {"label": want, "floor_sf": floor_sf, "current_tenants": current, "history": on_floor},
        "vacancy": {"occupied_sf_current_tenancies": round(current_sf), "listed_available_sf": round(listed_sf),
                    "occupied_share_of_gross": round(current_sf / gross, 3) if gross else None,
                    "note": "From open-ended tenancies and current listings in the kit; approximate."},
        "conflicts": [f"CoStar: {t['tenant']} occupies {t['sf_on_floor']:,.0f} sf of floor {floor} since {t['from']} with no end date. "
                      f"The Matterport scan shows the floor empty (scanned while vacant). Treat vacancy as unconfirmed."
                      for t in current],
        "rent_comps": {"radius_km": radius_km, "buildings": len(comps), "by_unit_type": rents, "nearest": comps[:12]},
    }
    folder = config.DATA / "conversion" / scan
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "market.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (folder / "market.md").write_text(to_md(out), encoding="utf-8")
    return out


def to_md(m):
    b, f, v, rc = m["building"], m["floor_detail"], m["vacancy"], m["rent_comps"]
    L = [f"# Market summary: {b['name']}, floor {m['floor']}", "",
         f"- Address: {b['address']}. Class {b['class']}, {b['storeys']} storeys, {b['gross_sf']:,.0f} sf gross.",
         f"- Built {b['year_built']}; construction events {b['construction_events']}. Sprinklers: {b['sprinklers']}. Zoning: {b['zoning']}.",
         f"- Floor {m['floor']}: {f['floor_sf']:,.0f} sf per CoStar.",
         f"- Building occupancy: {v['occupied_sf_current_tenancies']:,} sf in open tenancies "
         f"({(v['occupied_share_of_gross'] or 0):.0%} of gross); {v['listed_available_sf']:,} sf listed for lease. Approximate.", ""]
    if m["conflicts"]:
        L += ["## Conflict"] + [f"- {c}" for c in m["conflicts"]] + [""]
    L += ["## Tenants on this floor (oldest first)"]
    for t in f["history"]:
        L.append(f"- {t['tenant']}: {t['from']} to {t['to'] or 'now'}, {t['sf_on_floor']:,.0f} sf"
                 + (f" (also {', '.join(t['other_floors'])})" if t["other_floors"] else ""))
    L += ["", f"## Apartment rents within {rc['radius_km']:g} km ({rc['buildings']} buildings)",
          "| Type | Plans | Median rent/mo | Median sf | Median $/sf/mo |", "|---|---|---|---|---|"]
    for t, r in rc["by_unit_type"].items():
        L.append(f"| {t} | {r['plans']} | ${r['median_rent']:,} | {r['median_sf'] or '?'} | {r['median_rent_per_sf'] or '?'} |")
    L += ["", "## Nearest buildings", "| Building | km | Built | Units | Rent range |", "|---|---|---|---|---|"]
    for c in rc["nearest"][:10]:
        L.append(f"| {c['building']} | {c['distance_km']} | {c['year_built'] or '?'} | {c['units'] or '?'} | "
                 f"${c['min_rent'] or '?'} to ${c['max_rent'] or '?'} |")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--property", type=int, required=True)
    ap.add_argument("--floor", type=int, required=True)
    ap.add_argument("--kit", default=str(config.ROOT / "raw" / "costar"))
    ap.add_argument("--radius-km", type=float, default=3.0)
    a = ap.parse_args()
    from pathlib import Path
    out = run(a.scan, a.property, a.floor, Path(a.kit), a.radius_km)
    print(f"{out['building']['name']} floor {a.floor}: {out['floor_detail']['floor_sf']} sf; "
          f"{out['rent_comps']['buildings']} comp buildings; {len(out['conflicts'])} conflict(s)")
    for t, r in out["rent_comps"]["by_unit_type"].items():
        print(f"  {t}: {r['plans']} plans, median ${r['median_rent']}, {r['median_sf']} sf, ${r['median_rent_per_sf']}/sf")


if __name__ == "__main__":
    main()
