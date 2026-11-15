# Learnings: apartment generation (floor 16, 10880 Wilshire)

These come from the grading of v1 (Scheme A 54/100, Scheme B 67/100; both "major rework needed"). Sources:
- [floor16-generator-feedback.md](floor16-generator-feedback.md)
- `floor16-scheme-review.md` (in the apartment-compliance-review worktree)

Each item is a rule the generator should follow from now on.

## 1. Columns: a wall line is not enough
- **Check every column against the room it lands in, not just "is it near a wall".** In v1, column C10 sat in N8's 1.05 m entry and blocked it. The script still printed "21/21 columns OK", because it only checked distance to wall lines.
- **Allowed places for a column:**
  - a demising wall or the corridor wall
  - a kitchen or living room at least 3 m wide
  - a closet, a wet-wall chase or the amenity zone
- **Forbidden places:** an entry, a bathroom, a hallway, a door swing. One break costs 5 points.
- **Design around the columns you haven't found.**
  - The scan only finds columns that stand free.
  - A 69 m floor plate from 1970 has a regular grid: outer rows 4.2 m in from the north and south glass at about 8.5 m spacing (x ≈ −34.2, −25.7, −17.2, −8.7, −0.18, 8.67, 17.18), interior rows 8.4 m in, and a line at x ≈ 22.
  - Treat the extrapolated hidden columns as real.
- **Put demising walls on the structural grid where possible.** Where a column must land inside a unit, put a wide living room, a kitchen or a closet there.
- **Bedrooms get a wardrobe strip at their back (about 3.75–4.8 m from the glass).** The 4.2 m column row then lands in a closet, never in the open bedroom.
- **Narrow rooms are fragile.** Baths 1.65 m wide and entries 1.05 m wide have no slack for a 0.5–0.75 m column. Scheme B survived because its kitchens and living rooms were 4–6 m wide.

## 2. Depth: don't let the corridor fix unit depth
- **A rectangular corridor loop forced every unit to about 6.3 m deep.** That left 5,814 sf dark. Only 59% of the non-core floor was rentable, against a target of 75% or more.
- **Run the corridor along the core and let depth follow the glass-to-core distance, capped at 9.0 m.**
  - Where the core is only about 8.9 m from the glass, keep units about 6.3–6.5 m deep plus the corridor. The 8.4 m interior column row then sits behind the corridor wall instead of inside it.
  - Where units are 9 m deep, the 8.4 m interior row falls in the back third of the unit. Put the kitchen or a closet there, never the entry or the bath.
- **Use the extra depth for the bath, laundry and closets.** A den is allowed only with borrowed light: an opening at least half the shared wall and at least 25 sf (CBC 1204.2.1).
- **Corridor jogs need checking.** Where depth changes, the corridor steps. Each jog must stay clear of the core and of columns; some clearances are only a few centimetres. Let the script verify this, not my eye.
- **Leftover dark space should earn money.** Label it rentable storage lockers or co-working, not "amenity".

## 3. Egress and core: measure to real things
- **Measure travel distance to a stair door, not "to the core".**
- **Draw both stairs, one per core.** Put each on the face nearest the far end of the floor. They must be at least 25.7 m apart (a third of the 77 m diagonal).
- **Draw an enclosed elevator lobby at each core.** CBC 3006 requires it in a high-rise.
- Keep the corridor a loop with no dead ends. A 44 in corridor is the minimum; draw 5 ft.

## 4. Building services: plumbing, ventilation, fire, sound
- **Every bath and kitchen drain must run 8 m or less (Manhattan distance) to the nearest core face.** In v1, corner and end units ran up to 14.6 m.
  - Wet rooms go on the core side of the unit, in back-to-back pairs that share a wet wall.
- **The windows don't open, so every unit needs an exhaust/ventilation chase in its wet wall.**
  - Show it on the plan.
  - Keep slab openings 0.6 m or smaller, between column lines, not next to columns.
- **Label the fire and sound walls:** 1 hr walls between units, a ½ hr rated corridor, and STC 50 back-to-back wet rooms.

