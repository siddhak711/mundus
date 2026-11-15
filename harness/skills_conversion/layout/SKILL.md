---
name: layout
description: How to draw apartments on an office floor with draft_layout - unit sizes, depths, corners, columns and windows.
---

# Drawing a layout

- Units ring the facade; the corridor runs behind them, between the units and the core. The core is never touched.
- Unit depth: the distance from the facade to the corridor. Keep unit_depth_m + 1.6 m (corridor) <= the side's
  facade_to_core_m.min. Deeper units fail daylight_depth (35 ft = 10.7 m).
- Typical widths along the facade (bedrooms are drawn 3.2 m wide against the windows):
  studio 4.5 to 5.5 m; 1BR 6.5 to 7.5 m; 2BR 9.5 to 10.5 m; 3BR 12.8 m or more.
- Corners: the two longest sides run full length. Short sides fit between them: usable length = length - 2 x depth.
  A corner unit on a long side gets windows on two sides: a good place for a 2BR.
- Columns: read_floor lists column candidates per side as along_m and from_facade_m. A candidate with from_facade_m
  less than your unit depth sits inside your units: move a unit boundary so no demising wall lands within 0.5 m of it.
- Stretches with no windows (no_window_stretches_along_m): no bedroom there. Skip them with a
  {"type": "gap", "width_m": ...} entry and continue with units after the gap. Units start at the side's usable
  start, so the widths and gaps you list are positions along the side.
- Leftover facade at the ends of a side becomes amenity space. Fill sides as fully as the rules allow.
