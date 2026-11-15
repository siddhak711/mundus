# Backend Spec: World Context Layer (v1, 15-place evaluation set)

Status: draft for Siddha's review, then merge with the Frontend and Harness specs.
Owner: Backend session. Date: 2026-11-14.

Confidence labels: (high), (moderate), (low). "VERIFY" marks a fact that no one has tested with live keys. Every VERIFY item has an acceptance test in section 11 and a fallback.

## Decisions taken in this session

| Decision | Choice | Source |
|---|---|---|
| Depth scope | 15 LA places chosen for variety, as the evaluation set for the agent harness (section 1.2). Everything deep (rooms, panos, captions, Vexcel) is for these 15 only | Siddha |
| Hosting | One Google Cloud VM serves the World API to all three components | Siddha |
| Caption and embedding provider | Gemini for both, billed to the Google Cloud credits | Siddha |
| Database | One SQLite file (WAL mode). No separate vector database | Backend session, see 3.1 |
| Claims store | Backend database is the single source of truth | Shared kit recommendation, adopted |
| Live key verification | Done for Matterport, Vexcel and Gemini on 2026-11-14 (results below). Not done for the CoStar kit: `COSTAR_KIT_URL` is missing | See next table |

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

Live verification results (2026-11-14, real keys, about 40 requests in total):

| Check | Result | Confidence |
|---|---|---|
| Matterport key pair | Works. Root folder "HackPrinceton 2026", 14,945 models | high |
| Model visibility | `public` on all 6 models checked, so the Showcase embed should work | moderate (6 models checked, all in apartment buildings) |
| AI summaries | Real, one sentence of 25 to 40 words, listing tone. Example (Pool, 5ccpzGRBuXZ): "A modern outdoor amenity deck in downtown Los Angeles featuring a resort-style pool, spacious sun terrace, and a covered cabana lounge with urban skyline views." | high |
| `propertyClassifications` | Unreliable. Two studio apartments came back as `education` and `healthcare`; amenity spaces came back empty. Do not use it for `space_kind` | high |
| Rooms query | Works. Rooms include a `Void` room with no dimensions; `height` is missing on some rooms | high |
| Floor plans | 8 assets per model: JPG and PNG renders at 100 pixels per metre with origin, plus schematic DXF and PNG | high |
| Skybox faces | 6 signed URLs per pano on host `cdn-2.matterport.com`, query keys `t` and `k`. Each face is 2048 x 2048 JPEG, 0.5 to 1.0 MB. 6 faces downloaded in 2.6 seconds | high |
| Defurnished view | View id returned for a model flagged `defurnished = yes` | high |
| Vexcel `property/extract` | Returns a GeoJSON FeatureCollection. One feature per **parcel**: `geometry` is the parcel, `properties.structures[]` holds each building with `footprint.wkt`, `footprint.area` and roof attributes; parcel-level keys cover pool, vehicles, hardscape, tree cover, sport court | high |
| Vexcel coverage of the 15 places | All 15 return a parcel when queried at the kit's coordinates. 11 include at least one structure; 4 return a parcel with 0 structures. A point with no parcel returns HTTP 404 and answers with a 25 m square polygon instead (seen when querying at model coordinates) | high |
| Vexcel ortho | Works, 80 x 80 m at zoom 21 is a 439 KB JPEG | high |
| Vexcel embedding search | Works. Features carry only `score`, `source.product-type` and a geometry | high |
| Gemini caption model | `gemini-4-hydrogen` exists and produced a detailed, accurate JSON caption of a real pano (found the life ring, rescue pole, spa rules sign, emergency shutoff). 31.5 seconds per call, 4,595 input tokens, 760 output tokens, 3,036 thinking tokens | high |
| Gemini embeddings | `gemini-embedding-001` returns 768 dimensions on request, 0.32 seconds | high |
| CoStar kit | Downloaded (51.7 MB zip, 423 MB unzipped) and opened with the password. 8 JSON Lines files in `data/`; record counts match the documentation exactly (3,339 / 1,022 / 74,093 / 49,575 / 6,120 / 1,747 / 2,120 / 1,899). Field docs in `models/`, JSON Schemas and `enums.json` in `schemas/` | high |
| Commercial join | The kit's `commercial-properties.csv` (PropertyId, MatterportModelId) links 12,994 models to all 3,339 properties, and every one of those models is in `models_index.csv`. The index's own `costar_property_id` column covers only 6,191 models and disagrees with the kit on 224 of them (3.6%, mostly mistyped ids such as 1070785 for 10707085). 55 models are listed under more than one property | high |
| Residential join | The index's `homes_listing_id` matches the kit's `ResidentialListingId` (1,620 of 1,939), never `ListingId`. The kit's `residential-listings.csv` links 1,938 models, all present in the index | high |
| Child datasets | Every `propertyId` in occupancies, listings and apartment listings exists in the property file. Sale comps name 10,791 property ids of which 2,434 are in the kit (portfolio sales include outside properties) | high |
| Location agreement | Model geolocation against kit property coordinates, 9,863 pairs: median 33 m, 90th percentile 112 m, 512 pairs over 150 m, 70 over 1,000 m | high |
| LA composition | 1,581 LA properties: 1,417 multifamily, 98 office, 24 retail, 24 industrial, 10 flex, 8 other. 1,554 have at least one model; 147 have 8 or more | high |
| Where the market data is | Office buildings carry hundreds of tenancies each (Westside Towers East: 752). Apartment buildings carry 1 to 51 | high |

## As built (2026-11-14): differences from the sections below

The backend was built after `specs/harness.md` was read. Where the two specs differed, the harness contract won.
The code is the reference; these are the points where it departs from the text that follows.

