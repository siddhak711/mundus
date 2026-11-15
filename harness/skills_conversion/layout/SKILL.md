---
name: layout
description: How to draw apartments on an office floor with draft_layout - unit sizes, depths, corners, columns and windows.
---

# Drawing a layout

- The floor is cleared: the old offices, meeting rooms, corridors and furniture are gone. Only the facade, the core
  and the columns remain. Do not follow the old office plan; plan on the open floor between facade and core.
- Units ring the facade; one corridor runs behind them, along the core. The core is never touched.
- Unit depth: use unit_depth_m "auto". Each unit then runs from the facade back to a corridor along the core, up to
  10.5 m deep (deeper fails daylight_depth, 35 ft = 10.7 m). A fixed depth sized to the narrowest point
  (facade_to_core_m.min - 1.6) wastes the floor wherever the core is farther away.
- Deep units suit larger types: put 2BR and 1BR where depth reaches 8 to 10.5 m, studios where it is shallow.
- Typical widths along the facade (bedrooms are drawn 3.2 m wide against the windows):
  studio 4.5 to 5.5 m; 1BR 6.5 to 7.5 m; 2BR 9.5 to 10.5 m; 3BR 12.8 m or more.
- Corners: the two longest sides run full length. Short sides fit between them: usable length = length minus the
  depth of the long sides' end units (draft_layout works this out; read draft_problems).
  A corner unit on a long side gets windows on two sides: a good place for a 2BR.
- Columns: read_floor lists column candidates per side as along_m and from_facade_m. A candidate with from_facade_m
  less than your unit depth sits inside your units: move a unit boundary so no demising wall lands within 0.5 m of it.
- Stretches with no windows (no_window_stretches_along_m): no bedroom there. Skip them with a
  {"type": "gap", "width_m": ...} entry and continue with units after the gap. Units start at the side's usable
  start, so the widths and gaps you list are positions along the side.
- Leftover facade at the ends of a side becomes amenity space. Fill sides as fully as the rules allow.
