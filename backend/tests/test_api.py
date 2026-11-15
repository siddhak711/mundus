import asyncio
import json

import pytest
from conftest import PLACE, SID, SPACE, build_world
from fastapi.testclient import TestClient

from mundus_world.providers.http import Http, UpstreamAuthError
from mundus_world.runtime.api import create_app
from mundus_world.service import market
from mundus_world.service.ingest_kit import flatten, strip_private
from mundus_world.types.errors import ApiError


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(build_world(tmp_path, api_token="tok", admin_token="adm"))) as c:
        c.headers.update({"Authorization": "Bearer tok"})
        yield c


def test_auth(client):
    assert client.get("/healthz", headers={"Authorization": ""}).json()["deep_places"] == 1
    assert client.get("/v1/stats", headers={"Authorization": ""}).status_code == 401
    assert client.get("/v1/stats?token=tok", headers={"Authorization": ""}).status_code == 200
    assert client.post("/v1/admin/claims/reset", json={}).status_code == 401
    assert client.post("/v1/admin/claims/reset", json={}, headers={"Authorization": "Bearer adm"}).status_code == 200


def test_place_bundle_shape_and_evidence(client):
    d = client.get(f"/v1/places/{PLACE}").json()
    assert d["is_deep"] and d["spaces"][0]["space_id"] == SPACE
    assert d["market"]["tenancies"]["count"] == 3 and d["market"]["sales"]["count"] == 1
    assert d["aerial"]["match_method"] == "contains" and d["nearby_places"][0]["place_id"] == "place:costar:1002"
    ids = [d["evidence_id"], d["aerial"]["evidence_id"], *[i["evidence_id"] for i in d["market"]["tenancies"]["items"]]]
    for e in ids:
        assert client.get(f"/v1/evidence/{e}").status_code == 200


