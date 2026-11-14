"""Ask Atlas: a Claude agent that answers questions by combining the three data layers.

It searches CoStar records, measures from Vexcel aerial imagery, reads Matterport scans, and
drives the page (opens a property, marks floors, pulls out a scan). `run` yields plain dicts
that the server forwards to the browser as server-sent events:

    {"type": "text", "text": ...}       streamed answer text
    {"type": "step", "text": ...}       one line per tool call, for the activity trail
    {"type": "action", "name", "input"} something for the page to do
    {"type": "error", "message": ...}
"""
import json

import anthropic

from . import config, twin, vexcel

MODEL = "claude-opus-5-5"
MAX_TURNS = 14
CITIES = ("houston", "los-angeles")

SYSTEM = """You are Atlas, an analyst inside a property viewer covering Houston and Los Angeles.

You have three kinds of evidence, all for the same addresses:
- CoStar records: buildings, floor-by-floor tenants, space for lease with asking rents, sales, apartment floor plans, home listings.
- Vexcel aerial survey: measured building height, roof material and condition, and object detection on the aerial photo (cars, pools, solar panels, anything you can name).
- Matterport interior scans: measured floor area, room types and capture points for scanned suites and homes.

How to work:
- Look things up with the tools before answering. Never state a figure you did not get from a tool.
- Prefer answers that combine layers, for example an asking rent from CoStar with the scanned area of the same suite, or parking demand from the aerial photo against the tenant count.
- Say which layer each figure came from when it matters, and say plainly when a layer has nothing.
- Drive the page as you go: open the property you are discussing, mark the floors you mention, pull out a scan you describe. Do it without asking.
- Asking rents for office space are dollars per square foot per year. Annual cost is rent times area.
- Keep answers short and concrete: a direct answer first, then the few figures behind it. Plain sentences, no headings, no bullet symbols, no bold.
"""


def _tool(name, description, properties, required=()):
    return {
        "name": name, "description": description, "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False},
    }


_CITY = {"type": "string", "enum": list(CITIES)}
_KIND = {"type": "string", "enum": ["commercial", "home"], "description": "commercial for buildings, home for residential listings"}
_ID = {"type": "integer", "description": "Property id from search_properties"}

