# Backend Spec: World Context Layer (v1, proof of concept on 10 buildings)

Status: draft for Siddha's review, then merge with the Frontend and Harness specs.
Owner: Backend session. Date: 2026-11-14.

Confidence labels: (high), (moderate), (low). "VERIFY" marks a fact that no one has tested with live keys. Every VERIFY item has an acceptance test in section 11 and a fallback.

## Decisions taken in this session

| Decision | Choice | Source |
|---|---|---|
| Depth scope | 10 LA buildings that have a CoStar property id and many scans. Everything deep (rooms, panos, captions, Vexcel) is for these 10 only | Siddha |
| Hosting | One Google Cloud VM serves the World API to all three components | Siddha |
| Caption and embedding provider | Gemini for both, billed to the Google Cloud credits | Siddha |
| Database | One SQLite file (WAL mode). No separate vector database | Backend session, see 3.1 |
| Claims store | Backend database is the single source of truth | Shared kit recommendation, adopted |
| Live key verification | Not done. No keys were available to this session | See VERIFY items |

What was checked without keys (high confidence, computed from `models_index.csv` on 2026-11-14):

| Fact | Value |
|---|---|
| Rows in index | 14,945 |
| LA models (lon < -110) | 5,734 (5,451 commercial, 283 residential) |
| LA non-unit commercial (name heuristic) | 1,719 |
| LA models with a CoStar property id | 2,523, in 731 distinct buildings |
| LA buildings with 5 or more models | 196 |
| LA buildings with 8 or more models | 39 |
| LA models with an AI summary | 5,065 |
| LA models with defurnished panos | 2,935 |
| LA models with a splat | 34 |

---

## 1. Scope

### 1.1 Depth tiers

| Tier | Content | Scope in v1 | Priority |
|---|---|---|---|
| T0 | `models_index.csv`, `basemap.json` | All 14,945 rows loaded; LA flag set by lon < -110 | P0 |
| T1 | CoStar kit, all 8 datasets + 2 starter CSVs | All records | P0 |
| T2 | Matterport Basics (summary, type, counts, preview image) | The 10 buildings (about 126 models) | P0 |
| T3 | Rooms, walls, floor plans, pano positions | The 10 buildings | P0 |
| T4 | Pano image bytes (6 faces, 2k) and captions | Every pano in the 10 buildings (about 1,462 panos) | P0 |
| T4d | Defurnished pano bytes | Models in the 10 buildings that have them (about 41 models) | P2 |
| T5 | Vexcel elements, ortho, 4 obliques | The 10 buildings | P0 |
| T6 | Vexcel embedding search | Live tool, cached by query | P1 |
| T2-wide | Matterport Basics for all 5,734 LA models | Stretch: about 24 minutes at 4 requests per second | P2 |
| T7 | MatterPak, splats | Out of scope for v1 | Not built |

The other 5,700 LA models still appear in the API as shallow Space records (index fields only), so the map is full and the 10 deep buildings stand out.

### 1.2 Building selection

Selection is a pipeline step, not a hard-coded list, because the deciding fact is unknown until the CoStar kit is unzipped: whether a building's property id exists in the kit and how many kit records hang off it. A building with 19 scans and zero kit records is useless for the CoStar track (30% of the score is data combination).

Selection rule (`select_buildings` step):
1. Candidates: LA rows of the index grouped by `costar_property_id`, with at least 8 models.
2. Hard filter: the property id exists in the kit's commercial property dataset.
3. Score = 3 x (count of non-unit models, capped at 8) + 2 x (count of distinct kit datasets with at least 1 record for the property, range 0 to 5) + 1 x (models with defurnished panos, capped at 5) + 1 x min(total panos / 50, 5).
4. Take the top 10. Write them to `data/selection.json` with the score breakdown.
5. A manual override file `config/selection_override.json` (list of property ids) replaces the result if present.

Provisional list (ranked by scans only, kit membership VERIFY):

| # | CoStar property id | Address (from index) | Models | Non-unit | Panos | Rooms | Defurnished models |
|---|---|---|---|---|---|---|---|
| 1 | 8810904 | 803 S Hope St (Downtown) | 17 | 11 | 202 | 54 | 6 |
| 2 | 256445 | 736 S Los Angeles St (Downtown) | 15 | 9 | 183 | 23 | 0 |
| 3 | 11044249 | 228 N Vermont Ave | 13 | 8 | 235 | 55 | 13 |
| 4 | 6531330 | 427 W 5th St (Downtown) | 10 | 7 | 128 | 38 | 10 |
| 5 | 9332157 | 679 S Hobart Blvd (Koreatown) | 13 | 7 | 92 | 38 | 6 |
| 6 | 9266183 | 550 Main St (Downtown) | 12 | 7 | 82 | 22 | 0 |
| 7 | 6167888 | 1530 N Poinsettia Pl (Hollywood) | 19 | 3 | 212 | 73 | 0 |
| 8 | 10117553 | 445 S San Pedro St (Downtown) | 10 | 5 | 151 | 28 | 0 |
| 9 | 5695320 | 417 Hill St (Downtown) | 9 | 7 | 54 | 15 | 0 |
| 10 | 8829852 | 232 E 2nd St (Little Tokyo) | 8 | 6 | 123 | 69 | 6 |
| | Total | | 126 | 70 | 1,462 | 415 | 41 |

Alternates if any of the 10 fail the kit filter: 4799547 (630 Masselin Ave), 5340268 (3770 Figueroa St), 10310657 (4247 Eagle Rock Blvd), 6808656 (235 San Pedro St), 4559947 (7230 Franklin Ave).

Known weakness of this list (high confidence): by scan names, all 10 are apartment or mixed-use buildings. Their scans are lobbies, gyms, pools, lounges and units. Only #2 (two vacant retail spaces), #8 (live/work lofts) and #9 (executive suites) have commercial-flavoured interiors. Tenancy and lease records in the kit are more likely to attach to office and retail properties, so the kit filter in step 2 may reshuffle this list heavily. Six of the 10 sit within about 1.5 km of each other in Downtown LA, which helps map views and "nearby" queries.

---

## 2. Ingestion pipeline

One CLI, `mundus ingest <step>`, with `mundus ingest all` running steps in order. Every step is idempotent: it skips work whose output already exists, so rerunning after a crash resumes where it stopped.

### 2.1 Shared mechanics

