"""Build the 3-D site models of the office-to-housing candidates ahead of time, so even a first open is instant.

    python -m pipeline.prewarm              # candidates from data/conversion/los-angeles.json, walkthrough buildings first
    python -m pipeline.prewarm --all        # every LA office in the screen, candidate or not

A model is built once (four Vexcel calls and some processing, a few seconds) and cached under cache/twin/; this runs
those builds now instead of on the first click. Already cached models are skipped, so a rerun is cheap.
Needs VEXCEL_API_KEY in .env.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline import config, twin

CANDIDATES = {"strong", "possible", "review"}
WORKERS = 3     # parallel builds; each makes several Vexcel calls


def targets(everything=False):
    screen = json.loads((config.DATA / "conversion" / "los-angeles.json").read_text(encoding="utf-8"))
    rows = [b for b in screen["buildings"] if b["type"] == "Office" and (everything or b["status"] in CANDIDATES)]
    rows.sort(key=lambda b: (not b.get("walkthrough"), -(b.get("score") or 0)))
    return [b["id"] for b in rows]


def main():
    ids = targets(everything="--all" in sys.argv[1:])
    todo = [i for i in ids if not (config.CACHE / "twin" / f"commercial-{i}" / "twin.json").exists()]
    print(f"{len(ids)} buildings, {len(ids) - len(todo)} already cached, building {len(todo)}")
    started, done, failed = time.time(), 0, []
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(twin.get, "commercial", i): i for i in todo}
        for future in as_completed(futures):
            done += 1
            try:
                future.result()
            except Exception as error:  # one building's failure should not stop the rest
                failed.append((futures[future], str(error)[:120]))
            print(f"  {done}/{len(todo)} built ({time.time() - started:.0f} s)", end="\r", flush=True)
    print(f"\nbuilt {len(todo) - len(failed)}, failed {len(failed)}")
    for pid, error in failed:
        print(f"  {pid}: {error}")


if __name__ == "__main__":
    main()
