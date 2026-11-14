---
name: market-sql
description: How to query the CoStar market tables with query_market. Table list, join keys and example queries.
---

# Market SQL

`query_market` runs one read-only SELECT in the SQLite dialect. At most 200 rows come back. Call `describe_market`
first for the live table and column list, and `describe_market(table=...)` for sample values of one table.

## Tables

| Table | One row is | Key columns |
|---|---|---|
| `costar_property` | A building | `property_id`, `place_id`, `building_name`, `property_type_label`, `rentable_building_area_square_feet`, `num_stories_above_grade`, `year_built`, `parking_spaces_total` |
| `costar_occupancy` | A tenancy | `tenant_name`, `square_feet_occupied`, `from_date`, `move_in_date`, `lease_type_label`, `lease_deal_commencement_date`, `lease_deal_expiration_date`, `lease_deal_lease_term` |
| `costar_company` | A tenant company location | `name`, `num_employees`, `profile_industry_type_label` |
| `costar_listing` | A lease or sale listing | `listing_kind`, `listing_status_label`, `for_lease_summary_total_available_square_feet`, `for_sale_summary_asking_price_low` |
| `costar_listing_space` | One space on a lease listing | `listing_id`, `suite`, `floor_name`, `square_feet_max`, `rate_low`, `rate_high` |
| `costar_sale` | A completed sale | `sold_date`, `sold_for_price`, `sale_type_label` |
| `costar_sale_entity` | A sale joined to each property it covers | `sale_id`, `property_id`, `sold_date`, `sold_for_price` |
| `costar_apartment_listing` | An apartment community's rental listing | `min_rent`, `max_rent`, `num_units_available`, `total_num_units` |
| `costar_apartment_model` | A floor plan on that listing | `name`, `num_beds`, `num_baths`, `min_rent`, `max_rent`, `num_units_available` |
| `costar_res_listing` | An MLS home listing | `current_price`, `listing_status_label`, `property_beds_max`, `property_baths_max`, `property_sqft_max` |
| `place`, `space`, `room` | World entities | `place_id`, `name`, `is_deep`, `area_m2` |

Every `costar_*` table has `place_id` and `evidence_id`. Always select `evidence_id` so each fact can be cited.

## Rules

- Filter by `place_id = '<the place id>'`. `place_id` is null for properties outside Los Angeles.
- Code columns have a `_label` twin with readable text. Filter on the label.
- Dates are ISO strings. Use `substr(col, 1, 10)` to compare days and `substr(col, 1, 4)` for years.
- A null means the record does not say. Report it as unknown; do not treat it as zero.
- An aggregate row has no evidence id of its own: cite the evidence id of one or more rows it counted.

## Examples

```sql
-- largest tenants of a place
SELECT tenant_name, square_feet_occupied, substr(from_date,1,10) AS since, evidence_id
FROM costar_occupancy WHERE place_id = 'place:costar:246941' AND tenant_name IS NOT NULL
ORDER BY square_feet_occupied DESC LIMIT 10;

-- sale history of a place
SELECT substr(sold_date,1,10) AS sold, sold_for_price, evidence_id
FROM costar_sale_entity WHERE place_id = 'place:costar:755901' ORDER BY sold_date DESC;

-- space available for lease
SELECT s.suite, s.floor_name, s.square_feet_max, s.rate_low, s.rate_high, s.evidence_id
FROM costar_listing_space s WHERE s.place_id = 'place:costar:246941';
```
