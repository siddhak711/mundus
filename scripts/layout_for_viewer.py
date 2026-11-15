"""Turn the floor 16 generator's output (layout-v4.json) into the walkthrough viewer's data/layout.json.

    python scripts/layout_for_viewer.py web/walkthrough/data/studies/v4/layout-v4.json web/walkthrough/data/layout.json

The viewer reads the conversion agent's shape: walls [{a, b, kind}], units [{type, area_sf, polygon, label_at}],
structure {columns, exits}, summary. Walls are drawn from the generator's geometry:
- demising: unit outlines, except where they lie on the glass
- interior: room edges inside a unit
- corridor: the corridor's outline where no unit wall already stands
Exits are the two stair doors, marked assumed: the fire stairs were not scanned.
"""
import json
import sys
from pathlib import Path

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

RECT = (-38.42, 30.30, -10.30, 24.40)   # glass line (x0, x1, y0, y1), same as shell.json
TOL = 0.05


def segments(geom):
    """Every straight piece of a line geometry as (a, b), rounded to the centimetre."""
    if geom.is_empty:
        return []
    lines = geom.geoms if hasattr(geom, "geoms") else [geom]
    out = []
    for line in lines:
        if not isinstance(line, LineString):
            continue
        pts = list(line.coords)
        for p, q in zip(pts, pts[1:], strict=False):
            if LineString([p, q]).length >= 0.1:
                out.append(([round(p[0], 2), round(p[1], 2)], [round(q[0], 2), round(q[1], 2)]))
    return out


def boundary_lines(polys):
    return unary_union([p.boundary for p in polys])


def convert(v4):
    x0, x1, y0, y1 = RECT
    glass = box(x0, y0, x1, y1).boundary.buffer(TOL)
    units = [Polygon(u["poly"]) for u in v4["units"]]
    rooms = [box(*r["rect"]) for u in v4["units"] for r in u["rooms"]]
    corridor = unary_union([box(*c) for c in v4["corridor"]] + [box(*s["rect"]) for s in v4.get("stair_links", [])])

    unit_lines = boundary_lines(units).difference(glass)
    room_lines = boundary_lines(rooms).difference(glass).difference(unit_lines.buffer(TOL))
    corr_lines = corridor.boundary.difference(glass).difference(unit_lines.buffer(TOL))

    walls = ([{"a": a, "b": b, "kind": "demising"} for a, b in segments(unit_lines)]
             + [{"a": a, "b": b, "kind": "interior"} for a, b in segments(room_lines)]
             + [{"a": a, "b": b, "kind": "corridor"} for a, b in segments(corr_lines)])

    out_units = []
    for u, poly in zip(v4["units"], units, strict=True):
        c = poly.representative_point()
        out_units.append({"id": u["id"], "type": "2BR" if u["type"].startswith("2BR") else "1BR",
                          "bedrooms": 2 if u["type"].startswith("2BR") else 1, "area_sf": u["sf"],
                          "polygon": [[round(x, 2), round(y, 2)] for x, y in u["poly"]],
                          "label_at": [round(c.x, 2), round(c.y, 2)], "rent_mo": u.get("rent_mo")})

    columns = [{"x": c["x"], "y": c["y"], "confidence": "low" if c.get("kind") != "probable" else "medium"}
               for c in v4.get("columns", []) if "x" in c]
    exits = [{"x": s["door"][0], "y": s["door"][1], "kind": "stair", "confidence": "assumed"} for s in v4.get("stairs", [])]
    rent = sum(u.get("rent_mo") or 0 for u in v4["units"])
    return {
        "scan": "floor-16", "generated_by": f"scripts/apartment_study_{v4.get('version', 'v4')}.py",
        "walls": walls, "units": out_units,
        "structure": {"columns": columns, "exits": exits},
        "summary": {"units": len(out_units), "rentable_sf": int(sum(u["sf"] for u in v4["units"])),
                    "monthly_rent_usd": rent or None, "unit_mix": v4.get("unit_mix"),
                    "self_score": (v4.get("self_score") or {}).get("total")},
    }


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    out = convert(json.loads(src.read_text(encoding="utf-8")))
    dst.write_text(json.dumps(out, indent=1), encoding="utf-8")
    kinds = {k: sum(w["kind"] == k for w in out["walls"]) for k in ("demising", "interior", "corridor")}
    print(f"{dst}: {out['summary']['units']} units, {out['summary']['rentable_sf']} sf, walls {kinds}")


if __name__ == "__main__":
    main()
