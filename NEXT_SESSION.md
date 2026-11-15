> Superseded on Nov 15. Gemini is gone (Claude captions, local embeddings), Vexcel aerial facts are removed (photos
> stay), and the eval is 90 parallel cold runs. Current commands are in `README.md`. Kept for history only.

# Next session: what to do, in order

Starting point: branch `claude/new-session-e32bmm`, commit `7f65684`. Backend, harness and eval are built and
pass `scripts/verify.sh` (29 + 6 + 8 tests).

Assumed true at the start of the session:
- The Gemini key has paid credit.
- `ANTHROPIC_API_KEY` and `LANGSMITH_API_KEY` are visible in the environment.
- The Google Cloud VM exists (e2-standard-4, Ubuntu 24.04, 50 GB disk, HTTP and HTTPS allowed).

Hard deadline: Devpost submission Sun Nov 15, 8:00 AM ET.

---

## 0. Confirm the assumptions (5 minutes)

- [ ] `./scripts/verify.sh` prints `verify: ok`.
- [ ] Keys are present. This prints names only, never values:

```bash
for v in ANTHROPIC_API_KEY LANGSMITH_API_KEY GEMINI_KEY MATTERPORT_API_KEY MATTERPORT_API_TOKEN VEXCEL_API_KEY COSTAR_KIT_URL COSTAR_ZIP_PASSWORD; do [ -n "${!v}" ] && echo "$v set" || echo "$v MISSING"; done
```

- [ ] Gemini answers on the paid tier: one caption call returns HTTP 200, not 402 or 429.
- [ ] If the agent runs from a Claude cloud session and not from the VM: add `api.anthropic.com` and
      `api.smith.langchain.com` to the `mundus` environment's allowed hosts. On the VM nothing is needed.

## 1. Deploy and ingest on the VM (about 1 to 1.5 hours, mostly waiting)

In the VM's SSH window:

```bash
git clone https://github.com/siddhak711/mundus && cd mundus && git checkout claude/new-session-e32bmm && bash scripts/deploy/vm_setup.sh
```

The script asks for the keys once, writes `.env`, installs everything, ingests the 15 places and starts both
services behind HTTPS. It has never been run: expect to fix small things. If it stops, rerun it; ingestion resumes.

- [ ] `mundus ingest verify` exits 0. Expected: 15 deep places, 108 spaces, 1,270 selected panos, 7,620 face files,
      at least 98% captioned, 15 aerial records.
- [ ] `curl https://<host>/healthz` returns `"deep_places": 15`.
- [ ] `curl https://<host>/agent/ok -H "X-Agent-Token: <AGENT_TOKEN>"` returns 200, and 401 without the header.
- [ ] Give the Frontend session: the host, `WORLD_API_TOKEN`, `AGENT_TOKEN` (all in `.env` on the VM).

Things most likely to need a fix here (none were testable last session):

| Risk | Where | What to do |
|---|---|---|
| Caption speed: 31.5 s per call was measured with default thinking | `backend/mundus_world/providers/gemini.py` sends `thinkingConfig: {thinkingLevel: "low"}` and drops it on a 400 | Check `model_usage.tokens_thought` in `/v1/stats`. If thinking is still heavy, try the model's documented setting |
| Caddy config and systemd units | `scripts/deploy/` | Read `journalctl -u mundus-world -u mundus-harness -u caddy` |
| `langgraph dev` is the in-memory development server | `scripts/deploy/mundus-harness.service` | Fine for the demo. Threads are lost on restart, so do not restart during judging |
| Vexcel returns the wrong parcel for Josephine DTLA (`8810904`) | `ingest_scan.py`, `aerial` step | Check `footprint_area_m2` is over 1,000 for that place. The adjacent-parcel fallback exists but was only exercised by hand |

## 2. Choose the caption length (20 minutes)

Captions are 280 to 400 words by default (`CAPTION_DETAIL=deep`). Run the experiment before the full caption job
if time allows, otherwise right after it:

```bash
cd backend && .venv/bin/mundus qa caption-lengths -n 5
```

- [ ] Open `backend/data/reports/caption_lengths.html`: the same 5 panos at `brief`, `standard`, `deep`, `max`,
      with words, output tokens and seconds for each.
- [ ] Pick the level. If it is not `deep`, set `CAPTION_DETAIL` in `.env` and rerun
      `mundus ingest caption --force`, then `cards`, `embed`.
- [ ] Human check: `mundus qa captions`, read `captions.html` for 5 minutes. More than 3 of 30 with a clear
      invention means tighten the prompt in `gemini.py` and bump `CAPTION_PROMPT_VERSION`.
- [ ] Set Gemini prices so cost is not reported as unknown: `MODEL_PRICES="gemini-4-hydrogen=<in>,<out>"` in `.env`,
      from Google's price page. Claude prices are already in `harness/mundus_harness/config.py`.

