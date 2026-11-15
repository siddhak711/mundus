# Mundus harness eval: baseline and three improvement iterations

Run on Nov 15, 2026, 02:27 to 04:20 UTC. Aggregates only: answers, truth values and photos stay in the git-ignored
`eval/data/results/`. Each run is the same frozen suite: 15 tasks x 2 combinations x 3 repeats = 90 runs, 6 at a time,
every run starting from an empty private claim memory, graded by code (6 tasks) or Claude Fable 5.2 (9 tasks).

## Result

| | Baseline | Iteration 1 | Iteration 2 | Iteration 3 |
|---|---|---|---|---|
| Pass rate, both combinations pooled | 64.4% (58 of 90) | 67.8% (61) | 80.0% (72) | 81.1% (73) |
| Pass rate, Sonnet 5.5 orchestrator | 68.9% | 64.4% | 80.0% | 84.4% |
| Pass rate, Haiku 5.5 orchestrator | 60.0% | 71.1% | 80.0% | 77.8% |
| Failed runs with no citations at all | 19 | 11 | 4 | 3 |
| Tool calls that failed (Sonnet / Haiku) | 15.3% / 10.3% | 9.6% / 10.6% | 2.9% / 2.4% | 2.2% / 4.3% |
| Tokens per run (Sonnet / Haiku) | 838k / 696k | 573k / 561k | 404k / 413k | 401k / 394k |
| Model calls per run (Sonnet / Haiku) | 25.5 / 22.1 | 22.2 / 20.9 | 15.6 / 16.0 | 15.0 / 15.4 |
| Cost per run (Sonnet / Haiku) | $0.28 / $0.07 | $0.29 / $0.06 | $0.20 / $0.04 | $0.20 / $0.04 |
| Agent cost for the 90 runs | $16.01 | $15.63 | $11.00 | $10.81 |
| Median wall-clock per run (Sonnet / Haiku) | 45.8 s / 39.7 s | 40.9 s / 41.6 s | 42.1 s / 38.4 s | 38.4 s / 39.7 s |
| Runs that crashed | 0 | 0 | 3 | 1 |

What is established and what is not:

- **Baseline to iteration 3 is a real gain**: +16.7 points pooled, against a noise band of about 13 points for 90
  runs each. Cost per run fell 32% and tokens per run roughly halved at the same time.
- **Almost all of it came from iteration 2.** Iteration 1 alone (+3.4 points) and iteration 3 alone (+1.1 points) are
  inside the noise.
- **The two orchestrators are not distinguishable** in any run. The Haiku orchestrator costs about a fifth as much.
- Repeats of one task are not independent, so the true noise band is somewhat wider than stated.

## Pass rate by group

| Group | Baseline (S / H) | Iteration 1 | Iteration 2 | Iteration 3 |
|---|---|---|---|---|
| Retrieval | 73% / 60% | 67% / 73% | 87% / 87% | 80% / 93% |
| Cross-building | 87% / 73% | 87% / 80% | 100% / 93% | 100% / 93% |
| Physical reasoning | 47% / 47% | 40% / 60% | 53% / 60% | 73% / 47% |

## Per task (passes out of 6, both combinations)

| Task | What it asks | Baseline | It. 1 | It. 2 | It. 3 |
|---|---|---|---|---|---|
| R1 | Count of tenancies at one building | 4 | 6 | 5 | 6 |
| R2 | Asking price, and that no building is recorded | 6 | 4 | 4 | 5 |
| R3 | Space with the largest room and its area | 5 | 5 | 6 | 5 |
| R4 | Home list price and bedrooms | 5 | 6 | 6 | 6 |
| R5 | Scan count and rooms in the largest scan | 0 | 0 | 5 | 4 |
| A6 | Most and fewest tenancies of three offices | 5 | 5 | 6 | 6 |
| A7 | Which of four places have a pool or spa scan | 6 | 4 | 5 | 6 |
| A8 | Two retail buildings: on the market, sizes | 6 | 6 | 6 | 5 |
| A9 | Most recent sale of three, date and price | 5 | 6 | 6 | 6 |
| A10 | Rank four apartment places by scans, rental listing flags | 2 | 4 | 6 | 6 |
| P11 | Could a room hold a 40-person reception | 6 | 6 | 6 | 5 |
| P12 | Guest room contents, furnished against defurnished | 0 | 0 | 0 | 1 |
| P13 | Warehouse roof structure and loading access | 2 | 3 | 3 | 5 |
| P14 | Rooms without photo coverage | 0 | 0 | 2 | 1 |
| P15 | Structural failure question the data cannot answer | 6 | 6 | 6 | 6 |

