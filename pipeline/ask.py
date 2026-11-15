"""Ask Census: a bridge from the browser to the Census deep agent (harness/, served by LangGraph Server).

The site does not run a model itself. Each question becomes one run on a LangGraph thread, so the agent server keeps
the conversation. The harness reports its work as custom stream events (route, tool, claim, focus, answer, metrics),
and `run` turns them into the plain dicts the page already understands, sent as server-sent events:

    {"type": "thread", "key", "id"}               a conversation id; the page sends {key: id, ...} back as `threads`
    {"type": "step", "text": ...}                  one line for the activity trail
    {"type": "action", "name", "input"}            something for the page to do
    {"type": "text", "text": ...}                  the answer, citation markers numbered [1], [2], ...
    {"type": "sources", "items": [{n, claim_id, statement}]}
    {"type": "layout", "scan", "floor", "image", "summary"}   an apartment layout the conversion agent wrote
    {"type": "error", "message": ...}

Questions about laying out apartments on an interior scan ("lay out apartments on this space") go to the second graph
on the same agent server, `conversion` (harness/mundus_harness/conversion/): an orchestrator with layout, compliance
and cost subagents that works on one preprocessed floor scan. `run` picks that agent when the page asks for it or the
question asks for a layout, prepares the floor the first time (pipeline/floorprep.py, pipeline/market.py), and streams
the agents' tool calls as steps.

Standard library only, so the site runs without the harness installed.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from . import config

GRAPH = "mundus"
CONVERSION_GRAPH = "conversion"
CITY = "los-angeles"  # the harness world holds Los Angeles places only
MARKER = re.compile(r"\[(claim:[0-9a-f]{6,32})\]")
AGENT_NAMES = {"market-analyst": "Market analyst", "interior-inspector": "Interior inspector",
               "aerial-analyst": "Aerial analyst"}
QUIET_TOOLS = {"put_claim", "set_focus", "SubagentResult", "ls", "glob", "grep"}

# A layout request: a verb of designing plus something residential, or a word that only means a layout.
_DESIGN = re.compile(r"\b(design|draw|lay(ing)? ?out|layouts?|plan|build|convert|conversion|turn|fit|make|propose|"
                     r"redo|redraw|re-?draft|draft|what if)\b", re.I)
_HOMES = re.compile(r"\b(apartments?|flats?|units?|homes?|housing|residential|residences?|studios?|lofts?|"
                    r"[1-4] ?(br|bed(room)?s?)|one-bed(room)?s?|two-bed(room)?s?|bedrooms?)\b", re.I)
_ONLY_LAYOUT = re.compile(r"\b(apartment layout|unit mix|adaptive reuse layout|office[- ]to[- ](residential|housing|apartments?))\b", re.I)
CONVERSION_AGENTS = {"layout": "Layout agent", "compliance": "Compliance agent", "cost": "Cost agent"}
CONVERSION_PHRASES = {
    "read_floor": "reading the floor: facade, windows, core and columns",
    "draft_layout": "drawing a layout", "check_layout": "checking the layout against the rules",
    "read_market": "reading nearby apartment rents", "estimate_returns": "working out rent, cost and yield",
    "write_layout": "saving the final layout", "web_search": "checking a code rule online",
}


def _request(url, body=None, headers=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _agent_headers():
    return {"X-Agent-Token": config.AGENT_TOKEN} if config.AGENT_TOKEN else {}


def _world_json(path):
    headers = {"Authorization": f"Bearer {config.WORLD_API_TOKEN}"} if config.WORLD_API_TOKEN else {}
    try:
        with _request(config.WORLD_REST_URL + path, headers=headers, timeout=5) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def agent_ready():
    try:
        with _request(config.HARNESS_URL + "/ok", headers=_agent_headers(), timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _new_thread():
    with _request(config.HARNESS_URL + "/threads", {"metadata": {"source": "census-web"}}, _agent_headers()) as r:
        return json.load(r)["thread_id"]


def _sse(response):
    """Yields (event, data) pairs from a server-sent event stream."""
    event, data = "message", []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, "\n".join(data)


def place_id_for(prop):
    """The harness place id for the property open on the page."""
    if not prop or prop.get("id") is None:
        return None
    return f"place:{'home' if prop.get('kind') == 'home' else 'costar'}:{prop['id']}"


def page_target(place_id):
    """The page's open_property input for a harness place id, or None for ids the page cannot open."""
    m = re.fullmatch(r"place:(costar|home):(\d+)", place_id or "")
    if not m:
        return None
    return {"city": CITY, "kind": "home" if m.group(1) == "home" else "commercial", "id": int(m.group(2))}


