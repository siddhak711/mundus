# Floor-plan evals: conversion agent, floor 16 (10880 Wilshire)

15 Nov 2026. Aggregates only; layouts, grades and traces sit in git-ignored `eval/data/floorplan/` and in LangSmith
project `mundus-floorplan-eval` (every run tagged `floorplan`, `knob:<name>`, with grade feedback `grade_total_v2`).

## Setup

| | |
|---|---|
| Agent | merged conversion agent (`harness/mundus_harness/conversion`): orchestrator and layout on Sonnet 5.5, compliance and cost on Haiku 5.5 |
| Floor | scan cEvQ8q5GKZd, prepared by `pipeline/floorprep.py` (17 low-confidence column candidates, 2 core blocks, 4 assumed exits) |
| Runs | 3 per configuration, cold memory, each in its own copy of the floor folder |
| Grader | `conversion-v2` (frozen), `eval/mundus_eval/floorplan/conversion.py`: recomputes every value from the layout; never reads the agent's flags |
| Not graded | baths, kitchens, fixtures, doors, stairs, fire and sound: the agent does not draw them yet |
| Missing input | `market.md` (needs the CoStar kit), so the agent's cost step reports rents as unknown; money is scored by the frozen model |

## Headline

| | baseline | K1: checker fixes |
|---|---|---|
| Grade, mean (min to max) | 78.2 (73.3 to 82.4) | **81.6 (79.5 to 83.3)** |
| Hard breaks per run | 1.0 | **0.33** |
| Units the agent called passing that fail (per run) | 2.7 | **0.3** |
| Units | 16.3 | 15.7 |
| Cost / time per run | $0.21 / 2.6 min | $0.22 / 2.5 min |

The grade gain (+3.3) is inside the baseline's run-to-run range (9 points), so with 3 runs it is not proven. The
honesty gain is: the agent's report of passing units went from 2.7 wrong per run to 0.3.

## What the traces showed, and what was changed

1. **The agent's own checker passed failures the grader found.** In all 3 baseline runs the agent reported every
   unit passing. The grader found (a) bedrooms over column candidates in every run: the checker tested walls only;
   (b) units whose only route to an exit runs through other apartments or through gaps too narrow to walk: the
   checker walked across the whole plate, units included. Traces showed the agent stopping as soon as the checker
   said 0 fail, so it never saw these.
   **Fix (K1, `geometry.py` check_layout):** a bedrooms-clear-of-columns check; exit routes only over open floor
   at least 0.9 m (36 in) wide, with the door on a wall of the unit that faces it. With K1 the checker and the
   grader agree unit for unit on 4 of 6 graded layouts; the other 2 differ on one marginal passage each (0.6 to 0.9 m
   wide, where the checker's 5 cm grid and the grader's exact geometry round differently). After K1 every run
   iterated until the checker reported 0 failures.
2. **Draft choice is fine.** In every run the agent wrote the draft the grader also scores best. Larger drafts it
   rejected (18 to 19 units) put bedrooms on facade the scan never saw.
3. **Tested and rejected without spending runs:** redrawing the agent's best drafts at a fixed depth (8.5 to 9.5 m)
   or re-splitting them into narrow one-beds, with the agent's own tool and no model. Fixed depth put walls on
   columns (4 to 6 hard breaks); narrow one-beds added units but not rent, because rent per metre of facade is about
   the same for a one-bed ($563) and a two-bed ($573) under the money model.

## Grader corrections made while calibrating (each found by comparing grader and checker on the same layout)

| Version | Change | Why |
|---|---|---|
| v0 to v1 | columns as their real rectangles, not squares; exit route judged by the unit's outline, not its entry point | false fails on C11/C12; corner units read as disconnected |
| v1 | walls only a hard break when they cut 10 cm into a column | a 4 cm graze on a guessed facade-corner column zeroed a run |
| v2 | 0.9 m minimum passage; door reach 0.5 m; bedrooms on unscanned facade scored unknown (half), not failed; bedroom-column overlap over 0.1 m2 | grader and checker disagreed only at these margins |

All runs were rescored under v2; LangSmith carries both the original and the v2 feedback keys.

## Where the remaining points are

Mean points lost per K1 run: unit size vs market about 5, buyer yield about 5, owner view about 3, the rest under 1.
- **Money (about 8):** the frozen model gives 3.5% buyer yield against 7.15% needed. No layout fixes that; it needs
  real rents (the CoStar market summary) and the owner's office-lease alternative.
- **Unit size (about 5):** the criterion applies the 500 to 700 sf one-bed band to every unit, so it mostly
  penalises two-beds, which earn the same per metre of facade. Chasing it would optimise the metric, not the
  building. Next grader version should use a band per unit type.
- **Unused facade:** 2 of 3 K1 runs left 26 to 35 m of the north facade empty because the scan never saw it. Units
  there would be 18 to 19 instead of 16; whether that facade is glass needs the photos or a floor plan.

## Next

1. Per-type size bands in the grader (v3), rescore.
2. Give the agent the CoStar market summary, so rent and cost are its own reasoning, then grade money properly.
3. Decide the unscanned north facade (photo check), which is worth 2 to 3 units.
4. Then the schema knob: rooms, baths and fixtures in the agent's output, so the full rubric 1.0 applies.