TOOLS = [
    _tool("search_properties",
          "Search every indexed property and home in one city. Returns up to `limit` rows with id, kind, name, address, type, "
          "stories, size, year built, number of interior scans, tenant-record count and square feet available. "
          "Use this first to find candidates; all filters are optional and combine.",
          {"city": _CITY,
           "type": {"type": "string", "description": "Office, Multifamily, Home, Industrial, Hospitality, General Retail, Flex, Land, Specialty or Healthcare"},
           "text": {"type": "string", "description": "Matches the name or street address"},
           "min_stories": {"type": "integer"}, "min_size_sf": {"type": "number"}, "min_available_sf": {"type": "number"},
           "max_price": {"type": "number", "description": "Homes only: asking price or monthly rent"},
           "has_scans": {"type": "boolean"},
           "sort": {"type": "string", "enum": ["scans", "size", "stories", "available", "tenancies", "newest"]},
           "limit": {"type": "integer", "description": "Default 12, at most 40"}},
          required=["city"]),
    _tool("get_property",
          "Full CoStar record for one property: facts, current tenants by floor, every space for lease with asking rent, "
          "sales, apartment floor plans or home listing details, and the ids of its interior scans.",
          {"kind": _KIND, "id": _ID}, required=["kind", "id"]),
    _tool("floor_report",
          "Floor-by-floor status of a commercial building today: leased square feet, tenants, available suites and whether a scan exists. "
          "Use it to find empty or partly empty floors.",
          {"id": _ID}, required=["id"]),
    _tool("aerial_survey",
          "Vexcel measurements for a property: building height from the surface model, roof material, shape and condition, "
          "footprint area, tree cover, and how many neighbouring buildings were mapped. Also lists its interior scans with measured area and room types.",
          {"kind": _KIND, "id": _ID}, required=["kind", "id"]),
    _tool("count_from_air",
          "Run object detection on the current aerial photo of a property's site and count what is visible. "
          "Give specific labels, for example 'car', 'swimming pool', 'solar panel', 'loading dock', 'tennis court'.",
          {"kind": _KIND, "id": _ID, "labels": {"type": "array", "items": {"type": "string"}, "description": "One to five things to count"},
           "radius_m": {"type": "integer", "description": "Half-width of the square to scan, 30 to 150. Default 70."}},
          required=["kind", "id", "labels"]),
    _tool("search_aerial_nearby",
          "Search the aerial imagery around a property by description (for example 'park', 'surface parking lot', 'construction site') "
          "and return the best-matching locations with distance from the property.",
          {"kind": _KIND, "id": _ID, "description": {"type": "string"}}, required=["kind", "id", "description"]),
    _tool("open_property", "Open a property in the 3-D viewer so the user sees it.",
          {"city": _CITY, "kind": _KIND, "id": _ID}, required=["city", "kind", "id"]),
    _tool("show_list", "Show a set of properties as the list and map for a city, replacing the current results.",
          {"city": _CITY, "ids": {"type": "array", "items": {"type": "integer"}}}, required=["city", "ids"]),
    _tool("mark_floors", "Highlight floors on the open building's model.",
          {"floors": {"type": "array", "items": {"type": "integer"}}}, required=["floors"]),
    _tool("set_view", "Change how the open building is drawn: model (glass shell), floors (shell removed), stacked (floors pulled apart) or plan (top-down).",
          {"view": {"type": "string", "enum": ["model", "floors", "stacked", "plan"]}}, required=["view"]),
    _tool("open_scan", "Pull an interior scan out of the open building and show it cut open. Use a scan id from aerial_survey or get_property.",
          {"scan_id": {"type": "string"}}, required=["scan_id"]),
]
PAGE_ACTIONS = {"open_property", "show_list", "mark_floors", "set_view", "open_scan"}
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}

_index_cache = {}


def _index(city):
    if city not in _index_cache:
        _index_cache[city] = json.loads((config.DATA / "index" / f"{city}.json").read_text(encoding="utf-8"))
    return _index_cache[city]


# ---- tool implementations ------------------------------------------------------
def search_properties(city, type=None, text=None, min_stories=None, min_size_sf=None, min_available_sf=None,
                      max_price=None, has_scans=None, sort="scans", limit=12):
    rows = _index(city)
    if type:
        rows = [r for r in rows if r["type"].lower() == type.lower()]
    if text:
        needle = text.lower()
        rows = [r for r in rows if needle in f"{r['name']} {r['address']}".lower()]
    if min_stories:
        rows = [r for r in rows if (r.get("stories") or 0) >= min_stories]
    if min_size_sf:
        rows = [r for r in rows if (r.get("sizeSf") or 0) >= min_size_sf]
    if min_available_sf:
        rows = [r for r in rows if (r.get("availableSf") or 0) >= min_available_sf]
    if max_price:
        rows = [r for r in rows if r.get("price") and r["price"] <= max_price]
    if has_scans is not None:
        rows = [r for r in rows if bool(r["scans"]) == has_scans]
    keys = {"scans": "scans", "size": "sizeSf", "stories": "stories", "available": "availableSf", "tenancies": "tenancies", "newest": "yearBuilt"}
    rows = sorted(rows, key=lambda r: r.get(keys.get(sort, "scans")) or 0, reverse=True)
    limit = max(1, min(limit or 12, 40))
    return {"matches": len(rows), "rows": [{k: v for k, v in r.items() if k not in ("photo", "lat", "lon") and v not in (None, 0, False)} | {"id": r["id"]} for r in rows[:limit]]}


