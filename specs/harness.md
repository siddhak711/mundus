# Mundus Harness Spec (component 3: agent layer)

Status: v1, Nov 14 2026. Owner: Harness session. Audience: autonomous coding agents. Build from this file without asking questions. Where this file and the shared kit disagree, this file wins for the harness and the difference is listed in section 13 as a CONTRACT CHANGE PROPOSAL.

Decisions taken with Siddha on Nov 14:

| Question | Decision |
|---|---|
| Models | Orchestrator on Claude Sonnet-class. All subagents, vision and the router on Gemini Hydrogen (flash-tier). |
| Memory | A knowledge graph. Typed edges built by code from join keys and geometry, stored in the Backend DB. `similar_to` edges from embeddings are a stretch goal. No graph database, no model-extracted graph. |
| Hosting | Google Cloud VM. Everything stays configurable by environment variable so a laptop run is one command. |
| Human approval | Never pause. Conflicts are resolved by a fixed rule. |
| Language | Python (matches Backend). |

## 0. Verified facts about the library (checked Nov 14 against installed packages)

Pinned versions, all installed and imported successfully on Python 3.13:

```
deepagents==0.7.38
langchain==1.5.0
langgraph==1.2.22
langgraph-cli==0.4.43        # use: pip install "langgraph-cli[inmem]"
langgraph-sdk==0.4.14
langchain-mcp-adapters==0.3.2
langchain-anthropic==1.7.10
langchain-google-genai==4.5.0
langsmith==0.14.17
```

Verified by running code with a fake model (high confidence):

1. `create_deep_agent(model, tools, *, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, name)`. `model` accepts `"provider:model"` strings.
2. **`write_todos` is NOT built in as of 0.7.** The shared kit is wrong on this. Add `TodoListMiddleware()` from `langchain.agents.middleware`. It writes state key `todos`.
3. A custom file backend works: subclass `deepagents.backends.protocol.BackendProtocol`, implement `ls, read, write, edit, glob, grep`, return result dataclasses (`LsResult(entries=[{"path":...}])`, `ReadResult(file_data={"content":..., "encoding":"utf-8"})`, `WriteResult(error=...)`), never raise. Mount it with `CompositeBackend(default=StateBackend(), routes={"/world/": WorldBackend()})`. **The mounted backend receives paths with the route prefix removed** (`/world/places/p1/card.md` arrives as `/places/p1/card.md`).
4. `FilesystemPermission(operations=["write"], paths=["/world/**"], mode="deny")` blocks writes with the tool message `Error: permission denied for write on ...`.
5. Subagents are dicts: `name, description, system_prompt, tools, model, middleware, skills, permissions, response_format`. They are called through the `task` tool with `subagent_type`.
6. `langgraph.config.get_stream_writer()` called inside a tool emits a custom event. With `stream_mode=["custom","updates"], subgraphs=True`, an event from a subagent's tool arrives with namespace `("tools:<uuid>",)`; orchestrator events arrive with namespace `()`.
7. Files written to `StateBackend` appear in state key `files`.
8. `read_file` on `.png/.jpg/.jpeg/.gif/.webp` returns image content blocks. A custom tool can return `[{"type":"text",...},{"type":"image",...}]`.
9. `MultiServerMCPClient(connections, *, tool_interceptors, tool_name_prefix, handle_tool_errors)`; `await client.get_tools()`.
10. Stock middleware available in `langchain.agents.middleware`: `TodoListMiddleware, ToolRetryMiddleware, ModelRetryMiddleware, ModelFallbackMiddleware, ToolCallLimitMiddleware, ModelCallLimitMiddleware, ModelRouterMiddleware, SummarizationMiddleware, HumanInTheLoopMiddleware`. **Their constructor arguments were not checked. Builders must run `inspect.signature` before use.**

From the docs, not run (moderate confidence):

- Model string for Hydrogen in LangChain docs: `google_genai:gemini-4-hydrogen`. Claude Sonnet-class: `anthropic:claude-sonnet-5-5`. **UNVERIFIED that our keys can call both.** Task H0 checks.
- Frontend: `useStream` from `@langchain/react` with `{apiUrl, assistantId}` exposes `stream.messages`, `stream.subagents`, `stream.values` (todos, files), tool-call state. **UNVERIFIED how it surfaces custom events.** Section 8 gives a fallback.
- Summarization converts old messages to text, so image blocks do not survive it. Keep image work inside short-lived subagents.

## 1. Agent topology

One orchestrator, three specialist subagents. Four agents total. The kit's optional "cartographer" and "memory-curator" agents are cut as agents: place resolution is one tool call and card consolidation is deterministic code. Making either a model would add calls, which is the opposite of the pitch.

| Agent | Model | Tools | Why it is separate |
|---|---|---|---|
| `orchestrator` | `anthropic:claude-sonnet-5-5` | `resolve_place`, `get_neighbors`, `get_claims`, `put_claim`, `set_focus`, file tools, `write_todos`, `task` | Plans, reads memory first, delegates only for missing facets, synthesizes, writes cross-layer claims. Never sees raw tables or images. |
| `market-analyst` | `google_genai:gemini-4-hydrogen` | `get_place`, `query_market`, `get_neighbors`, `get_claims`, `put_claim`, `set_focus`, file tools | CoStar rows are wide and numerous. Isolation keeps them out of the orchestrator context. |
| `interior-inspector` | `google_genai:gemini-4-hydrogen` | `get_space`, `get_room`, `search_interiors`, `look_at_pano`, `get_claims`, `put_claim`, `set_focus`, file tools | Images are the most expensive context. They live and die inside this subagent. |
| `aerial-analyst` | `google_genai:gemini-4-hydrogen` | `get_aerial_facts`, `look_at_aerial`, `aerial_semantic_search`, `get_claims`, `put_claim`, `set_focus`, file tools | Same reason, for Vexcel imagery and attributes. |

