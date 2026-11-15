import json
from types import SimpleNamespace

import httpx

from mundus_eval import graders
from mundus_eval.report import summarize
from mundus_eval.runner import plan
from mundus_eval.tasks import _dig, build_truth, load_combos, load_tasks


def test_task_file_shape():
    tasks = load_tasks()
    assert len(tasks) == 15
    groups = [t["group"] for t in tasks]
    assert groups.count("retrieval") == groups.count("cross_building") == groups.count("physical") == 5
    assert sum(t["grader"] == "model" for t in tasks) == 9
    last = tasks[-1]
    assert last["id"] == "P15" and last["expect_refusal"] and last["forbidden_claim_patterns"]
    assert "truth" not in json.dumps([t.get("checks") for t in tasks])       # no answers stored in the task file


def test_plan_is_interleaved_and_combos_are_cold():
    combos = load_combos()["combos"]
    assert [c["name"] for c in combos] == ["cold-sonnet-haiku", "cold-all-haiku"] and all(c["memory"] == "cold" for c in combos)
    order = plan([{"id": "A"}, {"id": "B"}], combos, 3)
    assert len(order) == 2 * len(combos) * 3
    names = [c["name"] for c in combos]
    assert [c for _, t, c in order[:len(names)]] == names and {t for _, t, _ in order[:len(names)]} == {"A"}
    assert [r for r, _, _ in order] == sorted(r for r, _, _ in order)
    assert len(plan(load_tasks(), combos, load_combos()["runs_per_task"])) == 90


def test_no_task_depends_on_aerial_facts():
    for t in load_tasks():
        assert "aerial_facts" not in (t.get("required_evidence_types") or [])
        assert not any("/v1/aerial/" in str(v.get("path", "")) for v in (t.get("truth") or {}).values())


def test_resume_skips_only_clean_runs(tmp_path):
    from mundus_eval.runner import finished_keys
    p = tmp_path / "runs.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"task_id": "R1", "combo": "a", "repeat": 1, "error": None},
        {"task_id": "R1", "combo": "a", "repeat": 2, "error": "timeout after 600s"}]), encoding="utf-8")
    assert finished_keys(p) == {("R1", "a", 1)} and finished_keys(tmp_path / "missing.jsonl") == set()


def test_preflight_gates_on_captions_embeddings_and_aerial(monkeypatch):
    from mundus_eval import runner

    def world(counts, mode="hybrid", aerial=404):
        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/healthz":
                return httpx.Response(200, json={"deep_places": 15})
            if path == "/v1/stats":
                return httpx.Response(200, json={"counts": counts})
            if path == "/v1/interiors/search":
                return httpx.Response(200, json={"mode": mode, "hits": []})
            if path == "/v1/places/search":
                return httpx.Response(200, json={"places": [{"place_id": "place:x"}]})
            if path.startswith("/v1/aerial/"):
                return httpx.Response(aerial, json={})
            return httpx.Response(200, json={"place_id": "place:x"})
        return lambda admin=False: httpx.Client(base_url="http://world", transport=httpx.MockTransport(handler))

    good = {"pano_caption": 10, "panos_selected_with_faces": 10, "docs": 30, "docs_embedded": 30}
    monkeypatch.setattr(runner, "world_client", world(good))
    assert runner.preflight()["ok"]
    for bad_counts, kw in (({**good, "pano_caption": 9}, {}), ({**good, "docs_embedded": 0}, {}), (good, {"mode": "text_only"}),
                           (good, {"aerial": 200})):
        monkeypatch.setattr(runner, "world_client", world(bad_counts, **kw))
        assert not runner.preflight()["ok"]


def test_number_parsing_and_checks():
    assert graders.numbers_in("It sold for $9,000,000 in 2019 [claim:1234abcd5678ef90].") == [9000000.0, 2019.0]
    assert graders.numbers_in("about 2.3 million") == [2300000.0]
    assert graders.check_number("There are 752 tenancies.", 752)[0]
    assert not graders.check_number("There are 750 tenancies.", 752)[0]
    assert graders.check_number("Price $2,295,000", 2295550, 0.001)[0]
    assert graders.check_contains("The roof is a Membrane roof.", "membrane")[0]
    words = dict(true_words=["solar is detected"], false_words=["no solar"])
    assert graders.check_boolean("Rooftop solar is detected.", True, **words)[0]
    assert not graders.check_boolean("There is no solar.", True, **words)[0]
    assert graders.check_boolean("There is no solar.", False, **words)[0]
    assert graders.check_order("Westside Towers East has the most (752); The Preserve has the fewest (10).", "Westside Towers", "Preserve")[0]
    assert not graders.check_order("The Preserve has the most; Westside Towers the fewest.", "Westside Towers", "Preserve")[0]


def _run(answer, cites=1, dropped=(), types=("record",), claims=()):
    return {"answer": answer, "citations": [{"claim_id": f"claim:{i}", "evidence_ids": ["ev:1"]} for i in range(cites)],
            "dropped_markers": list(dropped), "evidence_types": list(types), "claims": list(claims), "metrics": {"model_calls": 5}}