def get_property(kind, id):
    d = twin.load_detail(kind, id)
    out = {k: v for k, v in d.items() if k not in ("photos", "tenancies", "floorSf", "description", "lat", "lon")}
    out["description"] = (d.get("description") or "")[:600]
    if kind == "commercial":
        current = {}
        for t in d.get("tenancies") or []:
            if t["to"] is None:
                entry = current.setdefault(t["tenant"], {"tenant": t["tenant"], "industry": t["industry"], "sf": 0, "floors": set(), "since": t["from"]})
                entry["sf"] += t["sf"] or 0
                if t["floor"]:
                    entry["floors"].add(t["floor"])
        tenants = sorted(current.values(), key=lambda e: -e["sf"])[:30]
        out["currentTenants"] = [{**e, "floors": sorted(e["floors"])} for e in tenants]
        out["tenancyRecordsAllTime"] = len(d.get("tenancies") or [])
    return out


def floor_report(id):
    d = twin.load_detail("commercial", id)
    stories = d.get("stories") or 1
    typical = d.get("typicalFloorSf") or ((d.get("sizeSf") or 0) / stories)
    floors = {n: {"floor": n, "leasedSf": 0, "tenants": [], "available": []} for n in range(1, stories + 1)}
    for t in d.get("tenancies") or []:
        if t["to"] is None and t["floor"] in floors:
            floors[t["floor"]]["leasedSf"] += t["sf"] or 0
            floors[t["floor"]]["tenants"].append(t["tenant"])
    for s in (d.get("availability") or {}).get("spaces") or []:
        if s["floor"] in floors:
            floors[s["floor"]]["available"].append({"suite": s["suite"], "sf": s["sf"], "askingRate": s["rate"], "fullFloor": s["fullFloor"]})
    rows = [f for f in floors.values() if f["tenants"] or f["available"]]
    return {"name": d["name"], "stories": stories, "typicalFloorSf": round(typical),
            "floorsWithRecords": rows, "floorsWithNoRecord": [n for n, f in floors.items() if not f["tenants"] and not f["available"]]}


def aerial_survey(kind, id):
    t = twin.get(kind, id)
    return {"heightMeters": t["building"]["top"], "heightFeet": round(t["building"]["top"] * 3.28084),
            "stories": t["building"]["stories"], "storiesEstimatedFromHeight": t["building"]["storiesEstimated"],
            "facts": dict(t["aerialFacts"]), "neighbouringBuildingsMapped": len(t["neighbours"]),
            "tallestNeighbourMeters": max((n["height"] for n in t["neighbours"]), default=0),
            "interiorScans": t["scans"]}


def count_from_air(kind, id, labels, radius_m=70):
    d = twin.load_detail(kind, id)
    radius = max(30, min(radius_m or 70, 150))
    found = vexcel.detect(vexcel.square(d["lat"], d["lon"], radius), labels[:5])
    return {"areaScanned": f"{2 * radius} m square centred on the property",
            "counts": {label: len(hits) for label, hits in found.items()},
            "note": "Counts come from one aerial capture and include neighbouring lots inside the square."}


def search_aerial_nearby(kind, id, description):
    d = twin.load_detail(kind, id)
    hits = vexcel.search_similar(vexcel.square(d["lat"], d["lon"], 1000), description)
    m_lat = vexcel.METERS_PER_DEGREE
    out = []
    for h in hits:
        north = (h["lat"] - d["lat"]) * m_lat
        east = (h["lon"] - d["lon"]) * m_lat * 0.87
        out.append({"distanceMeters": round((north ** 2 + east ** 2) ** 0.5), "direction": ("north" if north > 0 else "south") + ("east" if east > 0 else "west"), "score": h["score"]})
    return {"searched": "2 km square around the property", "matches": out, "note": "Scores are relative; compare within this search only."}


IMPLEMENTATIONS = {f.__name__: f for f in (search_properties, get_property, floor_report, aerial_survey, count_from_air, search_aerial_nearby)}


