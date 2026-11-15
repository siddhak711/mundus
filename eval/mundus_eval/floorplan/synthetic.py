"""A synthetic floor and a clean layout on it, in the v4 layout JSON shape. Contains no scan data, so it is committed
and drives the tests and the mutation examples. Every rule passes on it by construction (asserted in the tests)."""
from __future__ import annotations

import copy
from typing import Any

from mundus_eval.floorplan.floor import Floor, synthetic_floor
from mundus_eval.floorplan.layout import M2SF

DEPTH = 7.0          # glass to corridor
WZ = 4.8             # window rooms 0..4.8 m from the glass
BED_W, BED_D = 3.4, 3.75
BATH_W, HALL_W = 2.45, 1.2


def _unit(uid: str, band: str, a: float, z: float, mirrored: bool, wide_bath: bool = False) -> dict[str, Any]:
    """band S: glass at y=0, corridor at y=7. band N: glass at y=20, corridor at y=13."""
    bw = 2.6 if wide_bath else BATH_W

    def R(x0, x1, g0, g1):
        if band == "S":
            return [round(x0, 3), round(g0, 3), round(x1, 3), round(g1, 3)]
        return [round(x0, 3), round(20 - g1, 3), round(x1, 3), round(20 - g0, 3)]

    rooms = []
    if mirrored:   # bath, bed on the high side
        rooms += [("living", R(a, z - BED_W, 0, WZ)), ("bed", R(z - BED_W, z, 0, BED_D)), ("wardrobe", R(z - BED_W, z, BED_D, WZ)),
                  ("bath", R(z - bw, z, WZ, DEPTH)), ("hall", R(z - bw - HALL_W, z - bw, WZ, DEPTH)), ("kitchen", R(a, z - bw - HALL_W, WZ, DEPTH))]
        door_x, sink_x = z - bw - HALL_W / 2, z - bw - HALL_W - 0.35
    else:
        rooms += [("bed", R(a, a + BED_W, 0, BED_D)), ("wardrobe", R(a, a + BED_W, BED_D, WZ)), ("living", R(a + BED_W, z, 0, WZ)),
                  ("bath", R(a, a + bw, WZ, DEPTH)), ("hall", R(a + bw, a + bw + HALL_W, WZ, DEPTH)), ("kitchen", R(a + bw + HALL_W, z, WZ, DEPTH))]
        door_x, sink_x = a + bw + HALL_W / 2, a + bw + HALL_W + 0.35
    y = (lambda g: g) if band == "S" else (lambda g: 20 - g)
    bath = next(r for t, r in rooms if t == "bath")
    bcx = (bath[0] + bath[2]) / 2
    by_ = bath[3] if band == "S" else bath[1]
    chase = [round(bcx - 0.3, 3), round(by_ - 0.3, 3), round(bcx + 0.3, 3), round(by_, 3)] if band == "S" else \
        [round(bcx - 0.3, 3), round(by_, 3), round(bcx + 0.3, 3), round(by_ + 0.3, 3)]
    poly = [[a, y(0)], [z, y(0)], [z, y(DEPTH)], [a, y(DEPTH)]]
    fx = [{"kind": "bath1", "pos": [round(bcx, 3), round(y((WZ + DEPTH) / 2), 3)]},
          {"kind": "sink", "pos": [round(sink_x, 3), round(y(DEPTH - 0.35), 3)]},
          {"kind": "dishwasher", "pos": [round(sink_x + (-0.6 if mirrored else 0.6), 3), round(y(DEPTH - 0.35), 3)]},
          {"kind": "washer", "pos": [round(sink_x + (-1.2 if mirrored else 1.2), 3), round(y(DEPTH - 0.35), 3)]}]
    sf = round((z - a) * DEPTH * M2SF)
    return {"id": uid, "type": "1BR/1BA", "poly": poly, "sf": sf,
            "rooms": [{"type": t, "rect": r} for t, r in rooms], "door": [round(door_x, 3), y(DEPTH)],
            "fixtures": fx, "chases": [chase], "access": None}


def synthetic_layout() -> dict[str, Any]:
    units = []
    xs = [round(40.0 * i / 6, 3) for i in range(7)]
    for band in ("S", "N"):
        for i in range(6):
            units.append(_unit(f"{band}{i + 1}", band, xs[i], xs[i + 1], mirrored=(i % 2 == 0), wide_bath=False))
    # accessibility: 2 mobility (11% of 10, rounded up), 1 hearing/vision; mobility baths sized for 11B
    for uid in ("S2", "S3"):
        i = int(uid[1]) - 1
        units[i] = _unit(uid, "S", xs[i], xs[i + 1], mirrored=(i % 2 == 0), wide_bath=True)
        units[i]["access"] = "mobility"
    units[6]["access"] = "hearing/vision"
    return {
        "version": "synthetic-1", "coords": "synthetic metres",
        "units": units,
        "corridor": [[0.0, 7.0, 40.0, 8.5], [0.0, 11.5, 40.0, 13.0], [0.0, 8.5, 1.5, 11.5], [38.5, 8.5, 40.0, 11.5]],
        "stair_links": [{"rect": [10.4, 8.5, 11.6, 9.7], "rating": "enclosed ½ hr rated corridor"},
                        {"rect": [28.4, 10.3, 29.6, 11.5], "rating": "enclosed ½ hr rated corridor"}],
        "stairs": [{"name": "Stair 1", "rect": [10.0, 9.7, 12.0, 10.3], "door": [11.0, 9.7]},
                   {"name": "Stair 2", "rect": [28.0, 9.7, 30.0, 10.3], "door": [29.0, 10.3]}],
        "lobbies": [{"name": "Lobby W", "rect": [15.0, 8.5, 18.0, 9.7], "door": [16.5, 8.5]},
                    {"name": "Lobby E", "rect": [22.0, 10.3, 25.0, 11.5], "door": [23.5, 11.5]}],
    }


def synthetic() -> tuple[Floor, dict[str, Any]]:
    return synthetic_floor(), copy.deepcopy(synthetic_layout())
