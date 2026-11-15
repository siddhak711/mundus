"""Normalised layout: the shapes the checks need, read from a layout JSON. Flags the generator wrote (checks, ok,
column_overlaps, wet_rooms_paired, self_score, money) are kept under `claimed` and never used for grading."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

M2SF = 10.7639
WINDOW_ROOMS = {"bed", "living"}
WET_ROOMS = {"bath"}


@dataclass
class Room:
    type: str
    rect: tuple[float, float, float, float]

    @property
    def geom(self) -> Polygon:
        return box(*self.rect)

    @property
    def w(self) -> float:
        return self.rect[2] - self.rect[0]

    @property
    def d(self) -> float:
        return self.rect[3] - self.rect[1]

    @property
    def min_dim(self) -> float:
        return min(self.w, self.d)

    @property
    def sf(self) -> float:
        return self.geom.area * M2SF


@dataclass
class Fixture:
    kind: str
    pos: tuple[float, float]


@dataclass
class Unit:
    id: str
    type: str
    poly: Polygon
    rooms: list[Room]
    door: tuple[float, float] | None
    fixtures: list[Fixture] = field(default_factory=list)
    chases: list[tuple[float, float, float, float]] = field(default_factory=list)
    access: str | None = None

    @property
    def corner(self) -> bool:
        return "corner" in self.type or self.type.startswith("2BR")

    @property
    def sf(self) -> float:
        return self.poly.area * M2SF

    def rooms_of(self, t: str) -> list[Room]:
        return [r for r in self.rooms if r.type == t]


@dataclass
class Layout:
    version: str
    units: list[Unit]
    corridor: Any                       # shapely geometry
    stair_links: list[dict[str, Any]]
    stairs: list[dict[str, Any]]
    lobbies: list[dict[str, Any]]
    claimed: dict[str, Any]
    raw: dict[str, Any]

    @property
    def circulation(self) -> Any:
        parts = [self.corridor] + [box(*s["rect"]) for s in self.stair_links] + [box(*lb["rect"]) for lb in self.lobbies]
        return unary_union([p for p in parts if p is not None and not p.is_empty])


def _rect(r: Any) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = (float(v) for v in r)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _corridor(raw: Any) -> Any:
    if isinstance(raw, list):
        return unary_union([box(*_rect(r)) for r in raw]) if raw else Polygon()
    if isinstance(raw, dict):   # v1: a ring given by its inner rectangle and a width, plus connectors
        parts = []
        if raw.get("ring_inner") and raw.get("width_m"):
            inner = box(*_rect(raw["ring_inner"]))
            parts.append(inner.buffer(raw["width_m"], join_style="mitre").difference(inner))
        for c in raw.get("connectors") or []:
            parts.append(box(*_rect(c)))
        return unary_union(parts) if parts else Polygon()
    return Polygon()


def parse_layout(raw: dict[str, Any]) -> Layout:
    units = []
    for u in raw.get("units") or []:
        rooms = [Room(r["type"], _rect(r["rect"])) for r in u.get("rooms") or []]
        fx = [Fixture(f["kind"], (float(f["pos"][0]), float(f["pos"][1]))) for f in u.get("fixtures") or [] if f.get("pos")]
        door = tuple(float(v) for v in u["door"]) if u.get("door") else None
        units.append(Unit(str(u["id"]), str(u.get("type") or ""), Polygon(u["poly"]), rooms, door, fx,
                          [_rect(c) for c in u.get("chases") or []], u.get("access") or None))
    claimed = {"self_score": raw.get("self_score"), "money": raw.get("money"), "columns": raw.get("columns"),
               "units": {u["id"]: {k: u.get(k) for k in ("checks", "column_overlaps", "wet_rooms_paired", "drain_runs_m",
                                                         "egress_to_stair_m")} for u in raw.get("units") or []}}
    return Layout(str(raw.get("version") or raw.get("scheme") or ""), units, _corridor(raw.get("corridor")),
                  [s if isinstance(s, dict) else {"rect": _rect(s)} for s in raw.get("stair_links") or []],
                  raw.get("stairs") or [], raw.get("lobbies") or [], claimed, raw)


def point(p: tuple[float, float]) -> Point:
    return Point(*p)
