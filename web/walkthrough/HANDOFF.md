# Handoff: Office-to-Apartment Floor Walkthrough (HackPrinceton F26, CoStar track)

Written 15 Nov 2026 at the end of a Cowork session with Pranava. This is the complete context for continuing in Claude Code. The working folder (`~/Downloads/hackprinceton/floor-mockup/`) holds the data. Everything below is verified from that session unless marked as an assumption.

> Repo note (added when this file was copied into the repo): `index.html` here is now the v12 viewer from `floor-mockup/` (with columns). `data/` and `pano/` are local symlinks to `floor-mockup/` and are gitignored. See README.md.

---

## 1. The project in one paragraph

Team "mundus" (repo: github.com/siddhak711/mundus, members siddhak711 / Siddha Kanthi, mad10116, Pranava as PranavaM39). The product idea, decided after a mentor check-in with CoStar: **a developer picks an eligible LA office building, flies into a vacant floor, sees it as it is today (real Matterport photos), strips it to an empty shell, and watches agents fill it with affordable one-bed apartments; then edits the layout, reviews cost/compliance on a 2-D plan, and sends it to an architect in one step.** The CoStar track scores 30% data use, 30% agentic depth, 25% usefulness, 15% demo polish. Submission deadline: Sunday 15 Nov, 8:00 am (Devpost). Judging 9:30 am to 2:30 pm.

