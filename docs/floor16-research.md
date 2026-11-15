# Floor 16 apartment study: rules, assumptions, what to check

Draft for checking with your sources. This is not an architect's, code consultant's or investment opinion. To regenerate after changing inputs:

`python scripts/apartment_study.py all` (needs matplotlib, numpy, shapely, pillow)

## Files
- `01-empty-floor.png`: the floor as the scan gives it: fitted outer wall, core, and the 21 detected columns, labelled C1–C21.
- `02-scheme-A-min.png`: 28 code-minimum one-beds (408–545 sf, average 445).
- `03-scheme-B-market.png`: 22 larger one-beds (482–604 sf, average 566).
- `04-cost-benefit.png`: money for both schemes under three rent mixes, the break-even cost, and an optimistic/mid/pessimistic range.
- `layout-A.json`, `layout-B.json`: every unit, room, door and column check, in scan coordinates. This is the format the viewer will use later.
- `summary.json`: all the numbers in one place.

## Where the floor comes from
The script reads the same files the viewer loads: `shell.json` (outer wall, core, columns), `scene.json` and `floorfill.png`. All of them were derived from the Matterport scan of Suite 1600 (model cEvQ8q5GKZd). **None of it is an official floor plan.** The outer wall is a rectangle fitted to the scan (68.7 × 34.7 m, 25,667 sf). The core is the area the scanner never entered (4,489 sf). The columns were detected in the mesh: 16 "probable" and 5 "possible". Columns hidden inside old partitions were not found.

## How the layout was made
- **Corridor:** a 5 ft loop placed by hand. Its inner wall runs along the outer faces of the column rows (south row y≈−1.9, north row y≈16.0, east line x≈22, west possible columns x≈−30.2), so every probable column sits in the corridor wall and none lands inside an apartment. Three short corridors join the loop to the core, where the stairs and lifts are assumed to be.
- **Units:** about 21 ft deep from the glass to the corridor (6.2–6.45 m). Demising walls are placed by an optimiser that keeps widths in range and puts walls on column lines where a column would otherwise land inside a room. Scheme A maximises the unit count; scheme B aims for about 8.4 m wide units.
- **Inside each unit:** bedroom and living room on the glass; kitchen, bath and entry on the corridor side. Baths are mirrored in pairs so neighbours share a plumbing wall.
- **North side:** the wall between the window rooms and the kitchen/bath zone is 2.43 m from the corridor, so it runs through the second north column row (C10, C12, C16 at y≈20.2). Those columns sit in that wall and stick out about 0.3 m into the rooms.
- **Middle of the floor:** the area between the corridor and the core (5,814 sf) gets no daylight and is labelled amenity / storage / back-of-house. It is not counted as rentable.

