"""Floor-plan eval tests. Run on a synthetic floor (no licensed data). The seed rescore test runs only when the floor 16
seed files are present in eval/data/floorplan/seed/."""
import copy
import json
from pathlib import Path

import pytest

from mundus_eval.floorplan import checks as C
from mundus_eval.floorplan import rulecheck as R
from mundus_eval.floorplan.fixtures import turning_circle
from mundus_eval.floorplan.floor import Column, shell_path
from mundus_eval.floorplan.layout import parse_layout
from mundus_eval.floorplan.mutations import OPERATORS, mutate
from mundus_eval.floorplan.rubric import CRITERIA, RUBRIC_VERSION, calibration_gap, grade_layout
from mundus_eval.floorplan.synthetic import synthetic


def _status(floor, lay):
    return {(r.rule, r.subject): r for r in C.run_checks(floor, parse_layout(lay))}


def test_clean_synthetic_layout_passes_every_rule():
    floor, lay = synthetic()
    bad = [(r.rule, r.subject, r.value) for r in C.run_checks(floor, parse_layout(lay)) if r.status != "pass"]
    assert bad == []
    g = grade_layout(floor, lay)
    assert g["rubric_version"] == RUBRIC_VERSION == "1.0"
    assert g["groups"]["compliance"] == 40 and g["groups"]["structure"] == 30 and not g["hard_breaks"]
    assert sum(m for _, m, _, _ in CRITERIA) == 100


def test_turning_circle_needs_fixtures_placed():
    # v4 shortcut: a 1.75 m bath fits a 1.5 m circle when empty, but not with an 11B toilet clearance and a shower
    r = (0.0, 0.0, 1.75, 2.45)
    assert turning_circle(r, with_fixtures=False)["pass"]
    assert turning_circle(r, strict=False)["pass"]              # 11A adaptable
    assert not turning_circle(r, strict=True)["pass"]           # 11B mobility
    assert turning_circle((0.0, 0.0, 2.45, 2.45), strict=True)["pass"]
    assert not turning_circle((0.0, 0.0, 1.5, 2.45), strict=False)["pass"]


def test_column_footprint_not_centre_point():
    # v2 shortcut: C15's centre sat on the demising wall while its 0.64 m square put area into a bath
    floor, lay = synthetic()
    bath = next(r for r in lay["units"][0]["rooms"] if r["type"] == "bath")
    x0, y0, x1, y1 = bath["rect"]
    floor.columns.append(Column("T1", x1, (y0 + y1) / 2, 0.64, "probable"))     # centre exactly on the bath's side wall
    row = _status(floor, lay)[("column_footprint", "T1")]
    assert row.status == "fail" and row.hard and row.value > C.OVERLAP_TOL


def test_paired_needs_a_shared_straight_wall():
    floor, lay = synthetic()
    assert _status(floor, lay)[("paired_wet_rooms", "S1")].status == "pass"
    # slide S2's bath away from the shared wall so the two baths only meet at a corner
    s2 = next(u for u in lay["units"] if u["id"] == "S2")
    bath = next(r for r in s2["rooms"] if r["type"] == "bath")
    x0, y0, x1, y1 = bath["rect"]
    bath["rect"] = [x0, y0 + 2.2, x1, y1 + 2.2]
    assert _status(floor, lay)[("paired_wet_rooms", "S1")].status == "fail"


def test_drains_measure_every_fixture_and_missing_sink_is_worst_case():
    floor, lay = synthetic()
    u = lay["units"][0]
    u["fixtures"] = [f for f in u["fixtures"] if f["kind"] != "sink"]
    row = _status(floor, lay)[("drain_runs", u["id"])]
    assert "no sink declared" in row.detail


def test_generator_flags_are_ignored():
    floor, lay = synthetic()
    lay2 = copy.deepcopy(lay)
    lay2["units"][0]["rooms"] = [r for r in lay2["units"][0]["rooms"] if r["type"] != "hall"]
    lay2["units"][0]["checks"] = {"entry >= 1.07 m clear, door 0.91 m": {"ok": True}}
    assert _status(floor, lay2)[("entry_width", lay2["units"][0]["id"])].status == "fail"


def test_every_operator_flips_its_rule_and_neutral_ones_flip_nothing():
    floor, lay = synthetic()
    ms = mutate(floor, lay, "synthetic", per_op=4, seed=1)
    for name, (_, intended) in OPERATORS.items():
        mine = [m for m in ms if m.op == name]
        assert mine, name
        if intended:
            assert any(m.keep for m in mine), f"{name} never broke {intended}"
            assert all(intended in {f.split(':')[0] for f in m.flipped} for m in mine if m.keep)
        else:
            assert all(not m.flipped for m in mine), f"neutral {name} changed {[m.flipped for m in mine]}"


def test_rulecheck_cases_and_scoring():
    floor, lay = synthetic()
    ms = mutate(floor, lay, "synthetic", per_op=2, seed=2)
    cases = R.build_cases(ms, {})
    assert {c["truth"] for c in cases} == {"pass", "fail"}
    assert all(c["rule"] in R.RULE_TEXT for c in cases)
    ctx = R.context(floor, lay, "entry_width", "S1")
    assert "checks" not in json.dumps(ctx["unit"])                 # judge never sees generator flags
    res = [{"rule": "x", "truth": "fail", "pred": "pass"}, {"rule": "x", "truth": "fail", "pred": "fail"},
           {"rule": "x", "truth": "pass", "pred": "pass"}, {"rule": "x", "truth": "pass", "pred": "garbage"}]
    s = R.score(res)["x"]
    assert (s["tp"], s["fn"], s["tn"], s["bad"]) == (1, 1, 2, 1) and s["false_pass_rate"] == 0.5
    assert R.parse_reply('noise {"status": "FAIL", "value": 1.0} tail')["status"] == "fail"


def test_self_score_gap():
    floor, lay = synthetic()
    g = grade_layout(floor, lay)
    lay["self_score"] = {"items": {k: {"points": v["points"] + (2 if k == "Accessibility" else 0)} for k, v in g["criteria"].items()},
                         "total": g["total"] + 2}
    gap = calibration_gap(g, lay)
    assert gap["total_gap"] == 2 and gap["max_over"] == 2 and not gap["pass"]


SEED = Path(__file__).resolve().parents[1] / "data" / "floorplan" / "seed"
GRADED = {"layout-v3": 87.8, "layout-v4": 87.9}     # grader's totals; v1/v2 were graded under an earlier rubric


@pytest.mark.skipif(not (SEED.exists() and shell_path().exists()), reason="licensed floor 16 seed data not present")
@pytest.mark.parametrize("name,expected", sorted(GRADED.items()))
def test_rescore_seed_within_one_point(name, expected):
    from mundus_eval.floorplan.floor import load_shell
    lay = json.loads((SEED / f"{name}.json").read_text())
    assert abs(grade_layout(load_shell(), lay)["total"] - expected) <= 1.0
