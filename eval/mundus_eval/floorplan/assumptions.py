"""Assumptions baked into the ground truth. Every grade carries this list, so an as-built drawing that contradicts one
of them shows which labels it invalidates instead of silently changing them."""
from __future__ import annotations

ASSUMPTIONS: list[dict[str, str]] = [
    {"id": "stairs_in_core", "text": "Both fire stairs and the plumbing stacks are inside the core; the scan never entered it.",
     "affects": "travel_to_stair, stair_separation, drain_runs"},
    {"id": "hidden_columns", "text": "Columns hidden inside old partitions follow the 8.5 m grid extrapolated into the west "
     "half (11 hypothesised positions, 0.75 m square).", "affects": "column_footprint (hidden)"},
    {"id": "plenum_15in", "text": "A 15 in plenum is available for drain slope; it sets the 8 m drain-run limit.",
     "affects": "drain_runs"},
    {"id": "steel_frame", "text": "The frame is steel; exhaust chases need 0.6 m from any column.", "affects": "chases"},
    {"id": "access_11b_mobility", "text": "Mobility units follow CBC 11B (turning space with fixtures placed); all other "
     "units follow 11A (adaptable). The 11A vs 11B ruling is unresolved.", "affects": "turning_circle, accessibility"},
    {"id": "money_model_v1", "text": "Rent = ($974 + $3.34/sf) x 1.10, +$600 for a corner two-bed; build cost per sf; "
     "no per-unit fit-out in the score. This rewards unit count (known Goodhart risk, fixed in rubric 1.1).",
     "affects": "buyer_yield, owner_view"},
]


def assumption_ids() -> list[str]:
    return [a["id"] for a in ASSUMPTIONS]