class Translator:
    """Turns harness stream events into page events. One instance per question."""

    def __init__(self, open_place=None):
        self.statements = {}      # claim id -> statement, from claims written during this run
        self.names = {}           # place id -> name
        self.open_place = open_place

    def name(self, place_id):
        if place_id not in self.names:
            place = _world_json(f"/v1/places/{quote(place_id, safe='')}") or {}
            self.names[place_id] = place.get("name") or place_id
        return self.names[place_id]

    def __call__(self, ev):
        kind = ev.get("type")
        if kind == "route":
            yield from self._route(ev)
        elif kind == "tool":
            text = self._tool(ev.get("agent"), ev.get("name"), ev.get("args") or {})
            if text:
                yield {"type": "step", "text": text}
        elif kind == "claim":
            self.statements[ev["claim_id"]] = ev.get("statement", "")
            who = AGENT_NAMES.get(ev.get("agent"), "Census")
            yield {"type": "step", "text": f"{who} saved: {ev.get('statement', '')}"}
        elif kind == "conflict":
            yield {"type": "step", "text": f"Found a conflicting earlier fact on {ev.get('predicate')}; memory kept one of them."}
        elif kind == "focus":
            target = page_target(ev.get("place_id"))
            if target and ev.get("place_id") != self.open_place:
                self.open_place = ev["place_id"]
                yield {"type": "action", "name": "open_property", "input": target}
        elif kind == "answer":
            yield from self._answer(ev)
        elif kind == "metrics":
            yield {"type": "step", "text": self._metrics(ev)}

    def _route(self, ev):
        pid = ev.get("place_id")
        if not pid:
            return
        where = self.name(pid)
        missing, covered = ev.get("facets_missing") or [], ev.get("facets_covered") or []
        if ev.get("route") == "card_hit":
            text = f"World memory already covers this for {where}. Answering from it."
        elif covered:
            text = f"World memory has {', '.join(covered)} for {where}. Looking up {', '.join(missing)}."
        else:
            text = f"Nothing in world memory yet for {where}. Looking up {', '.join(missing) or 'the facts'}."
        yield {"type": "step", "text": text}

    def _tool(self, agent, name, args):
        if name in QUIET_TOOLS:
            return None
        who = AGENT_NAMES.get(agent)
        if name == "task":
            sub = AGENT_NAMES.get(args.get("subagent_type"), args.get("subagent_type", "a helper"))
            return f"Asked the {sub.lower()}: {args.get('description', '')[:160]}"
        if name == "write_todos":
            todos = args.get("todos")
            items = [t.get("content", "") for t in todos] if isinstance(todos, list) else []
            return "Plan: " + "; ".join(items) if items else None
        if name == "resolve_place":
            return f"Looking up the place: {args.get('text', '')[:100]}"
        if name == "read_file":
            path = args.get("file_path", "")
            m = re.match(r"/world/places/([^/]+)/", path)
            if m:
                return f"Reading what world memory holds on {self.name(m.group(1))}"
            return None if path.startswith(("/skills/", "/memory/", "/runs/")) else f"Reading {path}"
        if name in ("write_file", "edit_file"):
            return None
        phrases = {
            "query_market": "querying CoStar records", "describe_market": "reading the CoStar table layout",
            "get_place": "reading the place record", "get_space": "reading an interior scan",
            "get_room": "reading a room", "search_interiors": "searching interior photo captions",
            "look_at_pano": "looking at an interior photo", "look_at_aerial": f"looking at the {args.get('kind', 'ortho')} aerial photo",
            "aerial_semantic_search": "searching aerial photos", "get_neighbors": "checking nearby places",
            "get_claims": "checking world memory", "get_evidence": "checking a source record",
            "search_places": "searching places",
        }
        action = phrases.get(name, f"using {name}")
        return f"{who}: {action}" if who else action[:1].upper() + action[1:]

    def _answer(self, ev):
        order = []
        for cid in MARKER.findall(ev.get("text", "")):
            if cid not in order:
                order.append(cid)
        text = MARKER.sub(lambda m: f"[{order.index(m.group(1)) + 1}]", ev.get("text", ""))
        yield {"type": "text", "text": text}
        if order:
            items = []
            for n, cid in enumerate(order, 1):
                statement = self.statements.get(cid)
                if statement is None:
                    statement = (_world_json(f"/v1/claims/{quote(cid, safe='')}") or {}).get("statement", "")
                items.append({"n": n, "claim_id": cid, "statement": statement})
            yield {"type": "sources", "items": items}

    @staticmethod
    def _metrics(ev):
        parts = [f"{ev.get('model_calls', 0)} model calls", f"{ev.get('tool_calls', 0)} tool calls"]
        if ev.get("tokens_total"):
            parts.append(f"{ev['tokens_total']:,} tokens")
        if ev.get("est_cost_usd") is not None:
            parts.append(f"about ${ev['est_cost_usd']:.2f}")
        seconds = (ev.get("latency_ms") or 0) / 1000
        return f"Done in {seconds:.0f} s: " + ", ".join(parts) + "."


