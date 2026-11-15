# Floor 16 v4: self-score with measured values

Self-score **89.9 / 100** (hard-rule breaks: 0). Scored with the grader's rubric, the v3 clarifications and floor16-generator-feedback-v4.md.

| Criterion | Points | Max | Measured |
|---|---|---|---|
| LA zoning | 5.0 | 5 | 24 units, residential |
| Room size, daylight, escape | 7.0 | 7 | 100% of units pass; all bedrooms and living rooms on the glass |
| Exits and stairs | 8.0 | 8 | worst travel to stair door 46.0 m (limit 76.2); stairs 44.3 m apart (min 25.7); loop yes; 2 enclosed lobbies; stair links enclosed ½ hr, 1.30 m wide |
| Accessibility | 8.0 | 8 | baths 100%, kitchens 100%; 3 mobility + 1 hearing/vision of 24; mobility baths column-free: True |
| Fire, sound, ventilation | 6.8 | 7 | 1 hr demising + ½ hr corridor + 1 hr lockers/co-working wall labelled; chases clear 100%; wet rooms paired 83% |
| No hard failures | 5.0 | 5 | 0 breaks |
| Detected columns | 10.0 | 10 | 21/21 pass the footprint test |
| Hidden columns | 8.0 | 8 | 11/11 pass the footprint test |
| Drains to the core | 6.5 | 7 | 96% of units have every wet group <= 8 m; worst N1 dishwasher 9.0 m; paired 83% |
| Loads and earthquake | 5.0 | 5 | chases 0.6×0.3 m, 100% at least 0.6 m from any column |
| Buyer yield | 6.6 | 12 | 3.92% vs 7.15% |
| Owner view vs office | 4.4 | 8 | NOI $0.651M vs office $0.680M: gap $-0.0291M → 5 + 20 × gap |
| Share of floor rented | 5.6 | 6 | 74.4% |
| Unit size vs market | 4.0 | 4 | average 657 sf; smallest one-bed 529 sf |

Hard-rule penalty: −0

## Every unit

| Unit | Type | sf | Drain runs (m) | Column overlaps (m²) | Failing checks |
|---|---|---|---|---|---|
| S1 | 2BR/2BA | 1153 | bath1 5.8, bath2 7.8, sink 7.3, dishwasher 7.9, washer 6.7 | C11: wardrobe 0.41; H5: living 0.56 | none |
| S2 | 1BR/1BA | 634 | bath1 4.2, sink 2.2, dishwasher 2.8, washer 5.8 | H6: wardrobe 0.56 | none |
| S3 | 1BR/1BA | 747 | bath1 3.6, sink 2.7, dishwasher 2.7, washer 2.7 | H7: wardrobe 0.56 | none |
| S4 | 1BR/1BA | 529 | bath1 3.8, sink 3.9, dishwasher 4.5, washer 4.9 | C1: living 0.56; H8: living 0.56 | none |
| S5 | 1BR/1BA | 538 | bath1 2.7, sink 4.0, dishwasher 4.6, washer 2.6 | C21: closet 0.25; H9: living 0.56 | none |
| S6 | 1BR/1BA | 538 | bath1 7.1, sink 4.7, dishwasher 4.7, washer 4.5 | C7: closet 0.56 | none |
| S7 | 1BR/1BA | 529 | bath1 7.0, sink 6.3, dishwasher 6.3, washer 4.4 | C15: closet 0.41; H10: wardrobe 0.56 | none |
| S8 | 1BR/1BA | 529 | bath1 4.7, sink 5.6, dishwasher 6.2, washer 4.2 | C14: closet 0.46; H11: wardrobe 0.56 | none |
| S9 | 2BR/2BA | 1137 | bath1 5.6, bath2 7.7, sink 7.1, dishwasher 7.7, washer 6.5 | none | none |
| E1 | 1BR/1BA | 533 | bath1 5.8, sink 5.9, dishwasher 6.5, washer 3.2 | C6: closet 0.46; C18: closet 0.41 | none |
| E2 | 1BR/1BA | 533 | bath1 5.8, sink 4.6, dishwasher 4.6, washer 3.2 | C2: closet 0.46; C17: closet 0.41 | none |
| E3 | 1BR/1BA | 533 | bath1 4.1, sink 4.6, dishwasher 4.6, washer 3.2 | C3: closet 0.41 | none |
| E4 | 2BR/2BA | 898 | bath1 4.6, bath2 6.7, sink 6.1, dishwasher 6.7, washer 5.5 | none | none |
| N1 | 2BR/2BA | 1163 | bath1 6.9, bath2 9.0, sink 8.4, dishwasher 9.0, washer 7.8 | H4: living 0.56 | every drain run <= 8 m (bath1 6.9, bath2 9.0, sink 8.4, dishwasher 9.0, washer 7.8) |
| N2 | 1BR/1BA | 591 | bath1 5.4, sink 4.5, dishwasher 4.5, washer 7.0 | H3: wardrobe 0.56 | none |
| N3 | 1BR/1BA | 591 | bath1 5.5, sink 4.5, dishwasher 4.5, washer 7.0 | H2: living 0.46, wardrobe 0.10 | none |
| N4 | 1BR/1BA | 591 | bath1 5.5, sink 4.7, dishwasher 4.7, washer 7.1 | H1: living 0.56 | none |
| N5 | 1BR/1BA | 591 | bath1 5.0, sink 4.7, dishwasher 4.7, washer 6.6 | none | none |
| N6 | 1BR/1BA | 593 | bath1 5.4, sink 4.0, dishwasher 4.3, washer 6.6 | C16: wardrobe 0.25 | none |
| N7 | 1BR/1BA | 595 | bath1 3.3, sink 2.8, dishwasher 2.8, washer 2.8 | C10: living 0.56 | none |
| N8 | 1BR/1BA | 595 | bath1 4.0, sink 2.8, dishwasher 2.8, washer 2.8 | C12: living 0.56 | none |
| W1 | 1BR/1BA | 543 | bath1 4.9, sink 6.1, dishwasher 6.7, washer 4.7 | C4: closet 0.41; C13: closet 0.56 | none |
| W2 | 1BR/1BA | 543 | bath1 4.9, sink 4.0, dishwasher 4.0, washer 6.5 | none | none |
| W3 | 1BR/1BA | 540 | bath1 4.9, sink 5.9, dishwasher 6.5, washer 6.5 | none | none |

