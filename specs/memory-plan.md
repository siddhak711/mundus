# Memory plan: writing, upkeep and dreaming

Status: draft for discussion, Nov 15 2026. Nothing here is built yet.

## 1. What vendors recommend

Sources were checked on Nov 15 2026. The OpenAI and xAI pages could not be fetched from this session, so those rows
rest on search snippets and are one notch less certain. Confidence: H high, M moderate, L low.

| Question | LangChain | Anthropic | OpenAI | xAI |
|---|---|---|---|---|
| Kinds of memory | Semantic (facts), episodic (past runs), procedural (prompts, skills). Profile (one document updated in place) or collection (many small items) (H) | Many small focused files plus a capped index that is always loaded; topic files read on demand (H) | Structured profile plus free-text notes, each with `last_updated` (M) | Per-bot memory tied to the bot's role; xAI argues against one merged memory (M) |
| When to write | "For most applications, the hot path is sufficient." Background jobs only for latency or quality across many runs (H) | During the task, into files ("assume interruption") (H) | During the run into session notes, then promoted at session end (M) | Grok Build: during the session, plus `/flush` (M) |
| Offline consolidation ("dreaming") | Do-it-yourself only: a consolidation deep agent run by cron. The cron interval must equal the lookback window (H). LangMem: debounced reflection, 30 to 60 minutes after the last message (H) | Managed Agents Dreams: an async job that reads one store and up to 100 sessions and writes a **new** store. The input store is never changed; you review it, then switch to it or discard it (H) | ChatGPT "Dreaming" (June 2026) rewrites memories over time, for example a planned trip becomes "the trip happened" (M). Codex Memories: phase 1 extracts in parallel, phase 2 consolidates serially under one global lock (M) | Grok Build `/dream`: merges notes into topic files, also runs in the background (M). Nothing published on how consumer Grok consolidates |
| Conflicts | LangMem leaves them to the model, which rewrites in place with no versions. Deletes are off by default (H) | Dreaming cookbook: keep the current value and record what it replaced with dates and sources; otherwise mark CONFLICT and "do not guess" (H) | The newer note wins; the session overrides global memory (M) | Current instructions override saved notes (M) |
| Forgetting | Store TTL that resets on every read, the only built-in mechanism (H) | Delete files nobody has read in a long time; prune before a store fills (H) | Automatic prioritisation moves less-used memories to the background; Codex skips memories older than `max_unused_days` (M) | Users delete memories one at a time (M) |
| Safety | Memory "is not hidden system instructions"; prefer verified evidence over it (H) | Memory is a prompt-injection path. Agents mount it read-only; only the dream job writes (H) | An eval checks that consolidation invents nothing (M) | A team bot's learning needs owner approval (M) |

Measured results, all from the vendors' own internal evals:

| Result | Source | Confidence |
|---|---|---|
| Memory tool plus context editing is 39% better than baseline on agentic search; context editing alone cuts tokens 84% over 100 turns | Anthropic blog, Sep 29 2025 | H that they published it, L on transferability |
| Sleep-time compute: about 5x less test-time compute at equal accuracy; up to +13% and +18% accuracy; 2.5x cheaper per query when queries share a context | Letta and Berkeley, arXiv 2504.13171 | M (abstract only) |
| Harvey: about 6x completion rate with Dreams | A customer's claim, reported by Anthropic | L |

The industry has settled on one pattern: write small typed facts during the run, consolidate offline in a sandboxed
job, keep the output versioned and reviewable, inject a compact index, and treat memory as untrusted input. LangChain
and LangMem are the outliers that rewrite memory in place with a model. That approach is wrong for Mundus (see 3).

## 2. What Mundus has today