def _stream(thread_id, question, place_id):
    body = {
        "assistant_id": GRAPH,
        "input": {"messages": [{"role": "user", "content": question}]},
        "stream_mode": ["custom"],
        "stream_subgraphs": True,
        "config": {"recursion_limit": 200},
    }
    if place_id:
        body["context"] = {"place_id": place_id}
    return _request(f"{config.HARNESS_URL}/threads/{thread_id}/runs/stream", body, _agent_headers(), timeout=900)


def run(question, threads=None, context=None, agent=None):
    """Asks one question and yields page events. `threads` maps a conversation key to its agent-server thread: "mundus"
    for the place agent, "conversion:<scan>" for the apartment agent on one space (a plain string is the mundus one)."""
    context = context or {}
    threads = threads if isinstance(threads, dict) else {GRAPH: threads} if threads else {}
    if agent == CONVERSION_GRAPH or (agent is None and wants_layout(question) and context.get("property")):
        yield from run_conversion(question, threads, context)
        return
    thread_id = threads.get(GRAPH)
    prop = context.get("property")
    # The open property goes to the router as context.place_id: it answers "this building" questions, and a place
    # named in the question still wins. The question itself is sent unchanged.
    place_id = place_id_for(prop)
    try:
        if not thread_id:
            thread_id = _new_thread()
        try:
            response = _stream(thread_id, question, place_id)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            # the agent server forgot the thread (it keeps threads in memory and was restarted): start a new one
            thread_id = _new_thread()
            yield {"type": "step", "text": "The agent server restarted, so this is a new conversation."}
            response = _stream(thread_id, question, place_id)
        yield {"type": "thread", "key": GRAPH, "id": thread_id}
        translate = Translator(open_place=place_id)
        answered = False
        with response:
            for event, data in _sse(response):
                if event == "error":
                    try:
                        detail = json.loads(data)
                    except ValueError:
                        detail = {"message": data}
                    yield {"type": "error", "message": f"The agent stopped with an error: {detail.get('message') or detail}"}
                    return
                if not event.startswith("custom"):
                    continue
                try:
                    ev = json.loads(data)
                except ValueError:
                    continue
                answered = answered or ev.get("type") == "answer"
                yield from translate(ev)
        if not answered:
            yield {"type": "error", "message": "The agent finished without an answer."}
    except urllib.error.HTTPError as error:
        if error.code == 401:
            yield {"type": "error", "message": "The agent server rejected the request. Check AGENT_TOKEN in .env."}
        else:
            yield {"type": "error", "message": f"The agent server returned an error ({error.code})."}
    except (urllib.error.URLError, OSError):
        yield {"type": "error", "message": f"Could not reach the agent server at {config.HARNESS_URL}."}


# ---- apartment layouts: the conversion agent ------------------------------------------------------------------------

def wants_layout(question):
    """True when the question asks for apartments to be laid out, rather than about the market or the building."""
    q = question or ""
    return bool(_ONLY_LAYOUT.search(q) or (_DESIGN.search(q) and _HOMES.search(q)))


def pick_scan(context):
    """(scan, None) for the space the layout is for, or (None, reason) when there is no single obvious one.
    The scan open in the 3-D view wins; otherwise the property's only scan with a floor number."""
    if context.get("scan", {}) and context["scan"].get("id"):
        return context["scan"], None
    scans = [s for s in context.get("scans") or [] if s.get("id")]
    if not scans:
        return None, ("The apartment agent works on an interior scan of one floor, and no Matterport scan is linked to "
                      "this property.")
    if len(scans) == 1:
        return scans[0], None
    names = "; ".join(f"{s.get('name') or s['id']}" + (f" (floor {s['floor']})" if s.get("floor") else "") for s in scans[:8])
    return None, (f"This property has {len(scans)} scanned spaces: {names}. Open one in the Interiors tab (Show in "
                  "model, or Design apartments) and ask again, so the agent knows which space to lay out.")


def conversion_dir(scan_id):
    return config.DATA / "conversion" / scan_id