Rules common to all agents:

- Subagents write their own claims with `put_claim` (memory is contributed at the source, by every agent). The orchestrator writes only synthesis claims that cite other claims.
- Subagents return a compact result (schema below), not prose dumps.
- The orchestrator issues all needed `task` calls in a single model turn so they run in parallel.
- The default `general-purpose` subagent stays registered (removing it needs a harness profile) but the orchestrator prompt forbids using it.

Subagent return schema (pass as `response_format` on each subagent; pydantic):

```python
class Finding(BaseModel):
    claim_id: str            # id returned by put_claim
    statement: str           # one sentence
    confidence: float        # 0..1

class SubagentResult(BaseModel):
    findings: list[Finding]          # max 12
    gaps: list[str]                  # things asked for that the data does not contain
    notes_path: str                  # /runs/<run_id>/notes/<agent>.md
```

### Draft system prompts

`orchestrator`:

```
You answer questions about physical places in Los Angeles using a shared world memory.
Order of work, always:
1. If no place is identified yet, call resolve_place. If it returns several candidates, pick the best and say which.
2. Read /world/places/<place_id>/card.md. A ROUTE note in this conversation tells you which facets the card already covers.
3. Write a todo list with write_todos. One todo per missing facet, plus "synthesize".
4. Delegate ONLY missing facets, all in one turn: market -> market-analyst, interior -> interior-inspector, aerial and surroundings -> aerial-analyst. Give each a self-contained task: place_id, space ids if known, the exact question, what to return. Never use general-purpose.
5. Call set_focus when you move attention to a place.
6. Answer in under 200 words. Every factual sentence ends with one or more markers like [claim:1a2b3c4d5e6f7a8b] using only claim ids that you read from the card or that a subagent returned. If something is unknown, say so. Never state a fact without a marker.
7. If your answer combines facts from two or more layers into a new conclusion (for example "usable as a 20-person office"), record it with put_claim using predicate synthesis.* and the supporting claim ids in derived_from.
Write the final answer to /runs/<run_id>/answer.md as well.
```

`market-analyst`:

```
You extract market facts for one place from CoStar tables: building basics, listings and asking rents, tenants and lease terms, sale comps.
Use get_place first, then query_market with read-only SQL (SELECT only; the schema is in /skills/market-sql/SKILL.md).
Every row returned carries an evidence_id. For each fact worth keeping, call put_claim with a predicate from /skills/claims/SKILL.md and the evidence_id of the row it came from. Do not write a claim without an evidence_id you received from a tool.
Skip facts the card already has (call get_claims with predicate_prefix "market." first).
Write working notes to /runs/<run_id>/notes/market-analyst.md. Return SubagentResult.
```

`interior-inspector`:

```
You describe the inside of one place: spaces, rooms, sizes, layout, what it looks like.
Use get_space and get_room for structure and stored captions. Prefer stored captions and room dimensions. Call look_at_pano only when the task needs visual detail that no caption or claim covers. Limit: 12 images per task.
When you look at a pano, call set_focus with its pano_id first, then write what you saw as a claim on that pano (predicate pano.caption) and on the room or space when it supports a fact (predicates interior.*). Use the evidence_id returned with the image.
Areas come in square metres. Report both m2 and sq ft (1 m2 = 10.764 sq ft).
Write notes to /runs/<run_id>/notes/interior-inspector.md. Return SubagentResult.
```

`aerial-analyst`:

```
You describe the outside of one place and its surroundings from Vexcel data: footprint, parcel, roof, parking, trees, pools, neighbours.
Use get_aerial_facts first (structured attributes). Call look_at_aerial only for things attributes do not answer (parking layout, loading access, street frontage). Limit: 4 images per task. Use aerial_semantic_search for "what is near here" questions.
Write a claim for each fact with predicates aerial.* or surroundings.* and the evidence_id you received. Call set_focus with the place_id and the image kind when you look.
Write notes to /runs/<run_id>/notes/aerial-analyst.md. Return SubagentResult.
```

## 2. Tools

World API tools arrive over MCP from the Backend (`WORLD_MCP_URL`, transport `streamable_http`). Local tools are Python functions in the harness. Descriptions below are the exact text given to the model.

### 2a. World API tools (Backend, via MCP)

| Tool | Description for the model |
|---|---|
| `search_places(query?, near?, filters?, limit=10)` | Find places in Los Angeles by name, address, or location. Returns place summaries with ids. Use when you need candidates. |
| `get_place(place_id)` | Full record for one place: building basics, linked spaces, listings, tenancies, sales. Each item includes an evidence_id you must cite. |
| `get_space(space_id)` | One Matterport scan: summary, rooms with sizes, pano list with stored captions. Each item includes an evidence_id. |
| `get_room(room_id)` | One room: label, dimensions in metres, panos, captions. |
| `search_interiors(text, near?, limit=10)` | Search interiors by what they look like or contain ("sunlit kitchen with an island"). Returns ranked panos, rooms and spaces. |
| `get_aerial_facts(place_id)` | Vexcel structured facts for a place: footprint, parcel, roof, pool, solar, tree cover. Includes evidence_id. No image. |
| `aerial_semantic_search(text, near, radius_m=1000)` | Search aerial imagery around a point by description ("surface parking lot"). Returns features with scores and locations. |
| `query_market(sql)` | Run one read-only SELECT over CoStar tables. Max 200 rows. Each row includes an evidence_id. |
| `get_neighbors(node_id, rel?, depth=1, limit=50)` | Walk the knowledge graph from any node (place, space, room, pano, listing, tenancy, sale, company, claim). Returns edges and neighbour summaries. Use to find what is connected to something. |
| `get_claims(subject_id, predicate_prefix?, status="active")` | Stored facts about a node, with evidence ids, confidence and age. Read these before doing new work. |
| `put_claim(subject_id, predicate, value, statement, evidence_ids, confidence, unit?, derived_from?)` | Save one fact to shared memory. Requires at least one evidence_id you received from a tool, or derived_from claim ids. Returns the claim id and whether it was created, merged with an identical claim, or conflicted with an older one. |
| `get_evidence(ev_id)` | The source behind a claim: record excerpt or image reference. |