| Topic | Sections below say | Built as |
|---|---|---|
| Claim model (section 8) | Keyed on place and statement; conflicts returned, both stay active | `subject_id` is any node; fixed predicate vocabulary in `shared/predicates.yaml`; id is a hash of subject, predicate and normalised value; statuses `active`, `superseded`, `disputed`, `stale`; outcomes `created`, `merged`, `superseded_old`, `rejected_lower_rank`, `disputed`, decided by evidence rank |
| Numeric tolerance | Not specified | Numbers within 5% are the same fact, except predicates flagged `exact` (years, counts) |
| Knowledge graph | None | `edges` table built from joins and geometry, `get_neighbors`, room adjacency as `adjacent_to` edges |
| Images over MCP (section 7) | `view_pano` returns an image block | No image crosses MCP. REST serves `GET /v1/panos/{id}/faces/{face}` and `GET /v1/places/{id}/aerial` with `X-Evidence-Id` and `X-Content-Hash` headers (also without the `/v1` prefix) |
| MCP tools | 14 tools including `view_pano`, `get_aerial`, `invalidate_claim` | 13 tools: `search_places`, `get_place`, `get_space`, `get_room`, `search_interiors`, `get_aerial_facts`, `aerial_semantic_search`, `describe_market`, `query_market`, `get_neighbors`, `get_claims`, `put_claim`, `get_evidence` |
| `query_market` | 500 rows | 200 rows |
| Search | Captions and cards | Also indexes claim statements on panos, rooms and spaces |
| Floor plans | Columns on `floor` | Own table `floorplan`: the Matterport response does not tie a plan to a floor |
| CoStar tables | Columns listed by hand | Columns generated by flattening each record two levels deep; integer codes get a `_label` twin; contact fields are never stored |
| Captions (section 5) | Short summary and lists | In-depth description of 280 to 400 words plus structured fields; length set by `CAPTION_DETAIL`; `mundus qa caption-lengths` compares four lengths |
| Caption fallback | One fallback model | A list (`CAPTION_FALLBACK_MODELS`); a model whose daily quota is spent is skipped for the rest of the run |
| Token tracking | Not specified | Every backend model call is logged to `model_usage` and reported by `/v1/stats` |
| Card | Rendered by the harness | Rendered by the backend at `GET /v1/places/{id}/card`, including the `coverage:` line |

Verified by the two-place smoke run (The Preserve and the Royal Viking Motel): 9 spaces, 96 selected panos, 702 image
files, both aerial records with all 6 images each, 90 of 96 captions (the Gemini free tier ran out), `get_place` in
8 ms with all three layers present.

---

## 1. Scope

### 1.1 Depth tiers

