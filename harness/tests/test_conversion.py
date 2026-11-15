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


def test_auto_depth_reaches_the_core_and_starts_at_side_start(tmp_path):
    root = make_floor(tmp_path)
    open_floor = geo.draft_ring(SCAN, "auto", {"south": [{"type": "1BR", "width_m": 7}]}, root=root)["units"][0]
    assert abs(open_floor["polygon"][0][0]) < 0.01 or abs(open_floor["polygon"][1][0]) < 0.01   # starts at the side's start
    assert open_floor["depth_m"] == 10.5                 # nothing behind it: capped at the daylight limit
    facing_core = geo.draft_ring(SCAN, "auto", {"south": [{"type": "gap", "width_m": 11}, {"type": "1BR", "width_m": 7}]},
                                 root=root)["units"][0]
    assert 5.0 <= facing_core["depth_m"] <= 8.0 - 1.6 + 0.01   # the core is 8 m from the south facade here


def test_photo_rejected_column_is_not_structure(tmp_path):
    root = make_floor(tmp_path)
    st = json.loads((root / SCAN / "structure.json").read_text())
    st["columns"][0]["confidence"] = "rejected"
    (root / SCAN / "structure.json").write_text(json.dumps(st))
    bad = geo.draft_ring(SCAN, 6.0, {"north": [{"type": "studio", "width_m": 5}, {"type": "1BR", "width_m": 7}]}, root=root)
    rep = geo.check_layout(SCAN, bad, root)
    assert not any(v["status"] == "fail" for u in rep["units"] for k, v in u["checks"].items() if k == "walls_clear_of_structure")


def test_photo_notes_and_3br_rent_alias(tmp_path):
    root = make_floor(tmp_path)
    (root / SCAN / "photocheck.json").write_text(json.dumps([{"item_kind": "stair", "x": 1, "y": 2, "verdict": "confirmed",
                                                               "what_it_is": "open internal stair", "details": "railings", "panos": ["5"]}]))
    t = build_tools(root)
    assert "open internal stair" in t["read_floor"].invoke({"scan": SCAN})
    json.loads(t["draft_layout"].invoke({"scan": SCAN, "unit_depth_m": 6.0, "sides": {"south": [{"type": "3BR", "width_m": 13}]}}))
    out = json.loads(t["estimate_returns"].invoke({"scan": SCAN, "draft_id": "draft_1", "conversion_cost_per_sf": 400,
                                                   "monthly_rent_per_sf_by_type": {"3BR+": 3.65}}))
    assert out["monthly_rent_usd"] > 0


def test_short_side_moves_in_when_long_side_leaves_facade_at_the_corner(tmp_path):
    root = make_floor(tmp_path)
    lay = geo.draft_ring(SCAN, 6.0, {"south": [{"type": "1BR", "width_m": 7}] * 4,          # 2 m left over at the east end
                                     "east": [{"type": "studio", "width_m": 5}]}, root=root)
    south = [u for u in lay["units"] if u["side"] == "south"]
    east = [u for u in lay["units"] if u["side"] == "east"][0]
    ys = [p[1] for p in east["polygon"]]
    assert min(ys) >= max(max(p[1] for p in u["polygon"]) for u in south) - 0.01   # east unit starts above the south units


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


def test_bedroom_over_a_column_fails(tmp_path):
    # the grader found bedrooms over columns that this checker passed (it tested walls only)
    root = make_floor(tmp_path)
    unit = {"id": "U1", "type": "1BR", "bedrooms": 1, "polygon": [[2, 14], [9, 14], [9, 20], [2, 20]],
            "bedroom_polygons": [[[3.5, 16.4], [6.7, 16.4], [6.7, 20], [3.5, 20]]]}           # column at (5, 18) inside
    rep = geo.check_layout(SCAN, {"units": [unit], "walls": []}, root)
    assert rep["units"][0]["checks"]["bedrooms_clear_of_columns"]["status"] == "fail"
    unit["bedroom_polygons"] = [[[6.0, 16.4], [9.0, 16.4], [9.0, 20], [6.0, 20]]]              # moved off it
    rep = geo.check_layout(SCAN, {"units": [unit], "walls": []}, root)
    assert rep["units"][0]["checks"]["bedrooms_clear_of_columns"]["status"] == "pass"


def test_exit_route_may_not_pass_through_another_unit(tmp_path):
    # a unit boxed in by its neighbours and the core has no route out; the old check walked through apartments
    root = make_floor(tmp_path)
    box_ = lambda x0, y0, x1, y1: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]            # noqa: E731
    units = [{"id": "U1", "type": "studio", "bedrooms": 0, "polygon": box_(20, 8, 26, 12)},     # against the core's east face
             {"id": "U2", "type": "studio", "bedrooms": 0, "polygon": box_(20, 0, 30, 8)},      # below it
             {"id": "U3", "type": "studio", "bedrooms": 0, "polygon": box_(20, 12, 30, 20)},    # above it
             {"id": "U4", "type": "studio", "bedrooms": 0, "polygon": box_(26, 8, 30, 12)}]     # beyond it, to the facade
    rep = geo.check_layout(SCAN, {"units": units, "walls": []}, root)
    by = {u["id"]: u["checks"]["exit_travel"]["status"] for u in rep["units"]}
    assert by["U2"] == "pass" and by["U3"] == "pass"     # open onto the floor west of them, round to the west exit
    assert by["U4"] == "fail"            # sealed: only reachable through U1, U2 or U3
    assert by["U1"] == "fail"            # built over the assumed east stair, and boxed in: it blocks the exit too