| Kind | Where | Written by | State |
|---|---|---|---|
| Semantic | `claim` table (`backend/mundus_world/service/claims.py`) | Subagents and the orchestrator, in the hot path, through `put_claim` | Strong. Every claim needs evidence, the id is a hash of the fact, merges are decided by rule on evidence rank, every change is kept, staleness is tracked through evidence hashes |
| Index | `card.md`, rendered from claims; the router reads its `coverage:` line | No one: it is generated | Fills the role of the "always loaded index" |
| Procedural | `/memory/AGENTS.md`, a shared writable file (`harness/mundus_harness/graph.py` line 75) | Any agent: deepagents' `MemoryMiddleware` tells the agent to "update memory promptly" with `edit_file` | Nothing curates it. **Problem, see below** |
| Episodic | None. `/runs/<id>/notes` sits in `StateBackend` and dies with the thread; `langgraph dev` keeps threads in memory only | | Missing |
| Forgetting | 7-day TTL on `market.*`, evidence-hash staleness, `synthesis.*` goes stale when a parent does | Rules | Good for a static world |
| Disputes | Status `disputed` | Rules | Never settled unless a later write breaks the tie |
| Near-duplicates | The spec defines a `similar` hint (Jaccard 0.8); it is not built | | Missing |

**Problem: procedural memory leaks across eval runs (high confidence it can happen, unknown whether it has).**
`/memory/` is denied neither for writes nor per run, and the middleware prompt tells agents to write to it. The 90
parallel "cold" runs share one `AGENTS.md`, so a lesson written in one run reaches later runs. It is also an injection
path: anything an agent reads (a caption, a CoStar text field) could end up in every future system prompt. Check
`data/memory/AGENTS.md` on the VM. If it holds anything beyond the header line, the cold numbers in `eval/REPORT.md` are
not fully cold.

## 3. Design choice: dreaming adds claims; it never rewrites them

The usual counterargument: with 15 places and data that changes only at ingest, "dreaming" mostly amounts to
precomputing claims offline. A one-off seeding job would do the same. That is largely right, and it is the main
reason to build it: the Letta result is strongest exactly when the context is fixed and queries are predictable,
which is the Mundus case. The design should therefore be judged as offline precompute plus upkeep, not as a
cognitive-sounding feature.

Rules:
1. The dream job writes only through `put_claim` and `invalidate_claim`. Backend validation (known evidence ids,
   fixed predicates, rank rules) then blocks invention structurally. No model ever edits a claim's text in place, so
   the audit trail survives. This rejects LangMem's in-place rewrite, and the ChatGPT dreaming complaints (memories
   silently revised or dropped) are the reason.
2. Output goes to a staging scope, `dream:<id>`, and is promoted afterwards. This is the Anthropic Dreams pattern:
   the input stays unchanged, the output is a new version. The `scope` column and `claim_snapshot` already exist, so
   this costs little.
3. Disputes: re-read both evidence items with `get_evidence` and decide on evidence. If the evidence does not settle
   it, leave the claim `disputed` with a `note.` explaining why. Never guess (the Anthropic cookbook rule).
4. Locking: one dream per place at a time. Claims are partitioned by place, so a per-place lock is enough. Codex uses
   one global lock, but it has no natural partition.
5. Agents keep reading memory through `/world`, which is read-only. Only the dream job and the backend write.

## 4. The plan

### Phase 0. Fix procedural memory (half a day)
- Mount `/memory/` read-only for every agent (`FilesystemPermission` deny write), or route it per run when
  `claim_scope_run` is on.
- `AGENTS.md` changes only through phase 4, with human review.
- Add a test that an agent's `edit_file` on `/memory/AGENTS.md` is refused.

### Phase 1. Record episodes (half a day)
After each run, append one episode to a new `episode` table in the backend: run id, question, place id, route,
facets needed and missing, claim ids cited, which caps were hit, tool errors, and the grade when the eval supplies
one. This is the input the dream job needs. It replaces raw transcripts and avoids depending on `langgraph dev`
keeping threads.