### 2b. Local tools (harness)

| Tool | Behaviour | Description for the model |
|---|---|---|
| `resolve_place(text, near?)` | Calls `search_places`, returns top 3 with a match score. No model call. | Turn a name or address into a place_id. Call this first when the user has not selected a place. |
| `look_at_pano(pano_id, faces=[1,2,3,4], defurnished=False)` | GET image bytes from Backend REST, resize each face to max 768 px, JPEG quality 80, return a text block (pano id, room label, evidence_id per face) plus image blocks. Max 4 faces per call. Counts against the per-task image cap. Emits an `evidence` event. | Look at a 360 photo. Faces 1 to 4 are the four horizontal directions. Costly: use only when stored captions do not answer the question. |
| `look_at_aerial(place_id, kind="ortho", size_m=80)` | Same pattern for Vexcel. `kind` in `ortho, oblique-n, oblique-s, oblique-e, oblique-w`. Resize to max 1024 px. | Look at an aerial photo of a place from above or from one side. Costly. |
| `set_focus(place_id?, space_id?, pano_id?, rotation_deg?, aerial_kind?)` | Emits a `focus` event. Returns "ok". No other effect. | Tell the map and 3D viewer what you are looking at. Call it whenever your attention moves. |

Image block format returned by look tools: `{"type": "image", "base64": "<data>", "mime_type": "image/jpeg"}` (moderate confidence on field names; H3 has a test against the real model).

All calls to the Backend go through one `asyncio.Semaphore(4)` and a 20 s timeout.

## 3. File system design

```python
backend = CompositeBackend(
    default=StateBackend(),                                   # /runs/**, scratch. Per thread.
    routes={
        "/world/":  WorldBackend(world_rest_url),             # knowledge graph as files. Global. Read-only.
        "/skills/": FilesystemBackend(root_dir=HARNESS_DIR / "skills", virtual_mode=True),   # read-only
        "/memory/": FilesystemBackend(root_dir=DATA_DIR / "memory", virtual_mode=True),      # global playbook
    },
)
permissions = [
    FilesystemPermission(operations=["write"], paths=["/world/**", "/skills/**"], mode="deny"),
]
```

| Path | Backend | Scope | Writer |
|---|---|---|---|
| `/world/index.md` | WorldBackend | Global | Generated: counts, the 20 places with the most claims |
| `/world/places/<place_id>/card.md` | WorldBackend | Global, all users and agents | Generated from active claims |
| `/world/places/<place_id>/claims.jsonl` | WorldBackend | Global | Generated, one claim per line |
| `/world/places/<place_id>/neighbors.md` | WorldBackend | Global | Generated from graph edges, depth 1 |
| `/runs/<run_id>/plan.md` | State | Thread | Orchestrator (optional mirror of todos) |
| `/runs/<run_id>/notes/<agent>.md` | State | Thread | Each subagent |
| `/runs/<run_id>/answer.md` | State | Thread | Orchestrator |
| `/skills/<name>/SKILL.md` | Filesystem | Repo | Humans. Skills: `claims` (predicate vocabulary), `market-sql` (table schemas, example queries), `interior` (how to read room data, face numbering), `aerial` (attribute meanings) |
| `/memory/AGENTS.md` | Filesystem | Global | Orchestrator may append short lessons ("query X returns nothing, use Y"). Loaded through `memory=["/memory/AGENTS.md"]`. |

`WorldBackend` rules:

- Files are virtual. Each `read` calls the Backend REST API (`get_claims`, `get_place`, `get_neighbors`) and renders text. Cache rendered text for 5 s per path.
- `ls("/places/")` lists places that have at least one claim. `grep` and `glob` operate over the same set (fetch claims.jsonl for matching places; cap at 50 places).
- `write` and `edit` return `error="read-only: use put_claim"`. Memory changes only through `put_claim`, which is where hashing and conflict checks run.
- Place ids appear in paths unchanged (`place:costar:12345`). They contain colons. Test this in H2.

`card.md` format (rendered, not written by a model):

```
# <name> (<place_id>)
<address> · <type> · <size>
coverage: market=fresh(14) interior=fresh(9) aerial=none surroundings=stale(2)
updated: 2026-11-14T18:02Z · claims: 25 active, 1 disputed

## market
- Asking rent is $3.25 per sq ft per month for suite 300. [claim:1a2b3c4d5e6f7a8b] (0.9, record, 2h)
## interior
- ...
## disputed
- interior.floor_area_m2: 212 [claim:...] vs 240 [claim:...]
```

The `coverage:` line is the machine-readable summary the router uses (section 5).

## 4. Memory: the knowledge graph

Lives in the Backend DB (one source of truth; the frontend reads it over REST, agents read it as files and through tools). The harness defines the model and the rules; the Backend implements storage.

