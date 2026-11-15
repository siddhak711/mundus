---
name: claims
description: The fixed predicate vocabulary for put_claim, with types and units. Read before writing any claim.
---

# Writing claims

A claim is one fact about one node (place, space, room or pano) with the evidence it came from.

Rules:
- `predicate` must be one of the predicates below, or start with `note.` or `synthesis.` (free-form).
- `evidence_ids` must be ids a tool returned to you. A claim built only from other claims uses `derived_from`.
- `value` is the machine-readable value (number, string, true/false). `statement` is one plain sentence.
- Put the claim on the most specific node: a room fact on the room, a building fact on the place.
- Predicates marked multi can hold many values. The others hold one: a different value is a conflict, settled by
  evidence strength (record > room > image > caption > summary).
- Predicates marked exact must match exactly (years, counts). Other numbers within 5% count as the same fact.

| Predicate | Type | Unit | Notes |
|---|---|---|---|
| `market.building_type` | string |  |  |
| `market.building_area_sqft` | number | sqft |  |
| `market.year_built` | number |  | exact |
| `market.stories` | number |  | exact |
| `market.asking_rent` | number | usd_per_sqft_per_year |  |
| `market.available_area_sqft` | number | sqft |  |
| `market.listing_status` | string |  |  |
| `market.tenant_count` | number |  | exact |
| `market.largest_tenant` | string |  |  |
| `market.lease_term_months` | number | months | exact |
| `market.last_sale_price` | number | usd |  |
| `market.last_sale_date` | string |  |  |
| `market.nearby_sale_comp` | object |  | multi |
| `market.asking_price` | number | usd |  |
| `market.units_available` | number |  | exact |
| `market.min_rent` | number | usd_per_month |  |
| `market.max_rent` | number | usd_per_month |  |
| `market.home_list_price` | number | usd |  |
| `market.home_bedrooms` | number |  | exact |
| `market.home_bathrooms` | number |  | exact |
| `interior.space_kind` | string |  |  |
| `interior.floor_area_m2` | number | m2 |  |
| `interior.room_count` | number |  | exact |
| `interior.ceiling_height_m` | number | m |  |
| `interior.largest_room_area_m2` | number | m2 |  |
| `interior.capacity_estimate` | number |  |  |
| `interior.natural_light` | string |  |  |
| `interior.condition` | string |  |  |
| `interior.furnished` | boolean |  |  |
| `interior.amenity_present` | string |  | multi |
| `interior.layout_note` | string |  | multi |
| `interior.adjacent_room` | string |  | multi |
| `aerial.roof_condition` | string |  |  |
| `aerial.has_pool` | boolean |  |  |
| `aerial.has_solar` | boolean |  |  |
| `aerial.parking_visible` | string |  |  |
| `aerial.loading_access` | string |  |  |
| `surroundings.nearby_feature` | string |  | multi |
| `surroundings.street_frontage` | string |  |  |
| `pano.caption` | string |  | multi |