## What each iteration changed and what it did

Rule for every change: it may not mention a task, place, scan or expected answer. The suite, rubrics, references and
truth were not touched after the freeze.

### Iteration 1 (`32b4371`): the five changes from the baseline review

| Change | Effect seen |
|---|---|
| A subagent is warned on its last model call; every subagent result carries the claims it wrote | Failures with no citations 19 to 11 |
| Subagent limits 12 to 16 model calls, 30 to 40 tool calls | Subagents still hit the cap in 36 of 90 runs |
| Market table schema placed in the market analyst's prompt | `describe_market` errors gone; `query_market` failures 35% to 17% (Sonnet) |
| Orchestrator answers directly when the data cannot answer | The refusal task (P15) fell from about 1,000,000 tokens to about 45,000 and still passed 6 of 6 |
| Old tool results cleared from subagent history beyond 50,000 tokens | **Hurt.** Subagents fetched the same rooms again. Removed in iteration 2 |

### Iteration 2 (`9bb2ad9`): from call-by-call traces of failing tasks

| Finding in the traces | Change | Effect seen |
|---|---|---|
| `get_space` was cut off at 24,000 characters, so agents opened rooms one at a time and ran out of tool calls | Agent-facing `get_space`, `get_room` and `get_place` return compact views: every room on one line with its photo count, counts of rooms with and without photos, a scan count per place | Tool calls per run 40 to 29 |
| The interior subagent had no tool that lists a place's scans and kept inventing one | It gets `get_place`; `get_space` with a place id says what to call | R5 0 to 5 of 6, A10 4 to 6 of 6 |
| A third of `put_claim` calls were rejected for predicates the vocabulary lacks (`market.listing_count`) | An unlisted predicate in a known namespace is accepted as free-form | `put_claim` rejections 28% to 5% |
| Wrong column names in SQL | The error lists the table's columns | No measurable change: about 16% of `query_market` calls still fail |
| Captions name things that are not in the photo | Prompt: check the photo before describing contents; defurnished views are generated | P12 unchanged at 0 of 6 |

### Iteration 3 (`b27f8f3`): from iteration 2's failures

| Finding | Change | Effect seen |
|---|---|---|
| 3 runs died on a model API error (two results for one tool call). Did not reproduce; cause unknown | Duplicate tool results are dropped before every model call | That error did not recur. One run died on a different error (an empty file read) |
| Answers listed objects not in the photos | Agents state only what is plainly visible; the orchestrator leaves out visual findings under 0.8 confidence; photos shown at 1,024 px instead of 768 | P13 3 to 5 of 6. P12 0 to 1 of 6 |
| A 200-item neighbour list was reported as a total | `get_neighbors` returns true totals by edge kind | R1 5 to 6 of 6 |

## What still fails after iteration 3 (17 runs)

| Task | Failed | Cause |
|---|---|---|
| P12 | 5 of 6 | The Haiku interior subagent still reports objects that are not there (a framed painting, a mirrored closet, stools for chairs, vertical for horizontal blinds), from its own look at the photo as well as from captions. Prompting did not fix it |
| P14 | 5 of 6 | 2 gave the right count and satisfied the grader but cited the scan's record, not a room record, which the task's evidence check requires. 2 declined to commit to the count although the tool returns it. 1 run crashed |
| R5 | 2 of 6 | The question is ambiguous ("largest scan"): the truth uses room count, these runs used floor area |
| R2, R3, A8, P11, P13 | 1 each | A source-record detail that contradicts the reference (R2); a malformed citation marker (R3); a listing status not found (A8); no capacity figure stated (P11); correct answer citing photo evidence where the task requires caption evidence (P13) |

Three of these 17 are answers the grader accepted that failed only a code check on evidence type (P14 twice, P13 once).

## What I would do next

