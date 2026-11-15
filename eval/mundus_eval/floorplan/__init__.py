"""Floor-plan evals: a frozen rubric, independent geometric checks, layout mutations and rule-check accuracy.

The checks never trust a pass/fail flag written by the generator. Every check recomputes from geometry in the layout
JSON (units, rooms, doors, fixtures, corridor, stairs) and the floor (outer wall, core, columns).
"""
