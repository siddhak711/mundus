# Floor 16 generator: feedback for v3

Building: The Oppenheimer Tower, 10880 Wilshire, floor 16. Scan coordinates in metres (same as `shell.json`).

**Score history:**
- v1 Scheme A: 54
- v1 Scheme B: 67
- **v2: 76** (it self-scored 92)

**v3 target: 85 or more.** **Keep v2 as the base.** Its layout strategy is right: variable depth, two-bed corners, stairs, lobbies and chases. Fix the items below instead of starting over.

The rubric, money model, column list and assumptions are unchanged from `floor16-generator-feedback.md`, except for section 3 below.

---

## 1. Must fix (worth about 9 points)

### 1a. Column C15 is inside the S7 bath (hard-rule break: −5, and −2 detected columns, −2 accessibility)
- C15 is a probable column, 0.64 m wide, at (11.34, −1.80). The S6/S7 demising wall is at x = 11.07.
- So 0.38 m² of the column sits inside the S7 bathroom, which is a mobility unit.
- **The fix:**
  - Move the S6/S7 demising wall to x ≈ 11.34 so the column is centred in it, and check that no more than about 0.1 m sticks out either side; **or**
  - Swap S7's bath and closet so the closet takes the corner at the corridor where the column is (closet at y −3.82…−1.37, bath at −5.5…−3.06). Then move the exhaust chase and the paired wet wall to match.
  - Then re-check S6, since its bath also touches the column by 0.03 m².
- **Fix the checker, not just the layout:** test the column's **full square footprint** against every room. Any overlap above 0.02 m² with a bath, entry, hall or door swing is a break. A "demising wall" counts only if the whole footprint fits inside the wall thickness plus about 0.1 m each side.

### 1b. Drain runs must include kitchens (−2 drains)
- **Place the kitchen sink and the dishwasher** in every unit, and output their position.
- Measure the drain run from **every** wet fixture group (bath, kitchen sink, washer) to the nearest core face, using Manhattan distance. Each must be **8 m or less**.
- **Corners (S1, S8, N1, N8):** the kitchens are 9.0–9.4 m wide. Put the sink run at the end nearest the core, beside the bath wet wall. Their centres are 12.9–14.2 m from the core today.
- N1's second bath measures about 8.5 m from its centre: move it next to the first bath.

### 1c. Enclose the stair links (−1 exits)
- Draw the links from the corridor to Stair 1 and Stair 2 as **enclosed ½ hr rated corridor**, at least 1.12 m (44 in) wide. Exits can't pass through storage (CBC 1016.2).
- Split the middle zone into **(a) enclosed storage locker rooms** and **(b) a co-working lounge**, with a 1 hr wall between them. Neither may be on a path to a stair.

## 2. Should fix (worth about 4 points): close the office gap
v2 earns $54.5k/yr less than the floor would as office, so the owner view scores 3.9/8. Beating the office lease is worth up to 8. Under the grader's model, each extra unit carved out of the same floor area adds about $8.5k NOI/yr.

**Target: about 26–28 units, averaging 560–620 sf, no one-bed under 500 sf.**

| Where | v2 | v3 suggestion |
|---|---|---|
| North N2–N5 (4 × 719–727 sf) | 4 units, about 7.5 m wide | 5 units, about 6.0 m wide (~580 sf) |
| West W1–W2 (2 × 811–814 sf) | 2 units | 3 units (~540 sf), stacked along the 12.6 m deep west end |
| Corners S1, S8, N1 (1,173–1,221 sf) | Oversized two-bed units | Two-bed, two-bath at 950–1,050 sf. The freed glass goes to one more one-bed per side where frontage allows |
| South S3 (747 sf), S2 (615 sf) | | Check whether S2+S3 can become 3 units at ≥500 sf |

**Rules for carving units:**
- Keep every bedroom and living room on the glass.
- Keep the column rules: wardrobe strip, wide kitchen or living room only.
- Rerun the column footprint check after every change.
- New demising walls should fall on the about 8.5 m grid or halfway between grid lines (x ≈ −4.4, 4.2, 12.9), so columns stay in walls or in wide rooms.

## 3. Rubric clarifications (apply them in your self-score)
- **Owner view vs office (8 pts):** 8 if apartment NOI is at least the office alternative ($0.68M/yr). Otherwise max(0, 5 + 20 × gap in $M). Examples: −$0.05M → 4.0; −$0.10M → 3.0.
- **Columns:** footprint test as in 1a. The centre-point test is no longer accepted.
- **Drains:** every wet fixture group counts, including kitchens and washers, as in 1b.
- **Unit size vs market (4):** 4 if the average of all units is 500–700 sf and no one-bed is under 450 sf. Lose 0.5 per 50 sf outside the band.
- **Self-score must match the grader:** list every check with the measured value, not just pass/fail. A gap of more than 3 points between self-score and grade will be called out.

## 4. Keep from v2 (don't regress)
- Variable unit depth capped at 9.0 m; 74% or more of the floor rented.
- Two-bed corners with a bedroom on each façade.
- A stair in each core on the far face, at least 25.7 m apart. An enclosed elevator lobby at each core, opening onto the corridor. A corridor loop with no dead ends.
- A wardrobe strip behind bedrooms and living rooms at the 4.2 m column row.
- An exhaust chase per bath (0.6 × 0.3 m, clear of columns). Wet rooms paired.
- Accessibility mix: at least 11% mobility units and at least 4% hearing/vision units. Re-mark them if the unit count changes: 26 units → 3 mobility and 2 hearing/vision.
- Labelled fire and sound walls.

## 5. Output (same as v2, plus)
- For each unit: `sinks` (positions), `drain_runs_m` per wet group, and `column_overlaps` (room, m²) from the footprint test.
- For the floor: storage vs co-working areas, and the stair-link enclosure ratings.
- In the money block: `vs_office` and the owner-view points computed with the section 3 formula.