| Tier | Content | Scope in v1 | Priority |
|---|---|---|---|
| T0 | `models_index.csv`, `basemap.json` | All 14,945 rows loaded; LA flag set by lon < -110 | P0 |
| T1 | CoStar kit, all 8 datasets + 2 starter CSVs | All records | P0 |
| T2 | Matterport Basics (summary, type, counts, preview image) | The 15 places (108 models) | P0 |
| T3 | Rooms, walls, floor plans, pano positions | The 15 places | P0 |
| T4 | Pano image bytes (6 faces, 2k) and captions | At most 20 panos per space (Siddha's cap): 1,270 of the 2,175 panos in the 15 places | P0 |
| T4d | Defurnished pano bytes | Models in the 15 places that have them (49 models) | P1: the evaluation set relies on them |
| T4s | Drone photos for splat models (places 13 and 15): up to 12 photos per model, with GPS and gimbal angles read from XMP | 9 models | P1 |
| T5 | Vexcel elements, ortho, 4 obliques | The 15 places | P0 |
| T6 | Vexcel embedding search | Live tool, cached by query | P1 |
| T2-wide | Matterport Basics for all 5,734 LA models | Stretch: about 24 minutes at 4 requests per second | P2 |
| T7 | MatterPak, splat PLY files | Out of scope for v1 | Not built |

The other 5,700 LA models still appear in the API as shallow Space records (index fields only), so the map is full and the 15 deep places stand out.

### 1.2 Building selection: the 15-place evaluation set

Purpose changed on 2026-11-14: the deep set is the test bed for evaluating the agent harness, so it is chosen for variety, not for scan count or market depth. Each place covers a situation the other 14 do not. The list is curated and fixed in `config/selection.json` (committed, ids only). There is no scoring step.

All 15 were checked against the kit, the index and Vexcel on 2026-11-14.

| # | Id | Name and address | Type | Built | Storeys | Size (sq ft) | Models | Panos |
|---|---|---|---|---|---|---|---|---|
| 1 | 246941 | Westside Towers East, 11835 Olympic Blvd | Office | n/a | 12 | 244,392 | 8 | 448 |
| 2 | 120125 | The Granada Buildings, 672 La Fayette Park Pl | Office | 1927 | 4 | 54,612 | 6 | 198 |
| 3 | 11104240 | The Preserve, 1370 St Andrews Pl | Office | 2017 | 2 | 96,808 | 5 | 102 |
| 4 | 9134890 | 600 La Brea Ave | Retail | 2013 | 5 | 13,736 | 8 | 225 |
| 5 | 6067080 | Wall Street Garment Center, 510 Olympic Blvd | Retail | 1993 | 1 | 19,500 | 4 | 70 |
| 6 | 755901 | 1601 Perrino Pl | Industrial | 1969 | 1 | 70,565 | 4 | 83 |
| 7 | 5576060 | Bridge & Corner, 1451 4th St | Flex | 1924 | 2 | 43,964 | 1 | 67 |
| 8 | 4164481 | Royal Viking Motel, 2025 3rd St | Hospitality | 1961 | 2 | 19,995 | 4 | 21 |
| 9 | 255445 | The Annex, 5340 Alla Rd | Specialty | 1972 | 2 | 131,942 | 1 | 225 |
| 10 | 21290728 | Entitled development site, 7210 Western Ave | Land | none | none | none | 1 | 11 |
| 11 | 8810904 | Josephine DTLA, 801 Hope St | Multifamily | n/a | 22 | 300,000 | 17 | 202 |
| 12 | 256445 | Grether & Grether Lofts, 730 Los Angeles St | Multifamily | 1924 | 6 | 83,136 | 15 | 183 |
| 13 | 4025799 | Veteran Plaza, 512 Veteran Ave | Multifamily | 1986 | 4 | 58,512 | 8 | 126 |
| 14 | 20976526 | Cardinal Commons, 1286 35th Pl | Multifamily | 2025 | 3 | 7,090 | 25 | 110 |
| 15 | home 216888684 | 5134 Medina Rd (single-family home) | Residential | 2026 | 4 levels scanned | n/a | 1 | 104 |
| | Total | | | | | | 108 | 2,175 |

"Built: n/a" means this session did not extract the year for that property, not that the kit lacks it.

What each place has, and what it is in the set to test:

| # | Tenancies | Lease listings | Sale listings | Sales | Apartment listing | Scan content | Vexcel result | What it tests |
|---|---|---|---|---|---|---|---|---|
| 1 | 752 | 4 | 0 | 5 | no | 8 office suites | Parcel, 2 structures, pool flagged | Very large tenancy tables: aggregation, not listing |
| 2 | 152 | 1 | 0 | 2 | no | Suites scanned 2023, 2024, 2025 | Parcel, 3 structures | Historic low-rise; several structures on one parcel; scans from different years |
| 3 | 10 | 1 | 0 | 0 | no | Lobby and cafe, garden, courtyard, oval room | Parcel, 1 structure, 8 rooftop AC units | Outdoor and common-area scans in an office; no sales history; 29 kit amenities |
| 4 | 5 | 1 | 1 | 0 | no | Floors and a rooftop; 5 defurnished; 4 with no AI summary | Parcel, 0 structures | 3 models shared with a neighbouring property (836552); for lease and for sale at once; aerial has no footprint |
| 5 | 18 | 0 | 0 | 2 | no | 3 suites plus "Building Exterior & Loading Docks" | Parcel, 0 structures, 53 vehicles | Exterior scan; not on the market; aerial has no footprint |
| 6 | 14 | 1 | 1 | 5 | no | Warehouse, lobby and kitchen, office floor | Parcel, 1 structure, rooftop solar detected, 22 vehicles | Industrial interior; solar seen from above; long sale history |
| 7 | 44 | 2 | 0 | 1 | no | One 67-pano scan of a 45,000 sq ft office | Parcel, 1 structure, 20 rooftop AC units | One scan covers the whole building; many tenants, single space |
| 8 | 2 | 1 | 1 | 2 | no | 4 scans, all defurnished | Parcel, 1 structure, pool flagged, 23 vehicles | Hotel-type record; the index's property id is wrong on all 4 models; pool visible from above with no pool scan |
| 9 | 55 | 3 | 0 | 4 | no | One 225-pano scan of a 22,727 sq ft suite, no AI summary | Parcel, 2 structures, pool flagged, 46 vehicles | No summary to lean on: the agent must use captions; no type-specific kit block |
| 10 | 0 | 0 | 1 | 0 | no | One 11-pano scan, defurnished | Parcel, 0 structures | Almost everything is null: no building, no size, no tenants. Tests "the data does not say" |
| 11 | 18 | 3 listings in total | | 2 | yes | Pool, clubhouse, rooftop deck, fitness, 6 units; 6 defurnished | Parcel at the kit point holds a 23 sq m structure; the tower is on the adjacent parcel | Amenity-rich high-rise; rents by floor plan; aerial match needs the multi-parcel fallback |
| 12 | 51 | 2 | 0 | 2 | no | Lobby, clubhouse, spa, sundeck, two vacant retail spaces, lofts; scans from 2018 and 2020 | Parcel, 0 structures, pool flagged | Mixed use (apartments over retail); old scans; apartment building with no apartment listing |
| 13 | 1 | 0 | 0 | 2 | yes | 8 unit scans, all defurnished, all with splats and drone photos; 6 with no AI summary | Parcel, 1 structure, 43 rooftop AC units | Only units, no amenities; exterior drone imagery; furnished against defurnished comparison |
| 14 | 1 | 0 | 1 | 0 | no | 25 small scans of rooms and common areas, 24 defurnished | Parcel, 2 small structures | Tiny new co-living building with many scans; 4 models shared with property 21356901; for sale |
| 15 | n/a | n/a | n/a | n/a | n/a | One 104-pano, 36-room, 4-level scan; defurnished; splat; 408 drone photos; no AI summary | Parcel, 1 structure | Residential dataset instead of commercial: MLS listing at $2,295,550, 5 bedrooms; the same home has two MLS listing ids (235836573 with a features record, 235839859 hidden from the public with none) |

Coverage of the set:

| Dimension | Values covered |
|---|---|
| Property type | Office x3, Retail x2, Industrial, Flex, Hospitality, Specialty, Land, Multifamily x4, single-family home |
| Tenancy count | 0, 1, 1, 2, 5, 10, 14, 18, 18, 44, 51, 55, 152, 752 |
| Models per place | 1 (x4), 4 (x3), 5, 6, 8 (x3), 15, 17, 25 |
| Panos per place | 11 to 448 |
| Year built | 1924 to 2026, plus one site with no building |
| Storeys | 1 to 22 |
| Market status | Lease only, sale only, both, neither, apartment rental listing, MLS home listing |
| Interior text | Places where every model has an AI summary, some do, and none do |
| Defurnished | None, some, all |
| Splat and drone imagery | 2 places (13 and 15) |
| Aerial result | Footprint found, several structures, no structure, wrong parcel at the point |
| Known data defects | Wrong index property id (8), models shared across properties (4, 14), duplicate listings for one home (15), missing summary (4, 9, 13, 15), near-empty record (10) |

Held back as alternates: 5956257 (Healthcare, one lobby scan in a 154,799 sq ft building), 11044249 (sageLA: 32 models, and model coordinates that are thousands of kilometres off), 249530 (office with a lobby scan and defurnished suites), 246899 (office with a model 2.9 km from the property).

The home is not a kit commercial property. Its place id is `place:home:216888684` (the kit's `ResidentialListingId`, which groups the listings of one home). See CCP-11.

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
| 2 | `costar` | Kit zip at `COSTAR_KIT_URL`, password `COSTAR_ZIP_PASSWORD` | `costar_*` tables, `place` rows for all 1,581 LA commercial properties, `kit_model_link` rows, unmatched-id report | 1 download (51.7 MB) | 2 minutes |
| 3 | `select` | `config/selection.json` | `place.is_deep = 1` for 15 places (14 commercial properties and 1 home); fails if any id is missing from the kit | 0 | seconds |
| 4 | `basics` | Model ids of deep places | `space` rows updated (summary, classification, address), preview image bytes | 108 GraphQL + 108 images | 2 minutes |
| 5 | `rooms` | Same | `floor`, `room`, `wall_vertex`, `wall_edge`, `pano` (positions), floor plan images and DXF | 108 GraphQL + about 860 files | 4 minutes |
| 6 | `panos` | Same | 6 faces per pano at 2k on disk | 108 GraphQL + 7,620 images | 8 to 12 minutes at 8 concurrent (measured 0.43 s per face) |
| 7 | `panos-defurnished` (P1) | Models with a defurnished view | Defurnished faces on disk | 98 GraphQL + 2,586 images | 5 minutes |
| 8 | `aerial` | Deep places | `aerial_facts` rows, ortho x2 and oblique x4 images per place | 70 | 2 minutes |
| 9 | `resolve` | All of the above | `link` rows, pano to room assignment, `space_kind` | 0 | seconds |
| 10 | `caption` | Pano faces | `pano_caption` rows | 1,270 Gemini calls | 15 to 45 minutes, see section 5 |
| 11 | `cards` | Captions, rooms, kit, aerial | `room.card_text`, `space.card_text`, `place.card_text`; no model calls | 0 | seconds |
| 12 | `embed` | Card texts and captions | `embedding` rows | about 25 batched calls | 1 minute |
| 13 | `evidence` | All tables | `evidence` rows for every record, image and caption | 0 | seconds |
| 14 | `verify` | Database | Prints the acceptance report of section 11, exits non-zero on failure | 0 | seconds |

Step order note: pano selection needs room polygons, so `resolve` runs its pano-to-room and selection parts right after `rooms`, before `panos`. Total wall time from empty: about 45 to 75 minutes, dominated by captioning (moderate). Total Matterport API requests: about 450 GraphQL calls, well inside the shared-key budget.

### 2.3 Step details that are not obvious

- **`costar`:** the kit is one password-protected zip (traditional zip encryption, Python's `zipfile` opens it). Each dataset is `data/<dataset>.jsonl`, one record per line, with deep nesting (a property record has 39 top-level keys and arrays of attachments, contacts, floors, parking). Load each record's top-level scalar fields into columns, keep the whole record in `raw_json`, and add these extracted columns:
  - `costar_property`: `id`, `buildingName`, `propertyType` (decoded through `schemas/enums.json`), `primaryAddress.latitude`, `.longitude`, `.city`, `.postcode`, `.researchMarketId` (14 Houston, 20 Los Angeles), `rentableBuildingAreaSquareFeet`, `numStoriesAboveGrade`, year built from `constructionEvents`.
  - `costar_occupancy`: `propertyId`, `tenantLocationId`, `fromDate`, `moveInDate`, lease fields from `leaseDeal`, floor from `spaces[].propertyFloorId`.
  - `costar_sale`: one row per sale, plus a child table `costar_sale_entity(sale_id, property_id)` from `entities[].propertyId`, because a sale can cover several properties.
  - `costar_listing`: `propertyId`, `listingType`, `listingStatus`, fields of `forLeaseSummary`.
  - `costar_apartment_listing`: `propertyId`, rents, units available; child table of `apartmentModels[]` floor plans.
  - `costar_res_listing`: `id`, `residentialListingId`, price, status, `property.address` with coordinates.
  - Integer enum columns get a sibling `<name>_label` column decoded from `enums.json`, so the agent's SQL reads `property_type_label = 'Office'`.
  - `kit_model_link(property_id, sid)` from `commercial-properties.csv` and `kit_res_model_link(listing_id, residential_listing_id, sid)` from `residential-listings.csv`.
  - The kit's `models/*.md` field pages are copied to `data/kit_docs/` and their one-line field meanings feed `describe_market`.
  - Contact names, emails and phone numbers of brokers and agents are in the records. They are excluded from extracted columns and from the tables the SQL tool can read (`raw_json` is not selectable through `query_market`).
- **`rooms`:** a room's `boundary.edges` is an unordered set of wall edge ids. Build the polygon by chaining edges through shared vertex ids. If the chain does not close, store the convex hull of the edge vertices and set `room.polygon_quality = 'hull'`.
- **Pano cap:** `MAX_PANOS_PER_SPACE = 20` (config). The `rooms` step stores the position of every pano; the `resolve` step then marks at most 20 per space as `is_selected`, and only those are downloaded, captioned and embedded. 27 of the 108 spaces exceed the cap (largest: 225, 193 and 104 panos). Selection is deterministic so reruns pick the same panos:
  1. Spaces with 20 panos or fewer: select all.
  2. Otherwise, room coverage first: for each room, largest floor area first, select the pano nearest the room's centroid, until 20 are selected or every room with a pano has one.
  3. Fill the remaining slots by farthest-point sampling on (x, y, floor): repeatedly select the unselected pano farthest from all selected ones. Ties break on pano id.
  4. Record `room.pano_total` and `room.pano_selected`. Two spaces have more rooms than the cap (The Annex: 33 rooms; 5134 Medina Rd: 36 rooms), so some of their rooms end with `pano_selected = 0`.
- **`panos`:** store all 6 faces so the Frontend can run its own cube-map viewer if the Showcase embed is not possible. Face index semantics: 0 up, 1 to 4 horizon, 5 down. The compass direction of faces 1 to 4 is still VERIFY (B5).
- **`aerial`:** per deep place: `property/extract` at the place point; ortho at zoom 21 with bbox 80 x 80 m; ortho at bbox 250 x 250 m (context); the four obliques around the footprint with `buffer-meter=28`. `property/extract` returns parcels, each with a `structures` list (verified). Call it with the place point first. On HTTP 404, retry with a 25 m square polygon around the point. When several parcels or structures come back, keep the structure with the largest `footprint.area` whose footprint is within 50 m of the point, and its parcel. If the point query returns a parcel whose largest structure is under 100 sq m while the kit says the building is over 5,000 sq ft, run the 25 m polygon query as well and apply the same rule across all returned parcels (seen on 8810904, where the tower sits on the adjacent parcel). Store the raw JSON. Flatten parcel-level keys and the chosen structure's keys into `attributes_json`, dropping null values.

---

## 3. Storage design

### 3.1 Database choice

SQLite, one file `data/world.db`, WAL mode, opened by the single API process. Reasons:
- Data volume is tiny: about 140,000 kit rows, 15,000 spaces, 2,200 pano positions, 2,100 vectors.
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
  pano_total INTEGER, pano_selected INTEGER,   -- pano_selected = 0 means the room has no image or caption
  card_text TEXT, evidence_id TEXT
);
CREATE INDEX room_space ON room(space_id);

CREATE TABLE room_adjacency (
  room_a TEXT NOT NULL, room_b TEXT NOT NULL,    -- room_a < room_b, same space and floor
  shared_edge_ids TEXT NOT NULL,                 -- JSON array of wall edge ids
  shared_length_m REAL NOT NULL,
  edge_types TEXT,                               -- JSON array of distinct edge types on the shared boundary
  involves_void INTEGER NOT NULL DEFAULT 0,      -- 1 if either room is labelled Void
  PRIMARY KEY (room_a, room_b)
);

CREATE TABLE wall_vertex (vertex_id TEXT PRIMARY KEY, floor_id TEXT, x REAL, y REAL);
CREATE TABLE wall_edge (edge_id TEXT PRIMARY KEY, floor_id TEXT, v1 TEXT, v2 TEXT, type TEXT, thickness REAL);

CREATE TABLE pano (
  pano_id TEXT PRIMARY KEY,             -- pano:<sid>:<panoId>
  space_id TEXT NOT NULL, room_id TEXT, room_match TEXT,  -- inside|nearest|none
  label TEXT, x REAL, y REAL, z REAL,
  is_selected INTEGER NOT NULL DEFAULT 0,   -- 1 if inside the 20-per-space cap: only these have images and captions
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
CREATE TABLE api_log (ts TEXT, op TEXT, caller TEXT, run_id TEXT, ms REAL, cache TEXT, place_id TEXT, bytes_out INTEGER);
CREATE TABLE claim_archive (reset_id TEXT, archived_at TEXT, claim_json TEXT);
CREATE TABLE claim_snapshot (name TEXT, created_at TEXT, claim_json TEXT);
```

### 3.3 Vector index

| Item | Value |
|---|---|
| Documents | Pano caption text (1,270), room cards (about 700), space cards (108), place cards (15): about 2,100 vectors |
| Model | `EMBED_MODEL` env var, default `gemini-embedding-001` (verified) |
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

`data/` is git-ignored in full. Expected size: about 5.6 GB furnished, about 7.5 GB with defurnished (measured average 0.74 MB per 2k face). Use a 50 GB disk on the VM, not 30 GB.

---

## 4. Entity resolution

Order: id joins first, spatial joins second, nothing merged on a guess.

1. **Space to Place, id join:** the kit's `commercial-properties.csv` is the source of truth (12,994 models, all 3,339 properties). Link `method = id_join`, `confidence = 1.0`, `status = accepted`. The index's `costar_property_id` column is not used for joining: it covers half as many models and is wrong on 224. Where it disagrees with the kit, log it. The 55 models listed under more than one property get one accepted link per property.
2. **Sanity check on every id join:** compute haversine distance between the model's lat/lon and the kit property's lat/lon. Above 150 m: keep the link but add `note = 'distance_mismatch'` and log it. Above 1,000 m: set `status = candidate` and exclude from place responses.
3. **Space to Place, spatial:** for LA spaces with no property id, find kit properties within 40 m. Exactly one: link with `method = spatial`, `confidence = 0.6`, `status = candidate`. Several: one candidate link each with `confidence = 0.3`. Candidates are returned by the API in a separate `candidate_spaces` array and never mixed with accepted ones.
4. **Residential:** join through the kit's `residential-listings.csv` (`MatterportModelId` to `ListingId`). The index's `homes_listing_id` is a `ResidentialListingId`, not a `ListingId`, and must not be matched against listing `id`. Link `relation = listing_of_space`. These spaces get `place_id = place:geo:<lat4>_<lon4>`.
5. **Place to Vexcel:** call `property/extract` as described in 2.3. If the point lies inside a returned footprint: `match_method = contains`, distance 0. Otherwise take the nearest footprint within 50 m: `match_method = nearest`, distance recorded. No structure on the parcel (seen on 4 of the 15 places): store parcel only, `match_method = parcel_only`.
6. **Pano to Room:** point-in-polygon of the pano's (x, y) against room polygons on the same floor: `room_match = inside`. No hit: nearest room centroid within 3 m: `nearest`. Otherwise null and `none`.
6a. **Room adjacency:** two rooms on the same floor are adjacent when their `boundary.edges` sets share at least one wall edge id. Store one row per pair with the shared edge ids and the summed length of those edges. Checked on real data (model 1BToKRDx8fv): 5 rooms gave 7 adjacent pairs, shared lengths 0.68 to 4.19 m. Limits, both verified on that model: every edge has type `wall`, so adjacency means "shares a wall", not "connected by a door", and no walkable route can be derived from it; and `Void` rooms (shafts, unscanned areas) appear as neighbours, so they are flagged with `involves_void`. If other models return edge types besides `wall`, they are kept in `edge_types` and reported by the `verify` step.
7. **Unmatched report:** `mundus ingest resolve` prints and saves `data/reports/unmatched.json`: counts of index property ids missing from the kit, kit properties with no models, residential ids missing, distance mismatches.

`space_kind` rules, first match wins, on lower-cased name (deterministic, no model call). Matterport's `propertyClassifications` is not used: it was wrong on 2 of 6 models checked.

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
| Model | `CAPTION_MODEL` env var, default `gemini-4-hydrogen` (verified to exist and to caption well). Fallback `gemini-3.5-flash` |
| Unit of work | One call per pano: the 4 horizon faces (1 to 4), each downscaled to 1024 px, sent as 4 images in one request |
| Panos | The selected panos only: at most 20 per space, 1,270 in total (selection rule in 2.3) |
| Defurnished | Not captioned in v1. Furniture removal is generative, so captions of those images describe invented surfaces. Bytes are stored for display only (P2) |
| Context given | Space name, Matterport room label if assigned, room dimensions if assigned |
| Output | JSON, schema below, temperature 0 |
| Tokens | Measured per call: 4,595 input, about 3,800 output including thinking. For 1,270 panos: about 5.8 million input and 4.8 million output tokens. Dollar cost unknown: this session does not know the model's price |
| Time | Measured 31.5 seconds per call, mostly thinking. At 16 concurrent calls: about 45 minutes. Set the lowest thinking level the model accepts; if that cuts latency below 10 seconds, the job takes about 15 minutes. HTTP 503 "high demand" was seen on a sibling model, so retries with backoff are required |

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
| `get_space` | `GET /v1/spaces/{space_id}` | Space, floors, rooms, pano list with caption summaries, `room_adjacency: [[room_a, room_b, shared_length_m]]` |
| `get_room` | `GET /v1/rooms/{room_id}` | Room, polygon, panos with full captions, `adjacent_rooms: [{room_id, label, shared_length_m, involves_void}]` |
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
| Claims reset | `POST /v1/admin/claims/reset` body `{mode, name?, clear_caches?}` | Admin only, see 8.1. Not exposed as an MCP tool |
| Health | `GET /healthz` | `{"ok": true, "db": true, "deep_places": 15}` |

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
| `get_room` | Get one room: dimensions, floor polygon, full visual captions of each camera position in it, and which rooms share a wall with it. Sharing a wall does not mean there is a door: the data has no doors. | `room_id: string` |
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

### 8.1 Reset between evaluation runs

Agent-written claims carry over from one run to the next, so a later run reads answers an earlier run stored. Evaluation runs need a known starting state.

- **CLI:** `mundus claims reset [--mode empty|restore] [--name <snapshot>] [--clear-caches]`, `mundus claims snapshot --name <snapshot>`, `mundus claims list-snapshots`.
- **HTTP:** `POST /v1/admin/claims/reset` with the same options, so an evaluation runner can call it between runs without shell access. It requires a separate `WORLD_ADMIN_TOKEN`; the normal API token is refused with 401. It is never exposed through MCP, so an agent cannot wipe memory.
- **`mode = empty`** (default): archives all rows of `claim` into `claim_archive` with a `reset_id` and timestamp, then empties `claim`. Nothing is deleted for good.
- **`mode = restore`:** replaces `claim` with a named snapshot. This gives two controlled starting states for the memory comparison: cold (empty) and warm (a snapshot taken after a seeding run).
- **Also reset every time:** `claim.read_count` counters, the in-memory response cache, and the per-run counters behind `/v1/stats`.
- **`clear_caches = true`** additionally empties the query-embedding cache and the aerial-search cache. Leave it false by default: those caches hold upstream results, not agent knowledge, and clearing them adds network latency and variance to wall-clock measurements. Set it only to measure a fully cold system.
- **Never touched:** ingested data, captions, embeddings of documents, evidence rows.
- **Run tagging:** every request may carry header `X-Run-Id`. It is stored on `api_log` rows and on claims (`claim.run_id`), and `/v1/stats?run_id=` returns counts and latencies for that run alone. Sequential, interleaved runs therefore stay separable in the logs even without a reset.
- **Response:** `{"reset_id": "...", "archived": 42, "restored": 0, "caches_cleared": false}`.

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
None for reads of the 15 places. Two calls go out live: the Gemini embedding of a new search query (falls back to text search) and `aerial_semantic_search` (falls back to `upstream_unavailable`). `mundus warmup --queries config/demo_queries.txt` pre-embeds and pre-runs the demo's queries so both are cache hits.

### 9.4 Deployment
- One `e2-standard-2` VM (2 vCPU, 8 GB), 50 GB disk, Ubuntu 24.04, region `us-east4`. Firewall: 80 and 443 open.
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

- Secrets come from environment variables or a git-ignored `.env`: `MATTERPORT_API_KEY`, `MATTERPORT_API_TOKEN`, `VEXCEL_API_KEY`, `COSTAR_KIT_URL`, `COSTAR_ZIP_PASSWORD`, `GEMINI_KEY`, `WORLD_API_TOKEN`, `WORLD_ADMIN_TOKEN`. `.env.example` lists names with empty values.
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
| B3 | Step `costar` (LIVE: needs kit) | 8 `costar_*` tables exist; counts equal 3,339 / 1,022 / 74,093 / 49,575 / 6,120 / 1,747 / 2,120 / 1,899; `kit_model_link` has 13,096 rows over 12,994 distinct models; 1,581 places have market 20; the report lists 224 index-versus-kit id disagreements; `describe_market` output saved to `data/reports/market_schema.json` |
| B4 | Steps `select`, `basics`, `rooms` (LIVE) | 15 places are deep, matching the table in 1.2, including `place:home:216888684`. Every model of those places has `depth >= 3`. At least 90% of rooms have `polygon_quality = 'loop'`. **VERIFY results recorded:** 5 real AI summaries printed to `data/reports/summaries.md`; whether `visibility` allows Showcase embedding, saved for the Frontend |
| B5 | Step `panos` (LIVE) | No space has more than 20 selected panos; 1,270 panos are selected in total; at least 99% of expected face files (7,620) exist and decode as JPEG; no URL containing `?t=` appears anywhere in the database; rerun downloads 0 files. **VERIFY result recorded:** face order and compass direction, from one contact sheet image |
| B6 | Step `aerial` (LIVE) | 15 `aerial_facts` rows, each with a parcel; 11 have a footprint and 4 are `parcel_only` (9134890, 6067080, 21290728, 256445); for 8810904 the chosen structure is larger than 1,000 sq m (adjacent-parcel fallback); 6 images per place on disk |
| B7 | Step `resolve` | Every pano of a deep space has `room_match` set; at least 70% are `inside`; `link` has one accepted row per deep space; distance mismatches listed |
| B8 | Step `caption` and `qa captions` (LIVE) | At least 98% of panos have a valid caption; HTML sheet renders 30 samples; rerun makes 0 model calls |
| B9 | Steps `cards`, `embed`, `evidence` | Every deep place, space, room has `card_text`; `embedding` row count equals document count; every row of every fact table has a non-null `evidence_id` that resolves |
| B10 | REST API, all routes of 6.2, error shapes, auth, CORS, OpenAPI at `/docs` | Contract tests: each route returns the shape of 6.3 against a fixture database; unknown id gives 404 `not_found`; missing token gives 401; `get_place` on a deep place returns non-empty `spaces`, `aerial`, and at least one non-empty `market` list |
| B11 | Search: hybrid ranking, query cache, text-only fallback | Fixture test: the query "treadmills" ranks a fitness pano first; with the embedding call mocked to hang, the response arrives under 1 second with `mode = text_only` |
| B12 | Claims: put, dedupe, conflicts, invalidate, staleness, stats | Writing the same claim twice gives one row with `seen_count = 2`; a second claim with the same subject and predicate and a different value returns the first in `conflicts`; a claim with an unknown evidence id is rejected; changing an evidence hash marks the claim `stale` |
| B12a | Claims reset, snapshot, restore, run tagging (8.1) | After writing 3 claims, `reset` leaves `get_claims` empty and `claim_archive` holding 3; `snapshot` then `reset --mode restore` brings the same 3 claim ids back; the reset route returns 401 with the normal token and is absent from the MCP tool list; two requests with different `X-Run-Id` values appear separately in `/v1/stats?run_id=` |
| B7a | Room adjacency (section 4, 6a) | Fixture of model 1BToKRDx8fv gives exactly 7 adjacent pairs with Living Room to Kitchen at 4.19 m; every pair is symmetric and on one floor; `get_room` returns `adjacent_rooms` |
| B13 | SQL guard | `SELECT count(*) FROM costar_sale` works; `DROP TABLE place`, `SELECT 1; SELECT 2`, `ATTACH`, `PRAGMA`, `SELECT * FROM claim` and a recursive query that runs forever are each rejected or aborted with `sql_rejected` |
| B14 | MCP server at `/mcp` | An MCP client lists exactly the 14 tools of section 7; `get_place` through MCP equals REST output; `view_pano` with `include_image` returns an image block |
| B15 | Deploy scripts: VM provisioning, systemd unit, Caddy config, `snapshot`, `restore`, `warmup` | `curl https://<host>/healthz` returns `deep_places: 15`; restore on a second machine passes the same check |
| B16 | Load check and `verify` step | 200 sequential `get_place` calls: p95 under 100 ms; `mundus ingest verify` exits 0 |
| B17 (P2) | `panos-defurnished`, T2-wide basics for all LA | Defurnished face files exist for flagged models; LA spaces with a summary flag have `ai_summary` text |

A fixture database (`tests/fixtures/world_small.db`: 1 place, 2 spaces, 4 rooms, 6 panos, synthetic kit rows) is built in B0 so B10 to B14 do not wait on live ingestion.

---

## 12. Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | A set chosen for variety contains thin places by design (land site with no building, places with 0 to 2 tenancies) | Certain | Low for evaluation, moderate for a live demo | Demo storylines should use places 1, 2, 6, 11 or 12, which have depth in all three layers |
| 2 | Join built on the index's `costar_property_id` or `homes_listing_id` columns | High if the Matterport quickstart is copied | High: half the links missing, 224 wrong | Join through the kit's two starter CSVs only (section 4) |
| 12 | Broker and agent contact details in kit records leak through the API or SQL tool | Moderate | Moderate | Not extracted; `raw_json` not readable by `query_market` |
| 3 | Venue wifi fails during judging | Moderate | High | Snapshot and local restore, tested before midnight (9.5) |
| 4 | Shared keys get throttled or revoked by another team's abuse | Moderate | Moderate | Ingest early; whole pipeline needs about 460 Matterport API calls; everything cached to disk |
| 5 | Captions invent details | Moderate | Moderate: a judge checks a claim against the photo | Factual prompt, temperature 0, human sample check, evidence link from every caption back to the photo |
| 6 | Some models are private, so the Showcase embed is blocked | Low (6 of 6 checked are public) | Moderate for Frontend | All 6 faces stored and served, so a cube-map viewer works without Matterport |
| 7 | Vexcel `property/extract` shape differs or returns several buildings per parcel | Moderate | Low | Raw JSON kept, defensive parser, `match_method` recorded |
| 8 | Captioning is slow or the model returns 503 under load | Moderate | Moderate | 16 concurrent calls, lowest thinking level, backoff, fallback model, resumable ledger; start the job as soon as faces are on disk |
| 11 | Outbound network allowlists block image hosts | Seen in this session | Low | Hosts needed: `api.matterport.com`, `cdn-2.matterport.com`, `static.matterport.com`, `api.vexcelgroup.com`, `generativelanguage.googleapis.com`, plus the kit download host |
| 9 | Room polygons do not close | Moderate | Low | Hull fallback with `polygon_quality` flag |
| 10 | Licensed data leaks from a public VM | Low | Moderate | Bearer token, no directory listing, VM deleted after the event |

| 13 | The agent or an evaluation task treats "shares a wall" as "can walk between" | Moderate | Moderate: wrong route or egress answers | Tool description and field name say wall-sharing only; no door data exists in the Matterport fields we ingest |

---

## CONTRACT CHANGE PROPOSALS (carry to Frontend and Harness sessions)

**CCP-1. Depth scope.** Only 15 places are deep (`is_deep: true`). All other LA models are shallow spaces: index fields only, no rooms, panos, captions or aerial. Calls needing more return `409 not_ingested`. Frontend: style deep places differently on the map. Harness: pass `deep_only: true` by default.

**CCP-2. Geo place id format.** `place:geo:<lat>,<lon>` becomes `place:geo:<lat4>_<lon4>`, for example `place:geo:34.0468_-118.2592` (4 decimals, about 11 m). Commas in path segments cause encoding bugs.

**CCP-3. `query_market` is SQL only**, SQLite dialect, read-only. New companion tool `describe_market`. No structured query form.

**CCP-4. `get_pano_image` split.** REST returns JPEG bytes at a stable backend URL (never a Matterport URL). The MCP tool is named `view_pano` and returns the caption, plus an image block only when `include_image` is true. Same pattern on `get_aerial`.

**CCP-5. Claims.** `put_claim` gains optional `subject`, `predicate`, `value`, `scope_id`, `created_by`, `run_id`, and returns `{claim, created, conflicts, similar}`. New operation `invalidate_claim`. Claim statuses: `active`, `superseded`, `retracted`, `stale`. The backend database is the source of truth; `/world/places/<place_id>/claims.jsonl` is a mirror.

**CCP-6. Evidence** gains `content_sha256`, `fetched_at`, `source`. Types: `record`, `summary`, `room`, `pano_image`, `pano_caption`, `ortho_image`, `oblique_image`, `aerial_facts`, `floorplan`.

**CCP-7. New entities and routes.** `floor:<sid>:<floorId>` with floor plan metadata (origin, pixels per metre) so the Frontend can plot pano positions on the plan. `GET /v1/map/spaces` (GeoJSON), `GET /v1/map/basemap`, `GET /v1/stats`.

**CCP-8. Access.** One base URL in `WORLD_API_URL`, bearer token in `WORLD_API_TOKEN`, MCP at `<base>/mcp` (streamable HTTP), REST under `<base>/v1`.

**CCP-9. Pano to room link** is computed by the backend and may be null. `room_match` says how it was derived (`inside`, `nearest`, `none`).

**CCP-11. Home places.** A single-family home is a place with id `place:home:<ResidentialListingId>`. `get_place` on it returns `market.home_listings` (all MLS listings of that home, with price, status, beds, baths and the features record when one exists) instead of the commercial lists. `property_type` is `Residential`.

**CCP-13. Pano cap.** At most 20 panos per space have images and captions. `get_space` lists every pano position with `is_selected`; image and caption calls on an unselected pano return `409 not_ingested`. Each room carries `pano_total` and `pano_selected`. A room with `pano_selected: 0` has dimensions and a label but no visual evidence: the agent must say so, and evaluation questions about what such a room looks like have no answer in the data.

**CCP-14. Room adjacency.** `get_room` returns `adjacent_rooms` and `get_space` returns `room_adjacency`, derived from shared wall edges. It states which rooms share a wall and for what length. It does not state that a door or opening connects them: all edges checked have type `wall`.

**CCP-15. Claims reset and run tagging.** `POST /v1/admin/claims/reset` (admin token, not an MCP tool) empties or restores the claims store between evaluation runs. The Harness sends `X-Run-Id` on every World API and MCP request so cost and latency can be reported per run from `/v1/stats?run_id=`.

**CCP-12. Evaluation set.** The 15 deep places are fixed in `config/selection.json`. The Harness session can build evaluation questions against the coverage tables in section 1.2 of the backend spec.

**CCP-10. Space gains `space_kind`** (`unit`, `amenity`, `office`, `retail`, `industrial`, `common`, `home`, `other`) and `depth` (0, 2, 3, 4).

---

## Open items for Siddha

1. Confirm the 15-place evaluation set in 1.2, or name swaps from the alternates.
2. Carry the contract change proposals above to the Frontend and Harness sessions.
