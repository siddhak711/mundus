"""Tools that run inside the harness: place resolution, image looks, UI focus. No model calls."""
from __future__ import annotations

import base64
import io
import json
from typing import Any

from langchain_core.tools import tool
from PIL import Image

from mundus_harness import events, runctx
from mundus_harness.config import Config
from mundus_harness.world_client import WorldClient, WorldError


def _resize(data: bytes, max_px: int) -> bytes:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _img_block(data: bytes) -> dict[str, Any]:
    return {"type": "image", "base64": base64.b64encode(data).decode(), "mime_type": "image/jpeg"}


def resolve_candidates(client: WorldClient, text: str, near: dict | None = None) -> list[dict[str, Any]]:
    """Top 3 places for a name or address, deep places first. Score is 1.0 for an exact name or address match."""
    params: dict[str, Any] = {"q": text, "limit": 5}
    if near:
        params.update(lat=near.get("lat"), lon=near.get("lon"), radius_m=near.get("radius_m", 1000))
    places = client.get_json("/v1/places/search", **params)["places"]
    if not places and len(text.split()) > 3:      # long questions: retry on capitalised words and numbers only
        key = " ".join(w for w in text.replace("?", " ").split() if w[:1].isupper() or w[:1].isdigit())
        if key:
            places = client.get_json("/v1/places/search", q=key, limit=5)["places"]
    out = []
    low = text.lower()
    for i, p in enumerate(places[:3]):
        name, addr = (p.get("name") or "").lower(), (p.get("address") or "").lower()
        exact = bool(name and name in low) or bool(addr and addr in low)
        out.append({"place_id": p["place_id"], "name": p["name"], "address": p["address"], "property_type": p["property_type"],
                    "is_deep": p["is_deep"], "match_score": 1.0 if exact else round(0.7 - 0.15 * i, 2)})
    return out


def build_local_tools(cfg: Config, client: WorldClient) -> dict[str, Any]:
    @tool
    def resolve_place(text: str, near: dict | None = None) -> str:
        """Turn a name or address into a place_id. Call this first when the user has not selected a place.
        Returns up to 3 candidates with a match score. An empty list means no such place is known: say so."""
        try:
            cands = resolve_candidates(client, text, near)
        except WorldError as e:
            return f"Unavailable: {e.message}. Do not retry. Record this as a gap."
        return json.dumps({"candidates": cands, "note": "No place matched: tell the user it was not found." if not cands else
                           "Only places with is_deep true have interiors, captions and aerial facts."})

    @tool(response_format="content_and_artifact")
    def look_at_pano(pano_id: str, faces: list[int] | None = None, defurnished: bool = False) -> tuple[list, dict]:
        """Look at a 360 photo. Faces 1 to 4 are the four horizontal directions. Costly: use only when stored
        captions do not answer the question. Returns the images and one evidence_id per face to cite."""
        rid = runctx.run_id_from_config()
        rec = runctx.record(rid)
        faces = [f for f in (faces or [1, 2, 3, 4]) if f in (1, 2, 3, 4)][:4] or [1]
        if rec["pano_looks"] + len(faces) > cfg.max_pano_images:
            return ([{"type": "text", "text": f"Image limit reached ({cfg.max_pano_images} per task). Use stored captions."}], {})
        events.emit("focus", agent="interior-inspector", pano_id=pano_id)
        blocks: list[dict[str, Any]] = []
        lines = [f"Pano {pano_id}" + (" (defurnished)" if defurnished else "")]
        for f in faces:
            try:
                data, evid, _sha = client.image(f"/v1/panos/{pano_id}/faces/{f}", defurnished=int(defurnished))
            except WorldError as e:
                return ([{"type": "text", "text": f"Unavailable: {e.message}. Do not retry. Record this as a gap."}], {})
            blocks.append(_img_block(_resize(data, 768)))
            lines.append(f"face {f}: evidence_id {evid}")
            events.emit("evidence", agent="interior-inspector", evidence_id=evid, kind="pano_image", source_id=pano_id,
                        image_url=f"/v1/panos/{pano_id}/faces/{f}?defurnished={int(defurnished)}")
        with runctx.lock():
            rec["pano_looks"] += len(faces)
            rec["images"] += len(faces)
        return ([{"type": "text", "text": "\n".join(lines)}, *blocks], {"images": len(faces)})

    @tool(response_format="content_and_artifact")
    def look_at_aerial(place_id: str, kind: str = "ortho", size_m: int = 80) -> tuple[list, dict]:
        """Look at an aerial photo of a place from above (kind ortho) or from one side (oblique-n, oblique-s,
        oblique-e, oblique-w). Costly. Returns the image and an evidence_id to cite."""
        rid = runctx.run_id_from_config()
        rec = runctx.record(rid)
        if rec["aerial_looks"] + 1 > cfg.max_aerial_images:
            return ([{"type": "text", "text": f"Image limit reached ({cfg.max_aerial_images} per task)."}], {})
        events.emit("focus", agent="aerial-analyst", place_id=place_id, aerial_kind=kind)
        try:
            data, evid, _sha = client.image(f"/v1/places/{place_id}/aerial", kind=kind, size_m=size_m)
        except WorldError as e:
            return ([{"type": "text", "text": f"Unavailable: {e.message}. Do not retry. Record this as a gap."}], {})
        events.emit("evidence", agent="aerial-analyst", evidence_id=evid, kind="ortho_image" if kind == "ortho" else "oblique_image",
                    source_id=place_id, image_url=f"/v1/places/{place_id}/aerial?kind={kind}&size_m={size_m}")
        with runctx.lock():
            rec["aerial_looks"] += 1
            rec["images"] += 1
        return ([{"type": "text", "text": f"Aerial {kind} of {place_id}: evidence_id {evid}"}, _img_block(_resize(data, 1024))],
                {"images": 1})

    @tool
    def set_focus(place_id: str | None = None, space_id: str | None = None, pano_id: str | None = None,
                  rotation_deg: float | None = None, aerial_kind: str | None = None) -> str:
        """Tell the map and 3D viewer what you are looking at. Call it whenever your attention moves."""
        payload = {k: v for k, v in dict(place_id=place_id, space_id=space_id, pano_id=pano_id, rotation_deg=rotation_deg,
                                         aerial_kind=aerial_kind).items() if v is not None}
        events.emit("focus", **payload)
        return "ok"

    return {"resolve_place": resolve_place, "look_at_pano": look_at_pano, "look_at_aerial": look_at_aerial, "set_focus": set_focus}
