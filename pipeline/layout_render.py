"""Draw an agent's apartment layout over the floor's Matterport plan image: the 2-D proof of what the agent proposed.

    python -m pipeline.layout_render cEvQ8q5GKZd [--layout layout_sample.json]

Reads data/conversion/<scan>/layout.json (or --layout, a file name in the same folder) and writes layout.png next to it
(layout_sample.png for a sample). Layout positions are the scan's metres; the plan image maps onto them through its
origin (lower-left corner, metres) and resolution (pixels per metre): pixel = ((x - ox) * r, H - (y - oy) * r).
"""
import argparse
import json

from PIL import Image, ImageDraw, ImageFont

from pipeline import config

TINT = {"studio": (127, 200, 255), "1br": (47, 179, 165), "2br": (255, 176, 46), "3br": (197, 139, 242)}
WALL = (20, 230, 205)
CORRIDOR = (127, 200, 255)


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(scan_id, layout_name="layout.json", office=False):
    folder = config.DATA / "conversion" / scan_id
    lay = json.loads((folder / layout_name).read_text(encoding="utf-8"))
    meta = json.loads((folder / "raw" / "plan.json").read_text(encoding="utf-8"))
    if (folder / "raw" / "plan_color.jpg").exists() and "color" in meta:
        base = Image.open(folder / "raw" / "plan_color.jpg").convert("RGB")
        o, r = meta["color"]["origin"], meta["color"]["resolution"]
    else:
        base = Image.open(folder / "raw" / "plan.png").convert("RGB")
        o, r = meta["origin"], meta["resolution"]
    H = base.size[1]
    px = lambda p: ((p[0] - o["x"]) * r, H - (p[1] - o["y"]) * r)
    lw = max(4, round(r * 0.18))
    if office:   # the old office plan, muted, under the new layout
        base = Image.blend(base, Image.new("RGB", base.size, (20, 23, 28)), 0.55)
    else:        # the cleared floor the agent plans on: empty slab, facade with its windows, nothing else
        geo = json.loads((folder / "geometry.json").read_text(encoding="utf-8"))
        base = Image.new("RGB", base.size, (20, 23, 28))
        bd = ImageDraw.Draw(base)
        bd.polygon([px(p) for p in geo["outline"]], fill=(58, 62, 68))
        bd.line([px(p) for p in geo["outline"] + geo["outline"][:1]], fill=(200, 204, 210), width=lw)
        for run in geo.get("windows") or []:
            bd.line([px(p) for p in run], fill=(110, 190, 255), width=lw + 2)

    over = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    st = lay.get("structure") or {}
    core_mask = Image.new("L", base.size, 0)
    for ring in st.get("core") or []:
        pts = [px(p) for p in ring]
        d.polygon(pts, fill=(58, 64, 73, 200), outline=(170, 176, 184, 255))
        ImageDraw.Draw(core_mask).polygon(pts, fill=255)
    hatch = Image.new("RGBA", base.size, (0, 0, 0, 0))
    hd, step = ImageDraw.Draw(hatch), max(6, round(r * 0.6))
    for k in range(-base.size[1], base.size[0], step):            # diagonal hatch, kept only inside the core
        hd.line([(k, base.size[1]), (k + base.size[1], 0)], fill=(140, 146, 154, 110), width=2)
    over.paste(hatch, (0, 0), Image.composite(hatch, Image.new("RGBA", base.size, (0, 0, 0, 0)), core_mask))
    for u in lay.get("units") or []:
        if len(u.get("polygon") or []) > 2:
            c = TINT.get(str(u.get("type", "")).lower(), (154, 166, 180))
            d.polygon([px(p) for p in u["polygon"]], fill=c + (85,))
    base = Image.alpha_composite(base.convert("RGBA"), over)
    d = ImageDraw.Draw(base)

    for w in lay.get("walls") or []:
        d.line([px(w["a"]), px(w["b"])], fill=CORRIDOR if w.get("kind") == "corridor" else WALL, width=lw)
    s = r * 0.25
    for c in st.get("columns") or []:
        x, y = px((c["x"], c["y"]))
        d.rectangle([x - s, y - s, x + s, y + s], fill=(229, 72, 77), outline=(255, 255, 255), width=2)
    f_big, f_small = font(max(14, round(r * 0.55))), font(max(11, round(r * 0.4)))
    for e in st.get("exits") or []:
        x, y = px((e["x"], e["y"]))
        rr = r * 0.6
        d.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(61, 220, 132), width=lw)
        d.text((x, y - rr - 4), "EXIT" + (" (assumed)" if "assum" in f"{e.get('confidence', '')} {e.get('kind', '')}".lower() else ""),
               fill=(61, 220, 132), font=f_small, anchor="mb")
    for u in lay.get("units") or []:
        at = u.get("label_at")
        if not at and u.get("polygon"):
            at = [sum(p[0] for p in u["polygon"]) / len(u["polygon"]), sum(p[1] for p in u["polygon"]) / len(u["polygon"])]
        if not at:
            continue
        x, y = px(at)
        d.text((x, y), str(u.get("type", "unit")).upper(), fill=(255, 255, 255), font=f_big, anchor="md", stroke_width=3, stroke_fill=(20, 23, 28))
        if u.get("area_sf"):
            d.text((x, y + 4), f"{round(u['area_sf']):,} sf", fill=(220, 226, 232), font=f_small, anchor="ma", stroke_width=3, stroke_fill=(20, 23, 28))

    sm = lay.get("summary") or {}
    lines = [f"{sm.get('units', len(lay.get('units') or []))} apartments"]
    if sm.get("rentable_sf"):
        lines[0] += f" · {round(sm['rentable_sf']):,} sq ft"
    if sm.get("monthly_rent_usd"):
        lines.append(f"about ${round(sm['monthly_rent_usd']):,} a month")
    lines.append("red: possible columns (low confidence) · green: exits")
    y0 = 18
    for i, t in enumerate(lines):
        d.text((24, y0), t, fill=(233, 237, 242) if i < len(lines) - 1 else (150, 160, 172), font=f_big if i == 0 else f_small, stroke_width=3, stroke_fill=(20, 23, 28))
        y0 += round(r * (0.75 if i == 0 else 0.55))

    out = base.convert("RGB")
    out.thumbnail((2400, 2400))
    name = "layout.png" if layout_name == "layout.json" else layout_name.rsplit(".", 1)[0] + ".png"
    out.save(folder / name)
    return folder / name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--layout", default="layout.json")
    ap.add_argument("--office", action="store_true", help="draw over the old office plan instead of the cleared floor")
    a = ap.parse_args()
    print(render(a.scan, a.layout, a.office))


if __name__ == "__main__":
    main()
