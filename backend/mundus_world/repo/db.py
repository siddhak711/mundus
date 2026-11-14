"""SQLite access: schema, thread-local connections, serialized writes."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS place (
  place_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'commercial',     -- commercial | home
  costar_property_id TEXT UNIQUE,
  residential_listing_id TEXT,
  name TEXT, address TEXT, city TEXT, postal_code TEXT,
  lat REAL, lon REAL,
  property_type TEXT, building_sqft REAL, year_built INTEGER, stories INTEGER,
  is_deep INTEGER NOT NULL DEFAULT 0,
  card_text TEXT, evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS place_latlon ON place(lat, lon);

CREATE TABLE IF NOT EXISTS space (
  space_id TEXT PRIMARY KEY,
  sid TEXT UNIQUE NOT NULL,
  place_id TEXT,
  name TEXT, segment TEXT, space_kind TEXT,
  lat REAL, lon REAL, latlon_source TEXT, address TEXT,
  internal_id TEXT, index_costar_property_id TEXT, index_homes_listing_id TEXT,
  pano_count INTEGER, room_count INTEGER, floor_count INTEGER,
  has_summary INTEGER, has_defurnished INTEGER, has_splat INTEGER, drone_photos INTEGER,
  defurnished_view_id TEXT,
  original_created TEXT,
  ai_summary TEXT, mp_classification TEXT, visibility TEXT,
  showcase_url TEXT, preview_path TEXT, card_text TEXT,
  depth INTEGER NOT NULL DEFAULT 0,
  is_la INTEGER NOT NULL DEFAULT 0,
  evidence_id TEXT, summary_evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS space_place ON space(place_id);
CREATE INDEX IF NOT EXISTS space_latlon ON space(lat, lon);

CREATE TABLE IF NOT EXISTS floor (
  floor_id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL, label TEXT, seq INTEGER,
  plan_path TEXT, plan_format TEXT, plan_width INTEGER, plan_height INTEGER,
  plan_origin_x REAL, plan_origin_y REAL, plan_px_per_m REAL, dxf_path TEXT, evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS floor_space ON floor(space_id);

CREATE TABLE IF NOT EXISTS floorplan (
  plan_id TEXT PRIMARY KEY,                     -- plan:<sid>:<n>
  space_id TEXT NOT NULL, format TEXT, flags TEXT, path TEXT,
  width INTEGER, height INTEGER, px_per_m REAL, origin_x REAL, origin_y REAL, evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS floorplan_space ON floorplan(space_id);

CREATE TABLE IF NOT EXISTS room (
  room_id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL, floor_id TEXT,
  label TEXT, label_confidence REAL,
  area_m2 REAL, width_m REAL, depth_m REAL, height_m REAL,
  polygon_json TEXT, polygon_quality TEXT,
  centroid_x REAL, centroid_y REAL,
  pano_total INTEGER DEFAULT 0, pano_selected INTEGER DEFAULT 0,
  edge_ids_json TEXT,
  card_text TEXT, evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS room_space ON room(space_id);

CREATE TABLE IF NOT EXISTS room_adjacency (
  room_a TEXT NOT NULL, room_b TEXT NOT NULL,
  space_id TEXT NOT NULL,
  shared_edge_ids TEXT NOT NULL,
  shared_length_m REAL NOT NULL,
  edge_types TEXT,
  involves_void INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (room_a, room_b)
);

CREATE TABLE IF NOT EXISTS wall_vertex (vertex_id TEXT PRIMARY KEY, floor_id TEXT, x REAL, y REAL);
CREATE TABLE IF NOT EXISTS wall_edge (edge_id TEXT PRIMARY KEY, floor_id TEXT, v1 TEXT, v2 TEXT, type TEXT, thickness REAL);
CREATE INDEX IF NOT EXISTS wall_edge_floor ON wall_edge(floor_id);

CREATE TABLE IF NOT EXISTS pano (
  pano_id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL, room_id TEXT, room_match TEXT, floor_id TEXT,
  label TEXT, x REAL, y REAL, z REAL,
  is_selected INTEGER NOT NULL DEFAULT 0,
  has_faces INTEGER DEFAULT 0, has_defurnished_faces INTEGER DEFAULT 0,
  evidence_id TEXT
);
CREATE INDEX IF NOT EXISTS pano_space ON pano(space_id);
CREATE INDEX IF NOT EXISTS pano_room ON pano(room_id);

CREATE TABLE IF NOT EXISTS pano_face (
  pano_id TEXT NOT NULL, variant TEXT NOT NULL, face INTEGER NOT NULL,
  path TEXT NOT NULL, thumb_path TEXT, content_sha256 TEXT, bytes INTEGER, evidence_id TEXT,
  PRIMARY KEY (pano_id, variant, face)
);

CREATE TABLE IF NOT EXISTS pano_caption (
  pano_id TEXT NOT NULL, variant TEXT NOT NULL,
  model TEXT, prompt_version TEXT,
  caption_json TEXT NOT NULL, caption_text TEXT NOT NULL,
  input_sha256 TEXT, created_at TEXT, evidence_id TEXT,
  PRIMARY KEY (pano_id, variant)
);

CREATE TABLE IF NOT EXISTS aerial_facts (
  aerial_id TEXT PRIMARY KEY,
  place_id TEXT UNIQUE NOT NULL,
  footprint_wkt TEXT, parcel_wkt TEXT,
  footprint_area_m2 REAL, structure_count INTEGER, parcel_count INTEGER,
  attributes_json TEXT,
  match_method TEXT, match_distance_m REAL, query_method TEXT,
  fetched_at TEXT, evidence_id TEXT, raw_path TEXT
);
CREATE TABLE IF NOT EXISTS aerial_image (
  image_id TEXT PRIMARY KEY,
  place_id TEXT, kind TEXT, size_m INTEGER, path TEXT, width INTEGER, height INTEGER,
  content_sha256 TEXT, fetched_at TEXT, evidence_id TEXT
);
CREATE TABLE IF NOT EXISTS aerial_search_cache (
  cache_key TEXT PRIMARY KEY, request_json TEXT, response_json TEXT, fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS kit_model_link (property_id TEXT NOT NULL, sid TEXT NOT NULL, PRIMARY KEY (property_id, sid));
CREATE INDEX IF NOT EXISTS kit_model_link_sid ON kit_model_link(sid);
CREATE TABLE IF NOT EXISTS kit_res_model_link (
  listing_id TEXT NOT NULL, residential_listing_id TEXT, sid TEXT NOT NULL, PRIMARY KEY (listing_id, sid));

CREATE TABLE IF NOT EXISTS link (
  src_id TEXT, dst_id TEXT, relation TEXT, method TEXT,
  distance_m REAL, confidence REAL, status TEXT, note TEXT,
  PRIMARY KEY (src_id, dst_id, relation)
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  type TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL,
  place_id TEXT, url TEXT, excerpt TEXT, content_sha256 TEXT, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS evidence_source ON evidence(source_id);

CREATE TABLE IF NOT EXISTS claim (
  claim_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  place_id TEXT,
  predicate TEXT NOT NULL,
  value_json TEXT NOT NULL,
  unit TEXT,
  statement TEXT NOT NULL,
  evidence_ids TEXT NOT NULL,
  evidence_sha TEXT NOT NULL,
  derived_from TEXT NOT NULL DEFAULT '[]',
  confidence REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  confirmations INTEGER NOT NULL DEFAULT 1,
  rank INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, run_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  read_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS claim_subject ON claim(subject_id, predicate);
CREATE INDEX IF NOT EXISTS claim_place ON claim(place_id, status);
CREATE TABLE IF NOT EXISTS claim_archive (reset_id TEXT, archived_at TEXT, claim_json TEXT);
CREATE TABLE IF NOT EXISTS claim_snapshot (name TEXT, created_at TEXT, claim_json TEXT);
CREATE INDEX IF NOT EXISTS claim_snapshot_name ON claim_snapshot(name);

CREATE TABLE IF NOT EXISTS edges (
  src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL,
  source TEXT NOT NULL, weight REAL, created_at TEXT,
  PRIMARY KEY (src, rel, dst)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, rel);

CREATE TABLE IF NOT EXISTS embedding (
  doc_id TEXT PRIMARY KEY,
  doc_type TEXT, place_id TEXT, space_id TEXT, title TEXT,
  text TEXT, text_sha256 TEXT, model TEXT, dim INTEGER, vector BLOB, evidence_id TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(doc_id UNINDEXED, doc_type UNINDEXED, text);
CREATE VIRTUAL TABLE IF NOT EXISTS place_fts USING fts5(place_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS query_embed_cache (qhash TEXT PRIMARY KEY, query TEXT, model TEXT, vector BLOB, created_at TEXT);

CREATE TABLE IF NOT EXISTS ingest_log (
  step TEXT, key TEXT, status TEXT, attempts INTEGER DEFAULT 0, error TEXT, updated_at TEXT,
  PRIMARY KEY (step, key)
);
CREATE TABLE IF NOT EXISTS api_log (
  ts TEXT, op TEXT, caller TEXT, run_id TEXT, ms REAL, cache TEXT, place_id TEXT, bytes_out INTEGER, status INTEGER
);
CREATE INDEX IF NOT EXISTS api_log_run ON api_log(run_id);
CREATE TABLE IF NOT EXISTS model_usage (
  ts TEXT, purpose TEXT, model TEXT, run_id TEXT,
  tokens_in INTEGER, tokens_out INTEGER, tokens_thought INTEGER, estimated INTEGER DEFAULT 0, ms REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Database:
    """One SQLite file. Each thread gets its own connection; writes are serialized by a process lock."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        with self._write_lock:
            self.conn().executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA temp_store=MEMORY")
            self._local.conn = c
        return c

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            c = self.conn()
            nested = c.in_transaction
            if not nested:
                c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                if not nested and c.in_transaction:
                    c.execute("COMMIT")
            except BaseException:
                if not nested and c.in_transaction:
                    c.execute("ROLLBACK")
                raise

    def q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, tuple(params)).fetchall()

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn().execute(sql, tuple(params)).fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        r = self.one(sql, params)
        return r[0] if r else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.write() as c:
            c.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.write() as c:
            c.executemany(sql, rows)

    def upsert(self, table: str, row: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
        cols = list(row.keys())
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        if conn is not None:
            conn.execute(sql, [row[c] for c in cols])
        else:
            self.execute(sql, [row[c] for c in cols])

    def update(self, table: str, key_col: str, key: Any, values: dict[str, Any]) -> None:
        if not values:
            return
        sets = ",".join(f"{c}=?" for c in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE {key_col}=?", [*values.values(), key])

    def table_columns(self, table: str) -> list[str]:
        return [r["name"] for r in self.q(f"PRAGMA table_info({table})")]

    def tables(self) -> list[str]:
        return [r[0] for r in self.q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    # ---- ingest ledger -------------------------------------------------
    def ledger_done(self, step: str, key: str) -> bool:
        return self.scalar("SELECT status FROM ingest_log WHERE step=? AND key=?", (step, key)) == "done"

    def ledger_set(self, step: str, key: str, status: str, error: str | None = None) -> None:
        from mundus_world.types.ids import now_iso

        self.execute(
            "INSERT INTO ingest_log(step,key,status,attempts,error,updated_at) VALUES(?,?,?,1,?,?) "
            "ON CONFLICT(step,key) DO UPDATE SET status=excluded.status, attempts=attempts+1, "
            "error=excluded.error, updated_at=excluded.updated_at",
            (step, key, status, error, now_iso()),
        )


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]