### 4a. Nodes and edges

Nodes: `place, space, room, pano, listing, tenancy, sale, company, aerial, claim, evidence` (ids as in kit section 6a).

Edge table: `edges(src, rel, dst, source, weight, created_at)`.

| rel | src to dst | source | Built by |
|---|---|---|---|
| `part_of` | space to place, room to space, pano to room | join | Ingestion, from `costar_property_id` and Matterport ids |
| `has_listing`, `has_tenancy`, `has_sale` | place to record | join | Ingestion |
| `tenant_is` | tenancy to company | join | Ingestion |
| `has_aerial` | place to aerial | join | Ingestion |
| `near` | place to place, within 250 m, weight = metres | geometry | Ingestion, haversine |
| `about` | claim to subject node | agent | `put_claim` |
| `supported_by` | claim to evidence | agent | `put_claim` |
| `derived_from` | claim to claim | agent | `put_claim` |
| `supersedes`, `contradicts` | claim to claim | rule | `put_claim` conflict check |
| `similar_to` (stretch) | space to space, weight = cosine | embedding | Offline job: top 5 neighbours by summary plus caption embedding |

No model builds edges. Every edge is a join, a distance, a rule outcome, or a vector neighbour.

### 4b. Evidence

Every item the World API returns carries an `evidence_id`. Agents can only cite ids they received. `put_claim` rejects unknown ids. This makes invented citations impossible by construction.

```
evidence_id = "ev:" + sha256(type + "|" + source_id + "|" + content_hash)[:16]
content_hash = sha256(image bytes)                         for pano_image, ortho_image, oblique_image
             = sha256(canonical JSON, sorted keys)          for record, room, aerial_facts
             = sha256(utf-8 text)                           for summary, caption
type in: record | room | summary | caption | pano_image | ortho_image | oblique_image | aerial_facts | claim
```

If a source is re-fetched and its content hash differs, a new evidence id results. Claims that cite only the old id are marked `stale`.

### 4c. Claims

```json
{
  "id": "claim:1a2b3c4d5e6f7a8b",
  "subject_id": "space:abc123",
  "predicate": "interior.floor_area_m2",
  "value": 212.4,
  "unit": "m2",
  "statement": "The suite has about 212 m2 (2,286 sq ft) of floor area across 6 rooms.",
  "evidence_ids": ["ev:..."],
  "derived_from": [],
  "confidence": 0.9,
  "status": "active",
  "confirmations": 1,
  "created_by": "interior-inspector",
  "run_id": "...",
  "created_at": "2026-11-14T18:02:11Z"
}
```

`id = "claim:" + sha256(subject_id + "|" + predicate + "|" + normalize(value))[:16]`. `normalize`: numbers rounded to 3 significant figures; strings lower-cased, trimmed, whitespace collapsed; objects as canonical JSON.

`status` in `active | superseded | disputed | stale`.

Predicates come from a fixed vocabulary in `/skills/claims/SKILL.md` (about 40 entries, each with type and unit). Without a fixed vocabulary two agents would name the same fact differently and conflict detection would never fire. Namespaces: `market.*`, `interior.*`, `aerial.*`, `surroundings.*`, `synthesis.*`, `pano.caption`, `note.*`. `put_claim` rejects predicates outside the vocabulary except `note.*` and `synthesis.*`, which are free-form and never conflict. Starter vocabulary to ship in H1:

```
market.building_type, market.building_area_sqft, market.year_built, market.stories,
market.asking_rent, market.available_area_sqft, market.listing_status, market.tenant_count,
market.largest_tenant, market.lease_term_months, market.last_sale_price, market.last_sale_date,
market.nearby_sale_comp
interior.space_kind, interior.floor_area_m2, interior.room_count, interior.ceiling_height_m,
interior.largest_room_area_m2, interior.capacity_estimate, interior.natural_light,
interior.condition, interior.furnished, interior.amenity_present, interior.layout_note
aerial.footprint_area_m2, aerial.parcel_area_m2, aerial.roof_material, aerial.roof_condition,
aerial.has_pool, aerial.has_solar, aerial.tree_cover_pct, aerial.parking_visible, aerial.loading_access
surroundings.nearby_feature, surroundings.street_frontage
pano.caption
```

Multi-valued predicates (`interior.amenity_present`, `market.nearby_sale_comp`, `surroundings.nearby_feature`, `pano.caption`) are flagged `multi: true` in the vocabulary and never conflict.

### 4d. `put_claim` algorithm (deterministic, zero model calls)

1. Validate predicate and evidence ids. Reject otherwise.
2. Compute id. If a claim with this id exists: union evidence ids, `confirmations += 1`, return `outcome: "merged"`.
3. Else look up active claims with the same `(subject_id, predicate)` where the predicate is not multi-valued. If none: insert, `outcome: "created"`.
4. If one exists with a different value (numbers: differ by more than 5%; other types: normalized values differ): conflict. Compare evidence rank: `record (5) > room, aerial_facts (4) > pano_image, ortho_image, oblique_image (3) > caption (2) > summary (1)`; a claim's rank is the highest rank among its evidence; `derived_from`-only claims take the lowest rank of their parents.
   - New rank higher, or equal rank and old claim older than 24 h: old becomes `superseded`, add `supersedes` edge, `outcome: "superseded_old"`.
   - New rank lower: new is stored as `superseded`, `outcome: "rejected_lower_rank"`.
   - Equal rank and old claim younger than 24 h: both become `disputed`, add `contradicts` edge, `outcome: "disputed"`.
5. Return `{claim, outcome, conflicts: [claim ids]}`.