## 3. First real agent run (30 minutes)

Nothing has run through the harness with a real model. Do one question by hand before the eval.

- [ ] Ask one question about The Preserve through the agent server, twice. Expected: run 1 route `cold`, claims
      written, citations in the answer; run 2 route `card_hit`, no subagents, far fewer tokens.
- [ ] Watch for these, all untested with real models:

| Risk | Symptom | Fix |
|---|---|---|
| Gemini subagents skip `put_claim` or return a malformed result | `claims_written: 0`, or a structured-output error | Tighten the subagent prompts in `prompts.py`; fallback is `WORKER_MODEL=anthropic:claude-haiku-5-5` |
| Image block format for the look tools | Hydrogen says it cannot see the image | `tools_local.py`, `_img_block`: the block shape is from the harness spec at moderate confidence |
| Orchestrator does not call subagents in one turn | Several sequential `task` calls | Prompt rule in `prompts.py` |
| Router keyword rules pick the wrong facets | Wrong subagents run | Set `ROUTER_USE_MODEL=1` to use the one-call classifier |
| LangSmith tracing | No traces | Set `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=mundus` |

## 4. Run the eval (1 to 2 hours)

- [ ] Replace the draft wording in `eval/tasks.yaml` with the tasks designed in the eval session. The 15 there now
      were drafted from the data and marked `status: draft`. Keep the structure: `truth`, `checks` or `rubric`.
- [ ] Confirm `eval/combos.yaml` lists the harness combinations you want compared. It ships with three:
      cold and warm memory on Sonnet plus Hydrogen, and cold on all-Hydrogen.
- [ ] Run, in this order, with `WORLD_REST_URL`, `WORLD_API_TOKEN` and `WORLD_ADMIN_TOKEN` set:

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

- [ ] `truth` should report no missing values once all 15 places are ingested.
- [ ] `references` and the grader call Claude Fable 5.2 for the first time. They were tested with a fake client only.
      If the call shape is rejected, the code is in `eval/mundus_eval/graders.py` and `references.py`.
- [ ] Smoke first: `mundus-eval run --tasks R1,P15 --runs 1`. The full run is 15 tasks x 3 combinations x 3 repeats
      = 135 runs, sequential.
- [ ] Read `eval/data/results/<time>/report.md`: pass rate, tokens in and out, cost, wall-clock time, time to first
      action and tool calls per combination.

Known limit to state when presenting results: the data has no doors and no structural information. Task P15 is
scored on refusing to invent, and any task that needs a walking route has no ground truth.

## 5. Hand-offs to the other sessions

- [ ] Frontend: `specs/backend-spec.md`, the "As built" table and CCP-1 to CCP-15. The points that change frontend
      code: only 15 places are deep; at most 20 panos per space have images; images come from
      `/v1/panos/{id}/faces/{face}` and `/v1/places/{id}/aerial`; the card is at `/v1/places/{id}/card`;
      `/v1/map/spaces` and `/v1/map/places` feed the map; custom stream events are listed in `specs/harness.md` section 8.
- [ ] Frontend: confirm it can read the custom stream events. If not, set `UI_EVENTS_IN_STATE=1`. That fallback is a
      config flag only: the state-append path is not implemented yet (`harness/mundus_harness/events.py`).
- [ ] Harness session: read `harness/DECISIONS.md` (10 deviations from `specs/harness.md`), and note the harness spec
      on branch `claude/new-session-vubg4k` is not merged into this branch.

## 6. Before submission

- [ ] Snapshot for the laptop fallback, and test a restore on one laptop:

```bash
cd backend && .venv/bin/mundus snapshot --out world.tar.zst
```

- [ ] `mundus warmup --queries <file>` with the demo's search queries, so they hit the cache.
- [ ] Merge or open a pull request from `claude/new-session-e32bmm` to `main`. The repository must be public and
      contain no data: `data/`, `.env` and the kit are git-ignored. Check `git status` shows nothing under `data/`.
- [ ] Devpost write-up: do not claim data that is not used. Used: CoStar kit (8 datasets), Matterport (index, rooms,
      panos, defurnished views, floor plans, AI summaries), Vexcel (property attributes, ortho, obliques, embedding
      search). Not used: MatterPak meshes, point clouds, splat files.

## Not built (decide whether any of it matters)

| Item | Note |
|---|---|
| Drone photos for the two splat places | Planned as P1 in the spec, not implemented |
| `similar_to` edges, the curator agent, the context-arms eval (harness H11 to H13) | Stretch items |
| `UI_EVENTS_IN_STATE` state fallback | Flag exists, code path does not |
| Matterport Basics for all 5,734 LA models | Stretch; shallow spaces show index fields only |