## Every column (footprint test)

| Column | Kind | Where it lands (overlap m²) | OK |
|---|---|---|---|
| C1 | possible | S4 living 0.56 m² | yes |
| C2 | probable | E2 closet 0.46 m² | yes |
| C3 | probable | E3 closet 0.41 m² | yes |
| C4 | possible | W1 closet 0.41 m² | yes |
| C5 | probable | storage / co-working zone | yes |
| C6 | probable | E1 closet 0.46 m² | yes |
| C7 | probable | S6 closet 0.56 m² | yes |
| C8 | probable | storage / co-working zone | yes |
| C9 | probable | storage / co-working zone | yes |
| C10 | probable | N7 living 0.56 m² | yes |
| C11 | possible | S1 wardrobe 0.41 m² | yes |
| C12 | probable | N8 living 0.56 m² | yes |
| C13 | possible | W1 closet 0.56 m² | yes |
| C14 | probable | S8 closet 0.46 m² | yes |
| C15 | probable | S7 closet 0.41 m² | yes |
| C16 | probable | N6 wardrobe 0.25 m² | yes |
| C17 | probable | E2 closet 0.41 m² | yes |
| C18 | probable | E1 closet 0.41 m² | yes |
| C19 | probable | storage / co-working zone | yes |
| C20 | possible | storage / co-working zone | yes |
| C21 | probable | S5 closet 0.25 m² | yes |
| H1 | hidden | N4 living 0.56 m² | yes |
| H2 | hidden | N3 living 0.46 m²; N3 wardrobe 0.10 m² | yes |
| H3 | hidden | N2 wardrobe 0.56 m² | yes |
| H4 | hidden | N1 living 0.56 m² | yes |
| H5 | hidden | S1 living 0.56 m² | yes |
| H6 | hidden | S2 wardrobe 0.56 m² | yes |
| H7 | hidden | S3 wardrobe 0.56 m² | yes |
| H8 | hidden | S4 living 0.56 m² | yes |
| H9 | hidden | S5 living 0.56 m² | yes |
| H10 | hidden | S7 wardrobe 0.56 m² | yes |
| H11 | hidden | S8 wardrobe 0.56 m² | yes |

## Changes from v3 (old unit → new units)

| v3 unit | v3 sf | v4 units (sf) | Columns in the new units |
|---|---|---|---|
| S4 | 644 | S4 (529), S5 (538) | S4: C1 in living, H8 in living; S5: C21 in closet, H9 in living |
| S5 | 644 | S5 (538), S6 (538) | S5: C21 in closet, H9 in living; S6: C7 in closet |
| S6 | 654 | S6 (538), S7 (529) | S6: C7 in closet; S7: C15 in closet, H10 in wardrobe |
| S7 | 711 | S7 (529), S8 (529) | S7: C15 in closet, H10 in wardrobe; S8: C14 in closet, H11 in wardrobe |
| S8 | 1147 | S9 (1137) | none |
| E1 | 620 | E1 (533), E2 (533) | E1: C6 in closet, C18 in closet; E2: C2 in closet, C17 in closet |
| E2 | 659 | E2 (533), E3 (533) | E2: C2 in closet, C17 in closet; E3: C3 in closet |
| E3 | 595 | E3 (533), E4 (898) | E3: C3 in closet |
| N7 | 505 | N7 (595) | N7: C10 in living |
| N8 | 505 | N7 (595), N8 (595) | N7: C10 in living; N8: C12 in living |
| N9 | 803 | E4 (898), N8 (595) | N8: C12 in living |
| W1 | 814 | W1 (543), W2 (543) | W1: C4 in closet, C13 in closet |
| W2 | 811 | W2 (543), W3 (540) | none |

## Fit-out sensitivity (information only)

- $55,000 per extra unit (one kitchen + one bath) over v3's 22 units; information only, not scored
- Extra units: 2, extra cost $110,000
- Owner yield 5.84%, buyer yield 3.90%
- vs office after carrying the fit-out at 7.15%: $-36,959/yr