## 5. Accessibility: design to the stricter case
- Whether 11A or 11B applies to a conversion is undecided, so design to the stricter case.
- **Every bath needs a 1.5 m turning circle**, or a 30×48 in clear space outside the door swing.
- **Kitchen clearance:** at least 40 in for a galley, at least 60 in for a U-shape.
- **Entries at least 1.07 m clear; doors at least 0.91 m.**
- **Mark 11% of units as mobility units and 4% as hearing/vision units.**

## 6. Money: model what the grader models
- **Charge cost by area type:**
  - $500/sf on units and corridors
  - $150/sf on storage or amenity
  - $25/sf on the existing core
  - plus $1.0M for single-floor plumbing through the floor-15 ceiling
- **Charge the linkage fee on gross minus core (21,178 sf), not on gross.**
- **Operating costs are 35% of income, not 30%.** A single floor gets no economies of scale.
- **Rent:** the comp fit × 1.10 (high-rise premium), plus $600/mo for a two-bed corner unit.
- **Show two views:**
  - the buyer (pays $216/sf for the floor)
  - the owner (no purchase, but gives up about $0.68M/yr of office income)

  Conversion only wins if the floor can't be leased as office.
- **The $974 fixed part of the rent rewards unit count.** Within the size limits, more, smaller units yield more.
- **Unit size limits:**
  - average 500–700 sf
  - no one-bed under 450 sf
  - corners are two-bed, two-bath, with a bedroom on each façade
- **Report break-even per rentable sf, not per gross sf.** Per gross sf makes the gap look bigger than it is.

## 7. Process
- **Score each run with the rubric before handing it over.** Every check the grader runs should be a check in the script.
- **Output what the grader asks for:**
  - per unit: polygon, rooms, door, entry width, drain run, and the columns inside with the room each falls in
  - per floor: areas, stairs, lobbies, worst travel distance to a stair door, and the unit mix
- **Keep earlier runs** (v1 in `studies/`, v2 in `studies/v2/`) so changes can be compared.
- **Assumptions stay labelled:** stairs and stacks inside the core, hidden columns, a plenum of 15 in, and a steel frame.

## 8. What v2 did with these (self-scored with the grader's rubric, not yet graded)
- **Layout:** 21 units (17 one-beds and 4 two-bed, two-bath corners). Units total 15,765 sf, or 74% of the non-core floor (v1: 59%).
- **Columns:** 0 hard-rule breaks; all 21 detected and all 11 hypothesised columns land in a demising wall, the corridor wall, a wardrobe, a closet, or a wide living room or kitchen.
- **Services:** worst drain run 7.9 m; 16 of 21 units have paired wet rooms; every bath has a chase.
- **Exits:** worst travel to a stair door is 45 m (147 ft); the stairs are 44.3 m apart.
- **Accessibility:** units marked: 3 mobility, 1 hearing/vision.
- **Money:** buyer yield 3.8%, against 3.7% for v1 under the same model.
  - The owner view comes within $0.05M/yr of the office alternative; rents need to be about 9% higher to beat it.
  - The economics are still decided by rent, purchase price and the office alternative, not by the layout.
- **Self-score: 92/100.** The points still lost are mostly buyer yield (6.3 of 12), which no layout can fix at these rents.
- **Width choice:** the feedback suggested 7.5–8.5 m units. Narrower one-beds (6.4–6.8 m) scored higher, because every column is checked against its room explicitly and more units raise rent. Every one-bed is still at least 464 sf.

---

# Round 2: learnings from the v2 grade (graded 76; I self-scored 92)

Sources:
- [floor16-v2-review.md](floor16-v2-review.md) (the grade)
- [floor16-generator-feedback-v3.md](floor16-generator-feedback-v3.md) (what to fix for v3)

**The 16-point gap between my self-score and the grade is itself the main lesson.** The grader re-runs every check from the JSON. Any shortcut in my checker shows up as a gap, and a gap over 3 points gets called out.

