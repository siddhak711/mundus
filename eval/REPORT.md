# Mundus harness eval: results

Run on Nov 15, 2026, 02:27 to 02:40 UTC. Aggregates only: answers, truth values and photos stay in the git-ignored
`eval/data/results/20261115-022709/`.

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