## Rules checked (script prints pass/fail; all pass for both schemes)
| Rule | Value used | Source |
|---|---|---|
| LA Adaptive Reuse Ordinance | By right at ≥15 years old (built 1969); ≥5 units; no zoning minimum unit size; existing FAR and parking accepted; no open space requirement; Wilshire-Westwood Scenic Corridor plan does not apply; linkage fee applies | Ord. 188,793, LAMC §12.22 A.26, effective 1 Feb 2026 ([PDF](https://cityclerk.lacity.org/onlinedocs/2021/21-1230-S9_ord_188793_12-23-25.pdf)) |
| Room width | ≥7 ft in every direction, habitable rooms | CBC 2025 §1208.1 ([transcription](https://gocodebook.com/library/us/ca/ca-building-code/chapter-12-interior-environment/section-1208-interior-space-dimensions); check against official Title 24) |
| Room size | One room ≥120 sf (we use the living room); others ≥70 sf; unit ≥190 sf habitable | CBC 2025 §1208.3–1208.4 (same) |
| Ceiling | ≥7 ft 6 in habitable. Scan shows 8 ft 9 in, leaving about 15 in for new ducts and pipes | CBC 2025 §1208.2 |
| Daylight | Glazing ≥8% of room floor area; bedroom on an exterior wall | CBC §1204.2 ([link](https://gocodebook.com/library/us/ca/ca-building-code/chapter-12-interior-environment/section-1204-lighting)) |
| Escape window | Not required on floor 16 (only below the 4th storey; sprinklered high-rise exempt) | CBC §1031.2 |
| Exits | 2 per floor; travel ≤250 ft; common path ≤125 ft; dead end ≤50 ft (sprinklered R-2). Worst walk to the core is 127 ft (A) / 133 ft (B); the loop has no dead ends | CBC Table 1006.3.3, Table 1017.2, §1020.5 ([UpCodes](https://up.codes/viewer/california/ca-building-code-2022/chapter/10/means-of-egress)) |
| Corridor | ≥44 in; drawn at 5 ft for wheelchair turning | CBC §1020.2 (secondary source) |
| Accessibility | Elevator building, so all units are "covered" under CBC 11A. Rooms are sized with 30×48 in clear space in mind. With city funding: 11% mobility units and 4% hearing/vision units | CBC §1106A.1 ([UpCodes](https://up.codes/viewer/california/ca-building-code-2022/chapter/11A/housing-accessibility)); [HUD fact sheet](https://www.hud.gov/sites/dfiles/Main/documents/Fact-Sheet-and-QA-HUD-City-of-Los-Angeles-VCA.pdf) |
| Columns | No column loose in a bedroom or living room; each sits in a demising wall, the window-zone wall or the corridor wall | Study rule |

## Money inputs
| Input | Mid (optimistic–pessimistic) | Source |
|---|---|---|
| Conversion cost, all-in per gross sf | $500 ($400–600) | AECOM ARO Economic Analysis, Jul 2024, Table 5 ([CPC staff report](https://planning.lacity.gov/plndoc/Staff_Reports/2024/09-12-2024/CPC_2023_5986.pdf)); range from [Cooperative LA](https://cooperative.la/perspectives/office-to-residential-adaptive-reuse-playbook/), Jan 2026 |
| Acquisition of the floor | $216/sf ($93–539) | AECOM 2024, LA County vacant office sales; 10900 Wilshire next door at $539/sf ([Bisnow](https://www.bisnow.com/news/los-angeles/office/douglas-emmett-santa-monica-office-building-131-million-127761), Jan 2025) |
| Linkage fee | $16.76/sf net ($23.20 residential less $6.44 office credit; the net figure is derived). Exempt when ≥20% of units are low-income | [AHLF memo, Apr 2026](https://planning.lacity.gov/odocument/a098a8ca-11a2-4831-8f5a-d576285fe0b7/AHLF_Implementation_Memo_April_22,_2026.pdf) |
| Market rent | CoStar apartment listings: 167 one-bed floor plans in 38 buildings within 2 km. Median $3,245/mo at 681 sf. Unit rent = $974 + $3.34 × sf (straight-line fit to the comps) | CoStar hackathon kit |
| Affordable rent, 1-bed | $1,874 at 60% AMI; $2,499 at 80% AMI | [LAHD 2026 schedules](https://housing.lacity.gov/wp-content/uploads/2026/07/2026-Schedules-07012026.pdf), effective 1 Jul 2026 |
| Exit cap rate | 5.9% (optimistic case 4.5%) | [Kidder Mathews LA 3Q26](https://kidder.com/wp-content/uploads/market_report/multifamily-market-research-los-angeles-2026-3q.pdf); AECOM 2024 |
| Operating expenses | 30% of income (35% stress case) | AECOM 2024 |
| Vacancy 5%; other income $75/unit/mo; yield needed = exit cap + 1.25% | — | *Assumptions* |

## Result (mid case)
| Scheme | Rent mix | Units | NOI/yr | Total cost | Yield on cost | Needed | Verdict |
|---|---|---|---|---|---|---|---|
| A | 100% market | 28 | $0.57M | $18.8M | 3.0% | 7.15% | Not worth it |
| A | 80/20 mixed | 28 | $0.57M | $18.4M | 3.1% | 7.15% | Not worth it |
| A | 100% at 60% AMI | 28 | $0.44M | $18.4M | 2.4% | 7.15% | Not worth it |
| B | 100% market | 22 | $0.52M | $18.8M | 2.7% | 7.15% | Not worth it |

Even in the optimistic case (scheme A, 100% market) the yield is 4.3% against 5.5% needed.

**Why it fails:** only 59% of the floor area (after the core) can be rented, because the floor is deep and the middle gets no daylight. Yet the $500/sf cost is charged on the whole 25,667 sf. That works out to about $1,500 per rentable sf. Small units also rent for less: $2,458 per month on average, against the comps' median of $3,245.

**What would change the verdict:**
1. A much lower cost for the dark middle and the core. If it stays light-touch storage or amenity, it shouldn't cost $500/sf.
2. Turning the middle into income: storage lockers, coworking, or inboard units with borrowed light (CBC §1204.2.1).
3. Public subsidy or tax incentives for the affordable scenario.
4. A lower acquisition basis. Douglas Emmett already owns the building, so it may not be a cash cost.

## What to check with your sources
1. A real floor 16 plan, to confirm the columns, especially the west half where none were detected.
2. Where the stairs, lifts and plumbing risers are inside the core.
3. Which code edition LADBS currently applies (the 2025 CBC took effect 1 Jan 2026), and any LA local amendments.
4. Whether HCD treats an office-to-residential conversion as "covered" under CBC 11A.
5. Whether Westwood is still a "high market" area on the 2026 linkage fee maps.
6. The conversion cost per sf for this building, and whether the $500 all-in figure is right to apply to non-rentable area.
7. Window mullion spacing, so demising walls can meet the glass at a mullion.
