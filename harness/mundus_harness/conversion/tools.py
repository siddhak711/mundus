"""Tools for the conversion agents. Each returns compact JSON text; none returns raw rasters or the mesh."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from mundus_harness.conversion import geometry as geo

MAX_CHARS = 24000


def _dump(obj: Any) -> str:
    text = json.dumps(obj, separators=(",", ":"))
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "...[cut]"


def _drafts(scan: str, root: Path) -> Path:
    d = root / scan / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_draft(scan: str, draft_id: str, root: Path) -> dict[str, Any]:
    p = _drafts(scan, root) / f"{draft_id}.json"
    if not p.exists():
        raise ValueError(f"no draft {draft_id!r} for scan {scan}; draft ids come from draft_layout")
    return json.loads(p.read_text(encoding="utf-8"))


def _compact_report(rep: dict[str, Any], failing_only: bool) -> dict[str, Any]:
    units = []
    for u in rep["units"]:
        bad = {k: v.get("value") for k, v in u["checks"].items() if v["status"] != "pass"}
        if failing_only and not bad:
            continue
        units.append({"id": u["id"], "type": u["type"], "area_sf": u["area_sf"], "status": u["status"],
                      **({"problems": bad} if bad else {})})
    return {"counts": rep["counts"], "units": units, "walls_crossing_structure": rep["walls_crossing_structure"][:12],
            "assumptions": rep["assumptions"]}


def _photo_notes(scan: str, root: Path) -> list[str]:
    p = root / scan / "photocheck.json"
    if not p.exists():
        return ["No photo checks available for this floor."]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["photocheck.json could not be read."]
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for it in (items or [])[:20]:
        if isinstance(it, dict):
            out.append("; ".join(f"{k}={it[k]}" for k in ("kind", "x", "y", "verdict", "label", "what", "saw", "panos") if k in it))
    return out or ["photocheck.json has no items."]


def build_tools(root: Path | None = None) -> dict[str, Any]:
    root = root or geo.data_root()

    @tool
    def read_floor(scan: str) -> str:
        """Summary of one preprocessed office floor: facade sides (length, distance from facade to core, window
        share, stretches without windows, column candidates as distance along the side and from the facade), core
        blocks, stairs, assumed exits, ceiling height, daylight depth, and photo checks. Positions in metres."""
        s = geo.floor_summary(scan, root)
        s["photo_checks"] = _photo_notes(scan, root)
        return _dump(s)

    @tool
    def draft_layout(scan: str, unit_depth_m: float, sides: dict[str, list[dict[str, Any]]], corridor_m: float = 1.6) -> str:
        """Draw apartments along the facade and check them. `sides` maps a facade side name (north, south, east,
        west) to its units in order along the side, e.g. {"north": [{"type": "1BR", "width_m": 7.0}, ...]}.
        Types: studio, 1BR, 2BR, 3BR, or "gap" to leave that much facade unassigned (no windows, amenity) and
        continue with more units after it. Positions start at the side's usable start. Every unit is unit_depth_m deep from the facade; the corridor runs behind
        them. Bedrooms are drawn against the facade, 3.2 m wide each, so a 1BR needs at least 6.2 m of facade and a
        2BR 9.4 m. Returns a draft id, the check counts and every unit that does not pass, with the reason."""
        try:
            layout = geo.draft_ring(scan, float(unit_depth_m), sides, float(corridor_m), root)
        except ValueError as e:
            return _dump({"error": str(e)})
        d = _drafts(scan, root)
        draft_id = f"draft_{len(list(d.glob('draft_*.json'))) + 1}"
        layout["draft_id"] = draft_id
        rep = geo.check_layout(scan, layout, root)
        layout["report"] = rep
        (d / f"{draft_id}.json").write_text(json.dumps(layout), encoding="utf-8")
        mix: dict[str, int] = {}
        for u in layout["units"]:
            mix[u["type"]] = mix.get(u["type"], 0) + 1
        return _dump({"draft_id": draft_id, "units": len(layout["units"]), "unit_mix": mix,
                      "rentable_sf": sum(u["area_sf"] for u in layout["units"]),
                      "draft_problems": layout["draft_problems"], **_compact_report(rep, failing_only=True)})

    @tool
    def check_layout(scan: str, draft_id: str, failing_only: bool = False) -> str:
        """Every measured rule per unit of a saved draft (pass, fail or unknown, with the number behind it):
        inside the floor, clear of the core, unit size, window frontage, natural light, daylight depth, bedroom
        windows, exit travel distance, ceiling height, walls clear of core and columns."""
        try:
            layout = _load_draft(scan, draft_id, root)
        except ValueError as e:
            return _dump({"error": str(e)})
        rep = layout.get("report") or geo.check_layout(scan, layout, root)
        if failing_only:
            return _dump(_compact_report(rep, True))
        units = [{"id": u["id"], "type": u["type"], "area_sf": u["area_sf"], "status": u["status"],
                  "checks": {k: (v["status"] if v["status"] == "pass" and k not in ("exit_travel", "daylight_depth")
                                 else f"{v['status']}: {v.get('value', '')}") for k, v in u["checks"].items()}}
                 for u in rep["units"]]
        return _dump({"counts": rep["counts"], "units": units, "assumptions": rep["assumptions"],
                      "rules": {k: v.get("rule") for k, v in (rep["units"][0]["checks"].items() if rep["units"] else []) if v.get("rule")}})

    @tool
    def read_market(scan: str) -> str:
        """Market summary for the floor's building: floor size, occupancy, tenant history and nearby apartment rents
        from CoStar. Says so plainly when no market summary has been prepared."""
        folder = root / scan
        for name in ("market.md", "market.json"):
            p = folder / name
            if p.exists():
                text = p.read_text(encoding="utf-8")
                return text[:MAX_CHARS]
        return _dump({"error": "no market summary for this floor yet (market.md / market.json missing). "
                               "Say that rents are unknown; do not invent them."})

    @tool
    def estimate_returns(scan: str, draft_id: str, monthly_rent_by_type: dict[str, float],
                         conversion_cost_per_sf: float, operating_cost_share: float = 0.35) -> str:
        """Arithmetic for a draft: units by type x monthly rent per unit (from the market summary), gross annual
        rent, net operating income after operating_cost_share, conversion cost = rentable sf x cost per sf, and the
        simple yield (NOI / cost). Every input is an assumption you must state."""
        try:
            layout = _load_draft(scan, draft_id, root)
        except ValueError as e:
            return _dump({"error": str(e)})
        missing = sorted({u["type"] for u in layout["units"]} - set(monthly_rent_by_type))
        if missing:
            return _dump({"error": f"no monthly rent given for unit types {missing}"})
        monthly = sum(float(monthly_rent_by_type[u["type"]]) for u in layout["units"])
        sf = sum(u["area_sf"] for u in layout["units"])
        cost = sf * float(conversion_cost_per_sf)
        noi = monthly * 12 * (1 - float(operating_cost_share))
        out = {"draft_id": draft_id, "units": len(layout["units"]), "rentable_sf": sf,
               "monthly_rent_usd": round(monthly), "annual_rent_usd": round(monthly * 12), "noi_usd": round(noi),
               "conversion_cost_usd": round(cost), "simple_yield": round(noi / cost, 4) if cost else None,
               "inputs": {"monthly_rent_by_type": monthly_rent_by_type, "conversion_cost_per_sf": conversion_cost_per_sf,
                          "operating_cost_share": operating_cost_share}}
        (_drafts(scan, root) / f"{draft_id}.returns.json").write_text(json.dumps(out), encoding="utf-8")
        return _dump(out)

    @tool
    def write_layout(scan: str, draft_id: str, issues: list[str], assumptions: list[str],
                     monthly_rent_usd: float | None = None) -> str:
        """Write the final layout for the viewer from a checked draft. issues: problems left open (failing units,
        unconfirmed rules). assumptions: everything assumed (exits, columns, rents, costs, occupancy)."""
        try:
            layout = _load_draft(scan, draft_id, root)
        except ValueError as e:
            return _dump({"error": str(e)})
        rep = layout.get("report") or geo.check_layout(scan, layout, root)
        returns = {}
        rp = _drafts(scan, root) / f"{draft_id}.returns.json"
        if rp.exists():
            returns = json.loads(rp.read_text(encoding="utf-8"))
        mix: dict[str, int] = {}
        for u in layout["units"]:
            mix[u["type"]] = mix.get(u["type"], 0) + 1
        summary = {"monthly_rent_usd": monthly_rent_usd if monthly_rent_usd is not None else returns.get("monthly_rent_usd"),
                   "annual_rent_usd": returns.get("annual_rent_usd"), "conversion_cost_usd": returns.get("conversion_cost_usd"),
                   "simple_yield": returns.get("simple_yield"), "unit_mix": mix, "check_counts": rep["counts"],
                   "issues": issues, "assumptions": list(dict.fromkeys(list(assumptions) + rep["assumptions"]))}
        try:
            out = geo.finalize(scan, layout, rep, summary, generated_by=f"mundus conversion agent ({draft_id})", root=root)
        except ValueError as e:
            return _dump({"error": str(e)})
        return _dump({"written": str(root / scan / "layout.json"), "units": out["summary"]["units"],
                      "rentable_sf": out["summary"]["rentable_sf"], "check_counts": rep["counts"]})

    return {t.name: t for t in (read_floor, draft_layout, check_layout, read_market, estimate_returns, write_layout)}
