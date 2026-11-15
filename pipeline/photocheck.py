"""Confirm what the mesh flagged by looking at the nearest Matterport photos.

    python -m pipeline.photocheck cEvQ8q5GKZd [--max-calls 30]

Reads data/conversion/<scan>/structure.json and geometry.json. For every stair candidate, every assumed exit, up to 8
column candidates and 4 window stretches, it takes the 2 nearest camera positions, joins their four horizontal views
into one strip, and asks Claude one question: is the flagged thing visible, and what is it. Results go to
photocheck.json, and structure.json gains the evidence and an updated confidence. Photos are cached in photos/.
Signed photo links expire, so camera positions and links are fetched fresh on every run.
"""
import argparse
import base64
import io
import json
import math
import os
import re

import requests
from PIL import Image

from pipeline import config, matterport

MODEL = "claude-sonnet-5-5"
_Q = """query($id: ID!) { model(id: $id) {
  panoLocations { id label position { x y z } skybox(resolution: "high") { children } } } }"""

ASK = {
    "stair": ("The 3-D scan found geometry going down through the floor near this camera, about {d:.1f} m away: "
              "something that connects to the floor below. Is a staircase visible? If so, is it an open internal "
              "stair (railings, open to the office) or an enclosed fire-exit stair (behind a fire door, exit sign)?"),
    "exit": ("We assumed a fire-exit stair about {d:.1f} m from this camera, at the edge of the building core that "
             "was not scanned. Do you see a fire exit: an EXIT sign, a stair door, a fire door, or a stairwell?"),
    "column": ("The 3-D scan found a small solid floor-to-ceiling shape about {d:.1f} m from this camera, possibly a "
               "structural column (square or round pillar, often boxed in drywall). Is a column visible near there, or "
               "is it something else (partition end, cabinet, furniture, door frame)?"),
    "window": ("This camera is about {d:.1f} m from the building's exterior wall. Is that wall glazed: windows or "
               "floor-to-ceiling glass looking outside?"),
}
SYSTEM = ("You check building features in 360-degree office photos for an office-to-apartment conversion study. "
          "The image is four horizontal views (90 degrees each) side by side; there may be two such strips from two "
          "nearby camera positions, stacked. Answer only from what is visible. Reply with JSON only: "
          '{"verdict": "confirmed" | "rejected" | "unclear", "what_it_is": "<few words>", "details": "<one sentence>"}. '
          "confirmed = the asked-about thing is clearly visible; rejected = the spot is visible and it is something "
          "else; unclear = cannot tell.")


def folder(scan):
    return config.DATA / "conversion" / scan


def strip(scan, pano):
    """Four horizontal faces of one pano side by side, cached."""
    path = folder(scan) / "photos" / f"{pano['id']}.jpg"
    if path.exists():
        return Image.open(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    faces = [Image.open(io.BytesIO(requests.get(u, timeout=60).content)).convert("RGB").resize((512, 512))
             for u in pano["skybox"]["children"][1:5]]
    img = Image.new("RGB", (2048, 512))
    for i, f in enumerate(faces):
        img.paste(f, (i * 512, 0))
    img.save(path, quality=85)
    return img


def ask(client, kind, dists, images):
    canvas = Image.new("RGB", (2048, 512 * len(images)))
    for i, im in enumerate(images):
        canvas.paste(im, (0, i * 512))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    q = ASK[kind].format(d=min(dists))
    msg = client.messages.create(
        model=MODEL, max_tokens=300, system=SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": q}]}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        out = {}
    return {"verdict": out.get("verdict", "unclear"), "what_it_is": out.get("what_it_is", ""), "details": out.get("details", text[:200])}


def items(struct, geo):
    out = []
    for i, s in enumerate(struct["stairs"]):
        b = s["bbox"]
        out.append(("stair", i, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    for i, e in enumerate(struct["exits"]):
        out.append(("exit", i, e["x"], e["y"]))
    for i, c in enumerate(struct["columns"][:8]):
        out.append(("column", i, c["x"], c["y"]))
    runs = geo.get("windows") or []
    for i in sorted(range(len(runs)), key=lambda k: -len(runs[k]))[:4]:
        mid = runs[i][len(runs[i]) // 2]
        out.append(("window", i, mid[0], mid[1]))
    return out


def run(scan, max_calls=30):
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MUNDUS_ANTHROPIC_KEY")
    client = anthropic.Anthropic(api_key=key)
    f = folder(scan)
    struct = json.loads((f / "structure.json").read_text(encoding="utf-8"))
    geo = json.loads((f / "geometry.json").read_text(encoding="utf-8"))
    panos = [p for p in matterport._query(_Q, scan)["panoLocations"] if p.get("position") and (p.get("skybox") or {}).get("children")]
    results = []
    for kind, idx, x, y in items(struct, geo)[:max_calls]:
        near = sorted(panos, key=lambda p: math.hypot(p["position"]["x"] - x, p["position"]["y"] - y))[:2]
        dists = [math.hypot(p["position"]["x"] - x, p["position"]["y"] - y) for p in near]
        try:
            r = ask(client, kind, dists, [strip(scan, p) for p in near])
        except Exception as error:      # one failed look should not lose the rest
            r = {"verdict": "unclear", "what_it_is": "", "details": f"check failed: {str(error)[:150]}"}
        r.update({"item_kind": kind, "index": idx, "x": round(x, 2), "y": round(y, 2),
                  "panos": [p["label"] for p in near], "pano_ids": [p["id"] for p in near],
                  "distance_m": [round(d, 1) for d in dists]})
        results.append(r)
        print(f"{kind:7} {idx:2} ({x:6.1f},{y:6.1f}) panos {r['panos']}: {r['verdict']:9} {r['what_it_is']}")
    apply(struct, results)
    (f / "photocheck.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    (f / "structure.json").write_text(json.dumps(struct, indent=1), encoding="utf-8")
    return results


def apply(struct, results):
    for r in results:
        ev = f"photo (panos {', '.join(r['panos'])}): {r['verdict']}: {r['what_it_is']}. {r['details']}".strip()
        if r["item_kind"] == "stair":
            s = struct["stairs"][r["index"]]
            s["evidence"].append(ev)
            if r["verdict"] == "confirmed":
                s["confidence"] = "high"
                s["kind"] = r["what_it_is"] or s["kind"]
                low = (r["what_it_is"] + " " + r["details"]).lower()
                s["is_fire_exit"] = not ("open" in low or "internal" in low or "interconnect" in low) and ("fire" in low or "enclosed" in low)
        elif r["item_kind"] == "exit":
            e = struct["exits"][r["index"]]
            e["evidence"].append(ev)
            if r["verdict"] == "confirmed":
                e["sign_or_door_seen"] = True
        elif r["item_kind"] == "column":
            c = struct["columns"][r["index"]]
            c["evidence"].append(ev)
            c["confidence"] = {"confirmed": "medium", "rejected": "rejected"}.get(r["verdict"], c["confidence"])
        elif r["item_kind"] == "window":
            struct.setdefault("window_checks", []).append({"run": r["index"], "x": r["x"], "y": r["y"], "verdict": r["verdict"], "evidence": ev})
    struct["notes"] = [n for n in struct["notes"] if not n.startswith("Photo checks:")] + [
        f"Photo checks: {len(results)} looks at the 2 nearest camera positions per flagged item. Columns marked 'rejected' "
        "were seen to be something else; keep walls off the rest."]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--max-calls", type=int, default=30)
    a = ap.parse_args()
    run(a.scan, a.max_calls)


if __name__ == "__main__":
    main()