## 9. Columns: test the footprint, never the centre point
- **The bug:** C15 (0.64 m) was logged as "in the S6/S7 demising wall" because its centre was within half a column width of the wall line. Its square footprint actually put 0.38 m² into S7's bath, a mobility unit.
  - This is the same class of bug as v1's N8 entry. I fixed the symptom in v2, not the test.
- **The rule now:** intersect each column's full square footprint with every room of every unit, and with the corridor, stair links and lobbies.
  - Any overlap above 0.02 m² with a bath, entry hall, door swing or corridor is a break.
  - Overlap with a living room or kitchen is allowed only if that room is at least 3 m wide.
  - Overlap with a wardrobe, closet or storage room is allowed.
  - A bedroom isn't on the allowed list, so treat bedroom overlap as a fail too.
- **A column on a demising wall is not automatically OK.** It sticks out into the rooms on both sides, and both rooms must pass. Neighbours count as well: S6's bath touched C15 by 0.03 m².
- **Output `column_overlaps` (room, m²) for every unit,** so the grader can see the numbers.

## 10. Drains: every wet fixture, at a real position
- **Kitchens count.** v2 measured baths only.
  - Corner kitchens were 9–9.4 m wide, with centres 12.9–14.2 m from the core, and the plan never showed where the sink went.
- **Place the fixtures explicitly:**
  - the kitchen sink and dishwasher at the kitchen's end nearest the core, beside the wet wall;
  - the washer in the closet or laundry space;
  - output their positions.
- **Measure every wet group** (each bath, the sink, the dishwasher, the washer) to the nearest core face, with Manhattan distance. Each must be 8 m or less.
  - The grader measures baths from the room centre. A stacked "front" bath is about 2.5 m farther than the back one, so N1's second bath measured 8.5 m.
- **The far corners are far from the core whatever you do.** The north-west and south-west corners sit 4+ m from the nearest core face before any horizontal run. Show the measured value honestly, rather than calling it a pass.

## 11. Exits can't pass through storage
- **Links from the corridor to the stairs must be enclosed, ½ hr rated corridors,** at least 44 in (1.12 m) wide. Under CBC 1016.2, exits can't pass through storage rooms.
- **Split the dark middle zone into enclosed storage-locker rooms and a co-working lounge,** with a 1 hr wall between them. Co-working is office use and lockers are storage. Neither may sit on a path to a stair.

## 12. Score the owner view with the grader's formula
- 8 points if apartment NOI is at least the office alternative ($0.68M/yr). Otherwise max(0, 5 + 20 × gap in $M).
  - v2 was −$0.0545M, which scores 3.9, not the 7.4 I gave it. My linear guess was far too generous.
- **Each extra unit carved from the same floor adds about $8.5k NOI/yr.**
  - The target is 26–28 units averaging 560–620 sf, with no one-bed under 500 sf.
  - Corners should be two-bed, two-bath at 950–1,050 sf. v2's were 1,173–1,221 sf.
- **Unit size:** 4 points if the average is 500–700 sf and no one-bed is under 450 sf. Lose 0.5 per 50 sf outside the band.
- **The grader's caveat:** the model charges cost per sf and gives each unit a fixed $974 of rent, so unit count is flattered. Real kitchens and baths add $40–70k each. Report unit-count gains with that in mind.

## 13. Carving more units
- New demising walls go on the about 8.5 m grid, or halfway between grid lines (x ≈ −4.4, 4.2, 12.9), so columns stay in walls or in wide rooms.
- Narrower one-beds are fine if:
  - the bedroom is at least 2.75 m;
  - the living room is at least 3.0 m (the minimum for holding a column) and at least 120 sf;
  - the bath is at least 1.75 m, so the 1.5 m turning circle fits;
  - the kitchen is at least 2.4 m;
  - the unit is at least 500 sf.
- Rerun the footprint check after every change; the generator does this inside the optimiser.