1. Give visual questions to a stronger model than Haiku, or regenerate captions with one. P12 is a perception limit
   of the worker model, not a prompt problem: three different prompt changes moved it from 0 to 1 of 6.
2. Fix the two task defects before the next comparison: R5's wording, and the evidence-type checks on P13 and P14.
3. Find the cause of the crashed runs (4 in 180 across iterations 2 and 3).
4. `query_market` still fails on about 16% of calls.

## Limits

- 45 runs per combination per iteration. Differences under about 20 points for one combination, or about 13 pooled,
  are not established.
- The same 15 tasks were used to find the failures and to measure the fixes. Changes were kept general, but the gain
  on unseen questions is likely smaller than the gain reported here. There is no held-out set.
- The visual reference and the grader are Claude Fable 5.2, the same model family as the agents.
- I checked one of the three visual references (P13) against its photographs. P11 and P12 were read for
  plausibility only.
- Wall-clock times come from 6 overlapping runs.
- Grader and reference cost was not recorded. Agent cost across the four runs was $53.45.
- The world was ingested in the eval session with all 1,250 captions from Claude Haiku 5.5. The deployed VM holds the
  same 15 places with 463 older Gemini captions, and runs none of iterations 2 or 3 until it is updated.
- One grader fix was made after the freeze and before the first full run (`4c437c9`): a claim stating that data is
  absent no longer counts as an invented claim.

---

# Baseline run in detail

## Setup

| Item | Value |
|---|---|
| Runs | 90 = 15 tasks x 2 combinations x 3 repeats, 6 at a time, 13.5 minutes, 0 run errors, 0 grader errors |
| Combinations | `cold-sonnet-haiku`: Sonnet 5.5 orchestrator, Haiku 5.5 subagents. `cold-all-haiku`: Haiku 5.5 for both |
| Memory | Every run started from an empty, private claim memory. Memory comparison is deferred |
| World | 15 places, 108 scans, 1,250 panos all captioned by Claude Haiku 5.5, 1,841 search documents all embedded, hybrid search. No aerial facts; aerial photos only |
| Grading | 6 tasks by code, 9 by Claude Fable 5.2 against a rubric, reference facts and, for 3 tasks, a visual reference Fable wrote from the photographs |
| Code | Branch `claude/wonderful-tesla-0kv9l0`, suite frozen at `de170ce`, grader fix `4c437c9` applied before the full run |

## Headline

| | Sonnet orchestrator | Haiku orchestrator |
|---|---|---|
| Pass rate | 68.9% (31 of 45) | 60.0% (27 of 45) |
| Mean score | 0.72 | 0.62 |
| Runs with valid citations | 86.7% | 71.1% |
| Cost per run | $0.28 | $0.07 |
| Total cost, 45 runs | $12.71 | $3.29 |
| Median wall-clock per run | 45.8 s | 39.7 s |
| Median time to first action | 2.0 s | 1.9 s |
| Mean tokens per run | 838,000 | 696,000 |
| Model calls / tool calls per run | 25.5 / 47.7 | 22.1 / 41.0 |
| Tool error rate | 15.3% | 10.3% |
| Claims written per run | 6.2 | 3.9 |

The 8.9-point pass-rate gap is not a real difference at this sample size: two standard errors is about 20 points, and
the three repeats of a task are not independent. The cost gap is real: the Sonnet orchestrator costs 4 times as much
per run.

## Pass rate by group

| Group | Sonnet orchestrator | Haiku orchestrator |
|---|---|---|
| Retrieval | 73.3% | 60.0% |
| Cross-building | 86.7% | 73.3% |
| Physical reasoning | 46.7% | 46.7% |

## Per task (passes out of 3)

