---
name: interior
description: How to read interior data. Rooms, dimensions, camera positions, captions, the 20-photo cap and what adjacency means.
---

# Reading interiors

- A **space** is one Matterport scan. It may be a whole suite, one amenity, or one apartment.
- A **room** has a label, floor area in square metres, width, depth and sometimes ceiling height. Labels come from a
  model trained on homes: in offices and shops they are often wrong or "Other". Trust dimensions over labels.
- A room labelled `Void` is a shaft or an unscanned area. Ignore it.
- A **pano** is one camera position. Faces 1 to 4 are the four horizontal directions; 0 is up and 5 is down.
- At most 20 panos per space have photos and captions (`is_selected`). A room with `pano_selected: 0` has no photo.
  Its size is known. What it looks like is not. Say so.
- Captions are long descriptions written by a vision model from the four horizontal views. They are evidence of
  type `caption`, weaker than a record or a room measurement. Look at the photo yourself (`look_at_pano`) only when a
  caption does not settle the question.
- `adjacent_rooms` share a wall. The data has no doors and no openings. Never state that two rooms connect, and never
  describe a walking route, from adjacency alone.
- 1 m2 = 10.764 sq ft. Report both.
- Rough capacity rules, to be stated as estimates: open office 10 m2 per person, conference seating 2.5 m2 per seat,
  assembly standing 0.65 m2 per person.