- **Job ledger:** table `ingest_log(step, key, status, attempts, error, updated_at)` with primary key `(step, key)`. A unit of work (for example one model's Rooms query) is skipped when its row has `status = 'done'`. `--force` ignores the ledger.
- **Rate limits:** one token bucket per upstream host, shared process-wide. Matterport Model API: 4 requests per second, burst 4. Vexcel: 2 per second. Gemini: 8 concurrent requests. Signed image downloads: 8 concurrent.
- **Retries:** on HTTP 429, 5xx, timeouts and connection errors: exponential backoff 1, 2, 4, 8, 16 seconds with jitter, 5 attempts, then mark `failed` and continue. HTTP 401 or 403: stop the whole step at once and print which key is wrong (never the key value).
- **Raw responses:** every upstream JSON response is saved to `data/raw/<source>/<key>.json` before parsing, so parsers can be fixed and rerun without new requests.
- **Signed URLs:** never stored. Image bytes are downloaded in the same step that receives the URL, within 60 seconds.

### 2.2 Steps

| # | Step | Input | Output | Upstream requests | Estimated time |
|---|---|---|---|---|---|
| 1 | `index` | `models_index.csv`, `basemap.json` (static, no auth) | `space` rows for all 14,945 models with `depth = 0`; `data/basemap.json` | 2 | under 1 minute |
| 2 | `costar` | Kit zip at `COSTAR_KIT_URL`, password `COSTAR_ZIP_PASSWORD` | `costar_*` tables, `place` rows for every LA commercial property, unmatched-id report | 1 download (about 160 MB) | 5 minutes |
| 3 | `select` | Steps 1 and 2 | `data/selection.json`; `place.is_deep = 1` for 10 places | 0 | seconds |
| 4 | `basics` | Model ids of deep places | `space` rows updated (summary, classification, address), preview image bytes | 126 GraphQL + 126 images | 2 minutes |
| 5 | `rooms` | Same | `floor`, `room`, `wall_vertex`, `wall_edge`, `pano` (positions), floor plan images and DXF | 126 GraphQL + about 400 files | 3 minutes |
| 6 | `panos` | Same | 6 faces per pano at 2k on disk | 126 GraphQL + 8,772 images | 30 minutes (moderate) |
| 7 | `panos-defurnished` (P2) | Models with a defurnished view | Defurnished faces on disk | 82 GraphQL + about 3,000 images | 10 minutes |
| 8 | `aerial` | Deep places | `aerial_facts` rows, ortho x2 and oblique x4 images per place | 70 | 2 minutes |
| 9 | `resolve` | All of the above | `link` rows, pano to room assignment, `space_kind` | 0 | seconds |
| 10 | `caption` | Pano faces | `pano_caption` rows | 1,462 Gemini calls | 10 to 20 minutes |
| 11 | `cards` | Captions, rooms, kit, aerial | `room.card_text`, `space.card_text`, `place.card_text`; no model calls | 0 | seconds |
| 12 | `embed` | Card texts and captions | `embedding` rows | about 25 batched calls | 1 minute |
| 13 | `evidence` | All tables | `evidence` rows for every record, image and caption | 0 | seconds |
| 14 | `verify` | Database | Prints the acceptance report of section 11, exits non-zero on failure | 0 | seconds |

Total wall time from empty: about 60 to 75 minutes (moderate). Total Matterport API requests: about 460 GraphQL calls, well inside the shared-key budget.

### 2.3 Step details that are not obvious

- **`costar`:** the kit's schema is unknown. Load each dataset by flattening top-level scalar fields into columns (pandas `json_normalize`, max depth 2) and keep the full original record in a `raw_json` column. Column names are snake_cased. Print for each dataset: record count, detected id column, detected lat/lon columns. Compare record counts with the expected table in the shared kit (3,339 / 1,022 / 74,093 / 49,575 / 6,120 / 1,747 / 2,120 / 1,899) and warn on any difference above 1%.
- **`rooms`:** a room's `boundary.edges` is an unordered set of wall edge ids. Build the polygon by chaining edges through shared vertex ids. If the chain does not close, store the convex hull of the edge vertices and set `room.polygon_quality = 'hull'`.
- **`panos`:** store all 6 faces so the Frontend can run its own cube-map viewer if the Showcase embed is not possible. Face index semantics: 0 up, 1 to 4 horizon, 5 down. The compass direction of faces 1 to 4 is VERIFY.
- **`aerial`:** per deep place: `property/extract` at the place point; ortho at zoom 21 with bbox 80 x 80 m; ortho at bbox 250 x 250 m (context); the four obliques around the footprint with `buffer-meter=28`. The response shape of `property/extract` is VERIFY: store the raw JSON and read footprint, parcel and attributes defensively.

---

## 3. Storage design

### 3.1 Database choice

SQLite, one file `data/world.db`, WAL mode, opened by the single API process. Reasons:
- Data volume is tiny: about 140,000 kit rows, 15,000 spaces, 1,500 panos, 2,100 vectors.
- SQLite offers a real read-only connection (`file:world.db?mode=ro`) for the SQL tool, which is the safest guard available.
- FTS5 full-text search is built in.
- The whole world state is one file plus one image folder, so a snapshot is one `tar` command.

Vectors: stored as float32 blobs in SQLite and loaded into one in-memory numpy matrix at startup. Brute-force cosine over 2,100 x 768 takes under 5 ms (high). A vector database adds an install and a failure mode for no gain at this size. Revisit above about 200,000 vectors.

### 3.2 Tables (DDL)

```sql
CREATE TABLE place (
  place_id TEXT PRIMARY KEY,            -- place:costar:<pid> or place:geo:<lat4>_<lon4>
  costar_property_id TEXT UNIQUE,
  name TEXT, address TEXT, city TEXT, postal_code TEXT,
  lat REAL, lon REAL,
  property_type TEXT, building_sqft REAL, year_built INTEGER, floors INTEGER,
  is_deep INTEGER NOT NULL DEFAULT 0,   -- 1 for the 10 selected buildings
  card_text TEXT,                       -- derived fact card
  evidence_id TEXT, raw_json TEXT
);
CREATE INDEX place_latlon ON place(lat, lon);

CREATE TABLE space (
  space_id TEXT PRIMARY KEY,            -- space:<sid>
  sid TEXT UNIQUE NOT NULL,
  place_id TEXT REFERENCES place(place_id),
  name TEXT, segment TEXT, space_kind TEXT,   -- unit|amenity|office|retail|industrial|common|home|other
  lat REAL, lon REAL, latlon_source TEXT, address TEXT,
  internal_id TEXT, costar_property_id TEXT, homes_listing_id TEXT,
  pano_count INTEGER, room_count INTEGER, floor_count INTEGER,
  has_summary INTEGER, has_defurnished INTEGER, has_splat INTEGER,
  defurnished_view_id TEXT,
  original_created TEXT,
  ai_summary TEXT, mp_classification TEXT,
  showcase_url TEXT,                    -- https://my.matterport.com/show/?m=<sid>
  preview_path TEXT, card_text TEXT,
  depth INTEGER NOT NULL DEFAULT 0,     -- 0 index only, 2 basics, 3 rooms, 4 panos+captions
  is_la INTEGER NOT NULL DEFAULT 0,
  evidence_id TEXT
);
CREATE INDEX space_place ON space(place_id);
CREATE INDEX space_latlon ON space(lat, lon);

CREATE TABLE floor (
  floor_id TEXT PRIMARY KEY,            -- floor:<sid>:<floorId>
  space_id TEXT NOT NULL, label TEXT, seq INTEGER,
  plan_path TEXT, plan_format TEXT, plan_width INTEGER, plan_height INTEGER,
  plan_origin_x REAL, plan_origin_y REAL, plan_px_per_m REAL, dxf_path TEXT
);

CREATE TABLE room (
  room_id TEXT PRIMARY KEY,             -- room:<sid>:<roomId>
  space_id TEXT NOT NULL, floor_id TEXT,
  label TEXT, label_confidence REAL,
  area_m2 REAL, width_m REAL, depth_m REAL, height_m REAL,
  polygon_json TEXT,                    -- [[x,y],...] metres, model frame
  polygon_quality TEXT,                 -- loop|hull|none
  card_text TEXT, evidence_id TEXT
);
CREATE INDEX room_space ON room(space_id);

CREATE TABLE wall_vertex (vertex_id TEXT PRIMARY KEY, floor_id TEXT, x REAL, y REAL);
CREATE TABLE wall_edge (edge_id TEXT PRIMARY KEY, floor_id TEXT, v1 TEXT, v2 TEXT, type TEXT, thickness REAL);

CREATE TABLE pano (
  pano_id TEXT PRIMARY KEY,             -- pano:<sid>:<panoId>
  space_id TEXT NOT NULL, room_id TEXT, room_match TEXT,  -- inside|nearest|none
  label TEXT, x REAL, y REAL, z REAL,
  has_faces INTEGER DEFAULT 0, has_defurnished_faces INTEGER DEFAULT 0,
  evidence_id TEXT
);
CREATE INDEX pano_space ON pano(space_id);
CREATE INDEX pano_room ON pano(room_id);

CREATE TABLE pano_caption (
  pano_id TEXT NOT NULL, variant TEXT NOT NULL,   -- furnished|defurnished
  model TEXT, prompt_version TEXT,
  caption_json TEXT NOT NULL, caption_text TEXT NOT NULL,
  input_sha256 TEXT, created_at TEXT, evidence_id TEXT,
  PRIMARY KEY (pano_id, variant)
);

CREATE TABLE aerial_facts (
  aerial_id TEXT PRIMARY KEY,           -- aerial:<place_id>
  place_id TEXT UNIQUE NOT NULL,
  footprint_wkt TEXT, parcel_wkt TEXT,
  attributes_json TEXT,                 -- flattened Vexcel attributes
  match_method TEXT, match_distance_m REAL,
  fetched_at TEXT, evidence_id TEXT, raw_path TEXT
);
CREATE TABLE aerial_image (
  image_id TEXT PRIMARY KEY,            -- aimg:<place_id>:<kind>:<size_m>
  place_id TEXT, kind TEXT,             -- ortho|oblique-n|oblique-s|oblique-e|oblique-w
  size_m INTEGER, path TEXT, width INTEGER, height INTEGER,
  fetched_at TEXT, evidence_id TEXT
);
CREATE TABLE aerial_search_cache (
  cache_key TEXT PRIMARY KEY,           -- sha256(text|lat3|lon3|radius_m)
  request_json TEXT, response_json TEXT, fetched_at TEXT
);

-- CoStar kit: one table per dataset, columns discovered at load time.
-- Fixed columns present on every costar_* table:
--   row_id TEXT PRIMARY KEY, costar_property_id TEXT, place_id TEXT, evidence_id TEXT, raw_json TEXT
-- Tables: costar_property, costar_listing, costar_occupancy, costar_company,
--         costar_sale, costar_apartment_listing, costar_res_listing, costar_listing_features

CREATE TABLE link (
  src_id TEXT, dst_id TEXT, relation TEXT,   -- space_at_place|aerial_of_place|listing_of_space
  method TEXT,                               -- id_join|spatial|name
  distance_m REAL, confidence REAL, status TEXT,   -- accepted|candidate|rejected
  note TEXT, PRIMARY KEY (src_id, dst_id, relation)
);

CREATE TABLE evidence (
  evidence_id TEXT PRIMARY KEY,         -- ev:<16 hex>
  type TEXT NOT NULL,                   -- record|summary|room|pano_image|pano_caption|ortho_image|oblique_image|aerial_facts|floorplan
  source TEXT NOT NULL,                 -- costar|matterport|vexcel|derived
  source_id TEXT NOT NULL,              -- e.g. costar_sale:<row_id>, pano:<sid>:<panoId>
  place_id TEXT, url TEXT,              -- backend URL, never a signed upstream URL
  excerpt TEXT, content_sha256 TEXT, fetched_at TEXT
);
CREATE INDEX evidence_source ON evidence(source_id);

CREATE TABLE claim ( ... see section 8 ... );

CREATE TABLE embedding (
  doc_id TEXT PRIMARY KEY,              -- pano_id, room_id, space_id or place_id
  doc_type TEXT, place_id TEXT, space_id TEXT,
  text TEXT, text_sha256 TEXT, model TEXT, dim INTEGER, vector BLOB
);
CREATE VIRTUAL TABLE doc_fts USING fts5(doc_id UNINDEXED, doc_type UNINDEXED, text);

CREATE TABLE ingest_log (step TEXT, key TEXT, status TEXT, attempts INTEGER, error TEXT, updated_at TEXT, PRIMARY KEY (step, key));
CREATE TABLE api_log (ts TEXT, op TEXT, caller TEXT, ms REAL, cache TEXT, place_id TEXT);
```

### 3.3 Vector index

| Item | Value |
|---|---|
| Documents | Pano caption text (about 1,462), room cards (415), space cards (126), place cards (10) |
| Model | `EMBED_MODEL` env var, default `gemini-embedding-001` (moderate: confirm the id against the Gemini docs at build time) |
| Dimensions | 768 (request reduced output size), L2-normalised, float32 |
| Document task type | retrieval document; queries use retrieval query |
| Search | Hybrid: cosine top 50 and FTS5 BM25 top 50, merged by reciprocal rank fusion with k = 60 |
| Query embedding cache | Table keyed by sha256 of the lower-cased query; hit skips the Gemini call |

If the query embedding call does not return in 800 ms, the search returns the FTS5 result alone and sets `"mode": "text_only"` in the response.

### 3.4 File cache layout

```
data/
  world.db
  basemap.json
  selection.json
  raw/{matterport,vexcel,costar}/...            # raw upstream JSON
  kit/                                          # unzipped CoStar kit (git-ignored)
  img/pano/<sid>/<panoId>/<variant>_<res>_<face>.jpg    # variant: furn|defurn, res: 2k, face: 0..5
  img/pano_thumb/<sid>/<panoId>/<variant>_<face>.jpg    # 768 px, made at ingest
  img/preview/<sid>.jpg
  img/floorplan/<sid>/<floorId>.<ext>
  img/aerial/<pid>/<kind>_<size_m>.jpg
```

`data/` is git-ignored in full. Expected size: about 4 GB (moderate; assumes 400 KB per 2k face).

---

## 4. Entity resolution

Order: id joins first, spatial joins second, nothing merged on a guess.

1. **Space to Place, id join:** `space.costar_property_id` equals a kit property id. Link `method = id_join`, `confidence = 1.0`, `status = accepted`.
2. **Sanity check on every id join:** compute haversine distance between the model's lat/lon and the kit property's lat/lon. Above 150 m: keep the link but add `note = 'distance_mismatch'` and log it. Above 1,000 m: set `status = candidate` and exclude from place responses.
3. **Space to Place, spatial:** for LA spaces with no property id, find kit properties within 40 m. Exactly one: link with `method = spatial`, `confidence = 0.6`, `status = candidate`. Several: one candidate link each with `confidence = 0.3`. Candidates are returned by the API in a separate `candidate_spaces` array and never mixed with accepted ones.
4. **Residential:** `space.homes_listing_id` equals the residential listing id in the kit. Link `relation = listing_of_space`. These spaces get `place_id = place:geo:<lat4>_<lon4>`.
5. **Place to Vexcel:** call `property/extract` at the place point. If the point lies inside a returned footprint: `match_method = contains`, distance 0. Otherwise take the nearest footprint within 50 m: `match_method = nearest`, distance recorded. None within 50 m: store parcel only, `match_method = parcel_only`.
6. **Pano to Room:** point-in-polygon of the pano's (x, y) against room polygons on the same floor: `room_match = inside`. No hit: nearest room centroid within 3 m: `nearest`. Otherwise null and `none`.
7. **Unmatched report:** `mundus ingest resolve` prints and saves `data/reports/unmatched.json`: counts of index property ids missing from the kit, kit properties with no models, residential ids missing, distance mismatches.

`space_kind` rules, first match wins, on lower-cased name (deterministic, no model call):

| Kind | Rule |
|---|---|
| home | `segment = residential` |
| unit | matches `\d\s*(br|bd|bed)`, `studio`, `\d(\.\d)?\s*ba\b`, `plan [a-z0-9]+`, `live/work`, `townhouse`, `unit` |
| office | `suite`, `office`, `cowork`, `conference`, `executive` |
| retail | `retail`, `store`, `shop`, `restaurant`, `vacant` |
| industrial | `warehouse`, `industrial`, `dock` |
| amenity | `fitness`, `gym`, `pool`, `spa`, `lounge`, `club`, `roof`, `deck`, `theater`, `screening`, `game`, `yoga`, `bbq`, `barbecue`, `grill`, `pet`, `business center`, `courtyard`, `sundeck`, `terrace` |
| common | `lobby`, `entrance`, `entry`, `hall`, `mail`, `laundry`, `package`, `parking`, `elevator`, `foyer`, `leasing` |
| other | anything else |

---

## 5. Captioning job

| Item | Choice |
|---|---|
| Model | `CAPTION_MODEL` env var. Set it to the Gemini flash-tier model the team calls "Hydrogen". This session does not know that model's API id: Siddha supplies it |
| Unit of work | One call per pano: the 4 horizon faces (1 to 4), each downscaled to 1024 px, sent as 4 images in one request |
| Panos | All panos in the 10 buildings (about 1,462) |
| Defurnished | Not captioned in v1. Furniture removal is generative, so captions of those images describe invented surfaces. Bytes are stored for display only (P2) |
| Context given | Space name, Matterport room label if assigned, room dimensions if assigned |
| Output | JSON, schema below, temperature 0 |
| Estimated cost | Under $10 (low: depends on the model's image token pricing) |
| Estimated time | 10 to 20 minutes at 8 concurrent calls |

Prompt (version `cap-v1`):

```
You are documenting one position inside a building for a factual spatial database.
The 4 images are the four horizontal views from one 360-degree camera position, in rotation order.
Space name: {space_name}. Room label from the scanner: {room_label}. Room size: {dims}.

Describe only what is visible. No marketing language. No guesses about things out of view.
If something is uncertain, leave it out. Return JSON matching the schema.
```

Output schema:

```json
{
  "room_type": "string, e.g. lobby, gym, kitchen, corridor, pool deck, open office, bedroom",
  "summary": "2 sentences, plain, factual",
  "objects": [{"name": "treadmill", "count": 6}],
  "surfaces": {"floor": "string", "walls": "string", "ceiling": "string"},
  "light": "natural|artificial|mixed, plus window description",
  "access": ["doors, stairs, elevators, exits, ramps visible"],
  "safety": ["fire extinguisher, sprinkler heads, exit signs, alarms visible"],
  "visible_text": ["signage or text readable in the images"],
  "condition": "new|good|worn|damaged|under construction",
  "indoor_outdoor": "indoor|outdoor|mixed",
  "notable": ["up to 5 distinctive details"]
}
```

`caption_text` is a deterministic flattening of the JSON into one paragraph, used for search and embeddings.

Quality check:
- Automated: at least 98% of panos have valid JSON after one retry; fewer than 2% have an empty `summary`.
- Report: agreement rate between `room_type` and the Matterport room label on residential-labelled rooms (information only, no threshold).
- Human: `mundus qa captions` writes `data/reports/captions.html` with 30 random panos (4 face thumbnails next to the caption). One person reads it for 5 minutes and signs off. If more than 3 of 30 contain a clear invention, tighten the prompt and rerun with a new prompt version.

Derived cards (step `cards`, zero model calls):
- **Room card:** label, dimensions, then the summaries and object lists of its panos, deduplicated.
- **Space card:** name, kind, Matterport AI summary, room table (label, area), then room cards.
- **Place card:** name, address, type, size, year; counts of listings, tenancies, sales with the most recent of each; Vexcel attributes; list of spaces by kind.

---

## 6. World API

Base URL: `https://<vm-ip-with-dashes>.sslip.io` (see 9.4). Prefix `/v1`. JSON only, except image routes.

### 6.1 Conventions

- **Auth:** header `Authorization: Bearer <WORLD_API_TOKEN>`. Image routes also accept `?token=` so they work in `<img>` tags. `/healthz` is open.
- **Evidence:** every object that states a fact has `evidence_id`. Lists of records carry it per item.
- **Pagination:** `limit` (default 20, max 100) and `cursor` (opaque string). Responses carry `next_cursor`, absent on the last page.
- **Errors:** HTTP status plus

```json
{"error": {"code": "not_found", "message": "No place with id place:costar:123", "details": {}}}
```

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_argument` | 400 | Bad or missing parameter |
| `unauthorized` | 401 | Missing or wrong token |
| `not_found` | 404 | Unknown id |
| `not_ingested` | 409 | The id exists but is below the depth the call needs; `details.depth` says what is available |
| `sql_rejected` | 400 | SQL tool refused the statement; `details.reason` |
| `upstream_unavailable` | 503 | A live upstream call failed and no cache entry exists |

### 6.2 Operations

| Operation | REST | Notes |
|---|---|---|
| `search_places` | `GET /v1/places/search?q=&lat=&lon=&radius_m=&type=&has_interior=&has_listing=&deep_only=&limit=&cursor=` | Text match on name and address (FTS5), distance filter, sorted by distance when `lat`/`lon` given, else by text rank |
| `get_place` | `GET /v1/places/{place_id}` | Full place bundle |
| `get_space` | `GET /v1/spaces/{space_id}` | Space, floors, rooms, pano list with caption summaries |
| `get_room` | `GET /v1/rooms/{room_id}` | Room, polygon, panos with full captions |
| `get_pano` | `GET /v1/panos/{pano_id}` | Position, room, caption JSON, face URLs |
| `get_pano_image` | `GET /v1/panos/{pano_id}/image?face=1&defurnished=false&size=2k|thumb` | JPEG bytes from disk. `Cache-Control: public, max-age=86400` |
| `get_floorplan` | `GET /v1/spaces/{space_id}/floorplans` and `GET /v1/floors/{floor_id}/plan` | Metadata (origin, pixels per metre) and image bytes |
| `search_interiors` | `POST /v1/interiors/search` body `{text, place_id?, near?{lat,lon,radius_m}, kinds?["pano","room","space"], limit}` | Hybrid search, section 3.3 |
| `get_aerial` | `GET /v1/aerial/{place_id}` (facts) and `GET /v1/aerial/{place_id}/image?kind=ortho&size_m=80` | Kinds: `ortho`, `oblique-n`, `oblique-s`, `oblique-e`, `oblique-w`. Sizes for ortho: 80, 250 |
| `aerial_semantic_search` | `POST /v1/aerial/search` body `{text, lat, lon, radius_m, limit}` | Live Vexcel call, cached. Text queries only in v1 |
| `describe_market` | `GET /v1/market/schema` | Tables, columns, types, row counts, 3 sample values per column |
| `query_market` | `POST /v1/market/query` body `{sql, limit?}` | Read-only SQL, section 10 |
| `get_claims` | `GET /v1/places/{place_id}/claims?status=active` | |
| `put_claim` | `POST /v1/places/{place_id}/claims` | Section 8 |
| `invalidate_claim` | `POST /v1/claims/{claim_id}/invalidate` body `{reason, superseded_by?}` | |
| `get_evidence` | `GET /v1/evidence/{evidence_id}` | |
| Map layer | `GET /v1/map/spaces?bbox=&deep_only=` | GeoJSON points of LA spaces: `space_id, place_id, name, space_kind, depth` |
| Basemap | `GET /v1/map/basemap` | `basemap.json` as served by Matterport |
| Stats | `GET /v1/stats` | Counts per table, claims per place, API calls by cache status |
| Health | `GET /healthz` | `{"ok": true, "db": true, "deep_places": 10}` |

### 6.3 Response shapes (normative)

`get_place`:

```json
{
  "place_id": "place:costar:8810904",
  "name": "string", "address": "string", "lat": 34.0468, "lon": -118.2592,
  "property_type": "string", "building_sqft": 0, "year_built": 0, "floors": 0,
  "is_deep": true, "evidence_id": "ev:...",
  "card_text": "string",
  "spaces": [{"space_id": "space:abc", "name": "Pool", "space_kind": "amenity",
              "pano_count": 12, "room_count": 3, "depth": 4, "ai_summary": "string",
              "preview_url": "/v1/spaces/space:abc/preview", "showcase_url": "string", "evidence_id": "ev:..."}],
  "candidate_spaces": [],
  "market": {
    "listings":  {"count": 0, "items": [{"row_id": "...", "evidence_id": "ev:...", "fields": {}}]},
    "tenancies": {"count": 0, "items": []},
    "sales":     {"count": 0, "items": []},
    "apartment_listings": {"count": 0, "items": []}
  },
  "aerial": {"aerial_id": "aerial:place:costar:8810904", "footprint_wkt": "POLYGON(...)", "parcel_wkt": "POLYGON(...)",
             "attributes": {}, "images": [{"kind": "ortho", "size_m": 80, "url": "/v1/aerial/.../image?kind=ortho&size_m=80", "evidence_id": "ev:..."}],
             "evidence_id": "ev:..."},
  "claims": [{"claim_id": "claim:...", "statement": "string", "confidence": 0.8, "evidence_ids": ["ev:..."], "status": "active"}],
  "nearby_places": [{"place_id": "...", "name": "...", "distance_m": 310}]
}
```

`market.*.items` holds at most 10 items each, newest first; `count` is the true total. More rows come from `query_market`.

`search_interiors`:

```json
{"mode": "hybrid", "hits": [
  {"kind": "pano", "id": "pano:abc:xyz", "score": 0.83, "space_id": "space:abc", "room_id": "room:abc:r1",
   "place_id": "place:costar:8810904", "title": "Fitness Center, position 4", "snippet": "string",
   "thumb_url": "/v1/panos/pano:abc:xyz/image?face=1&size=thumb", "evidence_id": "ev:..."}]}
```

`get_evidence`:

```json
{"evidence_id": "ev:...", "type": "pano_caption", "source": "derived", "source_id": "pano:abc:xyz",
 "place_id": "place:costar:8810904", "url": "/v1/panos/pano:abc:xyz", "excerpt": "string, max 500 chars",
 "content_sha256": "hex", "fetched_at": "2026-11-14T18:00:00Z"}
```

`query_market`:

```json
{"columns": ["col_a", "col_b"], "rows": [[1, "x"]], "row_count": 1, "truncated": false, "elapsed_ms": 4}
```

---

## 7. MCP server

Same process, mounted at `/mcp`, streamable HTTP transport, built with the official Python `mcp` SDK (FastMCP). The Harness connects with `langchain-mcp-adapters`. Auth: same bearer token as a request header. Every tool is a thin wrapper over the same service function the REST route calls, so behaviour cannot drift.

Tool results are JSON text. Results are trimmed for model context: long lists are capped, and each result ends with a `hint` field naming the next useful tool.

| Tool | Description shown to the model | Arguments |
|---|---|---|
| `search_places` | Find buildings in Los Angeles by name, address or location. Start here when you have an address or an area and need a place_id. Only places with `is_deep: true` have interiors, captions and aerial facts. | `query?: string`, `near?: {lat, lon, radius_m}`, `filters?: {type?, has_interior?, has_listing?, deep_only?}`, `limit?: int = 10` |
| `get_place` | Get everything known about one building: market records (listings, tenants, sales), its interior spaces, aerial facts, and claims that earlier agents already established. Read `claims` first: if a claim answers your question, cite it and skip the expensive work. | `place_id: string` |
| `get_space` | Get one scanned interior space (one Matterport model): summary, rooms with sizes, and the camera positions with short captions. | `space_id: string` |
| `get_room` | Get one room: dimensions, floor polygon, and full visual captions of each camera position in it. | `room_id: string` |
| `view_pano` | Get the caption for one camera position and, when `include_image` is true, the actual photo so you can look at it yourself. Use the image only when the caption does not answer the question: images cost far more tokens. | `pano_id: string`, `face?: int 1..4 = 1`, `defurnished?: bool = false`, `include_image?: bool = false` |
| `search_interiors` | Search inside buildings by what is visible, in plain words, for example "gym with free weights and mirrors" or "kitchen with an island". Returns matching camera positions, rooms and spaces. | `text: string`, `place_id?: string`, `near?: {lat, lon, radius_m}`, `kinds?: string[]`, `limit?: int = 10` |
| `get_aerial` | Get what is visible from above for a building: footprint and parcel outline, roof and site attributes, and links to top-down and angled aerial photos. Set `include_image` to look at one photo. | `place_id: string`, `kind?: string = "ortho"`, `size_m?: int = 80`, `include_image?: bool = false` |
| `aerial_semantic_search` | Search aerial imagery around a point by description, for example "parking structure" or "rooftop solar". This calls a live service and can take a few seconds. | `text: string`, `lat: number`, `lon: number`, `radius_m?: int = 1000`, `limit?: int = 10` |
| `describe_market` | List the market data tables, their columns and sample values. Call this once before writing SQL. | none |
| `query_market` | Run one read-only SQL SELECT (SQLite dialect) over the CoStar market tables. Use for counts, comparisons and anything across many buildings. Every table has `place_id` and `evidence_id` columns: include `evidence_id` in your SELECT so you can cite rows. | `sql: string`, `limit?: int = 50` |
| `get_claims` | Read the facts earlier agents established about a place, each with its evidence. Cheaper than rediscovering them. | `place_id: string`, `status?: string = "active"` |
| `put_claim` | Save a fact you established about a place so future questions are answered from memory. Requires at least one evidence id. Give `subject`, `predicate` and `value` when the fact is a single attribute (for example subject "roof", predicate "has_solar", value "false") so conflicts with earlier claims are detected. Read the `conflicts` in the response. | `place_id`, `statement`, `evidence_ids: string[]`, `confidence: number 0..1`, `subject?`, `predicate?`, `value?`, `created_by?` |
| `invalidate_claim` | Mark a claim as wrong or replaced. Use after you find stronger evidence against it. | `claim_id`, `reason`, `superseded_by?` |
| `get_evidence` | Resolve an evidence id to its source, excerpt and link. | `evidence_id: string` |

`view_pano` and `get_aerial` with `include_image: true` return an MCP image content block (768 px JPEG) after the JSON text block.

---

## 8. Claims and memory store

```sql
CREATE TABLE claim (
  claim_id TEXT PRIMARY KEY,            -- claim:<16 hex>
  place_id TEXT NOT NULL,
  scope_id TEXT,                        -- optional narrower target: space, room or pano id
  statement TEXT NOT NULL,
  subject TEXT, predicate TEXT, value TEXT,   -- optional structured form
  evidence_ids TEXT NOT NULL,           -- JSON array, sorted
  evidence_sha TEXT NOT NULL,           -- JSON map evidence_id -> content_sha256 at write time
  confidence REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',     -- active|superseded|retracted|stale
  superseded_by TEXT, invalid_reason TEXT,
  created_by TEXT, run_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  seen_count INTEGER NOT NULL DEFAULT 1,
  read_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX claim_place ON claim(place_id, status);
CREATE INDEX claim_key ON claim(place_id, subject, predicate);
```

- **Hash:** `claim_id = "claim:" + first 16 hex of sha256(place_id + "\n" + normalise(statement) + "\n" + sorted evidence ids joined by ",")`. `normalise` lower-cases, collapses whitespace, strips trailing punctuation.
- **Evidence id hash:** `ev:` + first 16 hex of sha256(type + "|" + source_id + "|" + content_sha256).
- **Validation on write:** at least 1 evidence id; every id must exist; `confidence` in [0, 1]; statement 10 to 500 characters. Otherwise `invalid_argument`.
- **Dedupe:** same `claim_id` already present: increment `seen_count`, return the existing claim with `"created": false`. No second row.
- **Conflict detection (deterministic, zero model calls):** when `subject` and `predicate` are given, find active claims on the same `place_id` (and same `scope_id`) with the same lower-cased `subject` and `predicate` and a different `value`. Return them in `conflicts`. Both claims stay active: the writing agent decides, then calls `invalidate_claim`. Claims without the structured form skip this check.
- **Near-duplicate hint:** also return up to 3 active claims on the same place whose statement shares at least 0.8 Jaccard similarity on word sets, as `similar`. Information only.
- **Invalidation:** `invalidate_claim` sets `retracted`, or `superseded` when `superseded_by` is given. Rows are never deleted.
- **Staleness:** after any ingest step rewrites an evidence row with a different `content_sha256`, claims citing it become `stale`. `get_claims` excludes stale claims by default.
- **The "cheaper and smarter" number:** `get_claims` and `get_place` increment `read_count`. `/v1/stats` reports, per place: active claims, claim reads, and expensive calls (`view_pano` with image, `aerial_semantic_search`, `query_market`). The Frontend can show this as the memory payoff.

`put_claim` response:

```json
{"claim": {"claim_id": "claim:...", "status": "active", "...": "..."}, "created": true,
 "conflicts": [{"claim_id": "claim:...", "statement": "...", "value": "true"}], "similar": []}
```

Open question 4 is answered: the backend database is the source of truth. The Harness may mirror claims into `/world/places/<place_id>/claims.jsonl` in its virtual file system for the deepagents file story, but it writes through `put_claim` first and treats the file as a copy.

---

## 9. Performance and reliability

### 9.1 Latency targets (on the VM, measured server-side)

| Call | p95 target |
|---|---|
| `get_place`, `get_space`, `get_room`, `get_pano`, `get_claims`, `get_evidence` | 100 ms |
| Image routes (disk read) | 100 ms |
| `search_places` | 150 ms |
| `search_interiors`, cached query embedding | 150 ms |
| `search_interiors`, new query | 900 ms (one Gemini embedding call) |
| `query_market` | 500 ms, hard timeout 3 s |
| `aerial_semantic_search`, cached | 100 ms |
| `aerial_semantic_search`, new | 5 s, hard timeout 10 s |

### 9.2 Caching layers
1. Disk: all image bytes, raw upstream JSON.
2. SQLite: all structured data, embeddings, query embedding cache, aerial search cache.
3. Memory: vector matrix and id list loaded at startup; LRU cache (512 entries) of serialised `get_place` and `get_space` responses, cleared for a place when a claim on it changes.

### 9.3 Live dependencies during the demo
None for reads of the 10 buildings. Two calls go out live: the Gemini embedding of a new search query (falls back to text search) and `aerial_semantic_search` (falls back to `upstream_unavailable`). `mundus warmup --queries config/demo_queries.txt` pre-embeds and pre-runs the demo's queries so both are cache hits.

### 9.4 Deployment
- One `e2-standard-2` VM (2 vCPU, 8 GB), 30 GB disk, Ubuntu 24.04, region `us-east4`. Firewall: 80 and 443 open.
- Process: `uvicorn` on `127.0.0.1:8000`, run by systemd with restart on failure.
- TLS: Caddy reverse proxy with the hostname `<ip-with-dashes>.sslip.io`, which gets an automatic certificate (moderate). HTTPS matters because a Frontend served over HTTPS cannot call an HTTP API.
- CORS: allow the Frontend origins listed in `CORS_ORIGINS`.

### 9.5 Offline fallback
The VM choice makes the demo depend on venue wifi. Mitigation, required not optional:
- `mundus snapshot` writes `world-<timestamp>.tar.zst` (database plus `data/img`) and uploads it to a Cloud Storage bucket.
- `mundus restore <file>` plus `mundus serve` brings up an identical API on a laptop in under 5 minutes.
- Frontend and Harness read the base URL from `WORLD_API_URL`, so switching to `http://localhost:8000` is one variable.
- Acceptance: restore on one teammate laptop is tested before Saturday midnight.

---

## 10. Security

- Secrets come from environment variables or a git-ignored `.env`: `MATTERPORT_API_KEY`, `MATTERPORT_API_TOKEN`, `VEXCEL_API_KEY`, `COSTAR_KIT_URL`, `COSTAR_ZIP_PASSWORD`, `GEMINI_API_KEY`, `WORLD_API_TOKEN`. `.env.example` lists names with empty values.
- The repository is public. `data/`, `.env` and the kit are in `.gitignore` from the first commit. A pre-commit check fails if a staged file is larger than 1 MB or matches a key pattern.
- Logs never contain keys, `Authorization` headers, or query strings of upstream URLs (the Vexcel GET style puts the key in the URL: use the header style only).
- Signed Matterport URLs are never stored or returned.
- The Matterport SDK key belongs to the Frontend. The backend does not hold it.
- **SQL tool guard, three layers:**
  1. Separate SQLite connection opened read-only (`mode=ro`) with `PRAGMA query_only = ON`.
  2. An authorizer callback that allows only `SELECT`, `READ` and `FUNCTION` actions and denies reads of any table not named `costar_*`, `place`, `space`. `ATTACH`, `PRAGMA` and `load_extension` are denied.
  3. Statement checks: exactly one statement, must start with `SELECT` or `WITH`, results capped at `limit` (max 500 rows), progress handler aborts after 3 seconds.
- The token is a shared secret in a browser app, so it is weak protection. It stops casual scraping of licensed data from a public IP. That is the goal for 48 hours.

---

## 11. Build plan

Layout: `backend/` with package `mundus_world`, Python 3.11, `uv`, FastAPI, `httpx`, `pydantic`, `numpy`, `pandas`, `shapely`, `pillow`, `mcp`, `google-genai`, `pytest`. Tasks run in order; B4 to B7 can run in parallel after B3. Tests that need keys are marked LIVE and skip with a clear message when the key is absent.

| # | Task | Acceptance test |
|---|---|---|
| B0 | Repo skeleton, `.gitignore`, `.env.example`, config loader, CLI entry `mundus`, schema migration that creates all tables | `uv run mundus --help` lists `ingest`, `serve`, `snapshot`, `restore`, `warmup`, `qa`. `pytest` passes. `git status` shows no file under `data/` |
| B1 | HTTP client with per-host token bucket, retries, raw-response saving, ingest ledger | Unit test with a fake server: 20 calls at a 4 per second limit take at least 4 seconds; a 500-then-200 sequence succeeds; a 403 aborts the step; a rerun makes 0 requests |
| B2 | Step `index` | `space` has 14,945 rows; 5,734 have `is_la = 1`; 2,523 of those have a property id; `space_kind` counts for LA printed, with `unit` between 3,500 and 4,000 |
| B3 | Step `costar` (LIVE: needs kit) | 8 `costar_*` tables exist; counts within 1% of the expected table or a printed warning; `describe_market` output saved to `data/reports/market_schema.json`; unmatched report exists. **VERIFY result recorded:** how many of the 731 LA property ids from the index exist in the kit |
| B4 | Steps `select`, `basics`, `rooms` (LIVE) | `selection.json` has 10 places, each present in the kit. Every model of those places has `depth >= 3`. At least 90% of rooms have `polygon_quality = 'loop'`. **VERIFY results recorded:** 5 real AI summaries printed to `data/reports/summaries.md`; whether `visibility` allows Showcase embedding, saved for the Frontend |
| B5 | Step `panos` (LIVE) | At least 99% of expected face files exist and decode as JPEG; no URL containing `?t=` appears anywhere in the database; rerun downloads 0 files. **VERIFY result recorded:** face order and compass direction, from one contact sheet image |
| B6 | Step `aerial` (LIVE) | 10 `aerial_facts` rows; at least 8 have `match_method = contains`; 6 images per place on disk. **VERIFY result recorded:** list of attribute keys actually returned |
| B7 | Step `resolve` | Every pano of a deep space has `room_match` set; at least 70% are `inside`; `link` has one accepted row per deep space; distance mismatches listed |
| B8 | Step `caption` and `qa captions` (LIVE) | At least 98% of panos have a valid caption; HTML sheet renders 30 samples; rerun makes 0 model calls |
| B9 | Steps `cards`, `embed`, `evidence` | Every deep place, space, room has `card_text`; `embedding` row count equals document count; every row of every fact table has a non-null `evidence_id` that resolves |
| B10 | REST API, all routes of 6.2, error shapes, auth, CORS, OpenAPI at `/docs` | Contract tests: each route returns the shape of 6.3 against a fixture database; unknown id gives 404 `not_found`; missing token gives 401; `get_place` on a deep place returns non-empty `spaces`, `aerial`, and at least one non-empty `market` list |
| B11 | Search: hybrid ranking, query cache, text-only fallback | Fixture test: the query "treadmills" ranks a fitness pano first; with the embedding call mocked to hang, the response arrives under 1 second with `mode = text_only` |
| B12 | Claims: put, dedupe, conflicts, invalidate, staleness, stats | Writing the same claim twice gives one row with `seen_count = 2`; a second claim with the same subject and predicate and a different value returns the first in `conflicts`; a claim with an unknown evidence id is rejected; changing an evidence hash marks the claim `stale` |
| B13 | SQL guard | `SELECT count(*) FROM costar_sale` works; `DROP TABLE place`, `SELECT 1; SELECT 2`, `ATTACH`, `PRAGMA`, `SELECT * FROM claim` and a recursive query that runs forever are each rejected or aborted with `sql_rejected` |
| B14 | MCP server at `/mcp` | An MCP client lists exactly the 14 tools of section 7; `get_place` through MCP equals REST output; `view_pano` with `include_image` returns an image block |
| B15 | Deploy scripts: VM provisioning, systemd unit, Caddy config, `snapshot`, `restore`, `warmup` | `curl https://<host>/healthz` returns `deep_places: 10`; restore on a second machine passes the same check |
| B16 | Load check and `verify` step | 200 sequential `get_place` calls: p95 under 100 ms; `mundus ingest verify` exits 0 |
| B17 (P2) | `panos-defurnished`, T2-wide basics for all LA | Defurnished face files exist for flagged models; LA spaces with a summary flag have `ai_summary` text |

A fixture database (`tests/fixtures/world_small.db`: 1 place, 2 spaces, 4 rooms, 6 panos, synthetic kit rows) is built in B0 so B10 to B14 do not wait on live ingestion.

---

## 12. Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | The scan-rich buildings have few or no kit records (they are apartment buildings; tenancy data is likely concentrated in office and retail) | High | High: no data fusion on the hero buildings | Kit-aware selection in 1.2; alternates listed; if fewer than 10 pass, lower the model threshold from 8 to 5 (196 buildings qualify) |
| 2 | CoStar kit join fails or the kit schema differs from the docs | Moderate | High | Schema-agnostic loader, raw JSON kept, unmatched report, B3 runs first among live tasks |
| 3 | Venue wifi fails during judging | Moderate | High | Snapshot and local restore, tested before midnight (9.5) |
| 4 | Shared keys get throttled or revoked by another team's abuse | Moderate | Moderate | Ingest early; whole pipeline needs about 460 Matterport API calls; everything cached to disk |
| 5 | Captions invent details | Moderate | Moderate: a judge checks a claim against the photo | Factual prompt, temperature 0, human sample check, evidence link from every caption back to the photo |
| 6 | Models are private, so the Showcase embed is blocked | Unknown | Moderate for Frontend | All 6 faces stored and served, so a cube-map viewer works without Matterport |
| 7 | Vexcel `property/extract` shape differs or returns several buildings per parcel | Moderate | Low | Raw JSON kept, defensive parser, `match_method` recorded |
| 8 | The "Hydrogen" model id or the embedding model id is wrong | Moderate | Low | Both are env vars; B8 and B9 fail fast with the provider's error |
| 9 | Room polygons do not close | Moderate | Low | Hull fallback with `polygon_quality` flag |
| 10 | Licensed data leaks from a public VM | Low | Moderate | Bearer token, no directory listing, VM deleted after the event |

---

## CONTRACT CHANGE PROPOSALS (carry to Frontend and Harness sessions)

**CCP-1. Depth scope.** Only 10 places are deep (`is_deep: true`). All other LA models are shallow spaces: index fields only, no rooms, panos, captions or aerial. Calls needing more return `409 not_ingested`. Frontend: style deep places differently on the map. Harness: pass `deep_only: true` by default.

**CCP-2. Geo place id format.** `place:geo:<lat>,<lon>` becomes `place:geo:<lat4>_<lon4>`, for example `place:geo:34.0468_-118.2592` (4 decimals, about 11 m). Commas in path segments cause encoding bugs.

**CCP-3. `query_market` is SQL only**, SQLite dialect, read-only. New companion tool `describe_market`. No structured query form.

**CCP-4. `get_pano_image` split.** REST returns JPEG bytes at a stable backend URL (never a Matterport URL). The MCP tool is named `view_pano` and returns the caption, plus an image block only when `include_image` is true. Same pattern on `get_aerial`.

**CCP-5. Claims.** `put_claim` gains optional `subject`, `predicate`, `value`, `scope_id`, `created_by`, `run_id`, and returns `{claim, created, conflicts, similar}`. New operation `invalidate_claim`. Claim statuses: `active`, `superseded`, `retracted`, `stale`. The backend database is the source of truth; `/world/places/<place_id>/claims.jsonl` is a mirror.

**CCP-6. Evidence** gains `content_sha256`, `fetched_at`, `source`. Types: `record`, `summary`, `room`, `pano_image`, `pano_caption`, `ortho_image`, `oblique_image`, `aerial_facts`, `floorplan`.

**CCP-7. New entities and routes.** `floor:<sid>:<floorId>` with floor plan metadata (origin, pixels per metre) so the Frontend can plot pano positions on the plan. `GET /v1/map/spaces` (GeoJSON), `GET /v1/map/basemap`, `GET /v1/stats`.

**CCP-8. Access.** One base URL in `WORLD_API_URL`, bearer token in `WORLD_API_TOKEN`, MCP at `<base>/mcp` (streamable HTTP), REST under `<base>/v1`.

**CCP-9. Pano to room link** is computed by the backend and may be null. `room_match` says how it was derived (`inside`, `nearest`, `none`).

**CCP-10. Space gains `space_kind`** (`unit`, `amenity`, `office`, `retail`, `industrial`, `common`, `home`, `other`) and `depth` (0, 2, 3, 4).

---

## Open items for Siddha

1. Supply the API id of the Gemini "Hydrogen" model for `CAPTION_MODEL`.
2. The live keys (Matterport pair, Vexcel, kit URL and password, Gemini) go into `.env` on the ingestion VM. No one has yet tested them against this spec's VERIFY items; B3 to B6 do that first.
3. Confirm or replace the provisional building list after B3 reports which property ids exist in the kit.