def _describe(name, args):
    """One human line per tool call for the activity trail."""
    if name == "search_properties":
        bits = [args.get("type"), args.get("text"), args.get("min_stories") and f"{args['min_stories']}+ stories",
                args.get("min_available_sf") and f"{int(args['min_available_sf']):,}+ sq ft available"]
        return f"Searching {args.get('city', '').replace('-', ' ').title()}: {', '.join(str(b) for b in bits if b) or 'all properties'}"
    return {
        "get_property": "Reading the CoStar record", "floor_report": "Going through the building floor by floor",
        "aerial_survey": "Measuring from the aerial survey", "count_from_air": f"Counting {', '.join(args.get('labels', []))} on the aerial photo",
        "search_aerial_nearby": f"Searching the aerial imagery nearby for {args.get('description', '')}",
        "open_property": "Opening the property", "show_list": "Showing the shortlist on the map",
        "mark_floors": "Marking floors on the model", "set_view": f"Switching to the {args.get('view', '')} view", "open_scan": "Pulling out the interior scan",
    }.get(name, name)


def _invalid(name, args):
    """Eager input streaming skips server-side validation, so check required fields here."""
    if not isinstance(args, dict):
        return "input was not a JSON object"
    schema = _SCHEMAS[name]
    missing = [key for key in schema["required"] if key not in args]
    unknown = [key for key in args if key not in schema["properties"]]
    if missing or unknown:
        return f"missing {missing}, unexpected {unknown}"
    return None


def _run_tool(block):
    """Execute one tool call. Returns (tool_result content, is_error, page action or None)."""
    problem = _invalid(block.name, block.input)
    if problem:
        return f"Invalid input: {problem}", True, None
    if block.name in PAGE_ACTIONS:
        return "Done. The page has been updated.", False, {"type": "action", "name": block.name, "input": block.input}
    try:
        result = IMPLEMENTATIONS[block.name](**block.input)
        return json.dumps(result, default=list)[:60000], False, None
    except FileNotFoundError as error:
        return str(error), True, None
    except Exception as error:  # upstream API failure: tell the model so it can say so or try another route
        return f"{type(error).__name__}: {error}", True, None


def run(history, context):
    """Generator of events for one user turn. `history` is [{role, content}] of plain-text turns."""
    if not config.ANTHROPIC_API_KEY:
        yield {"type": "error", "message": "Ask Atlas needs ANTHROPIC_API_KEY in the .env file."}
        return
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    messages = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    on_screen = context.get("property")
    note = f"[On screen: city {context.get('city')}; " + (
        f"property open: {on_screen['name']} (kind {on_screen['kind']}, id {on_screen['id']})]" if on_screen else "no property open, the list and map are showing]")
    messages[-1] = {"role": "user", "content": f"{note}\n\n{messages[-1]['content']}"}

    try:
        for _ in range(MAX_TURNS):
            with client.beta.messages.stream(
                model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            ) as stream:
                for text in stream.text_stream:
                    yield {"type": "text", "text": text}
                response = stream.get_final_message()

            if response.stop_reason == "refusal":
                yield {"type": "error", "message": "The model declined this request."}
                return
            if response.stop_reason == "max_tokens":
                yield {"type": "error", "message": "The answer was cut off at the length limit."}
                return
            if response.stop_reason != "tool_use":
                return

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                yield {"type": "step", "text": _describe(block.name, block.input if isinstance(block.input, dict) else {})}
                content, is_error, action = _run_tool(block)
                if action:
                    yield action
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        yield {"type": "error", "message": "Stopped after too many steps."}
    except anthropic.AuthenticationError:
        yield {"type": "error", "message": "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env."}
    except anthropic.RateLimitError:
        yield {"type": "error", "message": "Rate limited by the Anthropic API. Try again in a moment."}
    except anthropic.APIStatusError as error:
        yield {"type": "error", "message": f"The Anthropic API returned an error ({error.status_code}): {error.message}"}
    except anthropic.APIConnectionError:
        yield {"type": "error", "message": "Could not reach the Anthropic API."}
