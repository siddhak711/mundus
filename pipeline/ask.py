"""Ask Atlas: a bridge from the browser to the Mundus deep agent (harness/, served by LangGraph Server).

The site does not run a model itself. Each question becomes one run on a LangGraph thread, so the agent server keeps
the conversation. The harness reports its work as custom stream events (route, tool, claim, focus, answer, metrics),
and `run` turns them into the plain dicts the page already understands, sent as server-sent events:

    {"type": "thread", "id": ...}                  the conversation id, sent back with the next question
    {"type": "step", "text": ...}                  one line for the activity trail
    {"type": "action", "name", "input"}            something for the page to do
    {"type": "text", "text": ...}                  the answer, citation markers numbered [1], [2], ...
    {"type": "sources", "items": [{n, claim_id, statement}]}
    {"type": "error", "message": ...}

Standard library only, so the site runs without the harness installed.
"""
import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote

from . import config

GRAPH = "mundus"
CITY = "los-angeles"  # the harness world holds Los Angeles places only
MARKER = re.compile(r"\[(claim:[0-9a-f]{6,32})\]")
AGENT_NAMES = {"market-analyst": "Market analyst", "interior-inspector": "Interior inspector",
               "aerial-analyst": "Aerial analyst"}
QUIET_TOOLS = {"put_claim", "set_focus", "SubagentResult", "ls", "glob", "grep"}


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
    with _request(config.HARNESS_URL + "/threads", {"metadata": {"source": "atlas-web"}}, _agent_headers()) as r:
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
            who = AGENT_NAMES.get(ev.get("agent"), "Atlas")
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


def run(question, thread_id=None, context=None):
    """Asks the deep agent one question on a thread and yields page events."""
    context = context or {}
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
        yield {"type": "thread", "id": thread_id}
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
