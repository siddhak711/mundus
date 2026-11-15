import pytest
from conftest import PLACE, SID

from mundus_world.service.claims import render_card
from mundus_world.types.errors import ApiError


def _ev(world, ev_type):
    return world.db.one("SELECT evidence_id FROM evidence WHERE type=? AND place_id=? ORDER BY evidence_id", (ev_type, PLACE))["evidence_id"]


def test_created_then_merged(world):
    rec = _ev(world, "record")
    a = world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants are recorded.", [rec], 0.9)
    assert a["outcome"] == "created" and a["claim"]["status"] == "active"
    b = world.claims.put(PLACE, "market.tenant_count", 3, "It has 3 tenants.", [_ev(world, "ortho_image")])
    assert b["outcome"] == "merged" and b["claim"]["id"] == a["claim"]["id"]
    assert b["claim"]["confirmations"] == 2 and len(b["claim"]["evidence_ids"]) == 2


def test_numbers_within_five_percent_merge(world):
    rec = _ev(world, "record")
    a = world.claims.put(PLACE, "market.building_area_sqft", 50000, "About 50,000 sq ft.", [rec])
    b = world.claims.put(PLACE, "market.building_area_sqft", 51000, "About 51,000 sq ft.", [rec])
    assert b["outcome"] == "merged" and b["claim"]["id"] == a["claim"]["id"]


def test_higher_rank_supersedes(world):
    low = world.claims.put(PLACE, "market.stories", 4, "Looks like four storeys.", [_ev(world, "caption")])
    high = world.claims.put(PLACE, "market.stories", 5, "The record says five storeys.", [_ev(world, "record")])
    assert high["outcome"] == "superseded_old" and high["conflicts"] == [low["claim"]["id"]]
    assert world.claims.one(low["claim"]["id"])["status"] == "superseded"
    assert world.db.one("SELECT 1 FROM edges WHERE rel='supersedes' AND src=? AND dst=?", (high["claim"]["id"], low["claim"]["id"]))


def test_lower_rank_is_rejected(world):
    world.claims.put(PLACE, "market.stories", 5, "The record says five storeys.", [_ev(world, "record")])
    low = world.claims.put(PLACE, "market.stories", 9, "Looks like nine storeys.", [_ev(world, "caption")])
    assert low["outcome"] == "rejected_lower_rank" and low["claim"]["status"] == "superseded"
    active = world.claims.get(PLACE, "market.stories")["claims"]
    assert [c["value"] for c in active] == [5]


def test_equal_rank_young_claims_are_disputed(world):
    rec = _ev(world, "record")
    a = world.claims.put(PLACE, "market.year_built", 1990, "Built in 1990.", [rec])
    b = world.claims.put(PLACE, "market.year_built", 1975, "Built in 1975.", [rec])
    assert b["outcome"] == "disputed"
    assert world.claims.one(a["claim"]["id"])["status"] == "disputed"
    assert "## disputed" in render_card(world.db, world.claims, PLACE)


def test_multi_valued_predicates_never_conflict(world):
    cap = _ev(world, "caption")
    a = world.claims.put(PLACE, "interior.amenity_present", "gym", "There is a gym.", [cap])
    b = world.claims.put(PLACE, "interior.amenity_present", "pool", "There is a pool.", [cap])
    assert a["outcome"] == b["outcome"] == "created"


def test_rejections(world):
    rec = _ev(world, "record")
    with pytest.raises(ApiError) as e:
        world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants.", ["ev:doesnotexist0000"])
    assert e.value.details["unknown_evidence_ids"] == ["ev:doesnotexist0000"]
    with pytest.raises(ApiError):
        world.claims.put(PLACE, "market.not_a_predicate", 3, "Three tenants.", [rec])
    with pytest.raises(ApiError):
        world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants.", [])
    with pytest.raises(ApiError):
        world.claims.put("place:costar:nope", "market.tenant_count", 3, "Three tenants.", [rec])
    assert world.claims.get(PLACE, status="all")["count"] == 0


def test_synthesis_from_claims_and_staleness(world):
    a = world.claims.put(PLACE, "market.stories", 5, "Five storeys.", [_ev(world, "record")])
    s = world.claims.put(PLACE, "synthesis.fit", "ok", "It suits a 20-person office.", derived_from=[a["claim"]["id"]])
    assert s["outcome"] == "created"
    world.claims.invalidate(a["claim"]["id"], "wrong")
    statuses = {c["id"]: c["status"] for c in world.claims.get(PLACE, status="all")["claims"]}
    assert statuses[s["claim"]["id"]] == "stale"


def test_claim_goes_stale_when_its_evidence_changes(world):
    rec = _ev(world, "record")
    a = world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants.", [rec])
    world.db.execute("UPDATE evidence SET content_sha256='changed' WHERE evidence_id=?", (rec,))
    assert world.claims.get(PLACE, status="active")["count"] == 0
    assert world.claims.one(a["claim"]["id"])["status"] == "stale"


def test_place_read_includes_claims_on_rooms(world):
    room = f"room:{SID}:A"
    world.claims.put(room, "interior.natural_light", "high", "The kitchen is bright.", [_ev(world, "caption")])
    assert world.claims.get(PLACE)["count"] == 1 and world.claims.get(room)["count"] == 1
    hits = world.search.interiors("bright kitchen", kinds=["claim"])["hits"]
    assert hits and hits[0]["kind"] == "claim"