def prepare_floor(scan, prop):
    """Preprocesses the floor scan and its market summary the first time; yields steps. Raises RuntimeError."""
    folder = conversion_dir(scan["id"])
    prop_id = prop.get("id") if prop else None
    prop_id = int(prop_id) if prop_id not in (None, "") else None
    floor = scan.get("floor")
    if not (folder / "grid.npz").exists():
        yield {"type": "step", "text": "Preparing the floor for the first time: reading the scan's floor plan, mesh, "
                                       "windows, core and columns from Matterport. This takes a minute or two."}
        try:
            from . import floorprep
        except ImportError as error:
            raise RuntimeError(f"Preparing a floor needs {error.name}: pip install opencv-python-headless numpy scipy "
                               "pillow requests") from error
        try:
            geo, struct = floorprep.run(scan["id"], prop_id, floor)
        except Exception as error:  # Matterport refused, no floor plan image, a multi-floor scan
            raise RuntimeError(f"This space could not be prepared for the apartment agent: {error}") from error
        yield {"type": "step", "text": f"Floor ready: plate {geo['plate_sf']:,} sq ft, windows on "
                                       f"{geo['window_share_of_facade']:.0%} of the facade, {len(struct['core'])} core "
                                       f"block(s), {len(struct['columns'])} possible columns."}
    if not (folder / "market.json").exists() and prop_id and floor:
        try:
            from . import market
            market.run(scan["id"], prop_id, int(floor), config.ROOT / "raw" / "costar")
            yield {"type": "step", "text": "Pulled nearby apartment rents from the CoStar kit."}
        except Exception as error:  # no kit on this machine, or the property is not in it: the cost agent says so
            yield {"type": "step", "text": f"No market summary for this floor ({error}); rents will be unknown."}


def _conversion_message(question, scan, first):
    if not first:
        return f"Floor scan {scan['id']}. {question}"
    where = f"floor {scan['floor']} of " if scan.get("floor") else ""
    return (f"Convert office floor scan {scan['id']} ({where}{scan.get('name') or 'the open space'}) into a rough-draft "
            f"apartment layout. Follow your process and write the layout with write_layout. The developer asked: {question}")


def _stream_conversion(thread_id, message):
    body = {
        "assistant_id": CONVERSION_GRAPH,
        "input": {"messages": [{"role": "user", "content": message}]},
        "stream_mode": ["updates"],
        "stream_subgraphs": True,
        "config": {"recursion_limit": 300},
    }
    return _request(f"{config.HARNESS_URL}/threads/{thread_id}/runs/stream", body, _agent_headers(), timeout=1800)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


class ConversionTranslator:
    """Turns the conversion graph's `updates` stream into page steps, and keeps the orchestrator's last answer."""

    def __init__(self):
        self.answer = ""

    def __call__(self, event, data):
        top = "|" not in event              # "updates" is the orchestrator; "updates|tools:..." a subagent
        for payload in (data.values() if isinstance(data, dict) else []):
            messages = payload.get("messages") if isinstance(payload, dict) else None
            if isinstance(messages, dict):  # an Overwrite wrapper
                messages = messages.get("value")
            for m in messages if isinstance(messages, list) else []:
                if not isinstance(m, dict):
                    continue
                if m.get("type") == "ai":
                    for call in m.get("tool_calls") or []:
                        text = self.tool_step(call.get("name"), call.get("args") or {})
                        if text:
                            yield {"type": "step", "text": text}
                    if top and not m.get("tool_calls"):
                        text = _text_of(m.get("content")).strip()
                        if text:
                            self.answer = text
                elif m.get("type") == "tool":
                    text = self.result_step(m.get("name"), _text_of(m.get("content")))
                    if text:
                        yield {"type": "step", "text": text}

    @staticmethod
    def tool_step(name, args):
        if name == "task":
            who = CONVERSION_AGENTS.get(args.get("subagent_type"), args.get("subagent_type", "a helper"))
            return f"Asked the {who.lower()}: {args.get('description', '')[:160]}"
        if name == "write_todos":
            todos = args.get("todos")
            items = [t.get("content", "") for t in todos] if isinstance(todos, list) else []
            return "Plan: " + "; ".join(items) if items else None
        phrase = CONVERSION_PHRASES.get(name)
        if not phrase:
            return None
        if name == "draft_layout" and isinstance(args.get("sides"), dict):
            n = sum(1 for units in args["sides"].values() for u in units or [] if isinstance(u, dict) and u.get("type") != "gap")
            phrase += f" with {n} units"
        if name == "web_search" and args.get("query"):
            phrase += f": {str(args['query'])[:100]}"
        return phrase[:1].upper() + phrase[1:]

    @staticmethod
    def result_step(name, text):
        try:
            r = json.loads(text)
        except ValueError:
            return None
        if not isinstance(r, dict):
            return None
        if r.get("error"):
            return f"{name} said: {str(r['error'])[:200]}"
        if name == "draft_layout":
            mix = ", ".join(f"{v} {k}" for k, v in (r.get("unit_mix") or {}).items())
            counts = r.get("counts") or {}
            return (f"{r.get('draft_id')}: {r.get('units')} units ({mix}), {r.get('rentable_sf', 0):,} sq ft; "
                    f"{counts.get('pass', 0)} pass, {counts.get('fail', 0)} fail, {counts.get('unknown', 0)} unknown.")
        if name == "estimate_returns" and r.get("monthly_rent_usd") is not None:
            y = r.get("simple_yield")
            return (f"{r.get('draft_id')}: about ${r['monthly_rent_usd']:,} a month in rent, conversion about "
                    f"${r.get('conversion_cost_usd', 0):,}" + (f", simple yield {y:.1%}." if y is not None else "."))
        return None


