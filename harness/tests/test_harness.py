"""End-to-end harness tests with scripted models against the real backend on fixture data."""
from __future__ import annotations

import json

import httpx
from conftest import PLACE, ScriptedModel, tool_call
from langchain_core.messages import AIMessage, ToolMessage

from mundus_harness import runctx
from mundus_harness.graph import build_agent, load_world_tools
from mundus_harness.middleware.answer import resolve_markers
from mundus_harness.middleware.guard import check_sql
from mundus_harness.middleware.metrics import summarize
from mundus_harness.middleware.router import classify, parse_coverage
from mundus_harness.tools_local import build_local_tools
from mundus_harness.world_backend import WorldBackend
from mundus_harness.world_client import WorldClient


def _tool_text(msgs, name):
    m = [x for x in msgs if getattr(x, "name", "") == name][-1]
    return m.content if isinstance(m.content, str) else m.content[0]["text"]


def _evidence(cfg) -> str:
    return httpx.get(f"{cfg.world_rest_url}/v1/places/{PLACE}").json()["market"]["tenancies"]["items"][0]["evidence_id"]


async def _run(agent, question, run_id, context=None):
    events = []
    async for ns, mode, chunk in agent.astream({"messages": [{"role": "user", "content": question}]},
                                              config={"configurable": {"thread_id": run_id, "run_id": run_id}},
                                              context=context, stream_mode=["custom", "updates"], subgraphs=True):
        if mode == "custom":
            events.append((ns, chunk))
    return events


def cold_scripts(cfg, value="Acme Corp"):
    ev = _evidence(cfg)
    worker = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[tool_call("get_place", {"place_id": PLACE})]),
        AIMessage(content="", tool_calls=[
            tool_call("put_claim", {"subject_id": PLACE, "predicate": "market.largest_tenant", "value": value,
                                    "statement": f"{value} is the largest tenant.", "evidence_ids": [ev], "confidence": 0.9}, "c1"),
            tool_call("put_claim", {"subject_id": PLACE, "predicate": "market.tenant_count", "value": 3,
                                    "statement": "Three tenancies are recorded.", "evidence_ids": [ev], "confidence": 0.9}, "c2"),
            tool_call("put_claim", {"subject_id": PLACE, "predicate": "market.stories", "value": 5,
                                    "statement": "The building has five storeys.", "evidence_ids": [ev], "confidence": 0.9}, "c3")]),
        lambda msgs: AIMessage(content="", tool_calls=[tool_call("SubagentResult", {"findings": [
            {"claim_id": json.loads(_tool_text(msgs, "put_claim"))["claim"]["id"], "statement": "done", "confidence": 0.9}],
            "gaps": [], "notes_path": ""})]),
    ], calls=[])
    orch = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[tool_call("read_file", {"file_path": f"/world/places/{PLACE}/card.md"})]),
        AIMessage(content="", tool_calls=[tool_call("write_todos", {"todos": [{"content": "market", "status": "in_progress"}]})]),
        AIMessage(content="", tool_calls=[tool_call("task", {"description": f"Largest tenant of {PLACE}?",
                                                             "subagent_type": "market-analyst"})]),
        lambda msgs: AIMessage(content="Acme Corp is the largest tenant ["
                               + json.loads(_tool_text(msgs, "task"))["findings"][0]["claim_id"] + "]. Bogus [claim:00000000aaaaaaaa]."),
    ], calls=[])
    return orch, worker


