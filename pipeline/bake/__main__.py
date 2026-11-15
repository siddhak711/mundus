"""Bake one scanned floor for the walkthrough.

    python -m pipeline.bake <scanId> [--4k] [--property <CoStar id>] [--floor <n>] [--only mesh,panos,...]

Steps, in order (each skips work already done, so a stopped bake resumes):
    source   the Matterport model, floor plan and MatterPak mesh (source.py)
    mesh     cleaned mesh, interior/shell classes, texture atlases, clean floor (mesh.py: bake_mesh)
    panos    the 360 photos: 2k always, 4k with --4k (panos.py: download_panos)
    scene    scene.json, daylight band and walkable area (scene.py: write_scene)
    shell    photo-baked outer walls, core and columns for the empty floor (shell.py: bake_shell)

Output: web/walkthrough/floors/<scanId>/ (licensed, git-ignored). Open it at /walkthrough/?scan=<scanId>; add the floor
to web/walkthrough/floors.json (card facts) and pipeline/walkthroughs.json (the building's walk pin).
Needs MATTERPORT_API_KEY and MATTERPORT_API_TOKEN in .env; numpy, scipy, pillow and opencv-python-headless.
"""
import argparse
import importlib
import inspect
import sys
import time

STEPS = [("source", None), ("mesh", "bake_mesh"), ("panos", "download_panos"), ("scene", "write_scene"), ("shell", "bake_shell")]


def _call(fn, scan, options):
    """Call a step with the scan id and whichever of the options its signature takes."""
    params = inspect.signature(fn).parameters
    takes_any = any(p.kind is p.VAR_KEYWORD for p in params.values())
    return fn(scan, **{k: v for k, v in options.items() if takes_any or k in params})


def run_source(scan):
    from pipeline.bake import source
    m = source.model(scan)
    source.plan(scan)
    source.matterpak(scan)
    return f"{m['name']}: {len(m['panoLocations'])} capture points"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.bake", description=__doc__.split("\n\n")[0])
    ap.add_argument("scan", help="Matterport model id, e.g. WhqAmKQ3YYP")
    ap.add_argument("--4k", dest="four_k", action="store_true", help="also download the 4k photos (about 3x the size)")
    ap.add_argument("--property", dest="property_id", type=int, help="CoStar property id")
    ap.add_argument("--floor", type=int, help="the floor the scan is on")
    ap.add_argument("--only", help="comma-separated steps to run (default: all)")
    args = ap.parse_args(argv)
    wanted = set(args.only.split(",")) if args.only else {name for name, _ in STEPS}
    options = {"four_k": args.four_k, "property_id": args.property_id, "floor": args.floor}

    for name, fn_name in STEPS:
        if name not in wanted:
            continue
        started = time.time()
        if name == "source":
            note = run_source(args.scan)
        else:
            try:
                module = importlib.import_module(f"pipeline.bake.{name}")      # lazily: steps land independently
            except ModuleNotFoundError as error:
                if error.name != f"pipeline.bake.{name}":
                    raise
                print(f"[{name}] skipped: pipeline/bake/{name}.py is not there yet")
                continue
            fn = getattr(module, fn_name, None)
            if fn is None:
                print(f"[{name}] skipped: pipeline/bake/{name}.py has no {fn_name}()")
                continue
            note = _call(fn, args.scan, options)
        print(f"[{name}] done in {time.time() - started:.0f} s" + (f": {note}" if isinstance(note, str) else ""))
    print(f"open /walkthrough/?scan={args.scan}")


if __name__ == "__main__":
    sys.exit(main())
