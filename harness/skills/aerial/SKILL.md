---
name: aerial
description: Which aerial photos exist for a place, what each is good for, and what cannot be claimed from them.
---

# Reading aerial photos

There are no structured aerial attributes. The only aerial data is photographs, seen with `look_at_aerial`.

- `ortho` looks straight down. Two sizes: 80 m across (the building and its roof) and 250 m across (the block).
  Use it for roof condition, rooftop equipment, solar panels, pools, parking layout and site access.
- Four obliques look from one side: `oblique-n`, `oblique-s`, `oblique-e`, `oblique-w`. Use them for facades,
  loading doors, storey counts and street frontage.
- A photo supports what is visible in it and nothing more. Do not give areas, percentages or exact vehicle counts as
  measurements. Cars visible on the capture date are not parking capacity.
- A pool or structure near the edge of the frame may belong to a neighbouring building. Say so when it is unclear.
- Cite the evidence_id returned with the image in every claim.
