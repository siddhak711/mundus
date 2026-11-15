---
name: compliance-la
description: Los Angeles rules for converting an office floor to apartments, each with its source, its status and how check_layout measures it.
---

# Los Angeles office-to-residential rules

Every rule below is **unconfirmed**: written from the codes as we understand them, not yet checked against the current
text. When you confirm or correct one, record it in /memories/compliance/la.md with the source and evidence.
The California Building Code (CBC, Title 24 Part 2) follows the International Building Code's section numbers.
Source for every CBC rule: California Building Code, current edition, https://codes.iccsafe.org

| Rule | Threshold | Source | Status | Measured by check_layout as |
|---|---|---|---|---|
| Adaptive reuse eligibility | Building in the City of LA, at least 15 years old for by-right approval | Citywide Adaptive Reuse Ordinance, Ordinance 188,793, https://planning.lacity.gov | unconfirmed | not measured: building-level, see market summary |
| Natural light | Glazing at least 8% of each habitable room's floor area | CBC 1204.2 | unconfirmed | natural_light (glazed height assumed 2 m) |
| Bedroom window | Every sleeping room has an exterior window | CBC 1204, 1030 | unconfirmed | bedroom_windows |
| Room size | One room of at least 120 sf per unit; other habitable rooms at least 70 sf | CBC 1208.3 | unconfirmed | bedroom_windows (70 sf part) |
| Room width | Habitable rooms at least 7 ft in any direction | CBC 1208.1 | unconfirmed | bedroom_windows (narrowest side) |
| Efficiency unit | At least 220 sf | CBC 1208.4 | unconfirmed | unit_size |
| Ceiling height | At least 7 ft 6 in in habitable rooms | CBC 1208.2 | unconfirmed | ceiling_height (as scanned, before new ceilings) |
| Exit travel distance | At most 250 ft, sprinklered Group R-2 | CBC Table 1017.2 | unconfirmed | exit_travel (exits assumed at the core) |
| Number of exits | At least two exits per storey for R-2 with more than 4 units | CBC 1006.3 | unconfirmed | not measured: fire stairs not scanned |
| Corridor width | At least 44 in | CBC 1020.3 | unconfirmed | draft_layout corridor (1.6 m default) |
| Dead-end corridors | At most 50 ft, sprinklered R-2 | CBC 1020.5 | unconfirmed | not measured |
| Separation between units | 1-hour fire partitions; sound STC 50 | CBC 708, 1206 | unconfirmed | not measured: construction detail |
| Daylight depth | 25 to 35 ft from a window | Conversion studies, rule of thumb, not code | n/a | daylight_depth (35 ft) |

Not knowable from the scan: wall fire ratings, sprinklers, accessibility unit counts, parking, the real fire stairs.
