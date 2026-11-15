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
| `harness/` | LangChain `deepagents` harness: one orchestrator, market / interior / aerial-photo subagents, router, metrics, guard and answer middleware | `harness/DECISIONS.md` |
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
cd eval && .venv/bin/mundus-eval preflight
```

```bash
cd eval && .venv/bin/mundus-eval truth
```

```bash
cd eval && .venv/bin/mundus-eval references
```

```bash
cd eval && .venv/bin/mundus-eval run --workers 6
```

The eval measures the harness: 15 tasks x 2 combinations (`combos.yaml`: Sonnet 5.5 or Haiku 5.5 as orchestrator,
Haiku 5.5 workers) x 3 repeats = 90 runs. Comparing memory states is deferred, so every run starts from an empty claim
memory.

- `preflight` refuses to go on unless every place is ingested, every selected pano is captioned, every search document
  is embedded, search answers in `hybrid` mode and no aerial facts are served. `run` repeats this check.
- `truth` computes ground truth from the World API. `references` has Claude Fable 5.2 write visual references from the
  actual photos; stored captions are never used as the reference, because the agent reads those same captions.
- `run` executes the runs several at a time. Each run gets a private claim memory keyed by its run id
  (`X-Claim-Scope: run`), so runs do not see each other's claims and the shared memory is not touched. A stopped
  suite continues with `--resume <results folder>`.
- The report is `eval/data/results/<time>/report.md`: pass rate overall and by group, tokens, cost, wall-clock time,
  time to first action, tool calls, tool error rate and claims written per combination, and passes out of 3 per task
  with a `flaky` mark. Six tasks are graded by code and nine by Claude Fable 5.2.
- Wall-clock figures come from overlapping runs, so read them as a comparison between combinations.

## Deploy

On a fresh Ubuntu 24.04 VM with ports 80 and 443 open:

```bash
git clone https://github.com/siddhak711/mundus && cd mundus && bash scripts/deploy/vm_setup.sh
```

The script asks for the keys once, ingests the 15 places, and starts both services behind HTTPS.

Without SSH (Google Compute Engine): pass `scripts/deploy/vm_boot.sh` as the instance's `startup-script` metadata
and the keys as `mundus-<KEY>` metadata attributes. It runs the same setup at boot and logs to the serial console.

---

# Atlas

A site-model viewer for every property in the HackPrinceton CoStar kit: 3,346 in Houston and
1,857 in Los Angeles. Pick a city, pick a property, and Atlas builds a 3-D model of it from three
sources that describe the same address.

| Source | What it contributes |
|---|---|
| CoStar | The property record, tenants by floor since the building opened, space for lease with asking rents, sales, apartment floor plans, home listings |
| Vexcel | Aerial photo, measured building heights, building footprints, roof facts, angled views, object detection |
| Matterport | Interior scans shown as cut-open models, with measured area and room types |

## Run it

1. Unzip the CoStar kit into `raw/costar/`.
2. Put the API keys in `.env` (see `.env.example`).
3. Install and build the index, then start the server:

```bash
pip install requests shapely pillow numpy tifffile imagecodecs anthropic
python pipeline/build_index.py
python server.py
```

Open http://localhost:5190.

## How it is put together

- `pipeline/build_index.py` reads the CoStar kit once and writes `data/index/<city>.json` plus one
  detail file per property.
- `pipeline/twin.py` builds a property's site model the first time it is opened (about three
  seconds) and caches it under `cache/`. `pipeline/vexcel.py` and `pipeline/matterport.py` are the
  API clients.
- `pipeline/agent.py` is Ask Atlas: Claude with tools that search the records, measure from the
  aerial survey, read the scans and drive the page.
- `server.py` serves the site and those APIs. `web/` is the front end: plain ES modules, three.js
  for the model, Leaflet for the map, no build step.

## What the model does and does not show

- Roofs and ground are the aerial photo. Building sides have no imagery, so they are plain massing.
- Only mapped building footprints are raised; trees stay flat under the photo.
- Scan floors and furniture are textured from Matterport's top-down photo plan; walls are plain.
- A scan is placed on its floor only when its name carries a suite or level number.

`raw/`, `data/`, `cache/` and `.env` are git-ignored: the CoStar data is licensed for the event and
the keys are private.
