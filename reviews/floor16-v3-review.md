# Floor 16 v3 layout: review and grade

Reviewed 15 Nov 2026. Inputs: `~/Downloads/hackprinceton/floor-mockup/data/studies/v3/` (layout-v3.json, self-score-v3.md, three PNGs).
Graded with the same rubric, the money model and the v3 clarifications (footprint column test, kitchens count for drains, owner-view formula). I re-ran every check from the JSON myself.

## Grade: **88 / 100**: build as drawn (layout); money still short. Self-score 88.3

| | v1 A | v1 B | v2 | **v3** |
|---|---|---|---|---|
| Compliance (40) | 22 | 29 | 31 | **39.7** |
| Structure (30) | 16 | 23 | 26 | **28.5** |
| Cost-benefit (30) | 15.6 | 15.1 | 19.3 | **19.6** |
| **Total** | 54 | 67 | 76 | **88** |
| Self-score | — | — | 92 | 88.3 |

This time the self-score matches the grade, within 0.5 points. The scoring rules are now tight enough that the generator scores itself honestly.

## What I verified
- **Areas:** units total 15,765 sf with no overlaps. Nothing touches the core. Corridors don't overlap units. Efficiency is 74.4%, the same as v2.
- **Columns (footprint test, all 32):** no column touches a bath, an entry or a hall.
  - C15 has moved into S7's 4.45 m kitchen. That fixes v2's hard-rule break.
  - Every other column sits in one of three kinds of place:
    - a kitchen at least 3.19 m wide;
    - a living room at least 3.35 m wide;
    - a wardrobe or a 1.75 m closet.
- **Rooms:** every bedroom and living room is on the glass. All entries are at least 1.07 m and all doors at least 0.91 m.
- **Exits:** the stairs are 44.3 m apart. The worst travel to a stair door is 45.1 m.
  - Both stair links are now enclosed ½ hr corridor, 1.5 m and 1.3 m wide.
  - Lockers (1,638 sf) and co-working (1,263 sf) are separated by a 1 hr wall.
- **Accessibility:** mobility units S4, S6, S7; hearing/vision unit S5. The mobility bathrooms have no columns in them.
- **Money:** matches the model.
  - NOI is $0.634M.
  - Yield is 3.82% for a buyer and 5.74% for the owner.
  - Against the office lease it's −$46.1k/yr, which is 4.08 points.

## Problems remaining
1. **Two corner units still have drain runs over 8 m.**
   - N1: second bath 9.0 m, sink 8.4 m, dishwasher 9.0 m.
   - N9: sink 9.5 m, dishwasher 10.1 m, second bath 8.4 m, washer 8.9 m.
   - The generator reported both honestly. 20 of 22 units pass. Wet rooms are paired in 16 of 22 units (73%).
2. **The unit-count changes I asked for were only partly done.**
   - North N2–N6 went from 4 to 5 units. The NE corner shrank to an 803 sf two-bed, and N7/N8 became 505 sf units.
   - **W1/W2 are still 811–814 sf**, and S1, S8 and N1 are still 1,147–1,163 sf corners. I asked for 950–1,050 sf.
   - The total went from 21 units to only 22. The target was 26–28.
   - That's why apartment income still trails the office lease by $46k/yr.
3. **Average unit size is 717 sf, just over the 700 cap,** which costs 0.5 points.
4. **The rentable share hasn't changed since v2** (15,765 sf, 74.4%). The middle 2,901 sf still sits on the $150/sf storage rate.

## Score breakdown

| Criterion | Max | Self | **Grader** | Note |
|---|---|---|---|---|
| LA zoning | 5 | 5 | **5** | |
| Room size, daylight, escape | 7 | 7 | **7** | |
| Exits and stairs | 8 | 8 | **8** | Links enclosed, lobbies, loop |
| Accessibility | 8 | 8 | **8** | Mobility bathrooms column-free |
| Fire, sound, ventilation | 7 | 6.7 | **6.7** | 1 hr locker/co-working wall; paired wet rooms 73% |
| No hard failures | 5 | 5 | **5** | |
| Detected columns | 10 | 10 | **10** | 21/21 |
| Hidden columns | 8 | 8 | **8** | 11/11 |
| Drains to the core | 7 | 6.0 | **5.5** | N1 and N9 over 8 m on several fixture groups |
| Loads and earthquake | 5 | 5 | **5** | |
| Buyer yield | 12 | 6.4 | **6.4** | 3.82% |
| Owner view vs office | 8 | 4.1 | **4.1** | −$46.1k/yr |
| Share of floor rented | 6 | 5.6 | **5.6** | 74.4% |
| Unit size vs market | 4 | 3.5 | **3.5** | 717 sf average |
| **Total** | 100 | 88.3 | **87.8** | |

## Verdict
- **The layout is code- and structure-clean on everything I can check without as-built drawings.** That's the "build as drawn" band.
- **The project still isn't viable as an investment.**
  - Buyer view: 3.8% vs 7.15% needed. Rents would have to rise about 87%, so no layout can fix this.
  - Owner view: rents would have to rise 7.3% to beat leasing the floor as office.
- **Ceiling:** the most this floor can score under the current money inputs is about 93–94. Buyer yield caps out around 6.5/12.
- **The points left within the layout's control** (about 5) are: the owner gap (up to +3.9), drains (+1.5), unit size (+0.5) and efficiency (+0.4).
