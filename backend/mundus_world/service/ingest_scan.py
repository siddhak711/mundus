"""Ingestion steps 4 onward for the deep places: Matterport structure and images, Vexcel, captions, cards, embeddings."""
from __future__ import annotations

import io
import json
import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PIL import Image
from shapely import wkt as shapely_wkt
from shapely.geometry import Point, shape

from mundus_world.config.settings import Settings
from mundus_world.providers.claude import CAPTION_PROMPT_VERSION, Claude, caption_short, caption_to_text
from mundus_world.providers.embedder import Embedder
from mundus_world.providers.http import Http, UpstreamAuthError, save_raw
from mundus_world.providers.matterport import Matterport
from mundus_world.providers.vexcel import OBLIQUE_KINDS, Vexcel, square_wkt
from mundus_world.repo.db import Database
from mundus_world.service import evidence as ev
from mundus_world.service import geometry as geo
from mundus_world.types.ids import floor_id, now_iso, pano_id, room_id, sha256_hex

log = logging.getLogger("mundus.ingest")
M2_TO_SQFT = 10.7639


def _jpeg_resized(data: bytes, max_px: int, quality: int = 85) -> bytes:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class ScanIngest:
    def __init__(self, settings: Settings, db: Database, http: Http):
        self.s, self.db, self.http = settings, db, http
        self.mp = Matterport(settings, http)
        self.vx = Vexcel(settings, http)
        self.cl = Claude(settings)
        self.cl.on_usage = ev.usage_logger(db)
        self.emb = Embedder(settings)

    # ---- helpers ---------------------------------------------------------
    def deep_spaces(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.q(
            "SELECT s.* FROM space s JOIN place p ON p.place_id=s.place_id WHERE p.is_deep=1 ORDER BY s.sid")]

    def deep_places(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.q("SELECT * FROM place WHERE is_deep=1 ORDER BY place_id")]

    def _each(self, step: str, items: list[Any], key: Callable[[Any], str], fn: Callable[[Any], None],
              force: bool = False, workers: int = 1) -> dict[str, int]:
        todo = [i for i in items if force or not self.db.ledger_done(step, key(i))]
        stats = {"total": len(items), "skipped": len(items) - len(todo), "done": 0, "failed": 0}

        def run(i: Any) -> None:
            k = key(i)
            try:
                fn(i)
                self.db.ledger_set(step, k, "done")
                stats["done"] += 1
            except UpstreamAuthError:
                raise
            except Exception as e:  # noqa: BLE001 - one bad item must not stop the step
                log.warning("%s %s failed: %s", step, k, e)
                self.db.ledger_set(step, k, "failed", str(e)[:300])
                stats["failed"] += 1

        if workers <= 1:
            for i in todo:
                run(i)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(run, todo))
        return stats

    def _img(self, rel: str) -> Path:
        p = self.s.img_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ---- step 4: basics --------------------------------------------------
    def basics(self, force: bool = False) -> dict[str, int]:
        def one(sp: dict[str, Any]) -> None:
            m = self.mp.basics(sp["sid"])
            save_raw(self.s.raw_dir, "matterport", f"basics_{sp['sid']}", {k: v for k, v in m.items() if k != "image"})
            summary = ((m.get("generatedDescription") or {}).get("summary") or "").strip() or None
            cls = ", ".join(c.get("classification", "") for c in m.get("propertyClassifications") or []) or None
            preview = None
            url = (m.get("image") or {}).get("url")
            if url:
                try:
                    p = self._img(f"preview/{sp['sid']}.jpg")
                    p.write_bytes(_jpeg_resized(self.mp.download(url), 1024))
                    preview = str(p.relative_to(self.s.data_dir))
                except Exception as e:  # noqa: BLE001
                    log.warning("preview %s: %s", sp["sid"], e)
            with self.db.write() as c:
                sev = None
                if summary:
                    sev = ev.register(c, "summary", "matterport", sp["space_id"], content=summary,
                                      place_id=sp["place_id"], url=f"/v1/spaces/{sp['space_id']}", excerpt=summary)
                c.execute("UPDATE space SET ai_summary=?, mp_classification=?, visibility=?, defurnished_view_id=?, "
                          "preview_path=COALESCE(?,preview_path), summary_evidence_id=?, depth=MAX(depth,2) WHERE space_id=?",
                          (summary, cls, m.get("visibility"), (m.get("view") or {}).get("id"), preview, sev, sp["space_id"]))

        return self._each("basics", self.deep_spaces(), lambda s: s["sid"], one, force)

    # ---- step 5: rooms, walls, floor plans, pano positions ----------------
    def rooms(self, force: bool = False) -> dict[str, int]:
        def one(sp: dict[str, Any]) -> None:
            sid = sp["sid"]
            m = self.mp.rooms(sid)
            slim = {k: v for k, v in m.items() if k != "assets"}
            save_raw(self.s.raw_dir, "matterport", f"rooms_{sid}", slim)
            plans = []
            for n, fp in enumerate(((m.get("assets") or {}).get("floorplans") or [])):
                flags = fp.get("flags") or []
                fmt = fp.get("format")
                keep = (fmt == "jpg" and flags == ["photogramy"]) or fmt == "dxf"
                if not keep or not fp.get("url"):
                    continue
                try:
                    data = self.mp.download(fp["url"])
                except Exception as e:  # noqa: BLE001
                    log.warning("floorplan %s #%d: %s", sid, n, e)
                    continue
                p = self._img(f"floorplan/{sid}/{n}.{fmt}")
                p.write_bytes(data)
                plans.append((n, fp, str(p.relative_to(self.s.data_dir)), sha256_hex(data)))
            self._store_rooms(sp, m, plans)

        return self._each("rooms", self.deep_spaces(), lambda s: s["sid"], one, force)

    def _store_rooms(self, sp: dict[str, Any], m: dict[str, Any], plans: list[tuple]) -> None:
        sid, space = sp["sid"], sp["space_id"]
        vpos: dict[str, tuple[float, float]] = {}
        edges: dict[str, tuple[str, str]] = {}
        with self.db.write() as c:
            for t in ("room", "pano", "floor", "floorplan"):
                if t == "pano":
                    c.execute("DELETE FROM pano WHERE space_id=? AND has_faces=0", (space,))
                else:
                    c.execute(f"DELETE FROM {t} WHERE space_id=?", (space,))
            for seq, f in enumerate(m.get("floors") or []):
                fid = floor_id(sid, f["id"])
                c.execute("INSERT OR REPLACE INTO floor(floor_id,space_id,label,seq) VALUES(?,?,?,?)",
                          (fid, space, f.get("label"), seq))
                for v in f.get("vertices") or []:
                    pos = v.get("position") or {}
                    vpos[v["id"]] = (float(pos.get("x", 0)), float(pos.get("y", 0)))
                    c.execute("INSERT OR REPLACE INTO wall_vertex(vertex_id,floor_id,x,y) VALUES(?,?,?,?)",
                              (v["id"], fid, *vpos[v["id"]]))
                for e in f.get("edges") or []:
                    vs = [v["id"] for v in e.get("vertices") or []]
                    if len(vs) == 2:
                        edges[e["id"]] = (vs[0], vs[1])
                        c.execute("INSERT OR REPLACE INTO wall_edge(edge_id,floor_id,v1,v2,type,thickness) VALUES(?,?,?,?,?,?)",
                                  (e["id"], fid, vs[0], vs[1], e.get("type"), e.get("thickness")))
            for r in m.get("rooms") or []:
                rid = room_id(sid, r["id"])
                eids = [e["id"] for e in ((r.get("boundary") or {}).get("edges") or [])]
                poly, quality = geo.build_polygon(eids, edges, vpos)
                cen = geo.polygon_centroid(poly)
                cls = (r.get("classifications") or [{}])[0]
                d = r.get("dimensions") or {}
                content = {"label": cls.get("label"), "dimensions": d, "edges": sorted(eids)}
                area = d.get("areaFloor")
                evid = ev.register(c, "room", "matterport", rid, content=content, place_id=sp["place_id"],
                                   url=f"/v1/rooms/{rid}",
                                   excerpt=f"Room {cls.get('label') or 'unlabelled'}: "
                                           f"{f'{area:.1f} m2' if area else 'no area'}, "
                                           f"height {d.get('height') or 'unknown'} m")
                c.execute(
                    """INSERT OR REPLACE INTO room(room_id,space_id,floor_id,label,label_confidence,area_m2,width_m,depth_m,
                         height_m,polygon_json,polygon_quality,centroid_x,centroid_y,edge_ids_json,evidence_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rid, space, floor_id(sid, (r.get("floor") or {}).get("id", "")) if r.get("floor") else None,
                     cls.get("label"), cls.get("confidence"), area, d.get("width"), d.get("depth"), d.get("height"),
                     json.dumps([[round(x, 3), round(y, 3)] for x, y in poly]), quality,
                     cen[0] if cen else None, cen[1] if cen else None, json.dumps(eids), evid))
            for p in m.get("panoLocations") or []:
                pos = p.get("position") or {}
                pid = pano_id(sid, p["id"])
                c.execute(
                    """INSERT INTO pano(pano_id,space_id,label,x,y,z) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(pano_id) DO UPDATE SET label=excluded.label, x=excluded.x, y=excluded.y, z=excluded.z""",
                    (pid, space, str(p.get("label") or ""), pos.get("x"), pos.get("y"), pos.get("z")))
            for n, fp, path, sha in plans:
                plan_id = f"plan:{sid}:{n}"
                evid = ev.register(c, "floorplan", "matterport", plan_id, content_sha=sha, place_id=sp["place_id"],
                                   url=f"/v1/floorplans/{plan_id}/image", excerpt=f"Floor plan ({fp.get('format')})")
                o = fp.get("origin") or {}
                c.execute("INSERT OR REPLACE INTO floorplan(plan_id,space_id,format,flags,path,width,height,px_per_m,"
                          "origin_x,origin_y,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (plan_id, space, fp.get("format"), ",".join(fp.get("flags") or []), path, fp.get("width"),
                           fp.get("height"), fp.get("resolution"), o.get("x"), o.get("y"), evid))
            c.execute("UPDATE space SET depth=MAX(depth,3) WHERE space_id=?", (space,))

    # ---- step 6: pano to room, pano cap, adjacency -------------------------
    def resolve(self) -> dict[str, int]:
        out = {"spaces": 0, "panos": 0, "selected": 0, "inside": 0, "adjacent_pairs": 0, "rooms_without_pano": 0}
        for sp in self.deep_spaces():
            space = sp["space_id"]
            rooms = [dict(r) for r in self.db.q("SELECT * FROM room WHERE space_id=?", (space,))]
            panos = [dict(r) for r in self.db.q("SELECT * FROM pano WHERE space_id=?", (space,))]
            if not panos and not rooms:
                continue
            floor_seq = {r["floor_id"]: r["seq"] for r in self.db.q("SELECT floor_id, seq FROM floor WHERE space_id=?", (space,))}
            rinfo = [{"room_id": r["room_id"], "floor_id": r["floor_id"], "polygon": json.loads(r["polygon_json"] or "[]"),
                      "centroid": (r["centroid_x"], r["centroid_y"]) if r["centroid_x"] is not None else None,
                      "is_void": (r["label"] or "").lower() == "void", "area": r["area_m2"],
                      "edge_ids": json.loads(r["edge_ids_json"] or "[]")} for r in rooms]
            by_floor: dict[Any, list[dict]] = {}
            for r in rinfo:
                by_floor.setdefault(r["floor_id"], []).append(r)
            # floor of a pano: the floor whose rooms contain it; ties resolved by the floor's median pano height
            assigned: dict[str, tuple[str | None, str, Any]] = {}
            zmed: dict[Any, float] = {}
            ambiguous: list[dict] = []
            for p in panos:
                if p["x"] is None:
                    assigned[p["pano_id"]] = (None, "none", None)
                    continue
                hits = [(f, *geo.match_pano_to_room(p["x"], p["y"], rs)) for f, rs in by_floor.items()]
                inside = [h for h in hits if h[2] == "inside"]
                if len(inside) == 1:
                    assigned[p["pano_id"]] = (inside[0][1], "inside", inside[0][0])
                elif len(inside) > 1:
                    ambiguous.append({"p": p, "hits": inside})
                else:
                    near = [h for h in hits if h[2] == "nearest"]
                    assigned[p["pano_id"]] = (near[0][1], "nearest", near[0][0]) if len(by_floor) == 1 and near else (None, "none", None)
            zs: dict[Any, list[float]] = {}
            for p in panos:
                a = assigned.get(p["pano_id"])
                if a and a[2] is not None and p["z"] is not None:
                    zs.setdefault(a[2], []).append(p["z"])
            zmed = {f: statistics.median(v) for f, v in zs.items()}
            for a in ambiguous:
                p = a["p"]
                best = min(a["hits"], key=lambda h: (abs((p["z"] or 0) - zmed.get(h[0], 1e9)), str(h[0])))
                assigned[p["pano_id"]] = (best[1], "inside", best[0])
            sel_in = [{"pano_id": p["pano_id"], "x": p["x"] or 0.0, "y": p["y"] or 0.0,
                       "floor_key": floor_seq.get(assigned[p["pano_id"]][2], 0) or 0,
                       "room_id": assigned[p["pano_id"]][0]} for p in panos]
            chosen = set(geo.select_panos(sel_in, [r for r in rinfo if not r["is_void"]], self.s.max_panos_per_space))
            vpos = {r["vertex_id"]: (r["x"], r["y"]) for r in self.db.q(
                "SELECT v.* FROM wall_vertex v JOIN floor f ON f.floor_id=v.floor_id WHERE f.space_id=?", (space,))}
            edges, etypes = {}, {}
            for r in self.db.q("SELECT e.* FROM wall_edge e JOIN floor f ON f.floor_id=e.floor_id WHERE f.space_id=?", (space,)):
                edges[r["edge_id"]] = (r["v1"], r["v2"])
                etypes[r["edge_id"]] = r["type"]
            adj = geo.adjacency(rinfo, edges, vpos, etypes)
            with self.db.write() as c:
                for p in panos:
                    rid, match, fid = assigned[p["pano_id"]]
                    c.execute("UPDATE pano SET room_id=?, room_match=?, floor_id=?, is_selected=? WHERE pano_id=?",
                              (rid, match, fid, int(p["pano_id"] in chosen), p["pano_id"]))
                    out["inside"] += match == "inside"
                for r in rooms:
                    tot = sum(1 for p in panos if assigned[p["pano_id"]][0] == r["room_id"])
                    sel = sum(1 for p in panos if assigned[p["pano_id"]][0] == r["room_id"] and p["pano_id"] in chosen)
                    c.execute("UPDATE room SET pano_total=?, pano_selected=? WHERE room_id=?", (tot, sel, r["room_id"]))
                    out["rooms_without_pano"] += int(sel == 0 and (r["label"] or "").lower() != "void")
                c.execute("DELETE FROM room_adjacency WHERE space_id=?", (space,))
                for a in adj:
                    c.execute("INSERT OR REPLACE INTO room_adjacency(room_a,room_b,space_id,shared_edge_ids,shared_length_m,"
                              "edge_types,involves_void) VALUES(?,?,?,?,?,?,?)",
                              (a["room_a"], a["room_b"], space, json.dumps(a["shared_edge_ids"]), a["shared_length_m"],
                               json.dumps(a["edge_types"]), a["involves_void"]))
            out["spaces"] += 1
            out["panos"] += len(panos)
            out["selected"] += len(chosen)
            out["adjacent_pairs"] += len(adj)
        return out

    # ---- step 7: pano images ----------------------------------------------
    def panos(self, force: bool = False, defurnished: bool = False) -> dict[str, int]:
        variant = "defurn" if defurnished else "furn"
        step = "panos-defurnished" if defurnished else "panos"
        spaces = [s for s in self.deep_spaces() if not defurnished or s.get("defurnished_view_id")]

        def one(sp: dict[str, Any]) -> None:
            sid = sp["sid"]
            wanted = {r["pano_id"] for r in self.db.q("SELECT pano_id FROM pano WHERE space_id=? AND is_selected=1", (sp["space_id"],))}
            if not wanted:
                return
            m = self.mp.panos(sp["defurnished_view_id"] if defurnished else sid)
            jobs = []
            for p in m.get("panoLocations") or []:
                pid = pano_id(sid, p["id"])
                kids = ((p.get("skybox") or {}).get("children")) or []
                if pid in wanted and len(kids) == 6:
                    jobs += [(pid, p["id"], face, url) for face, url in enumerate(kids)]

            def fetch(job: tuple) -> tuple:
                pid, raw_id, face, url = job
                data = self.mp.download(url)
                Image.open(io.BytesIO(data)).verify()
                p = self._img(f"pano/{sid}/{raw_id}/{variant}_2k_{face}.jpg")
                p.write_bytes(data)
                t = self._img(f"pano_thumb/{sid}/{raw_id}/{variant}_{face}.jpg")
                t.write_bytes(_jpeg_resized(data, 768, 80))
                return (pid, face, str(p.relative_to(self.s.data_dir)), str(t.relative_to(self.s.data_dir)),
                        sha256_hex(data), len(data))

            with ThreadPoolExecutor(max_workers=8) as ex:
                results = list(ex.map(fetch, jobs))
            with self.db.write() as c:
                got: dict[str, int] = {}
                for pid, face, path, thumb, sha, nbytes in results:
                    evid = ev.register(c, "pano_image", "matterport", f"{pid}:{variant}:{face}", content_sha=sha,
                                       place_id=sp["place_id"],
                                       url=f"/v1/panos/{pid}/faces/{face}?defurnished={int(defurnished)}",
                                       excerpt=f"360 photo face {face} ({'defurnished' if defurnished else 'furnished'}) in {sp['name']}")
                    c.execute("INSERT OR REPLACE INTO pano_face(pano_id,variant,face,path,thumb_path,content_sha256,bytes,"
                              "evidence_id) VALUES(?,?,?,?,?,?,?,?)", (pid, variant, face, path, thumb, sha, nbytes, evid))
                    got[pid] = got.get(pid, 0) + 1
                col = "has_defurnished_faces" if defurnished else "has_faces"
                for pid, n in got.items():
                    if n == 6:
                        c.execute(f"UPDATE pano SET {col}=1 WHERE pano_id=?", (pid,))
                if not defurnished:
                    c.execute("UPDATE space SET depth=MAX(depth,4) WHERE space_id=?", (sp["space_id"],))
            missing = wanted - set(got)
            if missing and not defurnished:
                # Matterport lists these camera positions but serves no images for them (a download error raises
                # above instead). Deselect them so counts, captions and room notes describe what was really ingested.
                log.warning("panos %s: %d selected panos have no images upstream; deselected", sid, len(missing))
                with self.db.write() as c:
                    c.executemany("UPDATE pano SET is_selected=0 WHERE pano_id=?", [(m_,) for m_ in sorted(missing)])
                    c.execute("UPDATE room SET pano_selected=(SELECT count(*) FROM pano p WHERE p.room_id=room.room_id "
                              "AND p.is_selected=1) WHERE space_id=?", (sp["space_id"],))

        return self._each(step, spaces, lambda s: s["sid"], one, force)

    # ---- step 8: aerial ----------------------------------------------------
    def aerial(self, force: bool = False) -> dict[str, int]:
        def one(pl: dict[str, Any]) -> None:
            lat, lon = pl["lat"], pl["lon"]
            if lat is None or lon is None:
                raise RuntimeError("place has no coordinates")
            fc = self.vx.property_at(f"POINT({lon} {lat})")
            feats = (fc or {}).get("features") or []

            def biggest(fs: list[dict]) -> float:
                return max((s.get("footprint.area") or 0 for f in fs for s in (f["properties"].get("structures") or [])),
                           default=0.0)

            if not feats or (biggest(feats) < 100 and (pl.get("building_sqft") or 0) > 5000):
                fc2 = self.vx.property_at(square_wkt(lat, lon, 25))
                more = (fc2 or {}).get("features") or []
                if more:
                    feats = feats + more
            key = pl["place_id"].replace(":", "_")
            # The property record is used only to frame the angled photos around the building. Nothing from it is kept.
            facts = pick_structure(feats, lat, lon)
            images = []
            for size in (80, 250):
                try:
                    images.append(("ortho", size, self.vx.ortho(lat, lon, size)))
                except Exception as e:  # noqa: BLE001
                    log.warning("ortho %s %dm: %s", pl["place_id"], size, e)
            bbox = facts.get("bbox_wkt") or square_wkt(lat, lon, 30)
            for kind in OBLIQUE_KINDS:
                try:
                    images.append((kind, 0, self.vx.oblique(bbox, kind)))
                except Exception as e:  # noqa: BLE001
                    log.warning("%s %s: %s", kind, pl["place_id"], e)
            with self.db.write() as c:
                for kind, size, data in images:
                    im = Image.open(io.BytesIO(data))
                    p = self._img(f"aerial/{key}/{kind}_{size}.jpg")
                    p.write_bytes(data)
                    iid = f"aimg:{pl['place_id']}:{kind}:{size}"
                    sha = sha256_hex(data)
                    ievid = ev.register(c, "ortho_image" if kind == "ortho" else "oblique_image", "vexcel", iid,
                                        content_sha=sha, place_id=pl["place_id"],
                                        url=f"/v1/places/{pl['place_id']}/aerial?kind={kind}&size_m={size}",
                                        excerpt=f"Aerial {kind} image" + (f", {size} m across" if size else ""))
                    c.execute("INSERT OR REPLACE INTO aerial_image(image_id,place_id,kind,size_m,path,width,height,"
                              "content_sha256,fetched_at,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (iid, pl["place_id"], kind, size, str(p.relative_to(self.s.data_dir)), im.width, im.height,
                               sha, now_iso(), ievid))

        return self._each("aerial", self.deep_places(), lambda p: p["place_id"], one, force)

    # ---- step 9: captions --------------------------------------------------
    def caption(self, force: bool = False, workers: int = 16) -> dict[str, int]:
        rows = [dict(r) for r in self.db.q(
            """SELECT p.pano_id, p.space_id, p.room_id, s.name AS space_name, s.place_id,
                      r.label, r.area_m2, r.width_m, r.depth_m, r.height_m
               FROM pano p JOIN space s ON s.space_id=p.space_id LEFT JOIN room r ON r.room_id=p.room_id
               WHERE p.is_selected=1 AND p.has_faces=1 ORDER BY p.pano_id""")]
        usage = {"in": 0, "out": 0, "thought": 0}

        def one(r: dict[str, Any]) -> None:
            faces = self.db.q("SELECT face, path, content_sha256 FROM pano_face WHERE pano_id=? AND variant='furn' "
                              "AND face BETWEEN 1 AND 4 ORDER BY face", (r["pano_id"],))
            if len(faces) != 4:
                raise RuntimeError("pano does not have 4 horizon faces")
            imgs = [_jpeg_resized((self.s.data_dir / f["path"]).read_bytes(), 1024) for f in faces]
            dims = ""
            if r["area_m2"]:
                dims = f"{r['area_m2']:.1f} m2 floor area, {r['width_m'] or 0:.1f} x {r['depth_m'] or 0:.1f} m"
                if r["height_m"]:
                    dims += f", ceiling {r['height_m']:.2f} m"
            cap, um, model = self.cl.caption(imgs, r["space_name"], r["label"] or "", dims, detail=self.s.caption_detail)
            usage["in"] += um["tokens_in"]
            usage["out"] += um["tokens_out"]
            usage["thought"] += um["tokens_thought"]
            text = caption_to_text(cap)
            with self.db.write() as c:
                evid = ev.register(c, "caption", "derived", r["pano_id"], content=text, place_id=r["place_id"],
                                   url=f"/v1/panos/{r['pano_id']}", excerpt=caption_short(cap))
                c.execute("INSERT OR REPLACE INTO pano_caption(pano_id,variant,model,prompt_version,caption_json,caption_text,"
                          "input_sha256,created_at,evidence_id) VALUES(?,?,?,?,?,?,?,?,?)",
                          (r["pano_id"], "furnished", model, f"{CAPTION_PROMPT_VERSION}:{self.s.caption_detail}",
                           json.dumps(cap, ensure_ascii=False), text,
                           sha256_hex("|".join(f["content_sha256"] for f in faces)), now_iso(), evid))
                c.execute("UPDATE pano SET evidence_id=? WHERE pano_id=?", (evid, r["pano_id"]))

        st = self._each("caption", rows, lambda r: r["pano_id"], one, force, workers=workers)
        st.update(tokens_in=usage["in"], tokens_out=usage["out"], tokens_thought=usage["thought"])
        return st

    # ---- step 10: cards ----------------------------------------------------
    def cards(self) -> dict[str, int]:
        n = {"rooms": 0, "spaces": 0, "places": 0}
        for sp in self.deep_spaces():
            space = sp["space_id"]
            rooms = [dict(r) for r in self.db.q("SELECT * FROM room WHERE space_id=? ORDER BY area_m2 DESC", (space,))]
            caps = {r["pano_id"]: dict(r) for r in self.db.q(
                "SELECT c.pano_id, c.caption_json, c.caption_text, p.room_id FROM pano_caption c JOIN pano p ON p.pano_id=c.pano_id "
                "WHERE p.space_id=? AND c.variant='furnished'", (space,))}
            room_cards = []
            with self.db.write() as c:
                for r in rooms:
                    lines = [room_header(r)]
                    for cap in (x for x in caps.values() if x["room_id"] == r["room_id"]):
                        lines.append(cap["caption_text"])
                    if r["pano_selected"] == 0 and (r["label"] or "").lower() != "void":
                        lines.append("No photo of this room was ingested, so its appearance is unknown.")
                    text = "\n".join(lines)
                    c.execute("UPDATE room SET card_text=? WHERE room_id=?", (text, r["room_id"]))
                    if (r["label"] or "").lower() != "void":
                        room_cards.append(lines[0] + (" " + caption_short(json.loads(next(
                            (x["caption_json"] for x in caps.values() if x["room_id"] == r["room_id"]), "{}"))) if any(
                            x["room_id"] == r["room_id"] for x in caps.values()) else ""))
                    n["rooms"] += 1
                total = sum(r["area_m2"] or 0 for r in rooms if (r["label"] or "").lower() != "void")
                head = (f"{sp['name']} ({sp['space_kind']} space, Matterport scan {sp['sid']}, scanned {sp['original_created']}). "
                        f"{len(rooms)} rooms, {total:.0f} m2 ({total * M2_TO_SQFT:.0f} sq ft) measured floor area, "
                        f"{sp['pano_count']} camera positions.")
                loose = [x["caption_text"] for x in caps.values() if not x["room_id"]]
                text = "\n".join([head, f"Summary: {sp['ai_summary']}" if sp.get("ai_summary") else "No Matterport summary.",
                                  *room_cards, *loose[:6]])
                c.execute("UPDATE space SET card_text=? WHERE space_id=?", (text, space))
                n["spaces"] += 1
        for pl in self.deep_places():
            text = place_card(self.db, pl)
            self.db.execute("UPDATE place SET card_text=? WHERE place_id=?", (text, pl["place_id"]))
            n["places"] += 1
        return n

    # ---- step 11: search documents and embeddings ---------------------------
    def embed(self, force: bool = False) -> dict[str, int]:
        docs: list[dict[str, Any]] = []
        for r in self.db.q("""SELECT c.pano_id, c.caption_text, c.evidence_id, p.space_id, s.place_id, s.name, p.label
                              FROM pano_caption c JOIN pano p ON p.pano_id=c.pano_id JOIN space s ON s.space_id=p.space_id
                              WHERE c.variant='furnished'"""):
            docs.append({"doc_id": r["pano_id"], "doc_type": "pano", "place_id": r["place_id"], "space_id": r["space_id"],
                         "title": f"{r['name']}, position {r['label']}", "text": r["caption_text"], "evidence_id": r["evidence_id"]})
        for r in self.db.q("""SELECT r.room_id, r.card_text, r.label, r.evidence_id, r.space_id, s.place_id, s.name FROM room r
                              JOIN space s ON s.space_id=r.space_id JOIN place p ON p.place_id=s.place_id
                              WHERE p.is_deep=1 AND r.card_text IS NOT NULL AND lower(coalesce(r.label,''))!='void'"""):
            docs.append({"doc_id": r["room_id"], "doc_type": "room", "place_id": r["place_id"], "space_id": r["space_id"],
                         "title": f"{r['name']}: {r['label'] or 'room'}", "text": r["card_text"], "evidence_id": r["evidence_id"]})
        for r in self.db.q("""SELECT s.space_id, s.card_text, s.name, s.place_id, s.evidence_id FROM space s
                              JOIN place p ON p.place_id=s.place_id WHERE p.is_deep=1 AND s.card_text IS NOT NULL"""):
            docs.append({"doc_id": r["space_id"], "doc_type": "space", "place_id": r["place_id"], "space_id": r["space_id"],
                         "title": r["name"], "text": r["card_text"], "evidence_id": r["evidence_id"]})
        for r in self.db.q("SELECT place_id, name, card_text, evidence_id FROM place WHERE is_deep=1 AND card_text IS NOT NULL"):
            docs.append({"doc_id": r["place_id"], "doc_type": "place", "place_id": r["place_id"], "space_id": None,
                         "title": r["name"], "text": r["card_text"], "evidence_id": r["evidence_id"]})
        have = {r["doc_id"]: (r["text_sha256"], r["vector"] is not None) for r in self.db.q(
            "SELECT doc_id, text_sha256, vector FROM embedding")}
        todo = [d for d in docs if force or have.get(d["doc_id"]) != (sha256_hex(d["text"]), True)]
        vectors: dict[str, bytes | None] = {}
        failed = 0
        dim = self.s.embed_dim
        if todo and self.emb.available():
            for i in range(0, len(todo), 64):
                chunk = todo[i:i + 64]
                try:
                    vecs = self.emb.documents([d["text"] for d in chunk])
                    for d, v in zip(chunk, vecs, strict=True):
                        vectors[d["doc_id"]] = v.tobytes()
                        dim = int(v.shape[0])
                except Exception as e:  # noqa: BLE001 - text search still works without vectors
                    log.warning("embedding batch failed: %s", e)
                    failed += len(chunk)
        with self.db.write() as c:
            ids = {d["doc_id"] for d in docs}
            for old in set(have) - ids:
                if not old.startswith("claim:"):
                    c.execute("DELETE FROM embedding WHERE doc_id=?", (old,))
                    c.execute("DELETE FROM doc_fts WHERE doc_id=?", (old,))
            for d in todo:
                c.execute("INSERT OR REPLACE INTO embedding(doc_id,doc_type,place_id,space_id,title,text,text_sha256,model,dim,"
                          "vector,evidence_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (d["doc_id"], d["doc_type"], d["place_id"], d["space_id"], d["title"], d["text"],
                           sha256_hex(d["text"]), self.s.embed_model, dim, vectors.get(d["doc_id"]), d["evidence_id"]))
                c.execute("DELETE FROM doc_fts WHERE doc_id=?", (d["doc_id"],))
                c.execute("INSERT INTO doc_fts(doc_id,doc_type,text) VALUES(?,?,?)",
                          (d["doc_id"], d["doc_type"], f"{d['title']}\n{d['text']}"))
        return {"docs": len(docs), "updated": len(todo), "embedded": len(vectors), "embed_failed": failed,
                "embed_provider": self.s.embed_provider if self.emb.enabled else "none"}


def room_header(r: dict[str, Any]) -> str:
    label = r["label"] or "Unlabelled room"
    if r["area_m2"]:
        s = (f"{label}: {r['area_m2']:.1f} m2 ({r['area_m2'] * M2_TO_SQFT:.0f} sq ft), "
             f"{r['width_m'] or 0:.1f} x {r['depth_m'] or 0:.1f} m")
        if r["height_m"]:
            s += f", ceiling {r['height_m']:.2f} m"
        return s + "."
    return f"{label}: no measured dimensions."


def _to_m(geom, lat0: float, lon0: float):
    """Rough local projection to metres around (lat0, lon0)."""
    import math

    from shapely.affinity import affine_transform
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 111320.0
    return affine_transform(geom, [kx, 0, 0, ky, -lon0 * kx, -lat0 * ky])


def pick_structure(features: list[dict[str, Any]], lat: float, lon: float) -> dict[str, Any]:
    """Choose the building for a place from Vexcel parcels: the largest footprint within 50 m of the point."""
    pt = Point(0, 0)
    best = None
    n_struct = 0
    for f in features:
        props = f.get("properties") or {}
        for s in props.get("structures") or []:
            n_struct += 1
            w = s.get("footprint.wkt")
            if not w:
                continue
            try:
                g = _to_m(shapely_wkt.loads(w), lat, lon)
            except Exception:  # noqa: BLE001
                continue
            d = g.distance(pt)
            if d <= 50:
                cand = (s.get("footprint.area") or g.area, -d, s, f, d)
                if best is None or cand[:2] > best[:2]:
                    best = cand
    out: dict[str, Any] = {"structure_count": n_struct, "parcel_count": len(features), "attributes": {}}
    parcel_f = best[3] if best else None
    if parcel_f is None and features:
        def pdist(f: dict) -> float:
            try:
                return _to_m(shape(f["geometry"]), lat, lon).distance(pt)
            except Exception:  # noqa: BLE001
                return 1e9
        parcel_f = min(features, key=pdist)
    if parcel_f is not None:
        props = parcel_f.get("properties") or {}
        out["attributes"] = {k: v for k, v in props.items() if k != "structures" and v is not None}
        try:
            pg = shape(parcel_f["geometry"])
            out["parcel_wkt"] = pg.wkt
            out["attributes"]["parcel.area_m2"] = round(_to_m(pg, lat, lon).area, 1)
            b = pg.bounds
            out["bbox_wkt"] = f"POLYGON(({b[0]} {b[1]},{b[2]} {b[1]},{b[2]} {b[3]},{b[0]} {b[3]},{b[0]} {b[1]}))"
        except Exception:  # noqa: BLE001
            pass
    if best:
        _, _, s, _, d = best
        out["footprint_wkt"] = s.get("footprint.wkt")
        out["footprint_area_m2"] = s.get("footprint.area")
        out["match_method"] = "contains" if d < 0.5 else "nearest"
        out["match_distance_m"] = round(d, 1)
        for k, v in s.items():
            if v is not None and not k.endswith(".wkt"):
                out["attributes"][f"structure.{k}"] = v
        try:
            b = shapely_wkt.loads(s["footprint.wkt"]).bounds
            out["bbox_wkt"] = f"POLYGON(({b[0]} {b[1]},{b[2]} {b[1]},{b[2]} {b[3]},{b[0]} {b[3]},{b[0]} {b[1]}))"
        except Exception:  # noqa: BLE001
            pass
    else:
        out["match_method"] = "parcel_only" if parcel_f is not None else "none"
    return out


def place_card(db: Database, pl: dict[str, Any]) -> str:
    """One text blob per place combining market and interior facts. No model call."""
    pid = pl["place_id"]
    lines = [f"{pl['name']} ({pid}). {pl['property_type'] or 'Unknown type'} at {pl['address'] or 'unknown address'}, "
             f"{pl['city'] or 'Los Angeles'}. "
             + (f"{pl['building_sqft']:.0f} sq ft. " if pl.get("building_sqft") else "Building size not recorded. ")
             + (f"Built {pl['year_built']}. " if pl.get("year_built") else "")
             + (f"{pl['stories']} storeys." if pl.get("stories") else "")]
    if pl["kind"] == "home":
        for r in (db.q("SELECT row_id, current_price, property_beds_max, property_baths_max, listing_status_label FROM "
                       "costar_res_listing WHERE place_id=?", (pid,)) if "costar_res_listing" in db.tables() else []):
            lines.append(f"Home listing {r['row_id']}: price {r['current_price']}, {r['property_beds_max']} beds, "
                         f"{r['property_baths_max']} baths, status {r['listing_status_label']}.")
    else:
        prop = pl["costar_property_id"]
        tables = set(db.tables())

        def count(table: str) -> int:
            return db.scalar(f"SELECT count(*) FROM {table} WHERE property_id=?", (prop,)) if table in tables else 0

        lines.append(f"Market records: {count('costar_occupancy')} tenancies, {count('costar_listing')} listings, "
                     f"{count('costar_sale_entity')} sales.")
        if "costar_sale_entity" in tables:
            last = db.one("SELECT sold_date, sold_for_price FROM costar_sale_entity WHERE property_id=? AND sold_date "
                          "IS NOT NULL ORDER BY sold_date DESC LIMIT 1", (prop,))
            if last:
                lines.append(f"Most recent sale: {str(last['sold_date'])[:10]} for {last['sold_for_price']}.")
        if "costar_apartment_listing" in tables:
            apt = db.one("SELECT min_rent, max_rent, num_units_available, total_num_units FROM costar_apartment_listing "
                         "WHERE property_id=?", (prop,))
            if apt:
                lines.append(f"Apartment listing: rents {apt['min_rent']} to {apt['max_rent']} per month, "
                             f"{apt['num_units_available']} of {apt['total_num_units']} units available.")
        if "costar_occupancy" in tables:
            tenants = [r[0] for r in db.q("SELECT DISTINCT tenant_name FROM costar_occupancy WHERE property_id=? AND "
                                          "tenant_name IS NOT NULL ORDER BY square_feet_occupied DESC LIMIT 8", (prop,))]
            if tenants:
                lines.append("Tenants include: " + ", ".join(tenants) + ".")
    spaces = db.q("SELECT name, space_kind, pano_count, room_count FROM space WHERE place_id=? ORDER BY name", (pid,))
    if spaces:
        lines.append(f"{len(spaces)} scanned spaces: " + "; ".join(f"{s['name']} ({s['space_kind']}, {s['room_count']} rooms)"
                                                                   for s in spaces[:30]) + ".")
    return "\n".join(lines)
