"""Office-to-residential conversion screen for Los Angeles, built on the Atlas index of the CoStar kit.

    python pipeline/build_index.py <kit folder>     # first: writes data/index and data/property
    python pipeline/conversion.py                   # then: writes data/conversion/

Output (git-ignored: the data is licensed), served by server.py for the /city/ page
    data/conversion/los-angeles.json         every LA commercial property in the index, with a conversion status
    data/conversion/property/<id>.json       one per office building in the City of LA: the screen and every floor

The screen has two parts.

1. Eligibility under the Citywide Adaptive Reuse Ordinance (Ordinance 188,793, in effect Feb 1, 2026):
   - the building is inside the City of Los Angeles (the ordinance does not apply in Santa Monica, Beverly Hills,
     Culver City and the other cities in the county);
   - the building is at least 15 years old for a by-right or administrative approval; 5 to 15 years old needs a
     Zoning Administrator's approval;
   - the site is in a multifamily, commercial, parking or public facilities zone. Manufacturing zones qualify only in
     certain Adaptive Reuse subareas, with administrative review. Read from the kit's zoning code.
   Only office buildings are screened, because that is the conversion this view is about.

2. Physical and market fit, as a 0 to 100 score. Thresholds are rules of thumb from conversion studies, not code:
   - vacancy: empty space is space that needs no tenant buy-out (full marks at 30% of the building available);
   - floor plate: residential units need daylight, which most studies put within 25 to 35 ft of a window. A
     typical floor under 20,000 sq ft rarely puts the core that far from the glass; over 40,000 sq ft usually does;
   - building class: class B and C buildings trade at prices where conversion can pay.

A floor counts as convertible now when at least half of it is listed as available.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CITY = "los-angeles"
CURRENT_YEAR = date.today().year

BY_RIGHT_AGE = 15          # years: by-right or administrative review
REVIEW_AGE = 5             # years: Zoning Administrator approval
FLOOR_CONVERTIBLE_SHARE = 0.5
FULL_VACANCY_POINTS = 0.30
STRONG_SCORE = 60

SOURCES = [
    {"label": "LA City Planning: Citywide Adaptive Reuse Ordinance", "url": "https://planning.lacity.gov/citywide-adaptive-reuse-ordinance"},
    {"label": "LA City Planning: Adaptive Reuse project review", "url": "https://planning.lacity.gov/project-review/adaptive-reuse"},
    {"label": "Ordinance 188,793 (adopted text)", "url": "https://cityclerk.lacity.org/onlinedocs/2021/21-1230-S9_ord_188793_12-23-25.pdf"},
    {"label": "LADBS: Adaptive Reuse Projects", "url": "https://dbs.lacity.gov/services/core-services/plan-check-permit/plan-check-permit-special-assistance/adaptive-reuse-projects"},
    {"label": "ZIMAS: zoning by parcel", "url": "https://zimas.lacity.org"},
]

# Postal place names that lie inside the City of Los Angeles. Many LA neighbourhoods have their own postal name
# (Van Nuys, San Pedro). CoStar also writes "Los Angeles" for some addresses on the city line, so this is a screen,
# not a boundary test.
CITY_OF_LA_NAMES = {
    "los angeles", "hollywood", "north hollywood", "studio city", "sherman oaks", "encino", "tarzana", "van nuys",
    "valley village", "woodland hills", "canoga park", "west hills", "winnetka", "reseda", "northridge", "north hills",
    "granada hills", "porter ranch", "chatsworth", "mission hills", "panorama city", "arleta", "pacoima", "sylmar",
    "sun valley", "sunland", "tujunga", "lake view terrace", "shadow hills", "san pedro", "wilmington",
    "harbor city", "venice", "playa vista", "playa del rey", "westchester", "eagle rock", "highland park",
    "silver lake", "echo park", "los feliz", "boyle heights", "el sereno", "lincoln heights", "westwood",
    "brentwood", "bel air", "pacific palisades", "west los angeles", "century city",
}

STATUS_LABELS = {
    "strong": "Strong candidate",
    "possible": "Eligible, weaker fit",
    "review": "Eligible with review",
    "zone_blocked": "Office in a zone that does not allow conversion",
    "too_new": "Office, too new to convert",
    "unknown_age": "Office, year built unknown",
    "outside_city": "Office outside the City of LA",
    "not_office": "Not an office building",
}

# LA zone classes (LAMC chapter 1). Multifamily, commercial, parking and public facilities qualify; manufacturing only
# in Adaptive Reuse subareas with review; single-family, agricultural and open space do not.
ZONE_PASS = {"CR": "commercial", "C1": "commercial", "C1.5": "commercial", "C2": "commercial", "C4": "commercial",
             "C5": "commercial", "RD": "multifamily", "R3": "multifamily", "RAS3": "multifamily", "R4": "multifamily",
             "RAS4": "multifamily", "R5": "multifamily", "P": "parking", "PB": "parking", "PF": "public facilities"}
ZONE_REVIEW = {"M1", "M2", "M3", "MR1", "MR2"}
ZONE_FAIL = {"R1", "R2", "RS", "RE", "RA", "A1", "A2", "OS"}
_ZONE = re.compile(r"(RAS[34]|C1\.5|CR|CM|C[1-5]|RD|RE|RS|RA|R[1-5]|PB|PF|P|MR[12]|M[1-3]|A[12]|OS)(?![A-Z])")


def zone_class(text):
    """'LAC2-1' -> 'C2', 'C4-2, Los Angeles' -> 'C4', '[Q] M1-2D-SN' -> 'M1'. None when it is not a chapter 1 code."""
    s = str(text or "").upper().replace(", LOS ANGELES", "").replace(",LOS ANGELES", "").strip()
    if re.match(r"^\[[A-Z]{2,}", s):          # downtown's new chapter 1A code: [MM1-CDF1-5].[IX4-FA]
        return None
    s = re.sub(r"^\[[A-Z]\]\s*", "", s)       # [Q] and [T] conditions
    s = re.sub(r"^LA(?=[CRMP])", "", s)       # assessor style: LAC2 = C2 in Los Angeles
    m = _ZONE.match(s)
    return m.group(1) if m else None


def zone_check(text):
    if not text:
        return {"name": "Zone allows housing", "result": "unknown", "note": "no zoning recorded: check the parcel on ZIMAS"}
    z = zone_class(text)
    if z in ZONE_PASS:
        return {"name": "Zone allows housing", "result": "pass", "note": f"{text} ({ZONE_PASS[z]})"}
    if z in ZONE_REVIEW:
        return {"name": "Zone allows housing", "result": "review",
                "note": f"{text}: manufacturing zone, eligible only in certain Adaptive Reuse subareas, with review"}
    if z in ZONE_FAIL:
        return {"name": "Zone allows housing", "result": "fail", "note": f"{text}: zone not covered by the ordinance"}
    return {"name": "Zone allows housing", "result": "unknown", "note": f"{text}: code not recognised, check ZIMAS"}


def place_name(address):
    """'10880 Wilshire Blvd, Los Angeles, CA 90024' -> 'los angeles'."""
    parts = [p.strip() for p in str(address or "").split(",")]
    return parts[-2].lower() if len(parts) >= 3 else ""


def in_city_of_la(address):
    return place_name(address) in CITY_OF_LA_NAMES


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def floor_size(b, n):
    sizes = b.get("floorSf") or {}
    sf = sizes.get(n) or sizes.get(str(n))
    if sf:
        return float(sf), "measured"
    if b.get("typicalFloorSf"):
        return float(b["typicalFloorSf"]), "typical"
    if b.get("sizeSf") and b.get("stories"):
        return float(b["sizeSf"]) / b["stories"], "average"
    return None, "unknown"


def current_tenants(tenancies, year=CURRENT_YEAR):
    """Tenancies that have started and have not ended."""
    return [t for t in tenancies or [] if (t.get("from") or 0) <= year and (t.get("to") is None or t["to"] >= year)]


def floors(b, walkthroughs=(), year=CURRENT_YEAR):
    """One row per floor above grade, bottom to top, with its size, vacancy and current tenants."""
    stories = int(b.get("stories") or 0)
    spaces = b.get("spaces") or []
    tenants = current_tenants(b.get("tenancies"), year)
    walk = {w["floor"]: w for w in walkthroughs}
    scans = {}
    for s in (b.get("daylight") or {}).get("scans") or []:
        if s.get("floor") and not s.get("error"):
            scans.setdefault(s["floor"], []).append(s)
    out = []
    for n in range(1, stories + 1):
        sf, size_source = floor_size(b, n)
        listed = [s for s in spaces if s.get("floor") == n]
        vacant = 0.0
        for s in listed:
            vacant += sf if (s.get("fullFloor") and sf) else float(s.get("sf") or 0)
        if sf:
            vacant = min(vacant, sf)
        here = [t for t in tenants if t.get("floor") == n]
        share = (vacant / sf) if sf else (1.0 if any(s.get("fullFloor") for s in listed) else None)
        if share is not None and share >= FLOOR_CONVERTIBLE_SHARE:
            status = "convertible"
        elif vacant > 0:
            status = "partial"
        elif here:
            status = "leased"
        else:
            status = "no_data"
        row = {
            "floor": n, "sf": round(sf) if sf else None, "sizeSource": size_source,
            "vacantSf": round(vacant), "vacantShare": round(share, 3) if share is not None else None,
            "status": status,
            "spaces": [{"suite": s.get("suite"), "sf": s.get("sf"), "fullFloor": s.get("fullFloor"),
                        "rate": s.get("rate"), "use": s.get("use")} for s in listed],
            "tenants": [{"name": t.get("tenant"), "sf": t.get("sf"), "suite": t.get("suite"), "to": t.get("to")} for t in here],
        }
        if n in scans:
            row["scans"] = [{k: s.get(k) for k in ("name", "scannedSf", "fullFloor", "within30ft", "deepestFt", "beyond30ftSf")}
                            for s in scans[n]]
        if n in walk:
            row["walkthrough"] = {"url": walk[n]["url"], "suite": walk[n].get("suite")}
        out.append(row)
    return out


def fit_score(b):
    """0 to 100, with the points behind it so the page can show why."""
    size = b.get("sizeSf") or 0
    vacancy = ((b.get("availableSf") or 0) / size) if size else None
    v_pts = round(50 * min((vacancy or 0) / FULL_VACANCY_POINTS, 1.0))
    plate = b.get("typicalFloorSf") or ((size / b["stories"]) if size and b.get("stories") else None)
    measured = ((b.get("daylight") or {}).get("plate")) or None
    if measured and measured.get("within30ft") is not None:
        share = measured["within30ft"]
        p_pts = 30 if share >= 0.85 else 20 if share >= 0.70 else 10 if share >= 0.55 else 0
        p_note = (f"measured on the floor {measured['floor']} scan: {round(100 * share)}% of the floor plate is within "
                  f"30 ft of a window; the deepest point is {round(measured['deepestFt'])} ft from one")
    elif plate is None:
        p_pts, p_note = 10, "floor plate size unknown"
    elif plate <= 20000:
        p_pts, p_note = 30, "small floor plate: most of each floor is near a window"
    elif plate <= 30000:
        p_pts, p_note = 20, "mid-size floor plate: some interior space far from windows"
    elif plate <= 40000:
        p_pts, p_note = 10, "deep floor plate: the middle of each floor is far from windows"
    else:
        p_pts, p_note = 0, "very deep floor plate: needs a light well or non-residential core uses"
    cls = (b.get("buildingClass") or "").strip().upper()[:1]
    c_pts = {"C": 20, "B": 15, "A": 5}.get(cls, 10)
    return {
        "score": v_pts + p_pts + c_pts,
        "vacancy": round(vacancy, 3) if vacancy is not None else None,
        "plateSf": round(plate) if plate else None,
        "plateMeasured": bool(measured and measured.get("within30ft") is not None),
        "parts": [
            {"name": "Vacancy", "points": v_pts, "of": 50,
             "note": f"{round(100 * vacancy)}% of the building is listed as available" if vacancy is not None else "building size unknown"},
            {"name": "Floor plate", "points": p_pts, "of": 30, "note": p_note},
            {"name": "Building class", "points": c_pts, "of": 20, "note": f"class {cls}" if cls else "class unknown"},
        ],
    }


def eligibility(b, year=CURRENT_YEAR):
    """(status, checks). An 'eligible' status is split into strong or possible by the fit score."""
    built = b.get("yearBuilt")
    age = (year - built) if built else None
    checks = [
        {"name": "Office building", "result": "pass" if b.get("type") == "Office" else "fail", "note": b.get("type") or "type unknown"},
        {"name": "Inside the City of Los Angeles", "result": "pass" if in_city_of_la(b.get("address")) else "fail",
         "note": place_name(b.get("address")).title() or "address unknown"},
    ]
    if age is None:
        checks.append({"name": "At least 15 years old", "result": "unknown", "note": "year built not recorded"})
    else:
        result = "pass" if age >= BY_RIGHT_AGE else ("review" if age >= REVIEW_AGE else "fail")
        checks.append({"name": "At least 15 years old", "result": result, "note": f"built {built}, {age} years old"})
    checks.append(zone_check(b.get("zoning")))
    office, city, age_r, zone_r = (c["result"] for c in checks)
    if office == "fail":
        return "not_office", checks
    if city == "fail":
        return "outside_city", checks
    if zone_r == "fail":
        return "zone_blocked", checks
    status = {"pass": "eligible", "review": "review", "fail": "too_new", "unknown": "unknown_age"}[age_r]
    if status == "eligible" and zone_r == "review":
        status = "review"
    return status, checks


def walkthroughs_for(b, entries):
    s = _norm(b.get("street"))
    return [w for w in entries if _norm(w["address"]) == s]


def assess(b, walk_entries=(), year=CURRENT_YEAR):
    status, checks = eligibility(b, year)
    out = {"status": status, "checks": checks}
    if status in ("eligible", "review"):
        fit = fit_score(b)
        if status == "eligible":
            status = "strong" if fit["score"] >= STRONG_SCORE else "possible"
        out.update(status=status, fit=fit)
    out["statusLabel"] = STATUS_LABELS[out["status"]]
    if b.get("type") == "Office" and in_city_of_la(b.get("address")):
        out["floors"] = floors(b, walk_entries, year)
        out["unplacedVacantSf"] = round(sum(float(s.get("sf") or 0) for s in b.get("spaces") or [] if not s.get("floor")))
    return out


def from_atlas(item, detail):
    """One Atlas index row and its detail file, as the record the screen works on."""
    avail = detail.get("availability") or {}
    spaces = avail["allSpaces"] if avail.get("allSpaces") is not None else (avail.get("spaces") or [])
    total = avail["allTotalSf"] if avail.get("allSpaces") is not None else (avail.get("totalSf") or 0)
    return {
        "id": item["id"], "name": item["name"], "street": item.get("address"), "address": detail.get("address"),
        "lat": item.get("lat"), "lon": item.get("lon"), "type": detail.get("type"), "buildingClass": detail.get("buildingClass"),
        "stories": detail.get("stories"), "yearBuilt": detail.get("yearBuilt"), "sizeSf": detail.get("sizeSf"),
        "typicalFloorSf": detail.get("typicalFloorSf"), "floorSf": detail.get("floorSf") or {},
        "zoning": detail.get("zoning"), "tenancies": detail.get("tenancies") or [],
        "spaces": spaces, "availableSf": total or 0, "photo": item.get("photo"), "daylight": None,
    }


def load_atlas(data=DATA):
    index_path = data / "index" / f"{CITY}.json"
    if not index_path.exists():
        sys.exit(f"{index_path} is missing: run  python pipeline/build_index.py <kit folder>  first")
    out = []
    for item in json.loads(index_path.read_text(encoding="utf-8")):
        detail_path = data / "property" / f"{item['id']}.json"
        if item.get("kind") == "commercial" and detail_path.exists():
            record = from_atlas(item, json.loads(detail_path.read_text(encoding="utf-8")))
            daylight_path = data / "daylight" / f"{item['id']}.json"       # pipeline/daylight.py, where it was run
            if daylight_path.exists():
                record["daylight"] = json.loads(daylight_path.read_text(encoding="utf-8"))
            out.append(record)
    return out


def write(buildings, out=DATA / "conversion", year=CURRENT_YEAR):
    """buildings: records from from_atlas()."""
    walk_entries = json.loads((Path(__file__).with_name("walkthroughs.json")).read_text(encoding="utf-8"))["floors"]
    (out / "property").mkdir(parents=True, exist_ok=True)
    rows, counts = [], {}
    for b in buildings:
        if b.get("lat") is None or b.get("lon") is None:
            continue
        walks = walkthroughs_for(b, walk_entries)
        result = assess(b, walks, year)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        fit = result.get("fit") or {}
        floor_rows = result.get("floors") or []
        rows.append({
            "id": b["id"], "name": b["name"], "address": b["street"], "lat": round(b["lat"], 6), "lon": round(b["lon"], 6),
            "type": b["type"], "stories": b.get("stories"), "sizeSf": b.get("sizeSf"), "yearBuilt": b.get("yearBuilt"),
            "buildingClass": b.get("buildingClass"), "zoning": b.get("zoning"),
            "status": result["status"], "score": fit.get("score"), "vacancy": fit.get("vacancy"),
            "availableSf": b.get("availableSf") or 0,
            "convertibleFloors": sum(1 for f in floor_rows if f["status"] == "convertible"),
            "walkthrough": bool(walks),
        })
        if "floors" in result:
            keep = ("id", "name", "address", "lat", "lon", "stories", "yearBuilt", "sizeSf", "buildingClass", "typicalFloorSf", "zoning", "photo")
            record = {**result, **{k: b.get(k) for k in keep},
                      "daylightPlate": (b.get("daylight") or {}).get("plate")}
            (out / "property" / f"{b['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    summary = {"city": CITY, "generated": date.today().isoformat(), "year": year, "source": "CoStar hackathon kit",
               "statusLabels": STATUS_LABELS, "sources": SOURCES, "counts": counts, "buildings": rows}
    (out / f"{CITY}.json").write_text(json.dumps(summary), encoding="utf-8")
    return counts


def main():
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA
    buildings = load_atlas(data)
    counts = write(buildings, data / "conversion")
    print(f"{len(buildings)} LA commercial properties screened:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