### 4e. Read-card-first, freshness, sharing

- Read-first is enforced in code by `RouterMiddleware` (section 5), not left to the prompt.
- Freshness class by namespace: `interior.*`, `aerial.*`, `pano.caption` never expire. `market.*` goes `stale` after 7 days. `synthesis.*` goes `stale` when any `derived_from` parent is not `active`.
- Sharing: there is one graph. Every agent in every thread for every user reads and writes the same store. There is no per-user namespace. This is the "global memory across agents" story.

## 5. Cost-reduction loop

`RouterMiddleware` (`before_agent` hook on the orchestrator), runs once per user turn:

1. **Resolve place.** Use `place_id` from run context if the frontend sent one. Otherwise call `resolve_place` on the user text (no model).
2. **Classify facets.** One Hydrogen call with structured output, max 50 output tokens: `{"facets": ["market"|"interior"|"aerial"|"surroundings"], "needs_visual_detail": bool}`. If it fails, fall back to keyword rules (rent, lease, tenant, sale, price to market; room, inside, layout, fit, look to interior; roof, parking, outside, parcel to aerial; near, around, neighbourhood to surroundings; no match means all four).
3. **Check coverage.** Read the card's `coverage:` line. A facet is covered when it has 3 or more fresh claims.
4. **Set route** in state and inject a system note:
   - `card_hit`: every needed facet covered and `needs_visual_detail` false. Note: "Answer from the card. Do not delegate." The orchestrator model for this turn is swapped to Hydrogen via `wrap_model_call` (`request.override(model=...)`; if `ModelRouterMiddleware` does this cleanly, use it).
   - `partial`: note lists covered and missing facets. Delegate missing only.
   - `cold`: no card or nothing covered. Full fan-out.
5. Emit a `route` event.

Other savings:

- Stored captions and room geometry before any live image look. Image caps: 12 per interior task, 4 per aerial task.
- Captions produced by a live look are written back as `pano.caption` claims, so the next agent never re-looks at that pano.
- Subagents call `get_claims(predicate_prefix=...)` before working and skip known facts.
- Anthropic prompt caching is on by default in deepagents for the orchestrator.

`MetricsMiddleware` (on the orchestrator and on every subagent, same class):

- `wrap_model_call`: record agent name, model, `usage_metadata` input and output tokens, latency.
- `wrap_tool_call`: record tool name, latency, error flag, images returned.
- Accumulate in a process-level dict keyed by `thread_id` plus turn index (thread id propagates to subagents through config; moderate confidence, tested in H5).
- `after_agent` on the orchestrator: compute totals, append one line to `DATA_DIR/run_metrics.jsonl`, look up the baseline (the earliest `cold` run for the same place), emit a `metrics` event.

Estimated cost uses a price table in `config.py` (`PRICES = {model: (usd_per_mtok_in, usd_per_mtok_out)}`). **Fill it from the provider price pages at build time; do not guess.**

Targets (moderate confidence until measured): exact repeat of a question on a warm place uses 0 subagents, at most 2 model calls, at least 80% fewer tokens, under 10 s. A different question on a warm place that needs one new facet uses 1 subagent and at least 40% fewer tokens than cold.

## 6. Vision handling

| Situation | Action |
|---|---|
| Question answerable from room geometry, Matterport summary, stored captions or claims | No live look |
| `needs_visual_detail` true, or no caption exists for the rooms in question | `look_at_pano`, up to 12 images |
| Parking, loading, frontage, anything Vexcel attributes lack | `look_at_aerial`, up to 4 images |
| Bulk captioning of target spaces | Not the harness. Backend offline job (kit "Approach 1"). |

- Model: Hydrogen for all image input. The orchestrator never receives image blocks.
- Sizes: pano faces 768 px, aerial 1024 px, JPEG quality 80. The Backend serves cached bytes; the harness resizes with Pillow.
- Pano choice: at most 2 panos per room, the ones nearest the room centroid (positions from `get_room`). Faces 1 to 4 only. Never faces 0 or 5.
- Defurnished view only when the question is about empty-space fit or layout and `has_defurnished` is true.
- Every look emits `focus` (before) and `evidence` (after) events.

## 7. Middleware

Orchestrator stack, in order (deepagents inserts these after its own base stack):

1. `TodoListMiddleware()`
2. `RouterMiddleware` (section 5)
3. `MetricsMiddleware` (section 5)
4. `WorldGuardMiddleware` (`wrap_tool_call`):
   - HTTP 429 or 5xx or timeout from the Backend: retry twice with 1 s then 3 s backoff, then return an error tool message.
   - 403, `not.found`, or "no coverage": no retry. Return `"Unavailable: <reason>. Do not retry. Record this as a gap."`
   - `query_market`: before sending, parse with `sqlglot`; reject anything that is not a single `SELECT`; append `LIMIT 200` if absent. The Backend enforces the same rule; this is defence in depth.
   - `put_claim`: after success, emit a `claim` event (and `conflict` when the outcome is not `created` or `merged`).
5. `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware`: 25 model calls and 60 tool calls per run for the orchestrator; 12 and 30 per subagent task. Check signatures first.
6. `AnswerMiddleware` (`after_agent`): parse `[claim:<id>]` markers in the final message, drop markers that do not resolve, resolve the rest to evidence ids through `get_claims`, emit an `answer` event. No model call.

Subagents get items 3, 4 and 5.