### Phase 2. Rule-based upkeep, no model (1 day)
`mundus claims maintain [--place]`, run after every ingest and before every dream:
- `refresh_stale` across all places and scopes. Today it runs only on reads.
- Build the near-duplicate pass (Jaccard 0.8 on `note.*` statements per subject). Merge only exact duplicates;
  report the rest.
- Find `note.*` claims whose wording matches a typed predicate, and report them to the dream job.
- Report per place: coverage, open disputes, stale counts.

### Phase 3. The dream job (2 to 3 days)
A second graph in `harness/langgraph.json`: a deep agent that reuses the three subagents, uses Haiku 5.5 workers, and
gets more model calls than live runs. The cap is the largest live failure: 19 of 32 failed runs ended at the
subagent cap.

Per place, in this order:
1. **Settle**: open disputes, as in rule 3.
2. **Promote**: rewrite `note.*` claims as typed predicates when one fits, then `invalidate_claim` the note with
   `superseded_by`.
3. **Fill**: for each facet below `fresh`, run the matching subagent offline. This is the sleep-time compute part.
4. **Anticipate**: write `synthesis.*` claims for the questions that episodes show are asked and that failed or
   were expensive. Examples: the largest room per place, rooms without photos, tenancy counts. Each one uses
   `derived_from`, so it goes stale when a parent does.

Triggers, cheapest first:

| Trigger | When |
|---|---|
| After ingest | Evidence hashes changed, so staleness and re-verification are due |
| Debounced per place | N new episodes on a place, or 30 minutes after the last one (LangMem `ReflectionExecutor` pattern) |
| Nightly cron | Over episodes since the last run. Interval equals lookback, per LangChain |
| Manual | `mundus dream --place <id>` |

Promotion gate. Promote automatically when all of these hold, otherwise hold for review:
- zero backend validation errors
- no claim that conflicts with one of higher rank
- on a sample of new claims, a Fable judge confirms that the cited evidence supports the statement (the
  non-invention check)

Cost estimate (low confidence): a cold Haiku-orchestrated run costs $0.07 and covers one question. A full fill of four
facets for 15 places is probably 15 to 60 subagent tasks, about $1 to $5 per complete dream. It needs measuring.

### Phase 4. Learned procedural memory (1 day, optional)
A weekly job reads episodes and the eval report and proposes changes to `AGENTS.md`, or to subagent prompts, as a
diff for review. It never writes them directly. LangMem's prompt optimizer is the reference design. Hold this until
phases 0 to 3 are measured: prompt edits change everything at once and are hard to attribute.

### Phase 5. Measure it (1 day)
The memory comparison was deferred in the current eval. Run three arms on the frozen suite:

| Arm | Memory at start |
|---|---|
| cold | empty (already measured) |
| warm-hot | snapshot after one pass of hot-path writes (`mundus-eval seed`) |
| warm-dream | warm-hot plus one dream |

Leakage: if the dream reads episodes from the same 15 tasks it is then tested on, it can store the answers. Split the
suite. Seed and dream on one half; test on the other half. Or test on reworded questions about the same places.

Metrics to add to the report: `card_hit` rate, cost and model calls per run, pass rate, the non-invention rate of
dream claims, and disputes settled correctly.

## 5. Decisions needed

| # | Decision | Recommendation |
|---|---|---|
| 1 | Promote dream output automatically or always review it | Automatic behind the gate in phase 3; review only what the gate holds |
| 2 | May the dream fill facets nobody has asked about, spending tokens before any question | Yes for 15 places, because cost is bounded. Revisit if the deep place set grows |
| 3 | Is `AGENTS.md` hand-written only, or learned through phase 4 | Hand-written until phase 5 numbers exist |
| 4 | How to keep the eval free of leakage: split the suite or use reworded questions | Split: it is simpler to defend |
| 5 | Where the dream runs: as a LangSmith cron on the deployment, or as a systemd timer on the VM | VM timer: the deployment runs `langgraph dev`, which has no cron |
