# Floor walkthroughs

A three.js viewer for scanned office floors: the real Matterport photos, the floor with its walls removed, and the floor laid out as finished apartments, with the agents' work in a sidebar and a review page after Submit. See [HANDOFF.md](HANDOFF.md) for the full background.

`?scan=<Matterport model id>` picks the floor. The baked floors, with their facts, are in `floors.json`:

| Scan | Building | Floor |
|---|---|---|
| `cEvQ8q5GKZd` (default) | The Oppenheimer Tower, 10880 Wilshire Blvd | 16, Suite 1600 |
| `aYTUWzQVbUs` | 3415 Sepulveda Blvd | 10, Suite 1000 |
| `6Z3p5m9AcFQ` | The Tower, 10940 Wilshire Blvd | 17, Suite 1700 |
| `WhqAmKQ3YYP` | The Launch at Airport Center, 5901 Century Blvd | 3, Suite 300 |

## Bake a floor

The scan data is licensed and never committed. Bake a floor from the Matterport API (keys in `.env`):

```bash
python -m pipeline.bake WhqAmKQ3YYP
```

This writes `floors/<scan>/` (raw download, `data/`, `pano/`); add `--4k` for the 4K photos too, which roughly triples the download. A stopped bake resumes. Then open `http://localhost:5190/walkthrough/?scan=WhqAmKQ3YYP` through Atlas's server, or from a building's 3-D model, where the floor shows blue with a "Walk floor N" pin.

To add another floor: bake it, then add an entry to `floors.json` (facts from CoStar and Matterport only) and to `pipeline/walkthroughs.json` (the building's street address as CoStar writes it, the floor and the scan id), and rerun `python pipeline/conversion.py`.

Suite 1600 also still runs from Pranava's original bake, linked next to this page:

```bash
ln -s ~/Downloads/hackprinceton/floor-mockup/data web/walkthrough/data
ln -s ~/Downloads/hackprinceton/floor-mockup/pano web/walkthrough/pano
```

A floor whose files are missing shows a message with the bake command and a link to Matterport's tour of the same scan.

## Apartments, agents and review

- **Layout**: `layouts/<scan>.json` (committed). Made from a layout study by `python3 scripts/layout_v4_to_viewer.py` (default: `studies/floor16/v4/layout-v4.json` → `layouts/cEvQ8q5GKZd.json`). It finds the walls and door gaps from the study's rooms. Without it, the page falls back to the conversion agent's `data/layout.json` and draws plain white walls.
- **Finishes**: `js/apartments.js` draws oak floors, tiled baths, painted walls with baseboards, kitchens, baths, beds and sofas, using CC0 textures in `vendor/materials/` (sources in `vendor/materials/LICENSE.md`). Walk inside with the apartments up: walls and furniture block you.
- **Sidebar**: `js/sidebar.js`. The layout, compliance, structure and cost-benefit agents replay the saved study step by step. Click a finished agent to read its file. Chat commands (“remove the walls”, “design apartments”, “floor plan”) run on the page. Other questions go to `/api/agent` when the page is served by Atlas's `server.py` with the agent up; otherwise the answer comes from the saved study, and the chat says so.
- **Review**: `review.html?scan=<id>` (Submit): summary, plan, compliance, cost-benefit, structure, open questions. "Send to architect" prints it to PDF, and "Download layout" saves the JSON.

## Files

- `index.html`: the viewer (ES modules, three.js 0.160 + three-mesh-bvh from `vendor/`), with `js/` for the apartments, sidebar and review
- `floors.json`: the card facts for each baked floor (committed; no licensed data)
- `floors/<scan>/`: baked floors, gitignored; `data/`, `pano/`: Suite 1600's original bake, gitignored (see HANDOFF.md §2)
- Debug flags: `?nohd=1` (no 4K photos), `?dbg=1` (wireframe)
- Test hooks: `window.__app`, `window.__U`, `window.__ready`
