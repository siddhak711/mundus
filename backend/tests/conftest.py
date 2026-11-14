"""A small synthetic world: 1 deep place, 1 space, 3 rooms plus a void, 24 panos, synthetic market rows.
Nothing here comes from the licensed data."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from mundus_world.config.settings import REPO_ROOT, Settings
from mundus_world.providers.http import Http
from mundus_world.repo.db import Database
from mundus_world.runtime.container import Container
from mundus_world.service import evidence as ev
from mundus_world.service import graph
from mundus_world.service.claims import Claims
from mundus_world.service.ingest_kit import _create_and_fill
from mundus_world.service.ingest_scan import ScanIngest
from mundus_world.service.search import Search
from mundus_world.service.world import World

PLACE = "place:costar:1001"
SID = "FIXTURE1"
SPACE = f"space:{SID}"


def synthetic_model() -> dict:
    """Rooms A (4x3), B (4x3) side by side, C (8x3) above them, and a void strip. Metres."""
    v = {"v1": (0, 0), "v2": (4, 0), "v3": (8, 0), "v4": (0, 3), "v5": (4, 3), "v6": (8, 3), "v7": (0, 6), "v8": (8, 6),
         "v9": (9, 0), "v10": (9, 3)}
    e = {"e1": ("v1", "v2"), "e2": ("v2", "v3"), "e3": ("v1", "v4"), "e4": ("v2", "v5"), "e5": ("v3", "v6"),
         "e6": ("v4", "v5"), "e7": ("v5", "v6"), "e8": ("v4", "v7"), "e9": ("v6", "v8"), "e10": ("v7", "v8"),
         "e11": ("v3", "v9"), "e12": ("v9", "v10"), "e13": ("v10", "v6")}

    def room(rid, label, edges, area, w, d, h=2.8):
        dims = {"areaFloor": area, "width": w, "depth": d, "height": h} if area else None
        r = {"id": rid, "floor": {"id": "f1"}, "classifications": [{"label": label, "confidence": 0.9}],
             "boundary": {"edges": [{"id": x} for x in edges]}}
        if dims:
            r["dimensions"] = dims
        return r

    panos = [{"id": f"p{i:02d}", "label": str(i), "position": {"x": 0.4 + (i % 8) * 0.95, "y": 0.5 + (i // 8) * 2.4, "z": 1.5}}
             for i in range(24)]
    return {
        "floors": [{"id": "f1", "label": "Floor 1",
                    "vertices": [{"id": k, "position": {"x": x, "y": y}} for k, (x, y) in v.items()],
                    "edges": [{"id": k, "type": "wall", "thickness": 0.12, "vertices": [{"id": a}, {"id": b}]}
                              for k, (a, b) in e.items()]}],
        "rooms": [room("A", "Kitchen", ["e1", "e3", "e4", "e6"], 12.0, 4, 3),
                  room("B", "Living Room", ["e2", "e4", "e5", "e7"], 12.0, 4, 3),
                  room("C", "Hallway", ["e6", "e7", "e8", "e9", "e10"], 24.0, 8, 3),
                  room("V", "Void", ["e5", "e11", "e12", "e13"], None, None, None)],
        "panoLocations": panos,
    }


def _jpeg(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "JPEG")
    return buf.getvalue()


def build_world(tmp_path, cap: int = 20, api_token: str = "", admin_token: str = "") -> Container:
    s = Settings(data_dir=tmp_path, max_panos_per_space=cap, api_token=api_token, admin_token=admin_token,
                 predicates_path=REPO_ROOT / "shared" / "predicates.yaml")
    db = Database(s.db_path)
    with db.write() as c:
        pev = ev.register(c, "record", "costar", "property:1001", content={"id": 1001}, place_id=PLACE, excerpt="Fixture Tower")
        c.execute("INSERT INTO place(place_id,kind,costar_property_id,name,address,city,lat,lon,property_type,building_sqft,"
                  "year_built,stories,is_deep,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                  (PLACE, "commercial", "1001", "Fixture Tower", "100 Test St", "Los Angeles", 34.05, -118.25, "Office",
                   50000.0, 1990, 5, pev))
        c.execute("INSERT INTO place_fts(place_id,text) VALUES(?,?)", (PLACE, "Fixture Tower 100 Test St Office 1001"))
        c.execute("INSERT INTO place(place_id,kind,costar_property_id,name,address,lat,lon,property_type,is_deep) "
                  "VALUES('place:costar:1002','commercial','1002','Shallow Plaza','200 Test St',34.0508,-118.25,'Retail',0)")
        c.execute("INSERT INTO place_fts(place_id,text) VALUES('place:costar:1002','Shallow Plaza 200 Test St Retail 1002')")
        sev = ev.register(c, "record", "matterport", SPACE, content={"sid": SID}, place_id=PLACE)
        sumev = ev.register(c, "summary", "matterport", SPACE, content="A bright test suite.", place_id=PLACE)
        c.execute("INSERT INTO space(space_id,sid,place_id,name,segment,space_kind,lat,lon,pano_count,room_count,floor_count,"
                  "has_summary,has_defurnished,has_splat,ai_summary,depth,is_la,evidence_id,summary_evidence_id,original_created) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (SPACE, SID, PLACE, "Suite 300", "commercial", "office", 34.05, -118.25, 24, 4, 1, 1, 0, 0,
                   "A bright test suite.", 2, 1, sev, sumev, "2024-01-01"))
        c.execute("INSERT INTO space(space_id,sid,name,segment,space_kind,lat,lon,pano_count,room_count,depth,is_la) "
                  "VALUES('space:SHALLOW','SHALLOW','Lobby','commercial','common',34.06,-118.26,3,1,0,1)")
    scan = ScanIngest(s, db, Http(limits={}))
    sp = dict(db.one("SELECT * FROM space WHERE space_id=?", (SPACE,)))
    scan._store_rooms(sp, synthetic_model(), [])
    scan.resolve()
    selected = [r["pano_id"] for r in db.q("SELECT pano_id FROM pano WHERE is_selected=1 ORDER BY pano_id")]
    with db.write() as c:
        for n, pid in enumerate(selected):
            raw = pid.split(":")[-1]
            for face in range(6):
                data = _jpeg((n * 9 % 255, face * 40, 120))
                rel = f"img/pano/{SID}/{raw}/furn_2k_{face}.jpg"
                (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
                (tmp_path / rel).write_bytes(data)
                fev = ev.register(c, "pano_image", "matterport", f"{pid}:furn:{face}", content=data, place_id=PLACE)
                c.execute("INSERT INTO pano_face(pano_id,variant,face,path,thumb_path,content_sha256,bytes,evidence_id) "
                          "VALUES(?,?,?,?,?,?,?,?)", (pid, "furn", face, rel, rel, ev.content_hash(data), len(data), fev))
            c.execute("UPDATE pano SET has_faces=1 WHERE pano_id=?", (pid,))
            text = ("Gym. A fitness room with 6 treadmills and wall mirrors." if n == 0 else
                    f"Office. An open office area with desks and task chairs, position {n}.")
            cev = ev.register(c, "caption", "derived", pid, content=text, place_id=PLACE, excerpt=text)
            c.execute("INSERT INTO pano_caption(pano_id,variant,model,prompt_version,caption_json,caption_text,created_at,evidence_id) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (pid, "furnished", "fixture", "cap-v2", json.dumps({"room_type": text.split(".")[0], "summary": text}),
                       text, "2026-11-14T00:00:00Z", cev))
        aev = ev.register(c, "aerial_facts", "vexcel", f"aerial:{PLACE}", content={"pool": False}, place_id=PLACE)
        c.execute("INSERT INTO aerial_facts(aerial_id,place_id,footprint_area_m2,structure_count,parcel_count,attributes_json,"
                  "match_method,match_distance_m,evidence_id) VALUES(?,?,?,?,?,?,?,?,?)",
                  (f"aerial:{PLACE}", PLACE, 900.0, 1, 1, json.dumps({"pool.detected": False, "vehicles.count": 4}),
                   "contains", 0.0, aev))
        c.execute("UPDATE space SET depth=4 WHERE space_id=?", (SPACE,))
    occ, sales = [], []
    with db.write() as c:
        for i, (name, sqft) in enumerate([("Acme Corp", 5000.0), ("Beta LLC", 2500.0), ("Gamma Inc", 1200.0)]):
            e_ = ev.register(c, "record", "costar", f"tenancy:{i}", content={"t": name}, place_id=PLACE, excerpt=f"Tenancy: {name}")
            occ.append({"row_id": str(i), "node_id": f"tenancy:{i}", "property_id": "1001", "place_id": PLACE, "evidence_id": e_,
                        "raw_json": json.dumps({"secret": "x"}), "tenant_name": name, "square_feet_occupied": sqft,
                        "from_date": f"202{i}-01-01T00:00:00Z", "tenant_location_id": str(100 + i)})
        e_ = ev.register(c, "record", "costar", "sale:9", content={"s": 1}, place_id=PLACE, excerpt="Sale 2019")
        sales.append({"row_id": "9:1001", "node_id": "sale:9", "property_id": "1001", "place_id": PLACE, "evidence_id": e_,
                      "raw_json": None, "sale_id": "9", "in_kit": 1, "sold_date": "2019-06-01T00:00:00Z", "sold_for_price": 9000000})
    _create_and_fill(db, "costar_occupancy", occ)
    _create_and_fill(db, "costar_sale_entity", sales)
    scan.cards()
    scan.embed()
    graph.build_edges(db)
    claims = Claims(db, s.predicates_path)
    return Container(settings=s, db=db, claims=claims, world=World(s, db, claims), search=Search(s, db))


@pytest.fixture()
def world(tmp_path) -> Container:
    return build_world(tmp_path)
