# Floor 16 v2 layout: review and grade

Reviewed 15 Nov 2026. Inputs: `~/Downloads/hackprinceton/floor-mockup/data/studies/v2/` (layout-v2.json, three PNGs) and the generator's learnings file.
I graded with the same rubric as v1 (compliance 40, structure 30, cost-benefit 30) and the same money model. I re-ran every check from the JSON myself rather than trusting the self-score.

## Grade: **76 / 100**. Viable after fixes (the self-score was 92)

| | v1 Scheme A | v1 Scheme B | **v2** |
|---|---|---|---|
| Compliance (40) | 22 | 29 | **31** |
| Structure (30) | 16 | 23 | **26** |
| Cost-benefit (30) | 15.6 | 15.1 | **19.3** |
| **Total** | **54** | **67** | **76** |

v2 is a real improvement. It clears all the big v1 problems:
- units go deeper where the core is far, and efficiency rises from 59% to 74%;
- the four corners are two-bed units;
- the stairs are 44.3 m apart and each core has an enclosed elevator lobby;
- every bath has an exhaust chase;
- every unit is labelled accessible or not, and the share of each type meets the target;
- all 11 hidden columns are clear.

**Why it isn't 92:** one hard-rule break the generator's own check missed, drain runs that leave out kitchens, and a generous owner-view score.

## What I verified (all from layout-v2.json)
- **Areas reconcile.** Units total 15,765 sf with no overlaps. Nothing intersects the core, and corridors don't overlap units. Corridor plus lobbies plus stair links come to 2,513 sf. Efficiency 74.4%.
- **Rooms.** Every bedroom and living room is on the glass. No bedroom, living room, entry or bath is under the minimum size.
- **Stairs and travel.** The stair doors are 44.3 m apart (≥25.7 needed). The worst travel to a stair door is 44.7 m (≤76 m allowed). The corridor is a loop.
- **Accessibility mix.** Mobility units S4, S6 and S7 (14%); hearing/vision unit S5 (4.8%). Both meet the 11% and 4% targets.
- **Money** matches the grader's model exactly: NOI $0.626M, buyer cost $16.59M, buyer yield 3.77%, owner yield 5.67%, −$54.5k/yr vs the office lease.

## Problems found

1. **Hard-rule break: column C15 sits inside the S7 bathroom.**
   - C15 is a probable column, 0.64 m wide, at (11.34, −1.80).
   - The generator logged it as "S6/S7 demising wall, ok". It tested the column's *centre point* against the wall line.
   - The wall is at x = 11.07, so the column's footprint (x 11.02–11.66) puts 0.38 m² into the S7 bath (2.0 × 2.45 m).
   - S7 is a **mobility unit**, so this also eats into the bath's turning space and fixture layout.
   - This is the same kind of bug as v1's N8 entry: the check is on the centre point, not the full column footprint.
2. **Drain runs only count bathrooms.**
   - The self-check reports a worst run of 7.9 m. Kitchens count too under the rubric.
   - The corner kitchens are 9.0–9.4 m wide, and their centres are 12.9–14.2 m (Manhattan) from the nearest core face (S1, S8, N1, N8).
   - The plan never says where the sink goes, so a run of 8 m or less isn't shown.
   - N1's second bath is about 8.5 m by my measurement (from room centres).
3. **The stair links cross the storage and co-working zone.**
   - The 2.1 m and 1.3 m links to Stair 1 and Stair 2 run through the zone ringed by the corridor.
   - They must be drawn as enclosed, rated corridor (½ hr). Exits can't pass through storage rooms (CBC 1016.2).
   - Co-working is office use and lockers are storage, so label and separate the two.
4. **The owner-view score is too generous.**
   - Apartments still lose to the office lease by $54.5k/yr, but the self-score gave 7.4 of 8.
   - With the rule used for v1 (A at −$0.10M got 3; B at −$0.15M got 2), v2 earns **3.9**.
   - The formula is now written into the rubric (see the feedback doc).
5. **Average unit size is 751 sf, above the 500–700 band.**
   - The corners are large: 1,173–1,221 sf (886 at N8).
   - The one-beds alone average 651 sf, which is fine.
   - Bigger units, under the rent model's fixed $974 per-unit part, are what keep the owner view slightly negative.

## Score breakdown

| Criterion | Max | Self | **Grader** | Note |
|---|---|---|---|---|
| LA zoning | 5 | 5 | **5** | |
| Room size, daylight, escape | 7 | 7 | **7** | Verified |
| Exits and stairs | 8 | 8 | **7** | Stair links through the storage zone must be enclosed, rated corridor |
| Accessibility | 8 | 8 | **6** | Mobility bath in S7 has a column in it |
| Fire, sound, ventilation | 7 | 6.8 | **6** | Co-working and storage use not separated |
| No hard failures | 5 | 5 | **0** | C15 in the S7 bath |
| Detected columns | 10 | 10 | **8** | 20 of 21 clear |
| Hidden columns | 8 | 8 | **8** | 11 of 11 clear |
| Drains to the core | 7 | 6.5 | **5** | Corner kitchens unproven; N1 second bath about 8.5 m |
| Loads and earthquake | 5 | 5 | **5** | Chases 0.6 × 0.3 m, clear of columns |
| Buyer yield | 12 | 6.3 | **6.3** | 3.77% vs 7.15% |
| Owner view vs office | 8 | 7.4 | **3.9** | −$54.5k/yr; 5 + 20 × gap in $M |
| Share of floor rented | 6 | 5.6 | **5.6** | 74.4% |
| Unit size vs market | 4 | 3.5 | **3.5** | Average 751 sf, but one-beds average 651 |
| **Total** | 100 | 92.0 | **76.3** | |

**Viability:** the layout grade is "viable after fixes". The money is not:
- **Buyer view:** 3.8% vs 7.15% needed; rents would have to rise about 90%. No layout fixes that.
- **Owner view:** v2 is now within 9% rent of beating the office lease. Closing that gap is the job for v3.

**Caveat about the money model:** cost is charged per square foot, and rent has a fixed $974 per-unit part. So more units always looks better, even though each extra kitchen and bath really adds roughly $40–70k of fit-out. I've kept the model unchanged so runs stay comparable, but treat unit-count gains with that in mind.