Tracing: set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=mundus`. Add run metadata `place_id` and `route` so traces filter by route.

Upstream rate limits (shared sponsor keys, under 10 requests per second) are the Backend's job. The harness contributes by capping concurrency at 4 and images per task.

## 8. Streaming events

The frontend connects with `useStream` (`@langchain/react`) to `LANGGRAPH_URL`, assistant id `mundus`. Two channels.

**Standard channel (no harness code needed):**

| UI need | Source |
|---|---|
| Run started / finished | stream lifecycle |
| Todo list | `stream.values.todos` (`[{content, status}]`) |
| Subagent started / finished, name, task | `stream.subagents` (`name`, `status`, `messages`, `tool_calls`) |
| Tool call name and args | `stream.tool_calls`, `subagent.tool_calls` |
| Files written | `stream.values.files` (keys are paths under `/runs/`) |
| Final answer text | last AI message |

**Custom channel (`stream_mode` includes `custom`).** Every event is one JSON object with this envelope:

```json
{"v": 1, "type": "<type>", "ts": "2026-11-14T18:02:11.120Z", "agent": "interior-inspector", "run_id": "<run_id>", ...payload}
```

| type | Payload | Emitted by |
|---|---|---|
| `route` | `place_id, route: "card_hit"\|"partial"\|"cold", facets_needed[], facets_covered[], facets_missing[]` | RouterMiddleware |
| `focus` | `place_id?, space_id?, pano_id?, rotation_deg?, aerial_kind?, lat?, lon?` | `set_focus`, look tools |
| `evidence` | `evidence_id, kind, source_id, image_url?` (image_url is a Backend REST URL, not a signed upstream link) | look tools |
| `claim` | `claim_id, subject_id, place_id, predicate, statement, evidence_ids[], confidence, outcome` | WorldGuardMiddleware |
| `conflict` | `subject_id, predicate, kept_claim_id, other_claim_id, outcome` | WorldGuardMiddleware |
| `metrics` | `route, model_calls, tool_calls, images, tokens_in, tokens_out, latency_ms, est_cost_usd, by_agent{}, claims_read, claims_written, baseline{same fields}\|null, savings{tokens_pct, calls_pct, latency_pct}\|null` | MetricsMiddleware |
| `answer` | `text, citations: [{claim_id, evidence_ids[]}], place_ids[]` | AnswerMiddleware |

Run input from the frontend:

```json
{"messages": [{"role": "user", "content": "..."}]}
```

with run context `{"place_id": "place:costar:123"}` when a place is selected (context schema: `class Ctx(TypedDict, total=False): place_id: str`).

Fallback if `useStream` cannot read custom events (UNVERIFIED, Frontend session checks first): the harness also keeps `ui_events: list` in agent state with an append reducer, and every emit helper appends the same object there. The frontend then reads `stream.values.ui_events`. Build the emit helper so this is one flag (`UI_EVENTS_IN_STATE=1`).

Metric display (for Frontend): a strip under the answer: "This answer: 2 model calls, 3.1k tokens, 6 s. First time: 14 calls, 41k tokens, 58 s. Saved 92% tokens." Fed entirely by the `metrics` event.

## 9. Human-in-the-loop

None. `interrupt_on` is not set and no permission rule uses `mode="interrupt"`. Conflicts are settled by the rule in 4d and surfaced as `conflict` events and a "disputed" section on the card. If approval is wanted later, it is one argument: `interrupt_on={"put_claim": True}`.

## 10. Evaluation

Real place ids cannot be written here because the CoStar kit join is still unverified. Task H9 instantiates the questions from the live Backend with the selection rules below and writes `harness/eval/questions.jsonl` (`{id, place_id, question, required_facets, required_evidence_types}`).

| # | Selection rule (LA only) | Question | Required evidence types |
|---|---|---|---|
| 1 | Place with a listing, 1+ non-unit space with rooms | Is the largest space here usable as a 20-person office? What does it look like and what is the asking rent? | room, record, caption or pano_image |
| 2 | Same place as 1 | Exact repeat of 1 (warm) | none new |
| 3 | Same place as 1 | What do the roof and parking look like from above? | aerial_facts, ortho_image |
| 4 | Place with 3+ tenancies | Who are the tenants and when do the leases end? | record |
| 5 | Place with a sale comp | What did this building last sell for and how does that compare with sales within 250 m? | record (2+) |
| 6 | Space named like fitness or gym | What equipment and amenities are in this gym? | pano_image or caption |
| 7 | Space with `has_defurnished` | How large is the main room and could it fit a 12-seat conference table? | room, pano_image |
| 8 | Residential listing with a space | How many bedrooms, and is the kitchen updated? | record, caption or pano_image |
| 9 | Place with Vexcel pool attribute true | Is there a pool, and where is it relative to the building? | aerial_facts, ortho_image |
| 10 | Any place with 2+ spaces | Which space here has the most natural light? | caption or pano_image (2+ spaces) |
| 11 | Free text, no place selected | Find a lobby in downtown LA with high ceilings. | caption or summary |
| 12 | Place with no interior | What is inside this building? | Must report a gap, zero interior claims |
| 13 | Place of 4 after 4 ran | What is the average lease term here? (warm, different question) | none new, or record |
| 14 | Place with a listing and aerial | Is there loading access for deliveries? | ortho_image or oblique_image |
| 15 | A made-up address | Tell me about 99999 Nowhere Blvd. | Must say not found, zero claims |

Run with LangSmith: dataset `mundus-eval`, one experiment per run of the suite, evaluators are code, not models:

| Check | Pass rule |
|---|---|
| Citation coverage | Every sentence in the answer that contains a digit or a proper noun has a `[claim:...]` marker. 100%. |
| Citation validity | Every marker resolves to a stored claim with 1+ evidence id or `derived_from`. 100%. |
| Evidence types | Claims written during the run include the required evidence types. |
| No invention | Questions 12 and 15 write zero claims of the forbidden kind and state the gap. |
| Warm savings | Q2 vs Q1: 0 subagents, at most 2 model calls, tokens down 80% or more. Q13 vs Q4: tokens down 40% or more. |
| Latency | Cold run 90 s or less. `card_hit` 10 s or less. |
| Budget | No run hits the call limits. |

Suite passes when 13 of 15 questions pass every applicable check, and citation validity is 100% across all 15.

### 10b. Context-engineering eval (task H13)

Goal: find which interior context gives the best answers per token.

Inputs:

| Code | Input |
|---|---|
| S | Matterport space summary. One per scan, not per room. |
| G | Room geometry. |
| C | Pano captions we generate with a vision model. |
| P | Raw panos. Fixed at 4 images per room: one pano, four horizontal faces. |
| M | Mesh-derived input. Form not decided. |

S+G is always on. C, P and M are each switched on or off. That gives 8 arms:

`S+G`, `+C`, `+P`, `+M`, `+C+P`, `+C+M`, `+P+M`, `+C+P+M`

Size: 15 questions, 3 repeats each. 45 runs per arm, 360 runs total.

Fixed across arms: model, prompt, questions. Logged per arm: accuracy, tokens, latency.

Not decided yet (do not build past these without Siddha):

- The form of M. A model cannot read a mesh. It must be a top-down render or measurements computed by code.
- Which spaces to test on.
- The 15 questions and their hand-checked answers.
- Card layout: flat or hierarchical. Not chosen.

Prerequisites, in order:

1. Confirm keys (model keys and Matterport keys).
2. Pick spaces.
3. Write the 15 questions with hand-checked answers.
4. Build the S, G, P, C and M inputs for those spaces.
5. Write a runner script that runs all 8 arms.

## 11. Build plan

Repo layout:

```
harness/
  pyproject.toml            # pins from section 0
  langgraph.json            # {"dependencies": ["."], "graphs": {"mundus": "./mundus_harness/graph.py:make_graph"}, "env": ".env"}
  mundus_harness/
    config.py               # env, model ids, limits, PRICES
    graph.py                # async make_graph(): loads MCP tools, builds the deep agent
    prompts.py
    tools_local.py          # resolve_place, look_at_pano, look_at_aerial, set_focus
    world_client.py         # httpx REST client + semaphore
    world_backend.py        # WorldBackend(BackendProtocol)
    events.py               # emit(type, **payload)
    middleware/router.py, metrics.py, guard.py, answer.py
    mock_world/             # FastAPI app + fixtures: 3 places, 5 spaces, 20 rooms, 40 panos, 8 jpgs
  skills/claims/SKILL.md, market-sql/SKILL.md, interior/SKILL.md, aerial/SKILL.md
  eval/build_questions.py, run_eval.py, evaluators.py
  tests/
