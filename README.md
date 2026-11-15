# Census

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

## Built with

**deepagents** · **LangGraph** · **CoStar data** · **Matterport** · **Vexcel** · **Claude (Anthropic)**

| Part | What it comes from | Built with |
|---|---|---|
| Map of LA offices | Every commercial property in the CoStar kit (location, year built, size, floors, vacancy), screened against LA's Adaptive Reuse Ordinance 188,793 | CoStar data, OpenStreetMap, Leaflet |
| Outside of the building | Vexcel surface heights, aerial photo, structure footprints, parcel and trees; floors coloured by CoStar availability and tenancies; facade walls are drawn, not data | Vexcel, CoStar data, three.js |
| Office as scanned | Matterport 360° photos (walk) and MatterPak mesh (dollhouse); building facts from CoStar | Matterport, CoStar data, three.js |
| Empty floor | Derived from the Matterport scan: interior walls dropped, window walls baked from the photos, columns and core found in the mesh | Matterport, three.js |
| Homes | Floor-16 layout study (`scripts/apartment_study_v4.py`) fitted to the scan's shell; CC0 finishes, drawn furniture | Matterport, Poly Haven, three.js |
| Compliance | LA Ordinance 188,793 and the 2025 California Building Code, measured on the layout (`docs/floor16-research.md`) | public code |
| Cost-benefit | Rents fitted to CoStar apartment listings within 2 km; costs from AECOM 2024 and LA Planning | CoStar data, public reports |
| Structure | Columns detected in the Matterport mesh, hidden ones inferred from the grid | Matterport |
| Agents and Ask Census | Orchestrator plus layout, compliance and cost subagents (`harness/`), on Claude Sonnet 5.5 and Haiku 5.5; the World API serves CoStar records and Matterport photos captioned by Claude; traces in LangSmith | deepagents, LangGraph, Claude, LangSmith |

The walkthrough's review page (`web/walkthrough/review.html`, after Submit) ends with the same table.

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

The script asks for the keys once, ingests the 15 places, builds the Census site's index from the same CoStar kit,
and starts three services behind HTTPS on one hostname:

| Path | Service | Access |
|---|---|---|
| `/v1/*`, `/mcp/`, `/healthz`, `/docs` | World API (`mundus-world`, port 8000) | Bearer `WORLD_API_TOKEN` |
| `/agent/*` | Agent server (`mundus-harness`, port 2024) | Header `X-Agent-Token: <AGENT_TOKEN>` |
| everything else | Census site (`mundus-site`, `server.py`, port 5190) | Public. Ask Census calls the agent server inside the VM, so anyone with the URL can spend model credits |

On a VM set up before the site was added, pull and rerun the same script: every step skips work already done.

Without SSH (Google Compute Engine): pass `scripts/deploy/vm_boot.sh` as the instance's `startup-script` metadata
and the keys as `mundus-<KEY>` metadata attributes. It runs the same setup at boot and logs to the serial console.

### Census on GitHub Pages

Pages serves this repository's `main` branch; the root `index.html` opens `web/`. Pages is static, so on github.io
`web/js/config.js` points the site at `server.py` on the VM (`https://<vm-host>/census`) for the CoStar index, site
models, walkthrough floors and the agent. Nothing licensed is in the repository. Set the VM up with
`scripts/deploy/vm_census.sh` (below).

### Census on Vercel

Vercel serves the site's own files (`web/`, about 50 files). Everything else is proxied by the rewrites in
`vercel.json` to `server.py` on the VM (`https://<vm-host>/census`): the CoStar index under `/data/`, site models
(`/api/twin`, `/cache/`), scans, angled photos, the agent (`/api/agent`) and the baked walkthrough floors. The VM is
the right home for those: the apartment agent reads the floor files that `server.py` prepares, and a walkthrough
floor is about 500 MB. Nothing licensed is uploaded to Vercel.

```bash
bash scripts/deploy/vm_census.sh
```

```bash
bash scripts/deploy/vercel_deploy.sh
```

The first runs on the VM (index, conversion screen, walkthrough bakes, `mundus-census` service, Caddy route); the
second from any machine logged in to Vercel.

## Run it

1. Unzip the CoStar kit into `raw/costar/`.
2. Put the API keys in `.env` (see `.env.example`).
3. Install and build the index, then start the server:

```bash
pip install requests shapely pillow numpy scipy opencv-python-headless tifffile imagecodecs
python pipeline/build_index.py
python server.py
```

Open http://localhost:5190.

Ask Census needs the World API (port 8000) and the harness's agent server (port 2024) running, as in
"Run it locally" above. `server.py` finds them through `WORLD_REST_URL` and `HARNESS_URL` in `.env`, which default
to those two ports. Set `AGENT_TOKEN` only when the agent server sits behind the VM's Caddy. Without the agent
server the rest of the site still works and the drawer says the agent is off.

## How it is put together

- `pipeline/build_index.py` reads the CoStar kit once and writes `data/index/<city>.json` plus one
  detail file per property.
