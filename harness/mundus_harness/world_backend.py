"""/world/ file mount: the knowledge graph as read-only files, rendered from the World API on every read."""
from __future__ import annotations

import fnmatch
import json
import re
import time

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from mundus_harness.world_client import WorldClient, WorldError

READ_ONLY = "read-only: /world is generated from shared memory. Use put_claim to add a fact."
FILES = ("card.md", "claims.jsonl", "neighbors.md")


class WorldBackend(BackendProtocol):
    """Receives paths with the /world prefix removed, for example /places/place:costar:1/card.md."""

    def __init__(self, client: WorldClient, ttl_s: float = 5.0):
        self.client, self.ttl = client, ttl_s
        self._cache: dict[str, tuple[float, str]] = {}

    # ---- rendering -------------------------------------------------------
    def _places(self) -> list[dict]:
        return self.client.get_json("/v1/claims/places")["places"]

    def _render(self, path: str) -> str:
        path = "/" + path.strip("/")
        hit = self._cache.get(path)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        if path == "/index.md":
            ps = self._places()
            text = "# World memory index\n" + f"{len(ps)} places have claims.\n\n" + "\n".join(
                f"- {p['name']} ({p['place_id']}): {p['active']} active of {p['claims']} claims" for p in ps[:20]) + "\n"
        else:
            m = re.fullmatch(r"/places/([^/]+)/(card\.md|claims\.jsonl|neighbors\.md)", path)
            if not m:
                raise FileNotFoundError(path)
            pid, name = m.group(1), m.group(2)
            if name == "card.md":
                text = self.client.get_text(f"/v1/places/{pid}/card")
            elif name == "claims.jsonl":
                cs = self.client.get_json("/v1/claims", subject_id=pid, status="all")["claims"]
                text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cs)
            else:
                n = self.client.get_json("/v1/graph/neighbors", node_id=pid, depth=1, limit=60)
                lines = [f"# Neighbours of {pid}", f"{n['total_edges_at_node']} edges in total. Counts shown: {n['counts_by_rel']}", ""]
                for e in n["edges"]:
                    other = e["dst"] if e["src"] == pid else e["src"]
                    s = n["nodes"].get(other) or {}
                    w = f" ({e['weight']} m)" if e.get("weight") is not None and e["rel"] == "near" else ""
                    lines.append(f"- {e['rel']}: {other}{w} {str(s.get('name') or '')[:90]}")
                text = "\n".join(lines) + "\n"
        self._cache[path] = (time.monotonic(), text)
        return text

    # ---- protocol ----------------------------------------------------------
    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        try:
            text = self._render(file_path)
        except FileNotFoundError:
            return ReadResult(error=f"File not found: /world{file_path}")
        except WorldError as e:
            return ReadResult(error=f"Unavailable: {e.message or e.code}")
        except Exception as e:  # noqa: BLE001 - a backend must never raise
            return ReadResult(error=f"Unavailable: {type(e).__name__}")
        lines = text.splitlines(keepends=True)
        chunk = lines[offset:offset + limit]
        return ReadResult(file_data={"content": "".join(chunk), "encoding": "utf-8"}, total_lines=len(lines),
                          start_line=offset + 1, end_line=offset + len(chunk))

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=READ_ONLY)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        return EditResult(error=READ_ONLY)

    def _all_paths(self) -> list[str]:
        out = ["/index.md"]
        for p in self._places()[:50]:
            out += [f"/places/{p['place_id']}/{f}" for f in FILES]
        return out

    def ls(self, path: str) -> LsResult:
        try:
            p = "/" + path.strip("/")
            if p in ("/", ""):
                return LsResult(entries=[{"path": "/index.md"}, {"path": "/places/", "is_dir": True}])
            if p == "/places":
                return LsResult(entries=[{"path": f"/places/{x['place_id']}/", "is_dir": True} for x in self._places()])
            m = re.fullmatch(r"/places/([^/]+)", p)
            if m:
                return LsResult(entries=[{"path": f"/places/{m.group(1)}/{f}"} for f in FILES])
            return LsResult(entries=[])
        except Exception as e:  # noqa: BLE001
            return LsResult(error=f"Unavailable: {type(e).__name__}")

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            base = "/" + (path or "/").strip("/")
            pat = pattern if pattern.startswith("/") else (base.rstrip("/") + "/" + pattern)
            return GlobResult(matches=[{"path": p} for p in self._all_paths() if fnmatch.fnmatch(p, pat)])
        except Exception as e:  # noqa: BLE001
            return GlobResult(error=f"Unavailable: {type(e).__name__}")

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None) -> GrepResult:
        try:
            base = "/" + (path or "/").strip("/")
            matches = []
            for p in self._all_paths():
                if not p.startswith(base.rstrip("/")) or (glob and not fnmatch.fnmatch(p.rsplit("/", 1)[-1], glob)):
                    continue
                if p.endswith("neighbors.md"):
                    continue
                for i, line in enumerate(self._render(p).splitlines(), 1):
                    if pattern.lower() in line.lower():
                        matches.append({"path": p, "line": i, "text": line[:400]})
                        if max_count and len(matches) >= max_count:
                            return GrepResult(matches=matches, truncated=True)
            return GrepResult(matches=matches)
        except Exception as e:  # noqa: BLE001
            return GrepResult(error=f"Unavailable: {type(e).__name__}")
