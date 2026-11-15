"""Download every capture point's 360° photo (six skybox faces) for the floor walkthrough.

    python -m pipeline.bake.panos <scanId> [--res 2k|4k]

Writes web/walkthrough/floors/<scanId>/pano/<res>/<panoId>_<face>.jpg, faces in Matterport's order (0 up, 1-4 the
sides turning right, 5 down); index.html maps them onto a cube. Resumable: files already on disk are skipped. Signed
links expire in about 30 minutes, so they are fetched fresh, and again if a download is refused part-way.
"""
import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from pipeline.bake import source

MAX_PER_SECOND = 8.0          # Matterport asks for under 10 requests a second
WORKERS = 8


class _Rate:
    """At most `per_second` starts per second across all threads."""

    def __init__(self, per_second):
        self.gap, self.next, self.lock = 1.0 / per_second, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.gap
        time.sleep(max(0.0, start - now))


def pano_dir(scan, res):
    d = source.floor_dir(scan) / "pano" / res
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_panos(scan, res="2k", log=print):
    """Fetch all faces not yet on disk. Returns (downloaded, skipped, failed)."""
    out = pano_dir(scan, res)
    rate = _Rate(MAX_PER_SECOND)
    links = {"urls": source.skybox_urls(scan, res), "at": time.monotonic()}
    lock = threading.Lock()

    def refresh_links():
        with lock:
            if time.monotonic() - links["at"] > 60:          # another thread may already have refreshed them
                links["urls"] = source.skybox_urls(scan, res)
                links["at"] = time.monotonic()

    jobs = [(pid, face) for pid, faces in links["urls"].items() for face in range(6)
            if not (out / f"{pid}_{face}.jpg").exists()]
    skipped = 6 * len(links["urls"]) - len(jobs)

    def one(pid, face):
        for attempt in range(4):
            url = (links["urls"].get(pid) or [None] * 6)[face]
            if not url:
                raise RuntimeError(f"no {res} face {face} for capture point {pid}")
            rate.wait()
            r = requests.get(url, timeout=120)
            if r.status_code in (401, 403, 410):              # the signed link expired: get fresh ones and retry
                refresh_links()
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            tmp = out / f".{pid}_{face}.part"
            tmp.write_bytes(r.content)
            tmp.rename(out / f"{pid}_{face}.jpg")
            return
        raise RuntimeError(f"{pid} face {face}: gave up")

    done = failed = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(one, pid, face): (pid, face) for pid, face in jobs}
        for f in as_completed(futures):
            try:
                f.result()
                done += 1
            except Exception as error:  # report and keep going: a rerun picks up what is missing
                failed += 1
                log(f"  failed {futures[f]}: {str(error)[:120]}")
            if (done + failed) % 60 == 0:
                log(f"  {res}: {done + failed}/{len(jobs)}")
    log(f"{scan} {res}: {done} downloaded, {skipped} already there, {failed} failed")
    return done, skipped, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan")
    ap.add_argument("--res", default="2k", choices=["2k", "4k"])
    a = ap.parse_args()
    download_panos(a.scan, a.res)


if __name__ == "__main__":
    main()