| Task | What it asks | Sonnet | Haiku |
|---|---|---|---|
| R1 | Count of tenancies at one building | 2 | 2 |
| R2 | Asking price, and that no building is recorded | 3 | 3 |
| R3 | Space with the largest room and its area | 3 | 2 |
| R4 | Home list price and bedrooms | 3 | 2 |
| R5 | Scan count and rooms in the largest scan | 0 | 0 |
| A6 | Most and fewest tenancies of three offices | 3 | 2 |
| A7 | Which of four places have a pool or spa scan | 3 | 3 |
| A8 | Two retail buildings: on the market, sizes | 3 | 3 |
| A9 | Most recent sale of three, date and price | 3 | 2 |
| A10 | Rank four apartment places by scans, rental listing flags | 1 | 1 |
| P11 | Could a room hold a 40-person reception | 3 | 3 |
| P12 | Guest room contents, furnished against defurnished | 0 | 0 |
| P13 | Warehouse roof structure and loading access | 1 | 1 |
| P14 | Rooms without photo coverage | 0 | 0 |
| P15 | Structural failure question the data cannot answer | 3 | 3 |

Flaky (neither 0 of 3 nor 3 of 3): R1, A10, P13 on both; R3, R4, A6, A9 on Haiku only.

## Why runs failed

All 32 failed runs were read. Causes, with a run counted once under its main cause:

| Cause | Sonnet | Haiku | Kind |
|---|---|---|---|
| A subagent returned nothing usable, so the orchestrator answered without claims and the answer had no valid citations. 15 of these 19 answers name the 12-model-call cap as the reason | 5 | 14 | Harness |
| Answer had citations but the content was wrong or incomplete (miscounts, a missing rental-listing flag, loading doors missed) | 3 | 1 | Harness |
| Answer listed things that are not in the photographs (a framed painting, stools, trucks in the yard) or misread the defurnished views | 5 | 2 | Harness and captions |
| Question was ambiguous: R5 asks for the "largest scan" and the truth uses room count, while the run chose floor area | 1 | 1 | Task |

Findings behind those numbers:

- **The subagent call cap is the largest single problem.** A subagent reached the cap of 12 model calls in 29 of 45
  runs on each combination (64%). When it does, it returns no result and no claims. The orchestrator then answers
  from graph lookups with raw evidence ids, which the citation check rejects. 19 of the 32 failures are this.
- **Subagents carry most of the cost.** They account for 89% (Sonnet) and 86% (Haiku) of input tokens, at about
  38,000 input tokens per subagent call, because each call resends the growing tool history.
- **A third of `put_claim` calls are rejected**: 152 of 433 (Sonnet) and 85 of 262 (Haiku). `query_market` fails 35% and
  23% of the time. These retries are part of why subagents run out of calls.
- **The refusal task costs as much as any other.** P15 passed 6 of 6, but used about 1,000,000 tokens per run to
  conclude that the data cannot answer.
- **No run was routed as a card hit**, as expected with empty memory. The router and memory reuse are not measured here.

## What to change in the harness, in order of expected effect

1. When a subagent hits its call cap, return what it has found and written so far instead of nothing.
2. Raise the subagent cap from 12, or cut the calls needed: give the market analyst the table schema up front (it
   spends calls on `describe_market`), and return clearer `put_claim` errors so one retry is enough.
3. Let the orchestrator write claims for facts it reads directly when a subagent fails, so its answer can be cited.
4. Stop early on questions the data cannot answer (P15) before delegating.
5. Trim tool results kept in subagent history; 38,000 input tokens per call is mostly resent tool output.

## Limits of this eval

- 45 runs per combination. Differences under about 20 points are not established.
- R5 is ambiguous and failed 6 of 6. Without R5 the pass rates are 73.8% and 64.3%.
- The visual reference and the grader are Claude Fable 5.2, the same model family as the agents under test.
- I checked one of the three visual references (P13, the warehouse) against its photographs; it matched. P11 and P12
  were read for plausibility only.
- Wall-clock times come from 6 overlapping runs. Use them to compare the two combinations, not as absolute latency.
- The data has no doors, stairs or structural information. P15 is scored on declining to invent.
- Grader and reference cost was not recorded. Agent cost was $16.00 for the 90 runs.
- This world was ingested in the eval session with all captions from Claude Haiku 5.5. The deployed VM holds the same
  15 places with 463 older Gemini captions, and still serves aerial facts until it is updated.

## Changes made after the suite was frozen

One, before the full run: the forbidden-claim check counted "there is no structural data on beams" as an invented
claim. Claims that state an absence are now excluded (`4c437c9`). Found in the 4-run smoke test. No task, rubric or
reference changed after the freeze, and no run was repeated.
