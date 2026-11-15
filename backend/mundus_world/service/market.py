"""Read-only SQL over the CoStar tables, with a three-layer guard, plus a schema description for agents."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from mundus_world.repo.db import Database
from mundus_world.types.errors import ApiError

MAX_ROWS = 200
TIMEOUT_S = 3.0
EXTRA_TABLES = {"place", "space", "room"}
HIDDEN_COLUMNS = {"raw_json", "card_text", "polygon_json", "edge_ids_json"}
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def allowed_tables(db: Database) -> list[str]:
    return sorted(t for t in db.tables() if t.startswith("costar_") or t in EXTRA_TABLES)


def _check_statement(sql: str) -> str:
    s = (sql or "").strip()
    while s.endswith(";"):
        s = s[:-1].rstrip()
    if not s:
        raise ApiError("sql_rejected", "Empty statement", {"reason": "empty"})
    bare = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", s)
    bare = re.sub(r"--[^\n]*|/\*.*?\*/", " ", bare, flags=re.S)
    if ";" in bare:
        raise ApiError("sql_rejected", "Only one statement is allowed", {"reason": "multiple_statements"})
    if not re.match(r"^\s*(select|with)\b", bare, flags=re.I):
        raise ApiError("sql_rejected", "Only SELECT statements are allowed", {"reason": "not_select"})
    return s


def query(db: Database, sql: str, limit: int | None = None) -> dict[str, Any]:
    stmt = _check_statement(sql)
    limit = max(1, min(int(limit or 50), MAX_ROWS))
    allowed = set(allowed_tables(db))
    conn = sqlite3.connect(f"file:{db.path}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")

        def authorizer(action: int, a1: str | None, a2: str | None, _db: str | None, _src: str | None) -> int:
            if action not in _ALLOWED_ACTIONS:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ:
                if a1 not in allowed or a2 in HIDDEN_COLUMNS:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        deadline = time.monotonic() + TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
        conn.set_authorizer(authorizer)
        t0 = time.monotonic()
        try:
            cur = conn.execute(stmt)
            rows = cur.fetchmany(limit + 1)
            cols = [d[0] for d in cur.description or []]
        except sqlite3.DatabaseError as e:
            msg = str(e)
            reason = "timeout" if "interrupt" in msg.lower() else ("not_authorized" if "authoriz" in msg.lower()
                                                                    or "prohibited" in msg.lower() else "sql_error")
            hint = ""
            if reason == "not_authorized":
                hint = f" Readable tables: {', '.join(sorted(allowed))}. Columns {sorted(HIDDEN_COLUMNS)} are not readable."
            if "no such column" in msg.lower() or "no such table" in msg.lower():
                used = [t for t in sorted(allowed) if t in stmt]
                with_cols = "; ".join(f"{t}: {', '.join(c for c in db.table_columns(t) if c not in HIDDEN_COLUMNS)}" for t in used[:3])
                hint = (f" Columns you can use: {with_cols}." if with_cols else f" Readable tables: {', '.join(sorted(allowed))}.")
            raise ApiError("sql_rejected", f"{msg}.{hint}"[:6000], {"reason": reason}) from None
        truncated = len(rows) > limit
        return {"columns": cols, "rows": [list(r) for r in rows[:limit]], "row_count": min(len(rows), limit),
                "truncated": truncated, "elapsed_ms": round((time.monotonic() - t0) * 1000, 1)}
    finally:
        conn.close()


def describe(db: Database, refresh: bool = False) -> dict[str, Any]:
    """Tables, columns, types, row counts and sample values. Cached in the meta table."""
    if not refresh:
        cached = db.scalar("SELECT value FROM meta WHERE key='market_schema'")
        if cached:
            return json.loads(cached)
    out = {"dialect": "sqlite", "notes": [
        "Every costar_* table has row_id, node_id, property_id, place_id and evidence_id. Select evidence_id to cite a row.",
        "Join tables on property_id or place_id. place_id is set only for Los Angeles properties.",
        "Integer code columns have a sibling <name>_label column with the decoded text.",
        "Dates are ISO strings: compare with substr(col,1,10).", f"At most {MAX_ROWS} rows are returned per query."],
        "tables": []}
    for t in allowed_tables(db):
        n = db.scalar(f"SELECT count(*) FROM {t}")
        cols = []
        info = db.q(f"PRAGMA table_info({t})")
        sample = db.q(f"SELECT * FROM {t} LIMIT 300")
        for c in info:
            name = c["name"]
            if name in HIDDEN_COLUMNS:
                continue
            vals = []
            for r in sample:
                v = r[name]
                if v is not None and v != "" and v not in vals:
                    vals.append(v if not isinstance(v, str) else v[:60])
                if len(vals) == 3:
                    break
            filled = sum(1 for r in sample if r[name] is not None)
            cols.append({"name": name, "type": c["type"], "samples": vals,
                         "filled_pct": round(100 * filled / max(1, len(sample)))})
        out["tables"].append({"name": t, "rows": n, "columns": cols})
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('market_schema',?)", (json.dumps(out),))
    return out


def describe_compact(db: Database, table: str | None = None) -> dict[str, Any]:
    """Smaller form for model context: per table, column names with types; samples only for one named table."""
    full = describe(db)
    if table:
        t = next((x for x in full["tables"] if x["name"] == table), None)
        if not t:
            raise ApiError("not_found", f"No table named {table}", {"tables": [x["name"] for x in full["tables"]]})
        return {"dialect": "sqlite", "notes": full["notes"], "table": t}
    return {"dialect": "sqlite", "notes": full["notes"] + ["Call again with table=<name> for sample values of one table."],
            "tables": [{"name": t["name"], "rows": t["rows"],
                        "columns": [c["name"] for c in t["columns"] if c["filled_pct"] > 0]} for t in full["tables"]]}
