"""The floor: outer wall, core and columns, in scan metres. Loaded from the walkthrough bake's shell.json (licensed,
never committed) or built synthetically for tests."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SHELL = REPO / "web" / "walkthrough" / "data" / "shell.json"

# Hypothesised hidden columns on floor 16: the 8.5 m grid extrapolated where the scan found nothing (assumption
# "hidden_columns"). Same positions the grader used for v2-v4, so the hidden-column criterion is comparable.
FLOOR16_HIDDEN = [(x, 20.2) for x in (-8.7, -17.2, -25.7, -34.2)] + \
    [(x, -6.1) for x in (-34.2, -25.7, -17.2, -8.7, -0.18, 8.67, 17.18)]
HIDDEN_SIZE = 0.75


@dataclass
class Column:
    id: str
    x: float
    y: float
    size: float
    kind: str  # probable | possible | hidden

    @property
    def square(self) -> Polygon:
        h = self.size / 2
        return box(self.x - h, self.y - h, self.x + h, self.y + h)


@dataclass
class Floor:
    rect: tuple[float, float, float, float]      # x0, y0, x1, y1
    core: Any                                     # shapely (multi)polygon
    columns: list[Column] = field(default_factory=list)
    name: str = ""

    @property
    def outline(self) -> Polygon:
        return box(*self.rect)

    @property
    def gross_m2(self) -> float:
        return self.outline.area

    @property
    def diagonal_m(self) -> float:
        x0, y0, x1, y1 = self.rect
        return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5


def shell_path() -> Path:
    p = os.environ.get("FLOORPLAN_SHELL")
    return Path(p) if p else DEFAULT_SHELL


def load_shell(path: Path | None = None, hidden: list[tuple[float, float]] | None = None) -> Floor:
    """shell.json: rect = [x0, x1, y0, y1], core = [{outer, holes}], columns = [{x, y, size, grade}]."""
    path = path or shell_path()
    sh = json.loads(Path(path).read_text(encoding="utf-8"))
    x0, x1, y0, y1 = sh["rect"]
    core = unary_union([Polygon(b["outer"], b.get("holes") or []).buffer(0) for b in sh["core"]])
    cols = [Column(f"C{i + 1}", c["x"], c["y"], c["size"], "probable" if c.get("grade") == "probable" else "possible")
            for i, c in enumerate(sh.get("columns") or [])]
    hidden = FLOOR16_HIDDEN if hidden is None else hidden
    cols += [Column(f"H{i + 1}", x, y, HIDDEN_SIZE, "hidden") for i, (x, y) in enumerate(hidden)]
    return Floor((x0, y0, x1, y1), core, cols, name=str(path))


def synthetic_floor() -> Floor:
    """A 40 x 20 m plate with a central core and an 8 m column grid. Committable; used by the tests."""
    cols = [Column(f"C{i + 1}", x, y, 0.6, "probable") for i, (x, y) in
            enumerate([(8.0, 4.3), (16.0, 4.3), (24.0, 4.3), (32.0, 4.3), (8.0, 15.7), (16.0, 15.7), (24.0, 15.7), (32.0, 15.7)])]
    cols.append(Column("H1", 4.0, 4.3, 0.75, "hidden"))
    return Floor((0.0, 0.0, 40.0, 20.0), box(4.0, 9.7, 36.0, 10.3), cols, name="synthetic")
