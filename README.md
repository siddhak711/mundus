# Mundus

A world context layer for physical places, and an agent harness that answers questions through it.
Built at HackPrinceton Fall 2026 on CoStar market records, Matterport interior scans and Vexcel aerial data
for Los Angeles.

```
frontend (separate)  ──REST──►  backend/   World API: ingestion, SQLite store, REST + MCP, claims memory
                     ──stream─► harness/   deepagents: orchestrator + 3 subagents, /world memory mount
                                eval/      15 tasks, code and model graders, interleaved runner
```

| Folder | What it is | Spec |
|---|---|---|
| `backend/` | Ingests the three data sources for a fixed 15-place evaluation set and serves one World API over REST and MCP | `specs/backend-spec.md` |
| `harness/` | LangChain `deepagents` harness: one orchestrator, market / interior / aerial subagents, router, metrics, guard and answer middleware | `harness/DECISIONS.md` |
| `eval/` | `tasks.yaml` (15 draft tasks), `combos.yaml` (harness combinations), graders, runner, report | this file |
| `shared/predicates.yaml` | The claim predicate vocabulary, read by both backend and harness | |
| `scripts/` | `verify.sh` (lint and tests for all three), `deploy/` (VM setup) | |

## Run it locally

Keys go in `.env` at the repository root (copy `.env.example`). Nothing licensed is ever committed: `data/` and `.env`
are git-ignored.

```bash
./scripts/verify.sh
```

```bash
cd backend && .venv/bin/mundus ingest all
```

```bash
cd backend && .venv/bin/mundus serve --port 8000
```

```bash
cd harness && uv pip install -e ".[serve]" && .venv/bin/langgraph dev --port 2024
```

A smaller run for testing ingests two places only:

```bash
cd backend && .venv/bin/mundus ingest all --places 11104240,4164481
```

Ingestion is resumable: every step skips work already done, so rerun the same command after a failure.

## Backend commands

| Command | What it does |
|---|---|
| `mundus ingest <step>` | `index`, `costar`, `select`, `basics`, `rooms`, `resolve`, `panos`, `panos-defurnished`, `aerial`, `caption`, `cards`, `embed`, `graph`, `verify`, or `all` |
| `mundus serve` | World API: REST under `/v1`, MCP at `/mcp/`, health at `/healthz`, OpenAPI at `/docs` |
| `mundus claims reset\|snapshot\|list-snapshots` | Empty or restore agent memory between evaluation runs |
| `mundus snapshot` / `mundus restore <file>` | Pack or unpack the database and images (laptop fallback) |
| `mundus qa captions` | HTML sheet of 30 random captions next to their photos |
| `mundus qa caption-lengths -n 5` | Captions the same panos at four lengths and reports words, tokens and seconds for each |
| `mundus warmup --queries file.txt` | Pre-embeds demo queries and caches the market schema |

Caption length is set with `CAPTION_DETAIL` (`brief`, `standard`, `deep`, `max`; default `deep`, 280 to 400 words).
Every model call the backend makes is logged with its token counts and reported at `GET /v1/stats`.

## Evaluation

```bash
cd eval && .venv/bin/mundus-eval truth
```

```bash
cd eval && .venv/bin/mundus-eval references
```

```bash
cd eval && .venv/bin/mundus-eval seed
```

```bash
cd eval && .venv/bin/mundus-eval run
```

`truth` computes ground truth from the World API. `references` has Claude Fable 5.2 write visual references from the
actual photos. `seed` builds the warm-memory snapshot. `run` executes every task for every combination in
`combos.yaml`, three times each, sequentially and interleaved, resetting agent memory before each run, and writes
`eval/data/results/<time>/report.md` with pass rate, tokens in and out, cost, wall-clock time, time to first action
and tool calls per combination. Six tasks are graded by code and nine by Claude Fable 5.2.

## Deploy

On a fresh Ubuntu 24.04 VM with ports 80 and 443 open:

```bash
git clone https://github.com/siddhak711/mundus && cd mundus && bash scripts/deploy/vm_setup.sh
```

The script asks for the keys once, ingests the 15 places, and starts both services behind HTTPS.
