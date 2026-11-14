# Atlas

A site-model viewer for every property in the HackPrinceton CoStar kit: 3,346 in Houston and
1,857 in Los Angeles. Pick a city, pick a property, and Atlas builds a 3-D model of it from three
sources that describe the same address.

| Source | What it contributes |
|---|---|
| CoStar | The property record, tenants by floor since the building opened, space for lease with asking rents, sales, apartment floor plans, home listings |
| Vexcel | Aerial photo, measured building heights, building footprints, roof facts, angled views, object detection |
| Matterport | Interior scans shown as cut-open models, with measured area and room types |

## Run it

1. Unzip the CoStar kit into `raw/costar/`.
2. Put the API keys in `.env` (see `.env.example`).
3. Install and build the index, then start the server:

```bash
pip install requests shapely pillow numpy tifffile imagecodecs anthropic
python pipeline/build_index.py
python server.py
```

Open http://localhost:5190.

## How it is put together

- `pipeline/build_index.py` reads the CoStar kit once and writes `data/index/<city>.json` plus one
  detail file per property.
- `pipeline/twin.py` builds a property's site model the first time it is opened (about three
  seconds) and caches it under `cache/`. `pipeline/vexcel.py` and `pipeline/matterport.py` are the
  API clients.
- `pipeline/agent.py` is Ask Atlas: Claude with tools that search the records, measure from the
  aerial survey, read the scans and drive the page.
- `server.py` serves the site and those APIs. `web/` is the front end: plain ES modules, three.js
  for the model, Leaflet for the map, no build step.

## What the model does and does not show

- Roofs and ground are the aerial photo. Building sides have no imagery, so they are plain massing.
- Only mapped building footprints are raised; trees stay flat under the photo.
- Scan floors and furniture are textured from Matterport's top-down photo plan; walls are plain.
- A scan is placed on its floor only when its name carries a suite or level number.

`raw/`, `data/`, `cache/` and `.env` are git-ignored: the CoStar data is licensed for the event and
the keys are private.
