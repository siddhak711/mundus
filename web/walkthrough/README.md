# Floor walkthroughs

A three.js viewer for scanned office floors: the real Matterport photos, the floor with its walls removed, and (next) the floor laid out as apartments. See [HANDOFF.md](HANDOFF.md) for the full background.

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

## Files

- `index.html`: the whole viewer (ES modules, three.js 0.160 + three-mesh-bvh from `vendor/`)
- `floors.json`: the card facts for each baked floor (committed; no licensed data)
- `floors/<scan>/`: baked floors, gitignored; `data/`, `pano/`: Suite 1600's original bake, gitignored (see HANDOFF.md §2)
- Debug flags: `?nohd=1` (no 4K photos), `?dbg=1` (wireframe)
- Test hooks: `window.__app`, `window.__U`, `window.__ready`
