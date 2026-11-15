# Floor 16 generator: feedback for v4

Building: The Oppenheimer Tower, 10880 Wilshire, floor 16. Scan coordinates in metres (same as `shell.json`).

**Score history:**
- v1 Scheme A: 54
- v1 Scheme B: 67
- v2: 76
- **v3: 88** (self-score 88.3, now accurate)

**v4 target: 92 or more.** The practical ceiling is about 94 under the current money inputs.

**Keep v3 exactly, and change only what is listed here.** The rubric, money model, column list, assumptions and scoring rules from `floor16-generator-feedback.md` and `floor16-generator-feedback-v3.md` all still apply.

---

## 1. Close the office gap (up to +3.9 points)
Apartment NOI is $46.1k/yr short of the office lease ($0.634M vs $0.680M). Under the grader's model:
- each extra unit carved out of the same floor area adds about $8.5k NOI/yr;
- about **6 more units (28 in total) closes the gap**;
- shrinking oversized corners also helps, because the rent formula's per-sf part pays less than its fixed per-unit part.

The v3 feedback asked for these. They were not done:

| Where | v3 | v4 change | Units |
|---|---|---|---|
| W1/W2 (811–814 sf) | 2 units on the 12.6 m deep west end | 3 units of about 540 sf, each with a bedroom and living room on the west glass | +1 |
| S1, S8, N1 corners (1,147–1,163 sf) | Oversized two-bed units | Two-bed, two-bath at 950–1,050 sf. Give the freed glass to the neighbouring one-bed so it can split in two | +1 to +2 per side |
| S2 + S3 (634 + 747 sf) | 2 units | 3 units of at least 500 sf if the 8.5 m column grid allows | +1 |
| E1–E3 (595–659 sf) | 3 units | Check whether 4 units of at least 500 sf fit on the 34.7 m east glass (the E side runs y −1.37 to 17.97) | +1 |

- **Rules:** no one-bed under 500 sf. Average all units at 560–650 sf. Rerun the full column footprint test and the hidden-column test after every new demising wall.
- **Accessibility:** if the count reaches 27–28, you need at least 3 mobility units (11%) and 2 hearing/vision units (4% of 28 rounds up to 2). v3 has only 1 hearing/vision unit.
- **Report both views** (information only, not scored): the grader's model, and the same model with $55k per extra kitchen and bath. This shows whether the extra units still pay off once real fit-out is counted.

## 2. Fix the two corner drains (+1.5)
- **N1:** move bath 2, the sink, the dishwasher and the washer onto the wet wall at the corridor/core end. The targets are bath 2 ≤8.0 m (from 9.0), sink ≤8.0 (from 8.4), dishwasher ≤8.0 (from 9.0).
- **N9:** turn the kitchen so the sink and dishwasher sit beside the paired baths near the corridor. The targets are sink ≤8 m (from 9.5) and dishwasher ≤8 m (from 10.1). Bring the washer to ≤8 m (from 8.9) and bath 2 to ≤8 m (from 8.4).
- Raise the share of units with paired wet rooms from 73% to at least 85%. Pair the new units' baths back to back across each new demising wall.

## 3. Unit size (+0.5)
Bring the average of all units to 700 sf or less (v3: 717). Section 1 does this on its own.

## 4. Optional: efficiency (+0.4)
74.4% is rented now; reaching 80% gets the full 6 points. You can only gain where the corridor still sits more than 9.0 m from the glass. Check for this along:
- the north side between x −25 and 4 (the corridor is at y 13.88–15.4 there);
- the south side by S3 (the corridor jog at x −19.8 to −9.2).

Don't move the stairs, lobbies or links.

## 5. Don't regress (all verified in v3)
- 0 hard-rule breaks. 21/21 detected and 11/11 hidden columns pass the footprint test.
- Mobility bathrooms column-free. Entries at least 1.07 m. Doors at least 0.91 m.
- Stairs 44.3 m apart. Worst travel to a stair door 45 m or less. Enclosed ½ hr stair links at least 1.12 m wide. Corridor loop. Two enclosed lobbies.
- Lockers and co-working separated by a 1 hr wall. Exhaust chases at least 0.6 m from any column.
- All bedrooms and living rooms on the glass.

## 6. Output (same as v3, plus)
- `money.fitout_sensitivity`: NOI, yield and vs-office with $55k per extra kitchen and bath (information only).
- In the self-score: a per-change list (old unit → new units, sf, columns hit).

## 7. After v4
Once the layout reaches about 92, more layout work gains little. The verdict will then depend on real inputs, not geometry:
- whether floor 16 can actually be leased as office;
- Wilshire Corridor high-rise rent comps;
- the as-built core drawings (stairs, stacks, beam depths);
- an accessibility ruling (11A vs 11B).