def layout_event(scan):
    """The page event for the layout the agent saved: the summary and a drawing of it over the floor plan."""
    folder = conversion_dir(scan["id"])
    layout = json.loads((folder / "layout.json").read_text(encoding="utf-8"))
    image = None
    try:
        from . import layout_render
        png = layout_render.render(scan["id"])
        image = f"/data/conversion/{scan['id']}/{png.name}?v={int(png.stat().st_mtime)}"
    except Exception:  # noqa: BLE001 - no plan image or Pillow missing: the summary still stands
        pass
    return {"type": "layout", "scan": scan["id"], "floor": layout.get("floor") or scan.get("floor"),
            "name": scan.get("name"), "image": image, "summary": layout.get("summary") or {}}


def run_conversion(question, threads, context):
    """Asks the conversion agent to lay out apartments on one scanned space; yields page events."""
    scan, reason = pick_scan(context)
    if not scan:
        yield {"type": "text", "text": reason}
        return
    key = f"{CONVERSION_GRAPH}:{scan['id']}"   # one conversation per space: drafts and what-ifs stay with their floor
    thread_id = threads.get(key)
    yield {"type": "action", "name": "open_scan", "input": {"scan_id": scan["id"]}}
    try:
        yield from prepare_floor(scan, context.get("property"))
    except RuntimeError as error:
        yield {"type": "error", "message": str(error)}
        return
    out = conversion_dir(scan["id"]) / "layout.json"
    before = out.stat().st_mtime if out.exists() else 0
    try:
        first = not thread_id
        if first:
            thread_id = _new_thread()
        try:
            response = _stream_conversion(thread_id, _conversion_message(question, scan, first))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            thread_id = _new_thread()
            yield {"type": "step", "text": "The agent server restarted, so this is a new conversation."}
            response = _stream_conversion(thread_id, _conversion_message(question, scan, True))
        yield {"type": "thread", "key": key, "id": thread_id}
        yield {"type": "step", "text": f"Sent {scan.get('name') or scan['id']} to the apartment agent: it drafts a "
                                       "layout, checks it against Los Angeles rules and prices it."}
        translate = ConversionTranslator()
        with response:
            for event, data in _sse(response):
                if event == "error":
                    try:
                        detail = json.loads(data)
                    except ValueError:
                        detail = {"message": data}
                    yield {"type": "error", "message": f"The apartment agent stopped with an error: {detail.get('message') or detail}"}
                    return
                if not event.startswith("updates"):
                    continue
                try:
                    yield from translate(event, json.loads(data))
                except ValueError:
                    continue
        if out.exists() and out.stat().st_mtime > before:
            yield layout_event(scan)
        if translate.answer:
            yield {"type": "text", "text": translate.answer}
        elif not (out.exists() and out.stat().st_mtime > before):
            yield {"type": "error", "message": "The apartment agent finished without a layout."}
    except urllib.error.HTTPError as error:
        if error.code == 401:
            yield {"type": "error", "message": "The agent server rejected the request. Check AGENT_TOKEN in .env."}
        elif error.code in (404, 422):
            yield {"type": "error", "message": "The agent server has no conversion graph. Restart it from harness/ "
                                               "(langgraph.json lists both graphs)."}
        else:
            yield {"type": "error", "message": f"The agent server returned an error ({error.code})."}
    except (urllib.error.URLError, OSError):
        yield {"type": "error", "message": f"Could not reach the agent server at {config.HARNESS_URL}."}
