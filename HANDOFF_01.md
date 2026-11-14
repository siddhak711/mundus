# Handoff: Sat Nov 14, 6:05 PM ET

Deadline: Devpost submission Sun Nov 15, 8:00 AM ET.

Read this first, then `NEXT_SESSION.md` (the full checklist). Where the two disagree, this file wins.

## Decision made this session

**Gemini is dropped. The build uses the Anthropic API only.** The Gemini key's project has no prepaid credit
(HTTP 402 on every model), and the owner chose not to fund it. Ignore every Gemini step in `NEXT_SESSION.md`:
the paid-tier check in step 0, the caption speed risk in step 1, the Gemini prices in step 2, and the Gemini
subagent risks in step 3.

## Open decision (owner has not answered)

Embeddings. Anthropic has no embeddings API. Options:

| Option | Effect |
|---|---|
| Small local model on the VM (recommended) | Keeps semantic search, no extra key |
| Keyword-only search | No new dependency; the database already has a full-text index (`doc_fts`, `place_fts`) |

## Blockers

| Blocker | Detail | Who fixes it |
|---|---|---|
| No Anthropic key in the cloud session | `ANTHROPIC_API_KEY` is saved on the `mundus` environment but was empty in the session shell; a test call returned 401. Cause not established: either it was added after the session started, or the platform withholds that name | Owner: save the same key as `MUNDUS_ANTHROPIC_KEY` on the environment, start a new session. The session then maps it to `ANTHROPIC_API_KEY` when launching the harness and eval |
| VM not located | The cloud session's Google token works for the Compute API only, which needs a project ID. None is recorded anywhere | Owner: give the project ID, zone and instance name |
| `vm_setup.sh` cannot run as written | It runs `mundus ingest all`, which includes the Gemini caption and embed steps | Next session: do the code work below first |

On the VM the Anthropic key is not a problem: `vm_setup.sh` asks for it and writes it to `.env`.

## Code work needed to drop Gemini (none of it started)

| Part | Where | Change |
|---|---|---|
| Captions | `backend/mundus_world/providers/gemini.py`, called from `service/ingest_scan.py` and `service/qa.py`; model names in `config/settings.py` and `.env.example` (`CAPTION_MODEL`, `CAPTION_FALLBACK_MODELS`) | Add a Claude caption provider and make it the default. Bump `CAPTION_PROMPT_VERSION` |
| Embeddings | `service/search.py`, `service/ingest_scan.py` (`embed` step), `EMBED_MODEL` | Per the open decision above |
| Subagents | `harness/mundus_harness/config.py` line 54: `WORKER_MODEL` defaults to `google_genai:gemini-4-hydrogen` | Change the default to `anthropic:claude-haiku-5-5`. `ROUTER_MODEL` follows it |
| Eval combinations | `eval/combos.yaml`: all three combinations name Hydrogen | Replace with Anthropic-only combinations, for example Sonnet plus Haiku cold, Sonnet plus Haiku warm, all-Haiku cold |
| Deploy script | `scripts/deploy/vm_setup.sh` asks for a Gemini key | Remove the prompt |
| Docs | `README.md`, `specs/`, the Devpost write-up list in `NEXT_SESSION.md` step 6 | Do not claim Gemini |

Cost and time for Claude captions are unmeasured. The count is about 1,270 panos, six face images each.

## Verified this session

- `./scripts/verify.sh` prints `verify: ok` on `claude/new-session-e32bmm`.
- The ingest steps that need no model (`index`, `costar`, `select`, `basics`, `rooms`, `resolve`, `panos`,
  `panos-defurnished`, `aerial`, `graph`) all exit 0 for Josephine DTLA (`--places 8810904`). About 4 minutes
  and 1.6 GB for that one place.
- The Vexcel wrong-parcel risk for Josephine DTLA did not occur: `footprint_area_m2` is 16,723 (threshold 1,000).
- Matterport, Vexcel and CoStar keys work.

## Defect found

Matterport model `CkYAnvDkzcE` ("1BR, 1BA - 758 SF", in place `8810904`) returns no pano images for its 20
selected panos. A retry gives the same result. The step logs it as failed and continues. The expected total of
7,620 face files will be at least 120 short. Not checked: whether `mundus ingest verify` still exits 0 with
that gap.

## Environment facts

- The LangSmith key is stored as `LANGCHAIN_API_KEY`, not `LANGSMITH_API_KEY`. The LangSmith SDK reads either
  name. On the VM, enter it at the LangSmith prompt.
- From a cloud session, `api.smith.langchain.com` is blocked by the `mundus` environment's allowed hosts.
  `api.anthropic.com` is reachable.
- SSH from a cloud session to the VM was not tested and is expected to be blocked. Plan on the owner pasting
  the deploy command into the VM's SSH window.
- The Gemini key was pasted into chat in plain text. Rotate it after the hackathon.

## Branches

- `claude/new-session-e32bmm`: the backend, harness and eval. All work happens here.
- `main`: holds one unrelated commit (`66dca39`, the Atlas viewer). The two diverged at the initial commit, and
  both changed `README.md`, so the merge in `NEXT_SESSION.md` step 6 will conflict there. Whether Atlas and
  Mundus stay in one repository is undecided.

## Order of work for the next session

1. Get the embedding decision and the VM's project ID, zone and instance name from the owner.
2. Do the Gemini-removal code work above; keep `./scripts/verify.sh` green.
3. Owner runs `vm_setup.sh` on the VM (`NEXT_SESSION.md` step 1).
4. Continue with `NEXT_SESSION.md` steps 2 to 6, skipping the Gemini items.
