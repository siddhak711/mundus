"""Run the conversion agent on one preprocessed floor and write data/conversion/<scan>/layout.json.

    python -m mundus_harness.conversion.run cEvQ8q5GKZd
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

from mundus_harness.conversion import geometry as geo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--ask", default="", help="extra instruction for this run, e.g. a what-if")
    ap.add_argument("--tag", action="append", default=[], help="extra LangSmith tag (repeatable), e.g. knob:fixtures")
    ap.add_argument("--meta", action="append", default=[], help="extra LangSmith metadata as key=value (repeatable)")
    a = ap.parse_args()
    from mundus_harness.config import load_config
    load_config()   # loads .env and maps MUNDUS_ANTHROPIC_KEY to ANTHROPIC_API_KEY
    from mundus_harness.conversion.graph import build_agent
    agent = build_agent()
    out = geo.data_root() / a.scan / "layout.json"
    before = out.stat().st_mtime if out.exists() else 0
    msg = (f"Convert office floor scan {a.scan} into a rough-draft apartment layout. "
           "Follow your process and write the layout with write_layout. " + a.ask)
    t0 = time.time()
    run_id = str(uuid.uuid4())
    meta = {"scan": a.scan, "conversion_run_id": run_id, **dict(m.split("=", 1) for m in a.meta)}
    result = agent.invoke({"messages": [{"role": "user", "content": msg}]},
                          config={"configurable": {"thread_id": run_id}, "recursion_limit": 300,
                                  "run_name": f"conversion:{a.scan}", "tags": ["conversion", a.scan, *a.tag],
                                  "metadata": meta})
    last = result["messages"][-1]
    print(getattr(last, "content", last) if isinstance(getattr(last, "content", None), str) else json.dumps(getattr(last, "content", ""), default=str)[:3000])
    if not out.exists() or out.stat().st_mtime <= before:
        print(f"\nNo new layout written to {out}", file=sys.stderr)
        return 1
    lay = json.loads(out.read_text(encoding="utf-8"))
    print(f"\nlayout.json: {lay['summary']['units']} units, {lay['summary']['rentable_sf']} sf, "
          f"checks {lay['summary'].get('check_counts')}, {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
