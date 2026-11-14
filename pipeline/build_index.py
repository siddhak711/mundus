"""Build the per-city index and one detail file per property from the CoStar kit.

    python pipeline/build_index.py            # reads raw/costar, writes data/

Output
    data/index/houston.json, data/index/los-angeles.json   one row per property or home
    data/property/<id>.json                                commercial property detail
    data/home/<id>.json                                    residential listing detail
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "raw" / "costar"
OUT = ROOT / "data"

ENUMS = json.loads((KIT / "schemas" / "enums.json").read_text(encoding="utf-8"))
CITY_BY_STATE = {"TX": "houston", "CA": "los-angeles"}


def rows(dataset):
    with open(KIT / "data" / f"{dataset}.jsonl", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def enum(name, value):
    """Enum integer -> readable label ('LeedCertifiedGold' -> 'Leed Certified Gold')."""
    label = ENUMS.get(name, {}).get(str(value))
    if not label or label.startswith("Unknown"):
        return None
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label.split("_")[-1])


def year(iso):
    return int(iso[:4]) if iso else None


# --- floor names -----------------------------------------------------------
# CoStar stores floors as an enum ("SixtyFourthFloor"). Turn the names back into numbers.
_UNITS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
          "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
          "eighteenth", "nineteenth"]
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_TENTHS = {"twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60, "seventieth": 70,
           "eightieth": 80, "ninetieth": 90, "hundredth": 100}


def _floor_number(name):
    if not name.endswith("Floor"):
        return {"Ground": 1, "Lobby": 1, "Plaza": 1}.get(name)
    words = [w.lower() for w in re.findall(r"[A-Z][a-z]+", name[:-5])]
    total = 0
    for w in words:
        if w == "one":
            continue
        if w == "hundred":
            total += 100
        elif w in _TENS:
            total += _TENS[w]
        elif w in _TENTHS:
            total += _TENTHS[w]
        elif w in _UNITS:
            total += _UNITS.index(w) + 1
    return total or None


FLOOR_NUMBER = {int(k): _floor_number(v) for k, v in ENUMS["FloorName"].items()}


def suite_floor(suite, stories):
    """'3610' -> 36. Only trusted when it fits inside the building."""
    m = re.match(r"\s*(\d{3,4})", str(suite or ""))
    if not m:
        return None
    n = int(m.group(1)) // 100
    return n if 1 <= n <= max(stories or 0, 1) else None


def street_address(a):
    parts = [a.get("streetNumber"), a.get("streetDirPrefix"), a.get("streetName"), a.get("streetType") or a.get("streetSuffix")]
    return " ".join(p for p in parts if p)


def photo_list(attachments, limit=24):
    seen, out = set(), []
    for a in attachments or []:
        uri = a.get("attachmentUri")
        if uri and uri not in seen:
            seen.add(uri)
            out.append({"url": uri.replace("/112/", "/113/"), "caption": a.get("caption") or ""})
    return out[:limit]


# --- load the datasets that hang off a property ----------------------------
def load_related():
    companies = {}
    for c in rows("company-detail"):
        profile = c.get("profile") or {}
        companies[c["id"]] = {
            "name": profile.get("companyName") or c.get("name"),
            "industry": enum("IndustryType", profile.get("industryType")),
            "employees": c.get("numEmployees"),
        }

    occupancies = defaultdict(list)
    for o in rows("location-occupancy"):
        occupancies[o["propertyId"]].append(o)

    listings = defaultdict(list)
    for l in rows("commercial-listing-summary"):
        if l.get("propertyId"):
            listings[l["propertyId"]].append(l)

    sales = defaultdict(list)
    for s in rows("commercial-sale-comp"):
        for e in s.get("entities") or []:
            if e.get("propertyId"):
                sales[e["propertyId"]].append(s)

    apartments = {a["propertyId"]: a for a in rows("apartment-listing")}

    models = defaultdict(list)
    with open(KIT / "commercial-properties.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["MatterportModelId"]:
                models[int(r["PropertyId"])].append(r["MatterportModelId"])
    return companies, occupancies, listings, sales, apartments, models


# --- commercial ------------------------------------------------------------
def tenancy_rows(prop, occs, companies, floor_by_id):
    stories = prop.get("numStoriesAboveGrade")
    out = []
    for o in occs:
        company = companies.get(o.get("tenantLocationId")) or {}
        deal = o.get("leaseDeal") or {}
        for space in o.get("spaces") or []:
            floor = floor_by_id.get(space.get("propertyFloorId")) or suite_floor(space.get("suite"), stories)
            out.append({
                "tenant": company.get("name") or "Undisclosed tenant",
                "industry": company.get("industry"),
                "floor": floor,
                "suite": space.get("suite"),
                "sf": space.get("squareFeetOccupied") or 0,
                "from": year(o.get("moveInDate") or o.get("fromDate")),
                "to": year(o.get("toDate")),
                "rate": (deal.get("askingRate") or {}).get("rateHigh"),
            })
    return out


def availability(lsts):
    lease = [l for l in lsts if l.get("forLeaseSummary") and l.get("listingStatus") == 1]
    if not lease:
        return None
    main = max(lease, key=lambda l: l["forLeaseSummary"].get("spaceCount") or 0)
    s = main["forLeaseSummary"]
    spaces = [{
        "floor": FLOOR_NUMBER.get(sp.get("floorName")),
        "suite": sp.get("suite"),
        "sf": sp.get("squareFeetMax"),
        "rate": sp.get("rateLow") if sp.get("askingRateHasValue") else None,
        "fullFloor": bool(sp.get("isFullFloor")),
        "use": enum("SpaceUse", sp.get("spaceUse")),
    } for sp in s.get("spaces") or []]
    return {
        "totalSf": s.get("totalAvailableSquareFeet"),
        "count": s.get("spaceCount"),
        "rateLow": s.get("askingRateLow") or None,
        "rateHigh": s.get("askingRateHigh") or None,
        "maxContiguousSf": s.get("maxContiguousSquareFeet"),
        "service": enum("ServiceType", s.get("serviceType")),
        "broker": main.get("brokerageCompanyName"),
        "spaces": spaces,
    }


def sale_rows(sls):
    out = []
    for s in sorted(sls, key=lambda s: s.get("soldDate") or "", reverse=True):
        out.append({
            "date": (s.get("soldDate") or "")[:10],
            "price": s.get("soldForPrice"),
            "interestPercent": s.get("partialInterestSalePercent"),
            "capRate": s.get("capitalizationRateActual"),
            "portfolio": len({e.get("propertyId") for e in s.get("entities") or [] if e.get("propertyId")}) > 1,
            "note": next((n["value"] for n in s.get("notes") or [] if n.get("value")), ""),
        })
    return out


def apartment_block(prop, listing):
    pa = prop.get("propertyApartment")
    if not pa:
        return None
    block = {
        "units": pa.get("totalNumUnits"),
        "style": enum("ApartmentStyleType", pa.get("apartmentStyleType")),
        "vacancyPercent": pa.get("vacancyPercent"),
        "buildings": pa.get("numBuildings"),
    }
    if listing:
        block.update({
            "minRent": listing.get("minRent"), "maxRent": listing.get("maxRent"),
            "unitsAvailable": listing.get("numUnitsAvailable"),
            "manager": listing.get("propertyManagementCompanyName"),
            "plans": [{
                "name": m.get("name"), "beds": m.get("numBeds"), "baths": m.get("numBaths"),
                "sfMin": m.get("minSquareFeet"), "sfMax": m.get("maxSquareFeet"),
                "rentMin": m.get("minRent"), "rentMax": m.get("maxRent"),
                "units": m.get("numUnits"), "available": m.get("numUnitsAvailable"),
            } for m in listing.get("apartmentModels") or []],
        })
    return block


def build_commercial(index):
    companies, occupancies, listings, sales, apartments, models = load_related()
    out_dir = OUT / "property"
    out_dir.mkdir(parents=True, exist_ok=True)
    for prop in rows("commercial-property"):
        pid = prop["id"]
        addr = prop["primaryAddress"]
        city = CITY_BY_STATE.get(addr.get("state"))
        if not city:
            continue
        floor_by_id = {f["propertyFloorId"]: FLOOR_NUMBER.get(f["floorName"]) for f in prop.get("floors") or []}
        floor_sf = {FLOOR_NUMBER[f["floorName"]]: (f.get("floorSize") or {}).get("squareFeet")
                    for f in prop.get("floors") or [] if FLOOR_NUMBER.get(f["floorName"])}
        tenancies = tenancy_rows(prop, occupancies.get(pid, []), companies, floor_by_id)
        avail = availability(listings.get(pid, []))
        apt = apartment_block(prop, apartments.get(pid))
        built = next((e["year"] for e in prop.get("constructionEvents") or [] if e.get("year")), None)
        type_name = enum("PropertyType", prop.get("propertyType")) or "Other"
        name = prop.get("buildingName") or street_address(addr)
        size = prop.get("rentableBuildingAreaSquareFeet") or prop.get("grossBuildingAreaSquareFeet")
        detail = {
            "id": pid, "kind": "commercial", "city": city, "name": name,
            "address": f"{street_address(addr)}, {addr.get('city')}, {addr.get('state')} {str(addr.get('postcode') or '')[:5]}",
            "lat": addr["latitude"], "lon": addr["longitude"],
            "type": type_name, "buildingClass": enum("BuildingClass", prop.get("buildingClass")),
            "stars": prop.get("buildingRating") or None,
            "stories": prop.get("numStoriesAboveGrade"), "yearBuilt": built, "sizeSf": size,
            "typicalFloorSf": prop.get("grossTypicalFloorSquareFeet"), "lotAcres": prop.get("lotSize"),
            "floorSf": floor_sf, "tenancies": tenancies, "availability": avail,
            "sales": sale_rows(sales.get(pid, [])), "apartments": apt,
            "leed": [{"year": l.get("beginYear"), "level": (enum("PropertyLeedType", l.get("propertyLeedType")) or "").replace("Leed", "LEED")}
                     for l in (prop.get("environmental") or {}).get("leedCertifications") or []],
            "parkingFees": [p["monthlyParkingFee"] for p in prop.get("parking") or [] if p.get("monthlyParkingFee")],
            "description": next((n["value"] for n in prop.get("notes") or [] if n.get("noteType") == 2), ""),
            "photos": photo_list(prop.get("attachments")),
            "scanIds": sorted(set(models.get(pid, []))),
        }
        (out_dir / f"{pid}.json").write_text(json.dumps(detail), encoding="utf-8")
        index[city].append({
            "id": pid, "kind": "commercial", "name": name, "address": street_address(addr),
            "lat": round(addr["latitude"], 6), "lon": round(addr["longitude"], 6), "type": type_name,
            "stories": prop.get("numStoriesAboveGrade"), "sizeSf": size, "yearBuilt": built,
            "scans": len(detail["scanIds"]), "tenancies": len(tenancies),
            "availableSf": (avail or {}).get("totalSf") or 0,
            "units": (apt or {}).get("units"), "rentFrom": (apt or {}).get("minRent"),
            "photo": (prop.get("primaryPhoto") or {}).get("attachmentUri", "").replace("/112/", "/113/") or None,
        })


# --- homes -----------------------------------------------------------------
MATTERPORT_REFERENCE_TYPES = {36, 234}
PHOTO_MEDIA_TYPE = 4


def build_homes(index):
    features = {f["id"]: f for f in rows("residential-listing-features")}
    out_dir = OUT / "home"
    out_dir.mkdir(parents=True, exist_ok=True)
    best = {}  # one listing per home: the most recently listed
    for l in rows("residential-listings"):
        key = l.get("propertyId") or l["id"]
        if key not in best or (l.get("listDate") or "") > (best[key].get("listDate") or ""):
            best[key] = l
    for l in best.values():
        p = l.get("property") or {}
        a = p.get("address") or {}
        city = CITY_BY_STATE.get(a.get("state"))
        if not city or not a.get("latitude"):
            continue
        scans = [m["videoKey"] for m in l.get("media") or [] if m.get("externalReferenceType") in MATTERPORT_REFERENCE_TYPES and m.get("videoKey")]
        photos = [{"url": m["uri"], "caption": ""} for m in l.get("media") or [] if m.get("type") == PHOTO_MEDIA_TYPE and m.get("uri")][:24]
        feat = features.get(l["id"]) or {}
        status = enum("ForSaleStatus", l.get("forSaleStatus")) or enum("ListingStatus", l.get("listingStatus"))
        name = a.get("fullStreetAddress") or "Address withheld"
        detail = {
            "id": l["id"], "kind": "home", "city": city, "name": name,
            "address": f"{name}, {a.get('city')}, {a.get('state')} {a.get('zip') or ''}".strip(),
            "lat": a["latitude"], "lon": a["longitude"],
            "type": p.get("mlsPropertyType") or "Home",
            "transaction": enum("TransactionType", l.get("transactionType")), "status": status,
            "price": l.get("currentPrice"), "originalPrice": l.get("originalPrice"),
            "listDate": (l.get("listDate") or "")[:10], "daysOnMarket": l.get("dom"),
            "beds": p.get("bedsMax"), "baths": p.get("bathsMax"), "sizeSf": p.get("sqftMax"),
            "lotAcres": p.get("lotSizeAcresMax"), "yearBuilt": p.get("yearBuilt"), "taxes": p.get("taxes"),
            "subdivision": p.get("subdivision"), "stories": 2 if (p.get("sqftMax") or 0) > 2600 else 1,
            "description": l.get("remarks") or "",
            "highlights": [h if isinstance(h, str) else h.get("text") or h.get("name") or "" for h in (feat.get("highlights") or [])][:8],
            "photos": photos, "scanIds": sorted(set(scans)),
        }
        (out_dir / f"{l['id']}.json").write_text(json.dumps(detail), encoding="utf-8")
        index[city].append({
            "id": l["id"], "kind": "home", "name": name, "address": name,
            "lat": round(a["latitude"], 6), "lon": round(a["longitude"], 6), "type": "Home",
            "stories": detail["stories"], "sizeSf": p.get("sqftMax"), "yearBuilt": p.get("yearBuilt"),
            "scans": len(detail["scanIds"]), "tenancies": 0, "availableSf": 0,
            "price": l.get("currentPrice"), "forRent": l.get("transactionType") == 2, "status": status,
            "beds": p.get("bedsMax"), "baths": p.get("bathsMax"),
            "photo": photos[0]["url"] if photos else None,
        })


def main():
    index = defaultdict(list)
    build_commercial(index)
    build_homes(index)
    (OUT / "index").mkdir(parents=True, exist_ok=True)
    for city, items in index.items():
        (OUT / "index" / f"{city}.json").write_text(json.dumps(items), encoding="utf-8")
        kinds = defaultdict(int)
        for it in items:
            kinds[it["type"]] += 1
        print(city, len(items), dict(sorted(kinds.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