## 14. Self-score honesty
- List every check with its measured value: overlap m², drain metres, travel metres, NOI gap. Pass/fail alone isn't enough.
- Use the grader's clarified formulas, not my own interpretation.
- Keep v2 as the base. Don't regress:
  - depth capped at 9 m and 74%+ rented;
  - two-bed corners;
  - stairs at least 25.7 m apart;
  - lobbies and a corridor loop;
  - the wardrobe strip;
  - chases;
  - the accessibility mix (re-mark it when the unit count changes);
  - labelled fire and sound walls.

## 15. What v3 did with these (self-score 88.3, not yet graded)
- **Columns:** 0 hard-rule breaks, now under the footprint test. All 21 detected and all 11 hidden columns pass.
  - C15 now sits wholly in S7's kitchen (0.41 m² overlap, kitchen at least 3 m wide); no bath or entry touches a column.
- **Fixtures:** sink, dishwasher and washer are placed in every unit. Drain runs are measured from every wet group.
  - 20 of 22 units have every group at 8 m or less.
  - The two failures are the far corners: N1 (north-west) up to 9.0 m and N9 (north-east) up to 10.1 m. Both are reported as fails with their measured values.
- **Exits:** stair links are drawn as enclosed ½ hr passages, 1.30 m wide. The middle zone is split into 1,638 sf of storage lockers and 1,263 sf of co-working, with a 1 hr wall between them.
- **Owner view:** scored with the grader's formula: −$0.046M vs office → 4.1/8. (v2 was −$0.0545M → 3.9.)
- **Unit count stayed at 22, not 26–28.** Three things block more units without breaking a rule:
  1. **West end:** C4 and C13 sit 1.5 m apart in the back of the first west unit. Splitting the west end into 3 units puts one of them in an entry or bath.
  2. **Under the core's south bump:** the shallow stretch is 10.6 m, which can't hold two units of 500+ sf at 6.55 m deep.
  3. **Corners:** shrinking them to 950–1,050 sf frees enough glass for one more unit (23). But all four corner drains then fail (v3 option tested: self-score 88.0 vs 88.3).

  I kept the drains, because they were a must-fix and corner size was a should-fix.
- **Next lever, if the grader agrees:** turn the north-east corner to face the east glass. Its wet rooms then sit next to the east core and drains pass, at the cost of one unit. Or find a way to let C4/C13 sit in a wider west-end kitchen.

---

# Round 3: learnings from the v3 grade (graded 88; I self-scored 88.3)

Sources:
- [floor16-v3-review.md](floor16-v3-review.md) (the grade)
- [floor16-generator-feedback-v4.md](floor16-generator-feedback-v4.md) (what to fix for v4)

## 16. The self-score is now trustworthy; keep it that way
- **v3 came within 0.5 points of the grade.** The footprint column test, all-fixture drains and the grader's formulas closed the 16-point v2 gap.
- **Keep every check exactly as it is.** Change only what the feedback lists ("keep v3 exactly").

## 17. "Blocked by geometry" needs a design attempt, not just an explanation
- In v3 I said the west end couldn't take 3 units, because C4 and C13 sit 1.5 m apart in the first unit's back zone. The grader asked again.
- **The fix was a room arrangement I hadn't tried: a closet strip at the corridor end of the kitchen column.**
  - Back-zone columns (8.0–8.8 m from the glass) can then sit in a closet, even when the kitchen is under 3 m wide.
  - This lets 5.5 m wide units work wherever an interior column row crosses the back of the unit.
- **Lesson:** when a column blocks a split, add a room arrangement that gives the column an allowed home (closet, wardrobe, wide room), then let the optimiser try it. Only after that, report "impossible".

## 18. Corners: choose the façade that's closest to the core
- **The north-east corner was a shallow (6.43 m) north-façade unit.** Its two baths and kitchen had to spread along the glass, away from the core, so drains ran up to 10.1 m.
- **Turned to belong to the east band instead, it's 9 m deep.** Both baths can stack at its inner end beside the east core.
  - Drains then pass, and the unit drops to the 950-sf range.
  - The east band then still fits 3 one-beds plus the corner.
