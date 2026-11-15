# Floor 16 v3: self-score with measured values

Self-score **88.3 / 100** (hard-rule breaks: 0). Scored with the grader's rubric and the section 3 clarifications in floor16-generator-feedback-v3.md.

| Criterion | Points | Max | Measured |
|---|---|---|---|
| LA zoning | 5.0 | 5 | 22 units, residential |
| Room size, daylight, escape | 7.0 | 7 | 100% of units pass; all bedrooms and living rooms on the glass |
| Exits and stairs | 8.0 | 8 | worst travel to stair door 45.1 m (limit 76.2); stairs 44.3 m apart (min 25.7); loop yes; 2 enclosed lobbies; stair links enclosed ½ hr, 1.30 m wide |
| Accessibility | 8.0 | 8 | baths 100%, kitchens 100%; 3 mobility + 1 hearing/vision of 22; mobility baths column-free: True |
| Fire, sound, ventilation | 6.7 | 7 | 1 hr demising + ½ hr corridor + 1 hr lockers/co-working wall labelled; chases clear 100%; wet rooms paired 73% |
| No hard failures | 5.0 | 5 | 0 breaks |
| Detected columns | 10.0 | 10 | 21/21 pass the footprint test |
| Hidden columns | 8.0 | 8 | 11/11 pass the footprint test |
| Drains to the core | 6.0 | 7 | 91% of units have every wet group <= 8 m; worst N9 dishwasher 10.1 m; paired 73% |
| Loads and earthquake | 5.0 | 5 | chases 0.6×0.3 m, 100% at least 0.6 m from any column |
| Buyer yield | 6.4 | 12 | 3.82% vs 7.15% |
| Owner view vs office | 4.1 | 8 | NOI $0.634M vs office $0.680M: gap $-0.0461M → 5 + 20 × gap |
| Share of floor rented | 5.6 | 6 | 74.4% |
| Unit size vs market | 3.5 | 4 | average 717 sf; smallest one-bed 505 sf |

Hard-rule penalty: −0

## Every unit

| Unit | Type | sf | Drain runs (m) | Column overlaps (m²) | Failing checks |
|---|---|---|---|---|---|
| S1 | 2BR/2BA | 1153 | bath1 5.8, bath2 7.8, sink 7.3, dishwasher 7.9, washer 6.7 | C11: wardrobe 0.41; H5: living 0.56 | none |
| S2 | 1BR/1BA | 634 | bath1 4.2, sink 2.2, dishwasher 2.8, washer 5.8 | H6: wardrobe 0.56 | none |
| S3 | 1BR/1BA | 747 | bath1 3.6, sink 2.7, dishwasher 2.7, washer 2.7 | H7: wardrobe 0.56 | none |
| S4 | 1BR/1BA | 644 | bath1 2.7, sink 3.9, dishwasher 4.5, washer 4.3 | C1: living 0.56; H8: living 0.56 | none |
| S5 | 1BR/1BA | 644 | bath1 2.7, sink 3.8, dishwasher 4.4, washer 4.3 | C21: kitchen 0.25; H9: wardrobe 0.56 | none |
| S6 | 1BR/1BA | 654 | bath1 5.4, sink 4.5, dishwasher 4.5, washer 6.8 | C7: kitchen 0.56; H10: wardrobe 0.56 | none |
| S7 | 1BR/1BA | 711 | bath1 4.7, sink 4.3, dishwasher 4.9, washer 6.3 | C14: kitchen 0.46; C15: kitchen 0.41; H11: wardrobe 0.56 | none |
| S8 | 2BR/2BA | 1147 | bath1 5.5, bath2 7.6, sink 7.0, dishwasher 7.6, washer 6.4 | none | none |
| E1 | 1BR/1BA | 620 | bath1 4.1, sink 3.6, dishwasher 4.2, washer 5.6 | C6: kitchen 0.46; C18: kitchen 0.41 | none |
| E2 | 1BR/1BA | 659 | bath1 5.8, sink 3.2, dishwasher 3.2, washer 3.2 | C2: closet 0.46; C17: kitchen 0.41 | none |
| E3 | 1BR/1BA | 595 | bath1 5.7, sink 3.2, dishwasher 3.2, washer 6.7 | C3: kitchen 0.41 | none |
| N1 | 2BR/2BA | 1163 | bath1 6.9, bath2 9.0, sink 8.4, dishwasher 9.0, washer 7.8 | H4: living 0.56 | every drain run <= 8 m (bath1 6.9, bath2 9.0, sink 8.4, dishwasher 9.0, washer 7.8) |
| N2 | 1BR/1BA | 591 | bath1 5.4, sink 4.5, dishwasher 4.5, washer 7.0 | H3: wardrobe 0.56 | none |
| N3 | 1BR/1BA | 591 | bath1 5.5, sink 4.5, dishwasher 4.5, washer 7.0 | H2: living 0.46, wardrobe 0.10 | none |
| N4 | 1BR/1BA | 591 | bath1 5.5, sink 4.7, dishwasher 4.7, washer 7.1 | H1: living 0.56 | none |
| N5 | 1BR/1BA | 591 | bath1 5.6, sink 4.1, dishwasher 4.1, washer 7.2 | none | none |
| N6 | 1BR/1BA | 593 | bath1 5.1, sink 4.1, dishwasher 4.6, washer 6.4 | C16: living 0.25 | none |
| N7 | 1BR/1BA | 505 | bath1 3.3, sink 2.9, dishwasher 3.5, washer 2.8 | C10: wardrobe 0.56 | none |
| N8 | 1BR/1BA | 505 | bath1 3.3, sink 2.8, dishwasher 2.8, washer 3.3 | C12: living 0.56 | none |
| N9 | 2BR/2BA | 803 | bath1 6.0, bath2 8.4, sink 9.5, dishwasher 10.1, washer 8.9 | none | every drain run <= 8 m (bath1 6.0, bath2 8.4, sink 9.5, dishwasher 10.1, washer 8.9) |
| W1 | 1BR/1BA | 814 | bath1 4.9, sink 4.0, dishwasher 4.0, washer 6.5 | C4: kitchen 0.41; C13: kitchen 0.56 | none |
| W2 | 1BR/1BA | 811 | bath1 4.9, sink 4.0, dishwasher 4.0, washer 6.5 | none | none |