```

Environment: `ANTHROPIC_API_KEY, GOOGLE_API_KEY, WORLD_MCP_URL, WORLD_REST_URL, WORLD_MODE=mock|live, ORCH_MODEL, WORKER_MODEL, DATA_DIR, LANGSMITH_*, UI_EVENTS_IN_STATE`.

The mock World API implements every tool in 2a, including the `put_claim` algorithm in 4d, so the harness is buildable and testable before the Backend exists. The Backend session may lift that `put_claim` code directly.

| Task | Work | Acceptance test |
|---|---|---|
| H0 | Scaffold, pins, `.env.example`. Script `check_models.py` sends one text call to each model and one image call to Hydrogen. | Script prints OK for 3 calls. `langgraph dev` starts and lists assistant `mundus`. |
| H1 | Mock World API (REST + MCP) with fixtures and `put_claim` rules. Claims skill with vocabulary. | Unit tests for 4d: created, merged, superseded_old, rejected_lower_rank, disputed, unknown evidence rejected, bad predicate rejected. |
| H2 | `WorldBackend` + composite + permissions. | `read_file /world/places/<id>/card.md` returns the rendered card with a `coverage:` line; `write_file` under `/world/` is denied; ids containing colons work; `ls /world/places/` lists only places with claims. |
| H3 | Local tools and `events.emit`. | `look_at_pano` returns at most 4 image blocks, each 768 px or smaller; real Hydrogen call describes a fixture image; `focus` and `evidence` events observed on the custom stream. |
| H4 | Orchestrator and 3 subagents with prompts, `TodoListMiddleware`, `response_format`. | Against mock, question 1 produces: todos in state, 2 or more `task` calls in one model turn, 5 or more claims stored, notes files under `/runs/`. |
| H5 | `MetricsMiddleware`. | `metrics` event totals equal the sum of per-agent numbers, and include subagent tokens; a line is appended to `run_metrics.jsonl`. |
| H6 | `RouterMiddleware` with model swap. | Second run of the same question: `route=card_hit`, 0 `task` calls, at most 2 model calls, `metrics.savings.tokens_pct` 80 or more. |
| H7 | `WorldGuardMiddleware`. | Mock returns 403: exactly one attempt and a gap is reported. Mock returns 429 twice then 200: succeeds. `DELETE` and multi-statement SQL are rejected before any HTTP call. `claim` events fire. |
| H8 | `AnswerMiddleware`. | Answer with one bogus marker: marker removed, `answer.citations` contains only valid ids. |
| H9 | Eval against the live Backend: build questions, run suite, upload to LangSmith. | Section 10 pass rule. |
| H10 | VM deploy. e2-standard-4, Ubuntu 24.04. systemd unit runs `langgraph dev --host 0.0.0.0 --port 2024 --no-browser`. Caddy in front for HTTPS (browsers block a secure page calling an insecure API) and a shared-secret header check. | Frontend on another machine streams a full run. A request without the header gets 401. |
| H11 (stretch) | `similar_to` traversal: orchestrator uses `get_neighbors(rel="similar_to")` to answer "other spaces like this one". | Question returns 3 spaces, each cited. |
| H12 (stretch) | Offline consolidation graph `curator`: finds `disputed` pairs and queues a re-look. | Not required for judging. |
| H13 | Context-engineering eval (section 10b). Runner `eval/context_arms.py` runs 8 arms x 15 questions x 3 repeats with model, prompt and questions fixed. Blocked until the open items in 10b are decided and its prerequisites are done. | 360 runs logged. One results table with accuracy, tokens and latency per arm. |

Order: H0, H1, H2, H3, H4 serial. Then H5, H7, H8 in parallel. Then H6. Then H9 and H10. H1 to H8 need no Backend.

## 12. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Model ids wrong or keys lack access | Moderate | H0 checks first. Ids are env vars. |
| `langgraph dev` on the VM is the in-memory development server and can lose threads on restart | Moderate | Nothing durable lives there: memory is in the Backend DB, metrics in a file. Do not restart during judging. |
| VM or venue network fails during a 2-minute pitch | Moderate | Same stack runs on a laptop with `WORLD_MODE` and URLs changed. Pre-warm demo places. Keep a recorded run. |
| Open agent endpoint lets strangers spend our model credits | Moderate | Shared-secret header at Caddy (H10). |
| Gemini workers skip `put_claim` or return malformed results | Moderate | `response_format` schema; `put_claim` rejects bad input with a corrective message; eval check on claims written. Fallback: set `WORKER_MODEL` to a Claude Haiku-class id. |
| Predicate vocabulary too narrow, agents overuse `note.*` | Moderate | Count `note.*` share in eval; extend vocabulary when above 30%. |
| Orchestrator does not parallelize `task` calls | Low to moderate | Prompt rule plus eval check in H4. |
| Custom events not readable by `useStream` | Unknown | State fallback flag in section 8. |
| Subagent token usage not attributed to the run | Moderate | H5 test. Fallback: read totals from the LangSmith trace. |
| Cold run slower than 90 s | Moderate | Image caps, parallel subagents, Hydrogen workers. Demo opens on a warm place and shows one cold place. |
| CoStar join broken, few places have all three layers | Unknown (Backend) | Eval selection rules pick only places where the data exists. |
| Backend not ready for contract changes | Moderate | Harness runs against its own mock. Minimum the Backend must add: `evidence_id` on responses, `put_claim` per 4d, `get_neighbors`. |

## 13. CONTRACT CHANGE PROPOSALS (carry to Backend and Frontend sessions)

**CCP-1 (kit correction, all sessions).** `write_todos` is opt-in in deepagents 0.7. Any text saying it is built in is out of date.

**CCP-2 (6a, Backend).** Claim becomes: `id, subject_id (any node id, not only a place), predicate, value, unit?, statement, evidence_ids[], derived_from[], confidence, status, confirmations, created_by, run_id, created_at`. Ids and hashing per 4b and 4c. Add an `edges` table per 4a. Places expose a derived `place_id` on every claim (the place the subject belongs to) for filtering.

**CCP-3 (6b, Backend).** Every item returned by every World API read carries `evidence_id`. The Backend registers evidence on read.

**CCP-4 (6b, Backend).** `put_claim(subject_id, predicate, value, statement, evidence_ids, confidence, unit?, derived_from?)` returns `{claim, outcome, conflicts}` and implements 4d. `get_claims(subject_id, predicate_prefix?, status?)`; passing a place id returns claims on the place and on its spaces, rooms and panos.

**CCP-5 (6b, Backend).** New `get_neighbors(node_id, rel?, depth<=2, limit)`. Split `get_aerial` into `get_aerial_facts(place_id)` (structured, MCP) and image bytes over REST only.

**CCP-6 (6b, Backend).** Image bytes are served over REST for the harness's look tools: `GET /panos/{pano_id}/faces/{face}?defurnished=0|1` and `GET /places/{place_id}/aerial?kind=&size_m=`, each with response headers `X-Evidence-Id` and `X-Content-Hash`. No image payloads over MCP.

**CCP-7 (6b, Backend).** `search_interiors` also indexes claim statements whose subject is a pano, room or space, so captions written by agents become searchable.

**CCP-8 (6c, Frontend).** Event stream is the standard `useStream` channel plus the custom events in section 8. Frontend sends `place_id` in run context when a place is selected. Frontend to confirm how `@langchain/react` exposes custom events; if it does not, read `stream.values.ui_events`.

**CCP-9 (6d, all).** `/world/**` is generated and read-only. `card.md` is rendered from claims, never written by a model. Added: `/world/index.md`, `/world/places/<id>/neighbors.md`, `/skills/`, `/memory/AGENTS.md`.

**CCP-10 (Backend, stretch).** `similar_to` edges: top 5 neighbours per space by embedding of summary plus captions.

## 14. Why deep agents fits (pitch)

A question about a building crosses three data systems and two kinds of image. Deep Agents gives us the four things that problem needs, and each is load-bearing: a **plan** that picks only the layers the question needs; **isolated subagents** so tables and images never reach the orchestrator; a **file system** where the world's knowledge graph is mounted as files that every agent reads before working; and **shared memory** where every claim is tied to hashed evidence and checked for conflicts by code, not by a model. The result is measured on screen: the second question about a place costs a fraction of the first.
