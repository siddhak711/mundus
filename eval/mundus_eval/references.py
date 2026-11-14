"""Visual references: Claude Fable 5.2 looks at the actual photographs and writes what is there.
The grader compares agent answers with this text, so nobody has to hand-grade visual tasks."""
from __future__ import annotations

import base64
from typing import Any

import httpx

from mundus_eval.graders import GRADER_MODEL

REFERENCE_SYSTEM = """You are writing a factual visual reference for an evaluation. You see photographs of one place.
Describe exactly what is visible: room type and apparent size, furniture and equipment with counts, surfaces and
materials, ceiling and roof structure, doors, loading doors, stairs, exit signs and anything written on signs. For
aerial images describe the roof, the site, vehicles and any loading areas. Where images are labelled furnished and
defurnished, state what differs. State uncertainty where a thing is only partly visible. Do not infer anything that is
not in the images. Write plain prose under 500 words."""


def _b64(data: bytes) -> dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(data).decode("utf-8")}}


def collect_images(spec: dict[str, Any], client: httpx.Client) -> list[tuple[str, bytes]]:
    """Picks panos for a task's reference_images spec and returns (label, jpeg bytes) pairs (768 px thumbnails)."""
    place = client.get(f"/v1/places/{spec['place_id']}").json()
    like = (spec.get("space_name_like") or "").lower()
    spaces = [s for s in place["spaces"] if like in (s["name"] or "").lower()] or place["spaces"]
    out: list[tuple[str, bytes]] = []
    want = int(spec.get("panos", 2))
    for s in spaces:
        if len(out) >= want * 4 * (2 if spec.get("defurnished") else 1):
            break
        sp = client.get(f"/v1/spaces/{s['space_id']}").json()
        panos = [p for p in sp.get("panos", []) if p["has_image"] and (not spec.get("defurnished") or p["has_defurnished_image"])]
        for p in panos[:want]:
            for face in (1, 2, 3, 4):
                r = client.get(f"/v1/panos/{p['pano_id']}/faces/{face}", params={"size": "thumb"})
                if r.status_code == 200:
                    out.append((f"{s['name']} position {p['label']} view {face} (furnished)", r.content))
                if spec.get("defurnished"):
                    r = client.get(f"/v1/panos/{p['pano_id']}/faces/{face}", params={"size": "thumb", "defurnished": 1})
                    if r.status_code == 200:
                        out.append((f"{s['name']} position {p['label']} view {face} (defurnished)", r.content))
        want -= len(panos[:want])
        if want <= 0:
            break
    for kind in spec.get("aerial") or []:
        r = client.get(f"/v1/places/{spec['place_id']}/aerial", params={"kind": kind})
        if r.status_code == 200:
            out.append((f"aerial {kind}", r.content))
    return out[:40]


def build_reference(task: dict[str, Any], world: httpx.Client, client: Any = None) -> dict[str, Any]:
    import anthropic

    client = client or anthropic.Anthropic()
    images = collect_images(task["reference_images"], world)
    if not images:
        return {"task_id": task["id"], "error": "no images available for this task", "text": None}
    content: list[dict[str, Any]] = []
    for label, data in images:
        content += [{"type": "text", "text": label}, _b64(data)]
    content.append({"type": "text", "text": f"The evaluation question is: {task['question']}\nWrite the visual reference."})
    try:
        with client.beta.messages.stream(
                model=GRADER_MODEL, max_tokens=32000, system=REFERENCE_SYSTEM, output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                messages=[{"role": "user", "content": content}]) as stream:
            resp = stream.get_final_message()
    except anthropic.APIStatusError as e:
        return {"task_id": task["id"], "error": f"reference call failed: {e.status_code}", "text": None}
    except anthropic.APIConnectionError:
        return {"task_id": task["id"], "error": "reference call failed: network", "text": None}
    if resp.stop_reason == "refusal":
        return {"task_id": task["id"], "error": "model declined", "text": None}
    return {"task_id": task["id"], "text": "".join(b.text for b in resp.content if b.type == "text"),
            "images": [label for label, _ in images], "model": resp.model,
            "tokens": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}}
