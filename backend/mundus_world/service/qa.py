"""Caption quality checks: a contact sheet for human review, and a length experiment."""
from __future__ import annotations

import html
import io
import json
import time
from typing import Any

from PIL import Image

from mundus_world.config.settings import Settings
from mundus_world.providers.claude import DETAIL_WORDS, Claude, caption_to_text
from mundus_world.providers.http import Http
from mundus_world.repo.db import Database


def _sample(db: Database, n: int) -> list[dict[str, Any]]:
    return [dict(r) for r in db.q(
        """SELECT p.pano_id, s.name AS space_name, r.label, c.caption_text, c.caption_json FROM pano p
           JOIN space s ON s.space_id=p.space_id LEFT JOIN room r ON r.room_id=p.room_id
           LEFT JOIN pano_caption c ON c.pano_id=p.pano_id AND c.variant='furnished'
           WHERE p.has_faces=1 ORDER BY random() LIMIT ?""", (n,))]


def _thumbs(s: Settings, db: Database, pano_id: str) -> list[str]:
    return [f"../{r['thumb_path'] or r['path']}" for r in db.q(
        "SELECT thumb_path, path FROM pano_face WHERE pano_id=? AND variant='furn' AND face BETWEEN 1 AND 4 ORDER BY face",
        (pano_id,))]


def caption_sheet(s: Settings, db: Database, n: int = 30) -> dict[str, Any]:
    rows = _sample(db, n)
    parts = ["<html><body style='font-family:sans-serif;max-width:1400px;margin:auto'><h1>Caption check</h1>"
             "<p>Read each caption against its four views. Flag anything stated that the photos do not show.</p>"]
    for r in rows:
        imgs = "".join(f"<img src='{html.escape(t)}' width='330'>" for t in _thumbs(s, db, r["pano_id"]))
        parts.append(f"<h3>{html.escape(r['space_name'] or '')} / {html.escape(r['label'] or 'no room')} "
                     f"<small>{html.escape(r['pano_id'])}</small></h3><div>{imgs}</div>"
                     f"<p>{html.escape(r['caption_text'] or 'NO CAPTION')}</p><hr>")
    out = s.data_dir / "reports" / "captions.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts) + "</body></html>", encoding="utf-8")
    valid = sum(1 for r in rows if r["caption_text"])
    return {"report": str(out), "sampled": len(rows), "with_caption": valid}


def caption_lengths(s: Settings, db: Database, http: Http, n: int = 5, levels: list[str] | None = None) -> dict[str, Any]:
    """Caption the same panos at several detail levels and report words, tokens and latency per level.
    Does not change stored captions."""
    levels = [lv for lv in (levels or list(DETAIL_WORDS)) if lv in DETAIL_WORDS]
    gm = Claude(s)
    rows = _sample(db, n)
    results: list[dict[str, Any]] = []
    agg = {lv: {"words": 0, "tokens_in": 0, "tokens_out": 0, "tokens_thought": 0, "seconds": 0.0, "n": 0} for lv in levels}
    parts = ["<html><body style='font-family:sans-serif;max-width:1500px;margin:auto'><h1>Caption length experiment</h1>"]
    for r in rows:
        faces = db.q("SELECT path FROM pano_face WHERE pano_id=? AND variant='furn' AND face BETWEEN 1 AND 4 ORDER BY face",
                     (r["pano_id"],))
        imgs = []
        for f in faces:
            im = Image.open(s.data_dir / f["path"]).convert("RGB")
            im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            imgs.append(buf.getvalue())
        thumbs = "".join(f"<img src='{html.escape(t)}' width='300'>" for t in _thumbs(s, db, r["pano_id"]))
        parts.append(f"<h2>{html.escape(r['space_name'] or '')} <small>{html.escape(r['pano_id'])}</small></h2><div>{thumbs}</div><table border=1 cellpadding=6><tr>")
        cells = []
        for lv in levels:
            t0 = time.time()
            try:
                cap, um, model = gm.caption(imgs, r["space_name"], r["label"] or "", "", detail=lv)
            except Exception as e:  # noqa: BLE001
                results.append({"pano_id": r["pano_id"], "level": lv, "error": str(e)[:200]})
                cells.append(f"<td valign=top><b>{lv}</b><br>failed</td>")
                continue
            dt = time.time() - t0
            text = caption_to_text(cap)
            words = len(str(cap.get("description") or "").split())
            a = agg[lv]
            a["words"] += words
            a["tokens_in"] += um["tokens_in"]
            a["tokens_out"] += um["tokens_out"]
            a["tokens_thought"] += um["tokens_thought"]
            a["seconds"] += dt
            a["n"] += 1
            results.append({"pano_id": r["pano_id"], "level": lv, "model": model, "description_words": words,
                            "text_chars": len(text), "tokens_out": um["tokens_out"], "seconds": round(dt, 1),
                            "objects": len(cap.get("objects") or []), "text": text})
            cells.append(f"<td valign=top width='25%'><b>{lv}</b>: {words} words, {um.get('candidatesTokenCount', 0)} tokens out, "
                         f"{dt:.0f}s<br><br>{html.escape(text)}</td>")
        parts.append("".join(cells) + "</tr></table>")
    summary = {lv: {k: (round(v / a["n"], 1) if k != "n" and a["n"] else v) for k, v in a.items()} for lv, a in agg.items()}
    rep = s.data_dir / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "caption_lengths.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1), encoding="utf-8")
    (rep / "caption_lengths.html").write_text("".join(parts) + "</body></html>", encoding="utf-8")
    return {"report": str(rep / "caption_lengths.html"), "panos": len(rows), "per_level_average": summary}
