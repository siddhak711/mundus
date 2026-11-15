"""Regenerates skills/claims/SKILL.md from shared/predicates.yaml (the one source of the vocabulary)."""
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[2]
vocab = yaml.safe_load((root / "shared" / "predicates.yaml").read_text(encoding="utf-8"))
lines = ["---", "name: claims", "description: The fixed predicate vocabulary for put_claim, with types and units. Read before writing any claim.",
         "---", "", "# Writing claims", "",
         "A claim is one fact about one node (place, space, room or pano) with the evidence it came from.", "",
         "Rules:", "- `predicate` must be one of the predicates below, or start with `note.` or `synthesis.` (free-form).",
         "- `evidence_ids` must be ids a tool returned to you. A claim built only from other claims uses `derived_from`.",
         "- `value` is the machine-readable value (number, string, true/false). `statement` is one plain sentence.",
         "- Put the claim on the most specific node: a room fact on the room, a building fact on the place.",
         "- Predicates marked multi can hold many values. The others hold one: a different value is a conflict, settled by",
         "  evidence strength (record > room > image > caption > summary).",
         "- Predicates marked exact must match exactly (years, counts). Other numbers within 5% count as the same fact.", "",
         "| Predicate | Type | Unit | Notes |", "|---|---|---|---|"]
for p, d in vocab.items():
    notes = ", ".join(n for n in ("multi" if d.get("multi") else "", "exact" if d.get("exact") else "") if n)
    lines.append(f"| `{p}` | {d.get('type')} | {d.get('unit', '')} | {notes} |")
(root / "harness" / "skills" / "claims" / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", len(vocab), "predicates")
