"""Task and combination files, ground truth, and visual references."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import yaml

EVAL_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = EVAL_DIR / "data"          # git-ignored: truth, references and results hold licensed data


def load_tasks(path: Path | None = None) -> list[dict[str, Any]]:
    doc = yaml.safe_load((path or EVAL_DIR / "tasks.yaml").read_text(encoding="utf-8"))
    tasks = doc["tasks"]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids")
    for t in tasks:
        if t.get("grader") not in ("code", "model"):
            raise ValueError(f"{t['id']}: grader must be code or model")
        if t["grader"] == "code" and not t.get("checks"):
            raise ValueError(f"{t['id']}: a code-graded task needs checks")
        if t["grader"] == "model" and not t.get("rubric"):
            raise ValueError(f"{t['id']}: a model-graded task needs a rubric")
    return tasks


def load_combos(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or EVAL_DIR / "combos.yaml").read_text(encoding="utf-8"))


def _dig(obj: Any, key: str) -> Any:
    """Dotted lookup that also accepts keys containing dots (Vexcel attribute names)."""
    if isinstance(obj, dict) and key in obj:
        return obj[key]
    parts = key.split(".")
    for i in range(1, len(parts)):
        head, rest = ".".join(parts[:i]), ".".join(parts[i:])
        if isinstance(obj, dict) and head in obj:
            found = _dig(obj[head], rest)
            if found is not None:
                return found
    return None


def build_truth(tasks: list[dict[str, Any]], client: httpx.Client) -> dict[str, dict[str, Any]]:
    """Computes every task's ground truth from the World API. Returns {task_id: {key: value}}."""
    out: dict[str, dict[str, Any]] = {}
    for t in tasks:
        vals: dict[str, Any] = {}
        for key, spec in (t.get("truth") or {}).items():
            try:
                if spec["kind"] == "sql":
                    r = client.post("/v1/market/query", json={"sql": spec["sql"], "limit": 5})
                    r.raise_for_status()
                    rows = r.json()["rows"]
                    vals[key] = rows[0][0] if rows else None
                elif spec["kind"] == "rest":
                    r = client.get(spec["path"])
                    r.raise_for_status()
                    vals[key] = _dig(r.json(), spec["key"])
                elif spec["kind"] == "static":
                    vals[key] = spec["value"]
                else:
                    raise ValueError(f"unknown truth kind {spec['kind']}")
            except (httpx.HTTPError, KeyError, ValueError) as e:
                vals[key] = None
                vals.setdefault("_errors", []).append(f"{key}: {type(e).__name__}: {str(e)[:120]}")
        out[t["id"]] = vals
    return out


def save_json(name: str, obj: Any) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = DATA_DIR / name
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def load_json(name: str, default: Any = None) -> Any:
    p = DATA_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