def test_reset_snapshot_restore(world):
    rec = _ev(world, "record")
    ids = [world.claims.put(PLACE, p, v, f"Statement {v}.", [rec])["claim"]["id"]
           for p, v in (("market.tenant_count", 3), ("market.stories", 5), ("market.year_built", 1990))]
    assert world.claims.snapshot("warm")["claims"] == 3
    out = world.claims.reset()
    assert out["archived"] == 3 and world.claims.get(PLACE, status="all")["count"] == 0
    assert world.db.scalar("SELECT count(*) FROM claim_archive") == 3
    assert world.db.scalar("SELECT count(*) FROM edges WHERE source IN ('agent','rule')") == 0
    assert world.claims.reset("restore", "warm")["restored"] == 3
    assert sorted(c["id"] for c in world.claims.get(PLACE, status="all")["claims"]) == sorted(ids)
    with pytest.raises(ApiError):
        world.claims.reset("restore", "missing")


def test_card_has_machine_readable_coverage(world):
    rec = _ev(world, "record")
    for p, v in (("market.tenant_count", 3), ("market.stories", 5), ("market.year_built", 1990)):
        world.claims.put(PLACE, p, v, f"Statement {v}.", [rec])
    card = render_card(world.db, world.claims, PLACE)
    assert "coverage: market=fresh(3) interior=none aerial=none surroundings=none" in card
    assert "[claim:" in card


def test_room_notes_count_toward_interior_coverage():
    from mundus_world.service.claims import coverage
    mk = lambda subj, pred: {"subject_id": subj, "predicate": pred, "status": "active"}  # noqa: E731
    cov = coverage([mk("room:X:a", "note.equipment"), mk("space:X", "note.amenity"), mk("pano:X:p", "pano.caption"),
                    mk("place:costar:1", "note.general")])
    assert cov["interior"]["state"] == "fresh" and cov["interior"]["fresh"] == 3
    assert cov["market"]["state"] == "none"


def test_private_scope_isolates_runs(world):
    """Two runs with their own scope never see or merge each other's claims, and the shared memory stays clean."""
    from mundus_world.service.claims import render_card
    from mundus_world.types.ctx import CLAIM_SCOPE
    rec = _ev(world, "record")
    ids = {}
    for run in ("run-a", "run-b"):
        tok = CLAIM_SCOPE.set(run)
        try:
            assert world.claims.get(PLACE)["count"] == 0
            out = world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants are recorded.", [rec], 0.9, run_id=run)
            assert out["outcome"] == "created"
            ids[run] = out["claim"]["id"]
            assert world.claims.get(PLACE)["count"] == 1 and "market=partial(1)" in render_card(world.db, world.claims, PLACE)
        finally:
            CLAIM_SCOPE.reset(tok)
    assert ids["run-a"] != ids["run-b"]
    assert world.claims.get(PLACE)["count"] == 0 and "No claims yet" in render_card(world.db, world.claims, PLACE)
    assert world.claims.purge_scoped() == {"purged": 2}
    assert world.db.scalar("SELECT count(*) FROM claim") == 0


def test_scoped_read_leaves_shared_claims_alone(world):
    """A run-scoped read must not mark shared claims stale, even when they are due."""
    from mundus_world.types.ctx import CLAIM_SCOPE
    rec = _ev(world, "record")
    cid = world.claims.put(PLACE, "market.tenant_count", 3, "Three tenants are recorded.", [rec], 0.9)["claim"]["id"]
    with world.db.write() as c:
        c.execute("UPDATE claim SET created_at='2000-01-01T00:00:00Z' WHERE claim_id=?", (cid,))
    tok = CLAIM_SCOPE.set("run-a")
    try:
        world.claims.get(PLACE)
    finally:
        CLAIM_SCOPE.reset(tok)
    assert world.db.scalar("SELECT status FROM claim WHERE claim_id=?", (cid,)) == "active"
    world.claims.get(PLACE)
    assert world.db.scalar("SELECT status FROM claim WHERE claim_id=?", (cid,)) == "stale"


def test_old_database_is_purged_of_aerial_facts(tmp_path):
    from mundus_world.repo.db import Database
    db = Database(tmp_path / "old.db")
    with db.write() as c:
        c.execute("CREATE TABLE aerial_facts (aerial_id TEXT PRIMARY KEY, place_id TEXT, evidence_id TEXT)")
        c.execute("INSERT INTO aerial_facts VALUES('aerial:p','p','ev:x')")
        c.execute("INSERT INTO evidence(evidence_id,type,source,source_id) VALUES('ev:x','aerial_facts','vexcel','aerial:p')")
        c.execute("INSERT INTO evidence(evidence_id,type,source,source_id) VALUES('ev:y','ortho_image','vexcel','aimg:p')")
        c.execute("INSERT INTO edges(src,rel,dst,source) VALUES('p','has_aerial','aerial:p','join')")
    db2 = Database(tmp_path / "old.db")
    assert "aerial_facts" not in db2.tables()
    assert [r[0] for r in db2.q("SELECT evidence_id FROM evidence")] == ["ev:y"]
    assert db2.scalar("SELECT count(*) FROM edges") == 0
