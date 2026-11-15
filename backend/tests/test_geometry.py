from conftest import SID, SPACE, build_world

from mundus_world.service import geometry as geo


def test_polygon_loop_and_centroid():
    edges = {"a": ("1", "2"), "b": ("2", "3"), "c": ("3", "4"), "d": ("4", "1")}
    vpos = {"1": (0, 0), "2": (4, 0), "3": (4, 3), "4": (0, 3)}
    poly, quality = geo.build_polygon(["c", "a", "d", "b"], edges, vpos)
    assert quality == "loop" and len(poly) == 4
    assert geo.polygon_centroid(poly) == (2.0, 1.5)


def test_adjacency_from_shared_wall_edges(world):
    rows = world.db.q("SELECT room_a, room_b, shared_length_m, involves_void FROM room_adjacency ORDER BY room_a, room_b")
    pairs = {(r["room_a"].split(":")[-1], r["room_b"].split(":")[-1]): (r["shared_length_m"], r["involves_void"]) for r in rows}
    assert pairs == {("A", "B"): (3.0, 0), ("A", "C"): (4.0, 0), ("B", "C"): (4.0, 0), ("B", "V"): (3.0, 1)}
    room = world.world.get_room(f"room:{SID}:A")
    assert {a["room_id"].split(":")[-1] for a in room["adjacent_rooms"]} == {"B", "C"}
    assert "no doors" in room["adjacency_note"]


def test_pano_cap_is_enforced_and_deterministic(tmp_path):
    w1 = build_world(tmp_path / "a", cap=20)
    sel1 = [r["pano_id"] for r in w1.db.q("SELECT pano_id FROM pano WHERE is_selected=1 ORDER BY pano_id")]
    assert len(sel1) == 20 and w1.db.scalar("SELECT count(*) FROM pano") == 24
    w2 = build_world(tmp_path / "b", cap=20)
    assert sel1 == [r["pano_id"] for r in w2.db.q("SELECT pano_id FROM pano WHERE is_selected=1 ORDER BY pano_id")]
    # every non-void room that has a pano keeps at least one
    for r in w1.db.q("SELECT label, pano_total, pano_selected FROM room WHERE space_id=?", (SPACE,)):
        if r["label"] != "Void" and r["pano_total"]:
            assert r["pano_selected"] >= 1


def test_small_cap_leaves_rooms_uncovered_and_reports_it(tmp_path):
    w = build_world(tmp_path, cap=2)
    assert w.db.scalar("SELECT count(*) FROM pano WHERE is_selected=1") == 2
    assert w.db.scalar("SELECT count(*) FROM room WHERE pano_selected=0 AND label!='Void'") >= 1
    uncovered = w.db.one("SELECT room_id FROM room WHERE pano_selected=0 AND label!='Void'")["room_id"]
    assert "appearance is not" in w.world.get_room(uncovered)["hint"]


def test_space_kind_rules():
    assert geo.space_kind("2BR, 2BA - 1,134 SF", "commercial") == "unit"
    assert geo.space_kind("Fitness Center", "commercial") == "amenity"
    assert geo.space_kind("Executive Tower - Suite 400", "commercial") == "office"
    assert geo.space_kind("Lobby", "commercial") == "common"
    assert geo.space_kind("5134 Medina Rd", "residential") == "home"