def test_errors_have_the_contract_shape(client):
    r = client.get("/v1/places/place:costar:999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    unselected = f"pano:{SID}:" + next(p["pano_id"] for p in client.get(f"/v1/spaces/{SPACE}").json()["panos"]
                                       if not p["is_selected"]).split(":")[-1]
    r = client.get(f"/v1/panos/{unselected}/faces/1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ingested"
    assert client.get("/v1/spaces/space:SHALLOW").json()["rooms"] == []


def test_images_carry_evidence_headers(client):
    pano = next(p["pano_id"] for p in client.get(f"/v1/spaces/{SPACE}").json()["panos"] if p["has_image"])
    for url in (f"/v1/panos/{pano}/faces/1", f"/panos/{pano}/faces/2?defurnished=0", f"/v1/panos/{pano}/image?face=3"):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert r.headers["x-evidence-id"].startswith("ev:") and len(r.headers["x-content-hash"]) == 64


def test_search_finds_the_gym_and_works_without_embeddings(client):
    d = client.post("/v1/interiors/search", json={"text": "treadmills", "limit": 3}).json()
    assert d["mode"] == "text_only" and "treadmills" in d["hits"][0]["snippet"].lower()
    assert client.get("/v1/places/search?q=fixture").json()["places"][0]["place_id"] == PLACE
    near = client.get("/v1/places/search?lat=34.05&lon=-118.25&radius_m=50").json()
    assert [p["place_id"] for p in near["places"]] == [PLACE]


def test_sql_guard(client, tmp_path):
    ok = client.post("/v1/market/query", json={"sql": "SELECT tenant_name, evidence_id FROM costar_occupancy ORDER BY 1"}).json()
    assert ok["row_count"] == 3 and ok["columns"] == ["tenant_name", "evidence_id"]
    for bad in ["DROP TABLE place", "SELECT 1; SELECT 2", "ATTACH DATABASE 'x' AS y", "PRAGMA table_info(place)",
                "SELECT * FROM claim", "SELECT raw_json FROM costar_occupancy", "UPDATE place SET name='x'",
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT count(*) FROM c"]:
        r = client.post("/v1/market/query", json={"sql": bad})
        assert r.status_code == 400 and r.json()["error"]["code"] == "sql_rejected", bad
    assert client.get(f"/v1/places/{PLACE}").json()["name"] == "Fixture Tower"


def test_row_cap(world):
    with pytest.raises(ApiError):
        market.query(world.db, "")
    out = market.query(world.db, "SELECT tenant_name FROM costar_occupancy", limit=2)
    assert out["row_count"] == 2 and out["truncated"]
    with pytest.raises(ApiError):                      # SELECT * would read the hidden raw_json column
        market.query(world.db, "SELECT * FROM costar_occupancy")


def test_claims_over_rest_and_run_tagging(client):
    ev_id = client.get(f"/v1/places/{PLACE}").json()["market"]["tenancies"]["items"][0]["evidence_id"]
    h = {"X-Run-Id": "run-A"}
    r = client.post("/v1/claims", headers=h, json={"subject_id": PLACE, "predicate": "market.tenant_count", "value": 3,
                                                   "statement": "Three tenants.", "evidence_ids": [ev_id]}).json()
    assert r["outcome"] == "created" and r["claim"]["run_id"] == "run-A"
    client.get(f"/v1/places/{PLACE}", headers={"X-Run-Id": "run-B"})
    a = client.get("/v1/stats?run_id=run-A").json()
    b = client.get("/v1/stats?run_id=run-B").json()
    assert [o["op"] for o in a["api_calls"]] == ["put_claim"] and [o["op"] for o in b["api_calls"]] == ["get_place"]
    assert "coverage:" in client.get(f"/v1/places/{PLACE}/card").text


def test_mcp_exposes_exactly_the_contract_tools(tmp_path):
    from mundus_world.runtime.api import CALLER, RUN_ID
    from mundus_world.runtime.mcp_server import build_mcp
    from mundus_world.runtime.tools import Ops

    c = build_world(tmp_path)
    mcp = build_mcp(c, Ops(c), RUN_ID, CALLER)
    names = sorted(t.name for t in asyncio.run(mcp.list_tools()))
    assert names == ["aerial_semantic_search", "describe_market", "get_aerial_facts", "get_claims", "get_evidence",
                     "get_neighbors", "get_place", "get_room", "get_space", "put_claim", "query_market",
                     "search_interiors", "search_places"]
    assert "claims_reset" not in names


def test_ops_match_between_rest_and_tools(client, tmp_path):
    from mundus_world.runtime.tools import Ops
    ops = Ops(client.app.state.container)
    assert json.dumps(ops.get_room(f"room:{SID}:A"), sort_keys=True) == json.dumps(
        client.get(f"/v1/rooms/room:{SID}:A").json(), sort_keys=True)


def test_private_fields_never_stored():
    rec = {"id": 1, "buildingName": "X", "contacts": [{"emailAddress": "a@b.c"}], "listingContacts": [{"firstName": "A"}],
           "propertyApartment": {"sitePhoneNumber": "555", "totalNumUnits": 9}, "propertyType": 5}
    clean = strip_private(rec)
    assert "contacts" not in clean and "sitePhoneNumber" not in clean["propertyApartment"]
    flat = flatten(rec, {"PropertyType": {"5": "Office"}})
    assert flat["property_type_label"] == "Office" and flat["property_apartment_total_num_units"] == 9
    assert not any("contact" in k or "phone" in k for k in flat)


def test_http_rate_limit_retry_and_auth_abort():
    import time

    import httpx
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if req.url.path == "/flaky":
            return httpx.Response(500 if calls["n"] == 1 else 200, json={"ok": True})
        if req.url.path == "/denied":
            return httpx.Response(403)
        return httpx.Response(200, json={"ok": True})

    h = Http(limits={"x.test": 20.0}, sleep=lambda _s: None, transport=httpx.MockTransport(handler))
    t0 = time.monotonic()
    for _ in range(40):
        h.get_json("https://x.test/ok")
    assert time.monotonic() - t0 >= 0.9          # 40 calls at 20 per second with a burst of 20
    calls["n"] = 0
    assert h.get_json("https://x.test/flaky") == {"ok": True} and calls["n"] == 2
    with pytest.raises(UpstreamAuthError):
        h.get_json("https://x.test/denied")