def test_code_grader_pass_and_fail():
    task = next(t for t in load_tasks() if t["id"] == "R1")
    good = graders.grade_code(task, {"tenancies": 752}, _run("752 tenancies are recorded [claim:1234abcd5678ef90]."))
    assert good["pass"] and good["score"] == 1.0
    wrong = graders.grade_code(task, {"tenancies": 752}, _run("700 tenancies are recorded [claim:1234abcd5678ef90]."))
    assert not wrong["pass"]
    invented = graders.grade_code(task, {"tenancies": 752}, _run("752 tenancies.", cites=0, dropped=["claim:dead"]))
    assert not invented["pass"] and not next(c for c in invented["checks"] if c["check"] == "citation_validity")["ok"]
    no_ev = graders.grade_code(task, {"tenancies": 752}, _run("752 tenancies [claim:1234abcd5678ef90].", types=("caption",)))
    assert not no_ev["pass"]
    assert graders.citation_coverage("It has 752 tenancies. It is tall [claim:1234abcd5678ef90].") == 0.0
    assert graders.citation_coverage("It has 752 tenancies. [claim:1234abcd5678ef90] It has 12 storeys [claim:1234abcd5678ef90].") == 1.0


def test_refusal_task_flags_invented_claims():
    task = next(t for t in load_tasks() if t["id"] == "P15")
    clean = graders.common_checks(task, _run("The data has no structural information.", cites=0, types=()))
    assert all(c["ok"] for c in clean if c["check"] != "budget")
    bad = graders.common_checks(task, _run("x", cites=0, types=(), claims=[{"statement": "Room 301 is at risk of collapse."}]))
    assert not next(c for c in bad if c["check"] == "no_invented_claims")["ok"]


class FakeAnthropic:
    def __init__(self, text, stop_reason="end_turn"):
        self.seen = None
        outer = self

        class Messages:
            def create(self, **kw):
                outer.seen = kw
                return SimpleNamespace(stop_reason=stop_reason, model="claude-fable-5-2",
                                       content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                                       usage=SimpleNamespace(input_tokens=900, output_tokens=120))
        self.beta = SimpleNamespace(messages=Messages())


def test_model_grader_request_and_verdict():
    task = next(t for t in load_tasks() if t["id"] == "P15")
    fake = FakeAnthropic('Here is my verdict: {"score": 0.9, "pass": true, "reasons": ["declined to invent a route"], "unsupported_statements": []}')
    g = graders.grade_model(task, {}, None, _run("I cannot identify rooms at risk from this data.", cites=0, types=()), client=fake)
    assert g["pass"] and g["score"] == 0.9 and g["grader_tokens"] == {"in": 900, "out": 120}
    assert fake.seen["model"] == "claude-fable-5-2" and "thinking" not in fake.seen and "temperature" not in fake.seen
    assert fake.seen["fallbacks"] == "default" and fake.seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert "RUBRIC" in fake.seen["messages"][0]["content"]
    # a passing verdict cannot override a hard check: a forbidden claim was written to memory
    g2 = graders.grade_model(task, {}, None, _run("x", cites=0, types=(), claims=[{"statement": "Beam failure puts room 3 at risk"}]), client=fake)
    assert not g2["pass"]
    refused = graders.grade_model(task, {}, None, _run("x", cites=0, types=()), client=FakeAnthropic("", stop_reason="refusal"))
    assert not refused["pass"] and refused["error"] == "grader declined"
    assert graders.parse_verdict("not json")["pass"] is False


def test_truth_from_world_api():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/market/query":
            return httpx.Response(200, json={"columns": ["n"], "rows": [[752]]})
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    tasks = [t for t in load_tasks() if t["id"] in ("R1", "R2", "R3")]
    with httpx.Client(base_url="http://world", transport=httpx.MockTransport(handler)) as c:
        truth = build_truth(tasks, c)
    assert truth["R1"] == {"tenancies": 752} and truth["R2"]["asking_price"] == 752
    assert truth["R3"] == {"space_name": 752, "largest_m2": 752}
    assert _dig({"attributes": {"pool.detected": True}}, "attributes.pool.detected") is True


def test_report_summary():
    def rec(combo, task, ok, tokens, wall):
        return {"combo": combo, "task_id": task, "group": "retrieval", "error": None, "wall_clock_s": wall,
                "time_to_first_action_s": 1.0, "grade": {"pass": ok, "score": 1.0 if ok else 0.0,
                                                         "checks": [{"check": "citation_validity", "ok": True}]},
                "metrics": {"tokens_in": tokens, "tokens_out": 10, "tokens_total": tokens + 10, "model_calls": 4,
                            "tool_calls": 6, "images": 0, "est_cost_usd": None}}
    s = summarize([rec("cold", "R1", True, 1000, 30), rec("cold", "R1", False, 1200, 40), rec("warm", "R1", True, 100, 5)])
    assert s["combos"]["cold"]["pass_rate"] == 0.5 and s["combos"]["warm"]["pass_rate"] == 1.0
    assert s["combos"]["cold"]["mean_tokens_total"] == 1110 and s["combos"]["cold"]["mean_cost_usd"] is None
    assert s["tasks"]["R1"]["warm"] == {"pass": 1, "runs": 1, "mean_tokens": 110, "flaky": False}
    assert s["tasks"]["R1"]["cold"]["flaky"] and s["combos"]["cold"]["tool_error_rate"] == 0.0
