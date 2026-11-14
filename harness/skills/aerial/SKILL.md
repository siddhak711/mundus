---
name: aerial
description: What the Vexcel aerial attributes mean, what match_method says about confidence, and which image kinds exist.
---

# Reading aerial facts

`get_aerial_facts` returns one parcel and, when found, one building on it.

- `match_method`: `contains` means the place's point falls inside the building footprint. `nearest` means the nearest
  footprint within 50 m was taken. `parcel_only` means Vexcel returned a parcel with no building: there is no footprint
  and no roof data, so say that.
- `structure_count` over 1 means several buildings share the parcel. The attributes describe the largest one.
- Attribute names: keys starting with `structure.` describe the building (`structure.roof-characteristics.material.class`,
  `structure.roof-characteristics.shape.value`, `structure.roof-objects.solar.value`, `structure.roof-objects.ac-unit.count`).
  Other keys describe the parcel (`pool.detected`, `vehicles.count`, `hardscapes.percent`, `parcel-tree-cover.percent`,
  `sport-court.detected`).
- `vehicles.count` is cars visible on the capture date. It is not parking capacity.
- A pool flagged on the parcel may belong to a neighbouring building on the same parcel.
- Images: `ortho` at 80 m and 250 m across, and four obliques (`oblique-n`, `oblique-s`, `oblique-e`, `oblique-w`).
  Use an oblique for facades, loading doors and storey counts; use ortho for roofs and site layout.
