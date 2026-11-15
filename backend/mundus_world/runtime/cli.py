"""`mundus` command line: ingestion, serving, claims maintenance, snapshots, quality checks."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mundus_world.config.settings import load_settings
from mundus_world.providers.http import default_http
from mundus_world.repo.db import Database

STEPS = ["index", "costar", "select", "basics", "rooms", "resolve", "panos", "panos-defurnished", "aerial", "caption",
         "cards", "embed", "graph", "verify"]


def _out(obj: Any) -> None:
    print(json.dumps(obj, indent=1, default=str))


def run_step(step: str, s, db: Database, http, args) -> Any:
    from mundus_world.service import graph
    from mundus_world.service.ingest_kit import KitIngest
    from mundus_world.service.ingest_scan import ScanIngest

    kit, scan = KitIngest(s, db, http), ScanIngest(s, db, http)
    only = set(args.places.split(",")) if getattr(args, "places", None) else None
    force = bool(getattr(args, "force", False))
    if step == "index":
        return kit.index(force)
    if step == "costar":
        return kit.costar()
    if step == "select":
        return kit.select(only)
    if step == "basics":
        return scan.basics(force)
    if step == "rooms":
        return scan.rooms(force)
    if step == "resolve":
        return scan.resolve()
    if step == "panos":
        return scan.panos(force)
    if step == "panos-defurnished":
        return scan.panos(force, defurnished=True)
    if step == "aerial":
        return scan.aerial(force)
    if step == "caption":
        return scan.caption(force, workers=args.workers)
    if step == "cards":
        return scan.cards()
    if step == "embed":
        return scan.embed(force)
    if step == "graph":
        return graph.build_edges(db)
    if step == "verify":
        return verify(s, db)
    raise SystemExit(f"unknown step {step}")


def verify(s, db: Database) -> dict[str, Any]:
    """Acceptance report. Exits non-zero through `ok: false` when a hard check fails."""
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None, hard: bool = True) -> None:
        checks.append({"check": name, "ok": bool(ok), "hard": hard, "detail": detail})

    deep = db.scalar("SELECT count(*) FROM place WHERE is_deep=1")
    check("deep places selected", deep > 0, deep)
    sp = db.q("SELECT s.space_id, s.depth FROM space s JOIN place p ON p.place_id=s.place_id WHERE p.is_deep=1")
    check("every deep space has rooms data (depth>=3)", all(r["depth"] >= 3 for r in sp),
          {"spaces": len(sp), "below": sum(r["depth"] < 3 for r in sp)})
    over = db.q("SELECT space_id, count(*) n FROM pano WHERE is_selected=1 GROUP BY space_id HAVING n>?", (s.max_panos_per_space,))
    check(f"no space has more than {s.max_panos_per_space} selected panos", not over, len(over))
    sel = db.scalar("SELECT count(*) FROM pano WHERE is_selected=1")
    faces = db.scalar("SELECT count(*) FROM pano_face WHERE variant='furn'")
    check("at least 99% of selected pano faces on disk", sel == 0 or faces >= 0.99 * sel * 6, {"selected": sel, "faces": faces})
    missing = [r["path"] for r in db.q("SELECT path FROM pano_face ORDER BY random() LIMIT 200") if not (s.data_dir / r["path"]).exists()]
    check("sampled face files exist", not missing, missing[:3])
    caps = db.scalar("SELECT count(*) FROM pano_caption")
    with_faces = db.scalar("SELECT count(*) FROM pano WHERE is_selected=1 AND has_faces=1")
    check("at least 98% of selected panos captioned", with_faces == 0 or caps >= 0.98 * with_faces,
          {"captions": caps, "panos_with_faces": with_faces})
    aer = db.scalar("SELECT count(DISTINCT place_id) FROM aerial_image WHERE kind='ortho'")
    check("an overhead photo for every deep place", aer >= deep, {"with_overhead_photo": aer, "deep": deep})
    signed = 0
    for t, col in (("evidence", "url"), ("pano_face", "path"), ("aerial_image", "path"), ("floorplan", "path")):
        signed += db.scalar(f"SELECT count(*) FROM {t} WHERE {col} LIKE '%?t=%' OR {col} LIKE '%&t=%'")
    check("no signed upstream URL stored", signed == 0, signed)
    for t in ("place", "pano_caption", "room"):
        col = "evidence_id"
        where = " WHERE is_deep=1" if t == "place" else ""
        n = db.scalar(f"SELECT count(*) FROM {t}{where}{' AND' if where else ' WHERE'} {col} IS NULL")
        check(f"{t}: every row has an evidence id", n == 0, n)
    dangling = db.scalar("SELECT count(*) FROM pano_caption c LEFT JOIN evidence e ON e.evidence_id=c.evidence_id WHERE e.evidence_id IS NULL")
    check("caption evidence ids resolve", dangling == 0, dangling)
    emb = db.scalar("SELECT count(*) FROM embedding WHERE vector IS NOT NULL")
    docs = db.scalar("SELECT count(*) FROM embedding WHERE doc_type!='claim'")
    # semantic search is required unless it was switched off on purpose
    check("search documents embedded", docs > 0 and emb >= 0.95 * docs, {"docs": docs, "embedded": emb},
          hard=s.embed_provider != "none")
    edges = db.scalar("SELECT count(*) FROM edges")
    check("graph edges built", edges > 0, edges)
    types = {r[0] or "null": r[1] for r in db.q("SELECT type, count(*) FROM wall_edge GROUP BY 1")}
    check("wall edge types (information)", True, types, hard=False)
    failed = [dict(r) for r in db.q("SELECT step, count(*) n FROM ingest_log WHERE status='failed' GROUP BY step")]
    check("no failed ingest items", not failed, failed)
    ok = all(c["ok"] for c in checks if c["hard"])
    return {"ok": ok, "checks": checks}


def cmd_ingest(args) -> int:
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    s = load_settings(args.data_dir)
    db, http = Database(s.db_path), default_http()
    steps = STEPS if args.step == "all" else [args.step]
    rc = 0
    for st in steps:
        t0 = time.time()
        res = run_step(st, s, db, http, args)
        print(f"[{st}] {time.time() - t0:.1f}s {json.dumps(res, default=str)[:1500]}", flush=True)
        if st == "verify" and not res["ok"]:
            rc = 1
        if isinstance(res, dict) and res.get("failed") and st not in ("panos-defurnished",):
            print(f"[{st}] {res['failed']} items failed; rerun this step to retry them", flush=True)
    return rc


def cmd_serve(args) -> int:
    import uvicorn

    if args.data_dir:
        import os
        os.environ["WORLD_DATA_DIR"] = args.data_dir
    uvicorn.run("mundus_world.runtime.api:app_factory", factory=True, host=args.host, port=args.port, workers=1,
                log_level="warning")
    return 0


def cmd_claims(args) -> int:
    from mundus_world.runtime.container import build

    c = build(load_settings(args.data_dir))
    if args.action == "reset":
        _out(c.claims.reset(args.mode, args.name, args.clear_caches))
    elif args.action == "snapshot":
        _out(c.claims.snapshot(args.name or "default"))
    elif args.action == "list-snapshots":
        _out(c.claims.list_snapshots())
    return 0


def cmd_snapshot(args) -> int:
    s = load_settings(args.data_dir)
    Database(s.db_path).conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    out = Path(args.out or f"world-{time.strftime('%Y%m%d-%H%M%S')}.tar.zst").resolve()
    items = [p for p in ("world.db", "img", "basemap.json") if (s.data_dir / p).exists()]
    cmd = ["tar", "--zstd", "-cf", str(out), "-C", str(s.data_dir), *items]
    if subprocess.run(["tar", "--zstd", "--version"], capture_output=True).returncode != 0:
        out = out.with_suffix(".gz")
        cmd = ["tar", "-czf", str(out), "-C", str(s.data_dir), *items]
    subprocess.run(cmd, check=True)
    _out({"snapshot": str(out), "bytes": out.stat().st_size, "items": items})
    return 0


def cmd_restore(args) -> int:
    s = load_settings(args.data_dir)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-xf", args.file, "-C", str(s.data_dir)], check=True)
    _out({"restored_to": str(s.data_dir), "deep_places": Database(s.db_path).scalar("SELECT count(*) FROM place WHERE is_deep=1")})
    return 0


def cmd_warmup(args) -> int:
    from mundus_world.runtime.container import build
    from mundus_world.service import market

    c = build(load_settings(args.data_dir))
    queries = [q.strip() for q in Path(args.queries).read_text(encoding="utf-8").splitlines() if q.strip()] if args.queries else []
    market.describe(c.db, refresh=True)
    _out({"queries": len(queries), "embedded": c.search.warm(queries)})
    return 0


def cmd_qa(args) -> int:
    from mundus_world.service.qa import caption_lengths, caption_sheet

    s = load_settings(args.data_dir)
    db = Database(s.db_path)
    if args.action == "captions":
        _out(caption_sheet(s, db, args.n))
    else:
        _out(caption_lengths(s, db, default_http(), args.n, [x for x in args.levels.split(",") if x]))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mundus", description="Census world context layer")
    p.add_argument("--data-dir", default=None, help="data folder (default: WORLD_DATA_DIR or backend/data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="run ingestion steps")
    i.add_argument("step", choices=["all", *STEPS])
    i.add_argument("--places", help="comma-separated property ids or home ids: restrict the deep set (smoke runs)")
    i.add_argument("--force", action="store_true", help="redo items already marked done")
    i.add_argument("--workers", type=int, default=6, help="concurrent caption calls")
    i.add_argument("-v", "--verbose", action="store_true")
    i.set_defaults(fn=cmd_ingest)
    sv = sub.add_parser("serve", help="run the World API (REST + MCP)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(fn=cmd_serve)
    cl = sub.add_parser("claims", help="reset, snapshot or list claim snapshots")
    cl.add_argument("action", choices=["reset", "snapshot", "list-snapshots"])
    cl.add_argument("--mode", default="empty", choices=["empty", "restore"])
    cl.add_argument("--name")
    cl.add_argument("--clear-caches", action="store_true")
    cl.set_defaults(fn=cmd_claims)
    sn = sub.add_parser("snapshot", help="pack the database and images into one file")
    sn.add_argument("--out")
    sn.set_defaults(fn=cmd_snapshot)
    rs = sub.add_parser("restore", help="unpack a snapshot into the data folder")
    rs.add_argument("file")
    rs.set_defaults(fn=cmd_restore)
    w = sub.add_parser("warmup", help="pre-embed queries and cache the market schema")
    w.add_argument("--queries")
    w.set_defaults(fn=cmd_warmup)
    q = sub.add_parser("qa", help="caption quality sheet, or caption length experiment")
    q.add_argument("action", choices=["captions", "caption-lengths"])
    q.add_argument("-n", type=int, default=30)
    q.add_argument("--levels", default="brief,standard,deep,max")
    q.set_defaults(fn=cmd_qa)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