## Every column (footprint test)

| Column | Kind | Where it lands (overlap m²) | OK |
|---|---|---|---|
| C1 | possible | S4 living 0.56 m² | yes |
| C2 | probable | E2 closet 0.46 m² | yes |
| C3 | probable | E3 kitchen 0.41 m² | yes |
| C4 | possible | W1 kitchen 0.41 m² | yes |
| C5 | probable | storage / co-working zone | yes |
| C6 | probable | E1 kitchen 0.46 m² | yes |
| C7 | probable | S6 kitchen 0.56 m² | yes |
| C8 | probable | storage / co-working zone | yes |
| C9 | probable | storage / co-working zone | yes |
| C10 | probable | N7 wardrobe 0.56 m² | yes |
| C11 | possible | S1 wardrobe 0.41 m² | yes |
| C12 | probable | N8 living 0.56 m² | yes |
| C13 | possible | W1 kitchen 0.56 m² | yes |
| C14 | probable | S7 kitchen 0.46 m² | yes |
| C15 | probable | S7 kitchen 0.41 m² | yes |
| C16 | probable | N6 living 0.25 m² | yes |
| C17 | probable | E2 kitchen 0.41 m² | yes |
| C18 | probable | E1 kitchen 0.41 m² | yes |
| C19 | probable | storage / co-working zone | yes |
| C20 | possible | storage / co-working zone | yes |
| C21 | probable | S5 kitchen 0.25 m² | yes |
| H1 | hidden | N4 living 0.56 m² | yes |
| H2 | hidden | N3 living 0.46 m²; N3 wardrobe 0.10 m² | yes |
| H3 | hidden | N2 wardrobe 0.56 m² | yes |
| H4 | hidden | N1 living 0.56 m² | yes |
| H5 | hidden | S1 living 0.56 m² | yes |
| H6 | hidden | S2 wardrobe 0.56 m² | yes |
| H7 | hidden | S3 wardrobe 0.56 m² | yes |
| H8 | hidden | S4 living 0.56 m² | yes |
| H9 | hidden | S5 wardrobe 0.56 m² | yes |
| H10 | hidden | S6 wardrobe 0.56 m² | yes |
| H11 | hidden | S7 wardrobe 0.56 m² | yes |