- **Rule:** for each corner, try both façades it could belong to. Keep the one whose inner end is closest to a core face.
- **Two-bed corners can be narrower:** corner bedroom 3.2 m + living 3.0 m + second bedroom 2.5 m, about 8.8 m. The second bedroom still meets the 70 sf / 7 ft rule.
- **The north-west corner is far from both cores in either orientation.**
  - Its nearest core face is about 5 m away vertically before any horizontal run, so a second bath can't get under 8 m by room centre.
  - Say so with the measured number. Don't let it bloat the corner to 1,250 sf to chase the drain.

## 19. Unit count: check the arithmetic per stretch before promising it
- **The grader's 28-unit target assumed several splits.** Each one either works or is blocked by the 500-sf minimum:
  - **West end:** 16.77 m / 3 = 5.59 m. Works with the closet-strip arrangement (+1).
  - **S2 + S3:** 29.2 m with a 10.4 m corner leaves 18.8 m for a deep unit plus two shallow units. The two shallow units need 7.1 m each for 500 sf at 6.55 m deep; 5.5 + 2 × 7.1 = 19.7 m. **Doesn't fit.**
  - **East band:** 19.34 m / 4 = 4.8 m, below the 5.5 m one-bed minimum. **Doesn't fit.** (Moving the north-east corner onto the east band keeps 3 one-beds there.)
  - **South deep stretch (S4–S7):** 5 units of about 5.5 m fit with the closet-strip arrangement (+1).
- **So the honest ceiling under the current rules is about 24 units, not 28.** Report the per-stretch arithmetic so the grader can see where the extra units would have to come from. A lower one-bed minimum or a taller floor is a decision for the grader, not for me.
- **Report the fit-out sensitivity:** each extra unit really adds about $55k of kitchen and bath, which this model doesn't count. Show both views.

## 20. Pairing
- **Aim for 85% or more of units with paired wet rooms.** Pair new units' baths back to back across each new demising wall.
- With narrower units there are more demising walls, so let the pairing pass try the new room arrangements too.

## 21. What v4 did with these (self-score 89.9, not yet graded)
- **Units:** 24, up from 22 (20 one-beds and 4 two-bed corners). Average 657 sf; smallest one-bed 529 sf.
  - **West end:** 3 units of 540–543 sf. C4 and C13 now sit in a closet at the corridor end of W1's kitchen column.
  - **South deep stretch:** 5 units of 529–538 sf instead of 4. Interior-row columns sit in kitchen closets; outer-row columns sit in living rooms or wardrobes.
  - **North-east corner:** now on the east glass (E4, 898 sf, 2BR/2BA). Every drain run is 7.9 m or less; v3's N9 reached 10.1 m.
- **Drains:** 23 of 24 units have every wet group at 8 m or less. Only N1 (north-west) still fails: second bath 9.0 m, sink 8.4 m, dishwasher 9.0 m.
- **Owner view:** vs office −$0.029M/yr → 4.4/8 (v3: −$0.046M, 4.1).
  - With $55k fit-out per extra unit carried at 7.15%: −$0.037M/yr. Still better than v3, so the extra units pay off even counting real fit-out.
- **Corners S1, S9 and N1 stay at 1,137–1,163 sf.** Shrinking them to 950–1,050 sf makes their drains fail (tested in v3). No extra unit comes free from the freed glass on those stretches: north 42.5 m − 10.4 m corner = 32.1 m, still only 5 one-beds at ≥5.5 m.
- **I found my own pairing bug.** The v3 "paired" flag counted two baths as paired whenever both touched the shared wall, even when one was at the front and one at the back. The honest v3 figure was lower than the 73% reported.
  - v4 tests baths physically: they must share at least 1 m of wall, lined up.
  - With the bedroom-depth option (C16 into a wardrobe) and a door that can slide within the hall (E4), pairing reaches 20/24 = 83%.
  - The remaining 4 are structural: S3 and W3 sit at the end of odd-length runs. E3's column forces its bath to the south wall, and E4's door needs its hall at the inner end.
- **Lesson:** every flag the score relies on (paired, ok, in wall) must be a geometric test the grader could repeat from the JSON. A logical shortcut is a bug waiting to be found.
