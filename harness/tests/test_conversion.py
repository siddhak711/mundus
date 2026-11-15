"""Conversion agent: geometry checks on a synthetic floor, and memory write permissions (no model calls)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import ScriptedModel
from langchain_core.messages import AIMessage

from mundus_harness.conversion import geometry as geo
from mundus_harness.conversion.tools import build_tools

SCAN = "synth"
RES = 20.0


def make_floor(root):
    """A 30 x 20 m floor, windows all round, a 10 x 4 m core in the middle, one column at (5, 18)."""
    d = root / SCAN
    d.mkdir(parents=True)
    w, h = int(30 * RES), int(20 * RES)
    plate = np.ones((h, w), bool)
    window = np.zeros((h, w), bool)
    window[0, :] = window[-1, :] = window[:, 0] = window[:, -1] = True
    core = np.zeros((h, w), bool)
    core[int(8 * RES):int(12 * RES), int(10 * RES):int(20 * RES)] = True        # y 8..12, x 10..20
    cols = np.zeros((h, w), bool)
    cols[int(1.6 * RES):int(2.4 * RES), int(4.6 * RES):int(5.4 * RES)] = True   # around (5, 18)
    np.savez_compressed(d / "grid.npz", plate=plate, window=window, core=core, columns=cols,
                        frame=np.array([0.0, 0.0, w, h, RES]))
    (d / "geometry.json").write_text(json.dumps({
        "name": "synthetic", "floor": 3, "outline": [[0, 20], [0, 0], [30, 0], [30, 20]], "plate_sf": 6458,
        "ceiling_height_ft": 8.7, "daylight": {}}), encoding="utf-8")
    (d / "structure.json").write_text(json.dumps({
        "core": [{"polygon": [[10, 12], [10, 8], [20, 8], [20, 12]], "area_m2": 40}],
        "columns": [{"x": 5, "y": 18, "confidence": "low"}],
        "exits": [{"x": 10, "y": 10, "kind": "fire stair (assumed)", "confidence": "assumed"},
                  {"x": 20, "y": 10, "kind": "fire stair (assumed)", "confidence": "assumed"}],
        "stairs": []}), encoding="utf-8")
    return root


def test_floor_summary_and_sides(tmp_path):
    root = make_floor(tmp_path)
    s = geo.floor_summary(SCAN, root)
    sides = {x["side"]: x for x in s["facade_sides"]}
    assert set(sides) == {"north", "south", "east", "west"}
    assert sides["north"]["runs_full_length"] and not sides["west"]["runs_full_length"]
    assert 7.5 <= sides["north"]["facade_to_core_m"]["min"] <= 8.25


def test_draft_and_checks(tmp_path):
    root = make_floor(tmp_path)
    good = geo.draft_ring(SCAN, 6.0, {"south": [{"type": "1BR", "width_m": 7}, {"type": "studio", "width_m": 5}]}, root=root)
    rep = geo.check_layout(SCAN, good, root)
    assert rep["counts"]["fail"] == 0 and rep["counts"]["pass"] == 2
    u = rep["units"][0]["checks"]
    assert u["bedroom_windows"]["status"] == "pass" and u["exit_travel"]["status"] == "pass"
    # a unit 9 m deep on the north side runs into the core; a demising wall at x = 5 cuts the column
    bad = geo.draft_ring(SCAN, 9.0, {"north": [{"type": "studio", "width_m": 5}, {"type": "1BR", "width_m": 7}]}, root=root)
    rep = geo.check_layout(SCAN, bad, root)
    fails = {k for u in rep["units"] for k, v in u["checks"].items() if v["status"] == "fail"}
    assert "clear_of_core" in fails
    with pytest.raises(ValueError):
        geo.draft_ring(SCAN, 6.0, {"south": [{"type": "2BR", "width_m": 40}]}, root=root)


def test_tools_write_layout(tmp_path):
    root = make_floor(tmp_path)
    t = build_tools(root)
    res = json.loads(t["draft_layout"].invoke({"scan": SCAN, "unit_depth_m": 6.0,
                                               "sides": {"south": [{"type": "1BR", "width_m": 7}]}}))
    assert res["draft_id"] == "draft_1" and res["counts"]["pass"] == 1
    out = json.loads(t["write_layout"].invoke({"scan": SCAN, "draft_id": "draft_1", "issues": [], "assumptions": ["x"]}))
    lay = json.loads((root / SCAN / "layout.json").read_text())
    assert out["units"] == 1 and lay["units"][0]["type"] == "1BR"
    assert {w["kind"] for w in lay["walls"]} <= {"demising", "interior", "corridor"}
    assert lay["structure"]["exits"] and lay["summary"]["assumptions"][0] == "x"


def test_memory_writes_only_in_own_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERSION_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_path / "hdata"))
    from mundus_harness.conversion.graph import build_agent
    call = lambda name, args, i: AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])  # noqa: E731
    layout_model = ScriptedModel(script=[
        call("write_file", {"file_path": "/memories/compliance/la.md", "content": "hijack"}, 1),
        call("write_file", {"file_path": "/memories/layout/note.md", "content": "mine"}, 2),
        AIMessage(content="done")], calls=[])
    orch = ScriptedModel(script=[
        call("task", {"description": "try writing memory", "subagent_type": "layout"}, 3),
        call("write_file", {"file_path": "/skills/layout/SKILL.md", "content": "x"}, 4),
        AIMessage(content="finished")], calls=[])
    idle = ScriptedModel(script=[], calls=[])
    agent = build_agent(orch_model=orch, worker_models={"layout": layout_model, "compliance": idle, "cost": idle},
                        data_root=tmp_path)
    agent.invoke({"messages": [{"role": "user", "content": "go"}]}, config={"configurable": {"thread_id": "t"}})
    mem = tmp_path / "mem"
    assert (mem / "layout" / "note.md").read_text() == "mine"
    assert "hijack" not in (mem / "compliance" / "la.md").read_text()
    assert (mem / "INDEX.md").exists()
    from mundus_harness.conversion.graph import SKILLS_DIR
    assert (SKILLS_DIR / "layout" / "SKILL.md").read_text().startswith("---")   # orchestrator's write was denied
