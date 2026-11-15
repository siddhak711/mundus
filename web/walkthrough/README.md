# Floor walkthrough (Suite 1600, 10880 Wilshire)

A standalone three.js viewer for one office floor: the real Matterport photos, the floor with its walls removed, and (next) the floor laid out as apartments. See [HANDOFF.md](HANDOFF.md) for the full background.

## Run

The scan data is licensed and never committed. Link it in from your local copy:

```bash
ln -s ~/Downloads/hackprinceton/floor-mockup/data web/walkthrough/data
ln -s ~/Downloads/hackprinceton/floor-mockup/pano web/walkthrough/pano
```

Then serve the folder (it does not work from `file://`):

```bash
cd web/walkthrough && python3 -m http.server 8123
```

Open http://localhost:8123.

## Files

- `index.html`: the whole viewer (ES modules, three.js 0.160 + three-mesh-bvh from `vendor/`)
- `data/`, `pano/`: generated from the scan, gitignored (see HANDOFF.md §2)
- Debug flags: `?nohd=1` (no 4K photos), `?dbg=1` (wireframe)
- Test hooks: `window.__app`, `window.__U`, `window.__ready`