- `pipeline/twin.py` builds a property's site model the first time it is opened (about three
  seconds) and caches it under `cache/`. `pipeline/vexcel.py` and `pipeline/matterport.py` are the
  API clients.
- `pipeline/ask.py` is Ask Census: a bridge to the Census deep agent in `harness/`. Each question is one run on a
  LangGraph thread, so the agent server keeps the conversation. The bridge turns the harness's stream events into
  the drawer's activity trail, opens the property the agent focuses on, and numbers the answer's claim citations.
  The agent knows only the Los Angeles places ingested into the World API, not the whole kit.
- `server.py` serves the site and those APIs. `web/` is the front end: plain ES modules, three.js
  for the model, Leaflet for the map, no build step.

## Office to housing (`/city/`)

A map of every Los Angeles office building in the kit, coloured by whether it could become housing. Picking a building
opens its 3-D model in Census: each floor is coloured by tenants and available space, the Conversion tab holds the
screen, and a floor with a walkthrough is painted blue with a "Walk floor N" pin, so clicking it goes inside. It runs
on the same index as the rest of Census:

```bash
python pipeline/build_index.py raw/costar
```

```bash
python pipeline/conversion.py
```

Optional, once: build every candidate's 3-D model ahead of time, so even a first open is instant (about 1.5 s
saved per building; already built models are skipped). Models built before trees were added are rebuilt, so run it
again after pulling:

```bash
python -m pipeline.prewarm
```

Then open http://localhost:5190/#/los-angeles/office-to-housing (the old /city/ address redirects there), or follow
"LA office to housing" in the top bar. The map is a view inside Census's page, so opening a building never loads a new
page: the map stays up while the 3-D model is drawn behind it, then zooms away as the model fades in. `conversion.py` writes
`data/conversion/los-angeles.json` and one floor file per office building in the City of LA. The page also starts
loading a building's model in the background when the pointer rests on it, when it is focused, or when a search
narrows to three buildings or fewer, so the click only has to draw it.

| Dot | Meaning |
|---|---|
| Green | Strong candidate: eligible by right and a fit score of 60 or more |
| Amber | Eligible by right, weaker fit |
| Purple | Eligible with review: 5 to 15 years old, or in a manufacturing zone |
| Grey | Not a candidate: not an office, too new, in a zone the ordinance does not cover, or outside the City of LA |

- Eligibility follows the Citywide Adaptive Reuse Ordinance (Ordinance 188,793, in effect Feb 1, 2026): an office
  building inside the City of LA, at least 15 years old, in a multifamily, commercial, parking or public facilities
  zone. The zone is read from the CoStar record's zoning code; codes the screen cannot read, such as downtown's new
  zoning code, are flagged for a check on ZIMAS.
- Fit (0 to 100) is vacancy (50 points at 30% of the building available), floor plate size (30 points under 20,000 sq
  ft, where most of a floor is near a window) and building class (C 20, B 15, A 5). These are rules of thumb from
  conversion studies, not code.
- A floor is convertible now when half or more of it is listed. Vacancy counts every active lease listing for the
  building (`allSpaces` in the index), each space once, leaving out spaces already pending a lease.
- "Inside the City of LA" is judged from the postal place name. CoStar writes "Los Angeles" for some addresses on the
  city line (8228 Sunset Blvd borders West Hollywood), so check those by hand.
- The kit holds 98 Los Angeles office buildings, not every office in the city.
- Daylight is measured where a building has a Matterport scan of a whole floor:

  ```bash
  python -m pipeline.daylight --walkthroughs
  ```

  This reads each scan's top-down floor plan, outlines the floor plate and measures how much of it lies within 25, 30
  and 35 ft of its edge, and how deep the deepest point is. The 30 ft share then replaces the floor-size guess in the fit
  score. Suite scans are recorded but not measured: their edges are mostly corridor walls. Needs the Matterport keys in
  `.env`. The Oppenheimer Tower's floor 16 measures 67% within 30 ft, deepest point 59 ft.
- Floors with a baked walkthrough are listed in `pipeline/walkthroughs.json` (and their card facts in
  `web/walkthrough/floors.json`): Suite 1600 of the Oppenheimer Tower, and the whole-floor scans of the top candidates,
  3415 Sepulveda Blvd floor 10, The Tower (10940 Wilshire) floor 17 and The Launch at Airport Center floor 3. Bake one
  with `python -m pipeline.bake <scanId>` (licensed, git-ignored, into `web/walkthrough/floors/<scanId>/`; see
  `web/walkthrough/README.md`). The walkthrough links back to the building's 3-D model. The 3-D model needs `VEXCEL_API_KEY` in `.env`.

## What the model does and does not show

- Roofs and ground are the aerial photo. Building sides have no imagery, so they are plain massing.
- Only mapped building footprints are raised; trees stay flat under the photo.
- Scan floors and furniture are textured from Matterport's top-down photo plan; walls are plain.
- A scan is placed on its floor only when its name carries a suite or level number.

`raw/`, `data/`, `cache/` and `.env` are git-ignored: the CoStar data is licensed for the event and
the keys are private.