The repo is now a Census "world API + deepagents harness" (backend/, harness/, eval/). The walkthrough is a **standalone front-end prototype** in `web/walkthrough/` (PR #6). It does not yet talk to the backend or the agent.

---

## 2. What was built: the floor walkthrough viewer

**Location on Pranava's Mac:** `~/Downloads/hackprinceton/floor-mockup/` (about 2.1 GB). Run with `start.command` (or `python3 -m http.server 8123` in that folder), open `http://localhost:8123`. Needs a local server, not `file://`. Everything is local and vendored, so it runs offline.

**Building:** The Oppenheimer Tower, 10880 Wilshire Blvd, Westwood, Los Angeles. CoStar property id **246826**. Built 1969, 24 floors, 618k SF, typical floor 24,499 SF. Full-floor Matterport scan of **Suite 1600** (floor 16), model id **`cEvQ8q5GKZd`**, 200 capture points, 26,711 SF listed, 20,493 SF scanned, ceiling 2.66 m (8 ft 9 in). Confirmed to be 10880 (scan name "10880 Wilshire - Suite 1600", CoStar link); Douglas Emmett's site lists a different Suite 1600 at 10960 Wilshire.

### Folder layout
```
floor-mockup/
  index.html          the whole viewer (single file, ES modules, three.js 0.160 + three-mesh-bvh)
  start.command       starts the local server and opens the browser
  vendor/             three.module.js, controls/OrbitControls.js, three-mesh-bvh.module.js
  data/               generated from the scan (LICENSED, never commit)
    scene.json        panos (id, position, quaternion), outline segments, floorY, bandRect, stats
    pos.bin / uv.bin / idx.bin / drop.bin   cleaned MatterPak mesh (484,656 tris); drop.bin = per-vertex class
    atlas0.jpg / atlas1.jpg                 mesh textures packed into 8192px atlases
    floorfill.png     clean carpet-colour floor with alpha; core painted rgb(52,58,66)
    walls.jpg + shell.json   photo-baked exterior window walls, core block outlines, 21 column candidates
    walk.png          walkable mask (8 px/m) for the empty floor
    band.png          daylight-zone overlay (within 30 ft of outer wall = 87% of scanned floor)
  pano/2k/<panoId>_<face>.jpg   200 x 6 skybox faces at 2048px (582 MB)
  pano/4k/<panoId>_<face>.jpg   same at 4096px (1.5 GB)
  _debug/             build scripts (see section 4) and debug images
  oppenheimer-suite-1600.html   obsolete first prototype (25 MB, embeds scan data) – can delete
```

### Viewer modes and controls (current, v12)
| Mode | What it shows | Controls |
|---|---|---|
| **Dollhouse** | cleaned textured mesh, ceiling/near walls hidden, glass ribbon on outline | drag rotate, scroll zoom, right-drag pan, double-click a spot to stand there |
| **Floor plan** | straight-down | drag pan, scroll zoom |
| **Walk inside (walls up)** | real 360° photo at each of the 200 capture points; white rings mark reachable points; click a ring/anywhere to move to the nearest point with a push-in fade (~0.5 s); 2K first, 4K swaps in on stop; mini-map bottom-left | drag look, scroll zoom (FOV), W/arrows step, Esc back |
| **Remove walls** (button or typed command "remove all the walls") | interior walls + furniture sink into the floor in a ripple (~3 s), scan floor/ceiling dissolve into the drawn floor and ceiling, exterior photo walls + core + **21 white columns rise**; reversible with "Bring walls back" | works from any mode (leaves walk first) |
| **Walk inside (walls down)** | the "empty shell": photo-baked window walls, drawn 2 ft ceiling tiles with light panels, clean carpet floor with daylight falloff, plain core walls, white columns | click floor to glide (4 m/s accel/decel), W A S D free walk with collision (walls, core, columns), mini-map click jumps |
| **Daylight zone** checkbox | amber/blue band overlay on floor in dollhouse/plan | |

Command box (bottom right) understands: remove/drop/clear walls, bring/put walls back, floor plan, dollhouse, walk inside.

**URL flags for debugging:** `?nohd=1` (no 4K), `?dbg=1` (wireframe), `?yaw=90` (pano yaw correction, 90 is correct), `?qfwd=1` (don't invert pano quaternion; wrong).

**Test hooks:** `window.__app = { panos, setMode, goTo, enterWalk, enterShell, shellMoveTo, markers, setWalls, camera, look(yaw,pitch), state() }`, `window.__U` (shader uniforms), `window.__ready`.

### Versions tried and rejected
Pranava rejected several movement experiments; the current file is the **original dot-to-dot photo walk + columns**. Rejected: continuous glide with photos projected on the mesh (warps at glass), routed multi-hop walks, "push/fade" with hidden dots, whole-photo shift with free positioning (bows straight lines), hop-chains. **Do not reintroduce free positioning in the photo walk**: the scan geometry is wrong at glass and every variant looked "warped" or "choppy".

---

## 3. Key technical findings (save hours)

**Matterport API** (`POST https://api.matterport.com/api/models/graph`, HTTP basic auth key:token, keep < 10 req/s):
- `panoLocations { id label position{x y z} rotation{x y z w} skybox(resolution:"4k"){children urlTemplate validUntil} }` – 6 faces per point, signed URLs expire in ~30 min. All 200 points had 2k and 4k.
- Skybox faces: 0 = up, 1-4 = sides turning right, 5 = down. Cube mapping used: three.js +x,-x,+y,-y,+z,-z = faces 2,4,0,5,1,3. Sampling direction = SWAP(x,z,y) · Rz(90°) · inverse(pano quaternion) · (point − panoPos) in scan coords (scan is z-up; three.js world = (x, z, −y)). Verified against the mesh.
- **`floors { vertices edges rooms{boundary} }` returned empty for this model** – no wall layout available; walls had to be inferred from the mesh.
- Rooms: 9, all classifications Void/Other (commercial scans are unlabeled; only the 1,930 residential models have room labels).
- `bundle(id:"mp:matterpak")` → 430 MB zip (cloud.xyz point cloud 1.2 GB uncompressed, OBJ 52 MB + 323 jpg textures). Pulled with HTTP range requests, skipping the point cloud (`_debug/rzip.py`, `gettex.py`). The API `assets.meshes` 50k OBJ has **no UVs**; use the MatterPak OBJ. The OBJ is not welded: weld by rounded position before finding connected components.
- The mesh breaks at windows (IR passes through glass): never show raw mesh close up; photos for eye level.

**Vexcel** (`X-API-KEY`, `https://api.vexcelgroup.com/v2`): property/extract, structure/extract, ortho/extract, dsm/extract, oriented/extract (obliques), elements/detect (SAM3 open-vocab), embedding/extract. Houston and LA only. All top candidate buildings had structure + parcel coverage.

**CoStar kit** (`~/Downloads/hackprinceton/costar-hackathon-kit/`): JSONL dumps (commercial-property 3,339; location-occupancy 74k; commercial-listing-summary 1,022; sale-comps 6,120; company-detail 49k; apartment-listing 1,747; residential-listings 2,120). `commercial-properties.csv` links PropertyId → MatterportModelId (13,096 links). 2,765 of 3,339 commercial properties are multifamily; 289 office. **models_index.csv is not needed.**

**Keys** are in `~/Downloads/hackprinceton/.env` (MATTERPORT_API_KEY, MATTERPORT_API_TOKEN, VEXCEL_API_KEY). Never commit; the repo .gitignore already excludes `.env`, `data/`, `**/data/`, `web/walkthrough/pano/`.

**Mesh cleaning recipe** (build3.py): drop faces outside the solid footprint (from the Matterport alpha floor plan, closed/opened morphologically), drop connected components < 1.5 m², classify faces: floor (normal up, < 0.12 m), ceiling (normal down, > 2.2 m), "deep" interior (> 0.4 m inside outer wall, not near core) → droppable; split shared vertices between classes so the vertex shader can sink only the interior.

**Shell recipe** (shell1-4.py): fit the outer wall as a rectangle from solid wall below the sills → **X −38.42..30.30, Y −10.30..24.40 (68.7 × 34.7 m ≈ 25,700 SF)**; bake each side at 160 px/m from the nearest capture point with line-of-sight (0.05 m runs, majority-smoothed, 14 px feathered joins); everything below the sill (row 347 of 435) replaced by drawn wall + baseboard; stretches with no clear photo or washed-out glass (18-30% per side) mirrored from the nearest good window. Core = big unscanned holes → simplified polygons (3 blocks).

**Columns** (cols1.py): slice mesh at knee/waist/under-ceiling, keep vertical surfaces present in all three, compact 0.25-1.3 m footprints, away from perimeter and core, merge within 1.3 m → 21 candidates; 16 "probable" (share a row/line with ≥ 2 others: a south row at y≈−1.9, a mirrored north row at y≈16.0, both ~9 m from the centre line y=7.05; an east line at x≈22). Stored in `data/shell.json` → `columns[{x,y,size,grade}]`. **Columns hidden inside partitions were not found** (west half of the floor is likely missing several). Treat as "probable structural column" until checked against a landlord floor plan (Douglas Emmett lists full-floor plans for floors 6, 7, 24 of this building; not fetched).

---

## 4. Build scripts (in `floor-mockup/_debug/`, run from `~/work/s1600/` with `~/work/gq.py`, `mp.py` helpers)
Order to regenerate: `rzip.py` + `gettex.py` (MatterPak OBJ + textures into `pak/`) → `build3.py` (mesh clean, atlases, drop flags, floorfill) → `getpanos.py 2k 150` / `4k 150` → `shell1.py` (outline) → `shell2.py plan` + `bake 0..3` → `shell4.py` (clean walls, core blocks, walk mask) → `shell3.py` (atlas walls.jpg, shell.json) → `cols1.py` + the merge snippet → shell.json columns. They assume the plan images `plan.jpg`, `plan_alpha.png` (+ .json) and `panos_full.json` from the API are present in the working dir. They are a record, not a one-command pipeline; porting them into `pipeline/` with paths as arguments is a good task.

---

## 5. Data research

**Hero buildings** (full ranking of all 289 office properties in `~/Downloads/hackprinceton/office-buildings-ranked.csv`):
1. The Launch at Airport Center, 5901 W Century Blvd (249530): 1968, 15 fl, 69% listed available, 32 priced spaces, 4 placed scans, room labels. Best conversion story.
2. The Oppenheimer Tower, 10880 Wilshire (246826): the only full-floor scan (Suite 1600) → built here.
3. Wells Fargo Plaza, Houston (233899): richest data, 71 fl, 7 scans placed, tenants since 1983.
4. The Tower, 10940 Wilshire (246836): 8 placed scans. 5. Century Park, 1880 Century Park E (247386). 6. 5757 W Century Blvd (256760): 42.6k SF floors = "hard to convert" contrast.

**Law** (for the pitch): LA Citywide Adaptive Reuse Ordinance, **Ordinance 188,793**, council Dec 2025, effective **1 Feb 2026**: commercial buildings ≥ 15 years old convert by-right via LADBS (5-15 yrs need a ZA conditional use permit); ≥ 5 units; no minimum unit size; existing FAR/parking/open space deemed compliant; affordable units optional but unlock +2 floors and unlimited density on added construction; linkage fee applies; downtown follows DTLA 2040; historic resources get extra review. NYC: 467-m tax incentive (Apr 2024, 25% affordable), City of Yes (Dec 2024, pre-1991 buildings citywide). Short-term rental is out: LA home-sharing ordinance = primary residence only, 120 nights; hotel conversion needs a Class 3 CUP.

**Comparable tools** (for positioning): Sasaki Office Shift Pro (unit-mix optimiser, no 3-D/daylight), Gensler conversion scorecard (100 data points, 1,300+ buildings, ~30% viable), Matterport defurnish/Project Genesis, World Labs Marble + Spark 2.0 (3DGS in three.js), Enscape/Twinmotion for walkthrough quality.

---

## 6. Agreed product flow (the spec to build toward)

1. **Find buildings**: filter by LA ARO eligibility (year built ≤ 2011, zone, not downtown) and vacancy (CoStar available SF). Show as a map.
2. **Pick a building, see the outside**: 3-D massing textured with Vexcel obliques, floors coloured leased/vacant (Census already has floor colouring + timeline; obliques are downloaded but not yet mapped onto walls).
3. **Click a floor → fly inside**: the walkthrough above (only floors with a full-floor scan; Suite 1600 is the one). Chat assistant stays open on the side.
4. **Three toggles**: Initial view (built), Empty view (built: walls down + columns), **Apartment view (next)**.
5. **Apartment view**: agents (layout / compliance / cost) design the floor; walls rise in 3-D along the window band; bedroom at the window, kitchen/bath at the corridor; one-bed one-bath default.
6. **2-D plan + analysis**: unit count/mix, compliance (ARO age rule, light, egress, accessibility), cost (plumbing risers, meters, linkage fee) vs rent (nearby CoStar apartment comps: 35 buildings within 2 km of 10880).
7. **Edit layout** (move/add walls, numbers update). 8. **Send to architect** (PDF/CAD, one click).

Open decisions not yet answered: affordable share (100% vs mixed), what "send to architect" means (email/link), whether agents are visible characters with plain formulas underneath.

### Suggested next steps
- Port the build scripts into `pipeline/` with CLI args.
- **Apartment view**: generate units inside the daylight band using `shell.json` rect/core/columns; raise drawn walls with the same ripple shader (reverse of the drop); keep columns fixed; count units, SF, rent.
- Cross-check columns against a Douglas Emmett floor plan if obtainable; fill the missing west-half grid.
- Wire the walkthrough into the Census frontend/agent (custom stream events; see `NEXT_SESSION.md`, `specs/backend-spec.md`).
- Demo mode: keyboard-driven steps, pre-cached everything, backup screen recording.

---

## 7. Repo state and rules

- PR #6 `walkthrough` → `main` (merged): adds `web/walkthrough/{index.html,start.command,vendor/}` + `.gitignore` line (`web/walkthrough/pano/`). Code only; data/ and pano/ must be linked in locally to run.
- `CLAUDE.md`: **humans only in git history**: no `Co-Authored-By: Claude`, no `Claude-Session`, no "Generated with Claude Code" in commits/PRs; a PreToolUse hook blocks them. Commit as the human owner.
- Through Census's `server.py` the viewer is also at `http://localhost:5190/walkthrough/` once data is in place.

## 8. Known limitations of the current viewer
- Walls-up walk: stops only at the 200 capture points (by design after the rejected experiments); tripod blur patch below/above each photo (Matterport's data); mid-move frame is a two-photo fade.
- Empty floor: ceiling light panels are on a regular pattern, not real fixture positions; floor is one flat carpet colour; mirrored window stretches are invented; core walls approximate, no doors; perimeter columns not drawn (visible in the photo walls); 5 of 21 columns are off-grid "possible".
- Only tested by headless rendering (SwiftShader, ~1 fps); never hand-tested for feel beyond Pranava's own use.
- Licensed data: keep `data/`, `pano/`, the old 25 MB HTML and the CoStar kit off GitHub and public links.