async def test_cold_run_then_card_hit(cfg):
    wt = await load_world_tools(cfg)
    orch, worker = cold_scripts(cfg)
    agent = build_agent(cfg, wt, orch_model=orch, worker_model=worker)
    ev1 = await _run(agent, "Who is the largest tenant at Fixture Tower?", "run-cold")
    types = [e["type"] for _, e in ev1]
    assert types[0] == "route" and ev1[0][1]["route"] == "cold" and ev1[0][1]["place_id"] == PLACE
    assert types.count("claim") == 3 and all(ns != () for ns, e in ev1 if e["type"] == "claim")     # from the subagent
    answer = next(e for _, e in ev1 if e["type"] == "answer")
    assert len(answer["citations"]) == 1 and answer["dropped_markers"] == ["claim:00000000aaaaaaaa"]
    assert "00000000aaaaaaaa" not in answer["text"]
    m1 = next(e for _, e in ev1 if e["type"] == "metrics")
    assert m1["subagents_used"] == ["market-analyst"] and m1["claims_written"] == 3
    assert m1["tokens_total"] == sum(a["tokens_in"] + a["tokens_out"] for a in m1["by_agent"].values())
    assert m1["by_agent"]["market-analyst"]["model_calls"] == 3 and m1["time_to_first_action_ms"] is not None
    # same question again: the card now covers market, so the router says card_hit and swaps to the fast model
    fast = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[tool_call("read_file", {"file_path": f"/world/places/{PLACE}/card.md"})]),
        lambda msgs: AIMessage(content="Acme Corp is the largest tenant " + _tool_text(msgs, "read_file").split("largest tenant. ")[1][:24])],
        calls=[])
    never = ScriptedModel(script=[AIMessage(content="the frontier model must not be called on a card hit")], calls=[])
    agent2 = build_agent(cfg, wt, orch_model=never, worker_model=fast)
    ev2 = await _run(agent2, "Who is the largest tenant at Fixture Tower?", "run-warm")
    r2 = next(e for _, e in ev2 if e["type"] == "route")
    assert r2["route"] == "card_hit" and r2["facets_missing"] == []
    m2 = next(e for _, e in ev2 if e["type"] == "metrics")
    assert m2["subagents_used"] == [] and m2["model_calls"] <= 2 and not never.calls
    assert m2["baseline"]["model_calls"] == m1["model_calls"] and m2["savings"]["tokens_pct"] >= 60
    sys_text = str(fast.calls[0][0].content)
    assert "Do not delegate" in sys_text and "shared world memory" in sys_text      # note appended, prompt kept
    lines = (cfg.data_dir / "run_metrics.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["route"] == "card_hit"


async def test_unknown_place_resolves_to_nothing(cfg):
    wt = await load_world_tools(cfg)
    orch = ScriptedModel(script=[AIMessage(content="", tool_calls=[tool_call("resolve_place", {"text": "99999 Nowhere Blvd"})]),
                                 AIMessage(content="That place was not found.")], calls=[])
    agent = build_agent(cfg, wt, orch_model=orch, worker_model=ScriptedModel(script=[], calls=[]))
    ev = await _run(agent, "Tell me about 99999 Nowhere Blvd.", "run-nowhere")
    assert next(e for _, e in ev if e["type"] == "route")["place_id"] is None
    assert not [e for _, e in ev if e["type"] == "claim"]
    assert "no place was resolved" in str(orch.calls[0][0].content) and "shared world memory" in str(orch.calls[0][0].content)
    assert httpx.get(f"{cfg.world_rest_url}/v1/claims/places").json()["places"] == []


async def test_guard_blocks_bad_sql_and_marks_gaps(cfg):
    wt = await load_world_tools(cfg)
    worker = ScriptedModel(script=[
        AIMessage(content="", tool_calls=[tool_call("query_market", {"sql": "DELETE FROM place"}, "q1")]),
        AIMessage(content="", tool_calls=[tool_call("query_market", {"sql": "SELECT tenant_name, evidence_id FROM costar_occupancy"}, "q2")]),
        AIMessage(content="", tool_calls=[tool_call("get_place", {"place_id": "place:costar:404"}, "q3")]),
        AIMessage(content="", tool_calls=[tool_call("SubagentResult", {"findings": [], "gaps": ["place 404"], "notes_path": ""})]),
    ], calls=[])
    orch = ScriptedModel(script=[AIMessage(content="", tool_calls=[tool_call("task", {"description": "x", "subagent_type": "market-analyst"})]),
                                 AIMessage(content="Nothing found.")], calls=[])
    agent = build_agent(cfg, wt, orch_model=orch, worker_model=worker)
    before = httpx.get(f"{cfg.world_rest_url}/v1/stats", params={"run_id": "run-guard"}).json()["total_calls"]
    await _run(agent, "Fixture Tower tenants?", "run-guard")
    seen = [m for call in worker.calls for m in call if isinstance(m, ToolMessage)]
    by_id = {m.tool_call_id: (m.content if isinstance(m.content, str) else m.content[0]["text"]) for m in seen}
    assert by_id["q1"].startswith("Rejected before sending")
    assert "Acme Corp" in by_id["q2"] and "LIMIT 200" not in by_id["q2"]
    assert by_id["q3"].startswith("Unavailable:") and "Do not retry" in by_id["q3"]
    ops = {o["op"]: o["calls"] for o in httpx.get(f"{cfg.world_rest_url}/v1/stats", params={"run_id": "run-guard"}).json()["api_calls"]}
    assert ops.get("query_market") == 1 and ops.get("get_place") == 1 and before == 0     # the DELETE never left the harness


def test_world_backend_files(cfg):
    client = WorldClient(cfg)
    ev = _evidence(cfg)
    httpx.post(f"{cfg.world_rest_url}/v1/claims", json={"subject_id": PLACE, "predicate": "market.stories", "value": 5,
                                                       "statement": "Five storeys.", "evidence_ids": [ev]})
    b = WorldBackend(client, ttl_s=0)
    assert [e["path"] for e in b.ls("/places").entries] == [f"/places/{PLACE}/"]
    card = b.read(f"/places/{PLACE}/card.md").file_data["content"]
    assert "coverage:" in card and "[claim:" in card
    claims = [json.loads(x) for x in b.read(f"/places/{PLACE}/claims.jsonl").file_data["content"].splitlines()]
    assert claims[0]["predicate"] == "market.stories"
    assert "has_tenancy" in b.read(f"/places/{PLACE}/neighbors.md").file_data["content"]
    assert b.write("/places/x/card.md", "hack").error.startswith("read-only")
    assert b.edit("/index.md", "a", "b").error.startswith("read-only")
    assert b.read("/places/place:costar:404/card.md").error and b.read("/nope.md").error
    assert b.grep("storeys").matches[0]["path"].endswith("card.md")
    assert f"/places/{PLACE}/card.md" in [m["path"] for m in b.glob("**/card.md").matches] or b.glob("/places/*/card.md").matches


def test_look_tools_return_small_images_and_events(cfg):
    client = WorldClient(cfg)
    tools = build_local_tools(cfg, client)
    space = httpx.get(f"{cfg.world_rest_url}/v1/places/{PLACE}").json()["spaces"][0]["space_id"]
    panos = httpx.get(f"{cfg.world_rest_url}/v1/spaces/{space}").json()["panos"]
    sel = next(p["pano_id"] for p in panos if p["has_image"])
    unsel = next(p["pano_id"] for p in panos if not p["is_selected"])
    runctx.reset("local")
    msg = tools["look_at_pano"].invoke({"name": "look_at_pano", "args": {"pano_id": sel}, "id": "x", "type": "tool_call"})
    blocks = msg.content
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 4 and blocks[0]["text"].count("evidence_id ev:") == 4
    kinds = [e["type"] for e in runctx.record("local")["events"]]
    assert kinds.count("focus") == 1 and kinds.count("evidence") == 4
    gap = tools["look_at_pano"].invoke({"name": "look_at_pano", "args": {"pano_id": unsel}, "id": "y", "type": "tool_call"})
    assert gap.content[0]["text"].startswith("Unavailable:")
    for _ in range(3):
        tools["look_at_pano"].invoke({"name": "look_at_pano", "args": {"pano_id": sel}, "id": "z", "type": "tool_call"})
    assert runctx.record("local")["pano_looks"] == 12                      # the cap of 12 images per task holds
    out = json.loads(tools["resolve_place"].invoke({"text": "Fixture Tower"}))
    assert out["candidates"][0]["place_id"] == PLACE and out["candidates"][0]["match_score"] == 1.0
    assert json.loads(tools["resolve_place"].invoke({"text": "99999 Nowhere Blvd"}))["candidates"] == []


def test_pure_helpers(cfg):
    assert check_sql("select 1 from t")[0].endswith("LIMIT 200")
    assert check_sql("drop table t")[1] and check_sql("select 1; select 2")[1] and check_sql("update t set a=1")[1]
    assert classify("What is the asking rent?")["facets"] == ["market"]
    assert set(classify("What do the roof and parking look like from above?")["facets"]) >= {"aerial"}
    assert classify("hmm")["facets"] == ["market", "interior", "aerial", "surroundings"]
    cov = parse_coverage("# x\ncoverage: market=fresh(14) interior=partial(2) aerial=none surroundings=stale(2)\n")
    assert cov == {"market": ("fresh", 14), "interior": ("partial", 2), "aerial": ("none", 0), "surroundings": ("stale", 2)}
    text, cites, dropped = resolve_markers(WorldClient(cfg), "A fact [claim:deadbeefdeadbeef].")
    assert text == "A fact." and not cites and dropped == ["claim:deadbeefdeadbeef"]
    assert summarize("never-ran")["model_calls"] == 0


def test_budget_warns_on_last_call_and_attaches_claims():
    from types import SimpleNamespace

    from langchain_core.messages import SystemMessage

    from mundus_harness.middleware.budget import LAST_CALL_NOTE, BudgetMiddleware, claims_block

    class Req(SimpleNamespace):
        def override(self, **kw):
            return Req(**{**self.__dict__, **kw})

    sub = BudgetMiddleware("market-analyst", 16, is_root=False)
    early = Req(state={"run_model_call_count": 3}, system_message=SystemMessage(content="base"))
    last = Req(state={"run_model_call_count": 15}, system_message=SystemMessage(content="base"))
    assert sub._last_call(early).system_message.content == "base"
    assert sub._last_call(last).system_message.content == "base" + LAST_CALL_NOTE
    assert "wrote no claims" in claims_block("market-analyst", [])
    assert "[claim:ab12]" in claims_block("market-analyst", [{"claim_id": "claim:ab12", "statement": "Three tenants."}])

    rid = "budget-test"
    rec = runctx.reset(rid)
    rec["claims_by_agent"] = {"market-analyst": [{"claim_id": "claim:ab12", "statement": "Three tenants."}]}
    root = BudgetMiddleware("orchestrator", 25, is_root=True)
    req = Req(tool_call={"name": "task", "args": {"subagent_type": "market-analyst"}, "id": "t1"})
    msg = ToolMessage(content="Model call limits exceeded", tool_call_id="t1", name="task")
    import mundus_harness.middleware.budget as b
    orig = b.runctx.run_id_from_config
    b.runctx.run_id_from_config = lambda *a, **k: rid
    try:
        out = root._attach(req, msg)
    finally:
        b.runctx.run_id_from_config = orig
    assert "Model call limits exceeded" in out.content and "[claim:ab12] Three tenants." in out.content
    other = Req(tool_call={"name": "get_claims", "args": {}, "id": "t2"})
    assert root._attach(other, msg) is msg


async def test_tool_events_name_the_calling_agent(cfg):
    wt = await load_world_tools(cfg)
    orch, worker = cold_scripts(cfg)
    agent = build_agent(cfg, wt, orch_model=orch, worker_model=worker)
    ev = await _run(agent, "Who is the largest tenant at Fixture Tower?", "run-tools")
    tools = [(e["agent"], e["name"]) for _, e in ev if e["type"] == "tool"]
    assert ("orchestrator", "task") in tools and ("market-analyst", "get_place") in tools
    assert tools.count(("market-analyst", "put_claim")) == 3
    task = next(e for _, e in ev if e["type"] == "tool" and e["name"] == "task")
    assert task["args"]["subagent_type"] == "market-analyst"
    # a tool event marks a call starting, not an action finishing: time to first action is still recorded once
    assert next(e for _, e in ev if e["type"] == "metrics")["time_to_first_action_ms"] is not None


async def test_memory_file_is_read_only_with_private_claims(cfg):
    import dataclasses
    wt = await load_world_tools(cfg)
    mem = cfg.data_dir / "memory" / "AGENTS.md"
    for private in (True, False):
        c = dataclasses.replace(cfg, claim_scope_run=private)
        orch = ScriptedModel(script=[
            AIMessage(content="", tool_calls=[tool_call("edit_file", {"file_path": "/memory/AGENTS.md",
                                                                      "old_string": "# Lessons", "new_string": "# Leaked"})]),
            AIMessage(content="done")], calls=[])
        agent = build_agent(c, wt, orch_model=orch, worker_model=ScriptedModel(script=[], calls=[]))
        await _run(agent, "Note something", f"run-mem-{private}")
        assert ("Leaked" in mem.read_text()) is (not private)
        mem.write_text("# Lessons learned by Census agents\n", encoding="utf-8")



async def test_named_place_beats_the_open_page(cfg, monkeypatch):
    from types import SimpleNamespace

    from langchain_core.messages import HumanMessage

    from mundus_harness.middleware.router import RouterMiddleware
    router = RouterMiddleware(cfg, WorldClient(cfg))
    monkeypatch.setattr(runctx, "run_id_from_config", lambda config=None: "run-route")

    def route(question, page_place=None):
        runctx.reset("run-route")
        router.before_agent({"messages": [HumanMessage(content=question)]},
                            SimpleNamespace(context={"place_id": page_place} if page_place else {}))
        return runctx.record("run-route")["route"]["place_id"]

    other = "place:costar:1002"
    assert route("Who is the largest tenant at Fixture Tower?", page_place=other) == PLACE   # named place wins
    assert route("Who is the largest tenant in this building?", page_place=PLACE) == PLACE   # page fills "this building"
    assert route("Who is the largest tenant at Fixture Tower?") == PLACE                     # no page: as before
