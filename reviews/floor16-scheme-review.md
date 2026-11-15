# Floor 16 review: Scheme A vs Scheme B (10880 Wilshire, Oppenheimer Tower)

Reviewed 15 Nov 2026 against the study in `~/Downloads/hackprinceton/floor-mockup/data/studies/`. These are draft review findings, not an architect's, engineer's or investment opinion. The geometry comes from the Matterport scan, not from as-built drawings.

## Verdict

| | Scheme A (28 code-minimum one-beds) | Scheme B (22 market one-beds) |
|---|---|---|
| LA zoning (adaptive reuse ordinance) | Pass | Pass |
| Building code as drawn | Mostly passes. **Fails at the N8 entry.** Several stated passes are unproven | Mostly passes. Unproven items are the same |
| Structure (columns) | **Weak.** One probable column blocks the N8 entry. Likely hidden columns hit 2 baths and 1 entry | **Robust.** Every likely column lands in a 6 m wide kitchen or living room |
| Money, buyer view | Not viable: 3.7% yield vs 7.15% needed (study said 3.0%) | Not viable: 3.4% (study said 2.7%) |
| Money, owner view | Viable only if the floor can't be leased as office | Same, slightly worse |
| Optimal? | **No.** About 3,700 sf of rentable depth is left as dark "amenity" | **No.** Same problem |

**Bottom line:** neither scheme is viable as a stand-alone development, and neither layout is optimal. The study's "not worth it" call is right, but some of its reasons are wrong. It overstates cost by about $3.2M. It also misses the two things that actually decide this floor:

1. **The office alternative.** The owner gives up roughly $0.7–1.0M/yr of office income to earn about $0.58M/yr of apartment income.
2. **A layout that wastes depth.** Making units deeper where the core is far away raises rentable area from 12,453 to about 16,100 sf.

## 1. LA compliance

**Zoning: checked against the ordinance text.** Ord. 188,793 (LAMC 12.22 A.26) applies to "all or any portion" of a building ≥15 years old, by right. It needs ≥5 units, sets no minimum unit size under zoning and no density limit, and the linkage fee applies. The study gets all of this right.

**Building code: items the study passes that need correcting or that remain unproven.**

| Item | Study says | Review |
|---|---|---|
| Egress travel distance | 127 / 133 ft "to the core" | Must be measured to an **exit stair door**. Stair locations are assumed, not known. The two stairs must also be ≥1/3 of the 77 m diagonal apart (≥25.7 m). The core centroids are only about 23 m apart, so this could fail if both stairs sit on the inner faces. |
| Elevator lobby | Not checked | In a high-rise, corridors open straight into the core. CBC 3006 requires an enclosed elevator lobby or equivalent hoistway protection. |
| Accessibility | "All units covered under 11A" | **Unresolved.** 11A covers *newly constructed* covered dwellings, and whether a conversion counts needs an HCD/LADBS ruling. If city money is involved, 11B applies plus the HUD agreement (11% mobility, 4% hearing/vision). Scheme A's 1.05 m entries and 1.65 m baths leave no slack for 11B units. |
| Ventilation | Not checked | The curtain wall is almost certainly fixed glass, so every unit needs a new mechanical ventilation and exhaust system. Bath and kitchen exhaust ducts have to reach shafts or the façade, within the 15 in left above an 8 ft 9 in ceiling. |
| Sound | Not checked | STC/IIC 50 between units and from public or service areas (CBC 1206). The office floors above and below make the slab question real. |
| Mixed occupancy | Not checked | A residential floor (R-2) between office floors (B) needs a 1 hr separation (Table 508.4). The existing high-rise slab probably meets it, but this needs confirming. Shared elevators need access control. |
| Seismic | Not mentioned | Office (B) to apartments (R-2) stays in Risk Category II, so **the change of use alone does not trigger** a CEBC seismic upgrade. Check whether 10880 is on LADBS's non-ductile concrete or pre-Northridge steel lists. A retrofit would add roughly $50–100/sf to the whole building. |
| Room sizes, daylight, escape windows, dead ends, corridor width | Pass | Agree. |

## 2. Structure

The study reports "Columns: 21/21 in walls, corridor wall or amenity zone". That is true only for the columns the scanner happened to find. A wall line is not enough. A 0.5–0.75 m column inside a 1.05 m entry or a 1.65 m bath breaks the room.

What the detected columns show:
- An outer row 4.2 m in from the north glass (C16, C10, C12), spaced about 8.5 m.
- Interior rows 8.4 m in from both façades (y ≈ −1.9 and 16.0).
- The south outer row appears only as two "possible" hits (C1, C11).

A 1970 tower with a 69 m long plate is not column-free across its west half. Continuing the 8.5 m outer rows west and mirroring them south gives about 11 more likely columns. I tested every detected and likely column against every room:

- **Scheme A**
  - C10 (probable) takes 0.40 m² out of **N8's 1.05 m entry**. That leaves about 0.3–0.5 m to walk past: **a failure today.**
  - Likely columns land in the **S2, S7 and N2 baths (1.65 m wide)** and the **S8 entry**. They also hit kitchens in S1, S4, S5, S10, N1, N4 and N5.
- **Scheme B:** every detected and likely column lands in a 5.6–6.0 m kitchen or a 3.8–4.9 m living room or bedroom. That is workable everywhere.

**Load-bearing beams.** Partitions on a 1970 high-rise floor are not load-bearing, so walls can go anywhere structurally. The beams matter for **drains**. Every bath and kitchen drains through the slab into the floor 15 ceiling, then runs horizontally to the core stacks under or through the beams.

Best-case runs to the nearest core face are 3.6–14.6 m, which needs 3–12 in of fall at ¼ in per ft. The longest are the corner and end units: N1, S1, S11, W1, E1 and N11. If the existing stacks sit in a few spots inside the core (likely), runs double. The fall then exceeds a typical 12–18 in clear plenum below beams. The fixes are ⅛ in per ft on a 4 in main with AHJ approval, pumped above-floor drainage, or new stacks.

All of these involve **construction inside another tenant's ceiling**. Neither scheme or cost model accounts for it.

## 3. Cost-benefit: the study's numbers vs mine

I reproduced the study's figures exactly ($974 + $3.34 × sf rent, 5% vacancy, 30% opex, $500 + $216 + $16.76 per gross sf). The differences come from five corrections:

| # | Study assumption | Correction | Why |
|---|---|---|---|
| 1 | $500/sf on all 25,667 gross sf | $500/sf on units and corridors. $150/sf on the dark storage/amenity zone. $25/sf on the existing core. **Plus $1.0M** for single-floor items: drains in the floor 15 ceiling, stack tie-ins, separations | The $500 figure is a whole-building average (AECOM). The core already exists, and storage doesn't need $500/sf finishes. The study's own note says so. |
| 2 | Linkage fee on 25,667 sf | On 21,178 sf (gross minus core) | LAMC floor area excludes shafts and stairs. |
| 3 | Opex 30% | 35% | One residential floor inside an office building has no staffing or scale economies. |
| 4 | Comp fit as is | +10% high-rise premium (assumption) | The 2 km comp set includes low-rise Westwood stock. Wilshire Corridor high-rise one-beds list at about $3,480–4,195 for roughly 700 sf. |
| 5 | Acquisition at $216/sf | Shown two ways: a buyer paying $216/sf, and the owner's view (no purchase, but office income given up) | You cannot buy one floor of a Douglas Emmett tower. For the owner, the real cost is lost office rent. |

**Results (mid case)**

| Scheme | Study: cost / NOI / yield | Mine, buyer view: cost / NOI / yield | Mine, owner view: new capital / yield |
|---|---|---|---|
| A, 28 units | $18.81M / $0.57M / 3.0% | $15.56M / $0.58M / **3.7%** | $10.0M / 5.8% |
| B, 22 units | $18.81M / $0.52M / 2.7% | $15.56M / $0.53M / **3.4%** | $10.0M / 5.2% |
| C, deeper units (massing estimate) | — | $16.61M / $0.68M / **4.1%** | $11.1M / 6.1% |

All cases fall short of the 7.15% needed. With the cost corrections alone, before any rent change, A rises from 3.0% to 3.6%.

**What the study missed: the office alternative.** At the West LA Class A asking rent of $5.88/sf/mo full-service, less 20% concessions and about $1.40/sf/mo opex, the floor's 26,711 rentable sf yields about $1.06M/yr as office. After amortising $100/sf of tenant improvements over a 7-year lease, that is about $0.68M/yr.

- If the floor could be leased, conversion **loses** money compared with keeping it as office: A −$0.10M/yr, C ±$0.
- With a 50% chance of leasing, the incremental yield is only 2–3%.
- Conversion wins only if floor 16 is effectively unleasable as office.

**Rent needed to make it work (35% opex):**

| | Buyer view, rent needed | Owner view, rent needed |
|---|---|---|
| A | +120% (average about $5,400/mo for 445 sf) | +38% (about $3,390/mo) |
| C | +100% | +30% (about $3,770/mo for about 577 sf) |

C's owner-view number is within reach of Wilshire Corridor high-rise listings. **That is the only path to viability I see.**

**Why the study is too pessimistic and too optimistic at once**
- *Too pessimistic:* it charges $500/sf on the core and the storage zone, and charges the linkage fee on shafts.
- *Too optimistic:* it leaves out single-floor plumbing and venting through another tenant's space, the opex of a one-floor operation, and the office income given up.
- Its "break-even conversion cost $76/sf" spreads the break-even across the whole gross floor area, which makes the gap look bigger than it is. That number is only meaningful per rentable sf.

### Per-unit cost-benefit

Method:
- Rent = comp fit + 10%.
- Unit NOI = (rent × 12 + $900 other income) × 95% occupancy × 65% after opex.
- Cost is my buyer-view total, allocated by unit sf. Shared space is carried pro rata.
- The drain run is from the bath to the nearest core face; fall is at ¼ in per ft.

**Scheme A**

| Units | sf | Rent/mo | NOI/yr | Cost | Yield | Drain run / fall |
|---|---|---|---|---|---|---|
| N2–N10 (9 units) | 408 | $2,569 | $19.6k | $510k | 3.8% | 3.7–8.8 m / 3–7 in |
| S2–S10 (9 units) | 410 | $2,576 | $19.6k | $512k | 3.8% | 3.6–10.3 m / 3–8 in |
| E1–E3 | 482–486 | $2,840–2,855 | $21.6–21.7k | $602–607k | 3.6% | 6.8–11.9 m / 6–10 in |
| W1–W3 | 492–495 | $2,877–2,888 | $21.9–22.0k | $615–619k | 3.5–3.6% | 7.5–12.1 m / 6–10 in |
| Corners N1, N11, S1, S11 | 536–545 | $3,038–3,071 | $23.1–23.3k | $670–681k | **3.4%** | 9.6–14.6 m / 8–12 in |

**Scheme B**

| Units | sf | Rent/mo | NOI/yr | Cost | Yield | Drain run / fall |
|---|---|---|---|---|---|---|
| N2–N7, S2–S7 (12 units) | 599–604 | $3,270–3,288 | $24.8–24.9k | $748–755k | 3.3% | 3.7–10.1 m / 3–8 in |
| Corners N1, N8, S1, S8 | 571–580 | $3,167–3,200 | $24.0–24.3k | $714–725k | 3.4% | 9.1–14.1 m / 7–12 in |
| E1–E3, W1–W3 | 482–495 | $2,840–2,888 | $21.6–22.0k | $602–619k | 3.5–3.6% | 6.8–12.1 m / 6–10 in |

Reading the tables:
- **Under this rent curve, smaller units always yield more.** The $974 fixed part of the rent favours unit count, which is why A beats B.
- **Corner units are the weakest in both schemes,** and they have the longest drain runs. Corners have two façades, so they are the natural place for **two-bed units**. The one-bed-only comp curve undervalues them.

## 4. Is either layout optimal? No.

The study chose a rectangular corridor loop. That fixes every unit at 6.2–6.45 m (about 21 ft) deep. But the glass is **13.2–13.4 m from the core along most of the north-west and south-east**, and 12–13 m at the ends. The result is 5,814 sf of dark "amenity" floor that earns nothing but still carries cost.

US residential depth is normally 30–35 ft. A **variable-depth scheme (C)**:
- puts the corridor against the core where the core is far away;
- keeps the current depth where the core is 8.9 m from the glass;
- caps units at 9.0 m (29.5 ft) and uses the deep end for the bath, laundry and a den or closet. A den would need borrowed light under CBC 1204.2.1.

On a simplified massing (±10%), that gives:
- **about 16,100 sf of units vs 12,453 (+30%);**
- floor efficiency of 76% vs 59%;
- about 2,800 sf of leftover space;
- the same 28 front doors, averaging about 577 sf.

C also puts the 8.4 m interior column rows inside the units' back third, in closets and wet walls, instead of in a corridor wall. It shortens drain runs too, because baths sit closer to the core.

The cost-benefit table above already includes C. It raises the buyer-view yield from 3.7% to 4.1% and the owner-view yield to 6.1%.

## 5. What would flip the verdict
1. Confirm floor 16 is unlikely to lease as office (the owner view). This is the deciding fact.
2. Redesign as C. Make corners two-beds.
3. Real Wilshire Corridor high-rise comps, filtered to 12th floor and up with views.
4. Get the as-built structural drawings and the core plan from LADBS: stairs, stack locations, beam depths, plenum height on floor 15.
5. Get an HCD/LADBS ruling on 11A vs 11B for a conversion.
6. Check the LADBS retrofit lists for 10880.

## 6. Scores out of 100

The weights are compliance 40, structure 30 and cost-benefit 30.

**Grade bands**
- 85+: build as drawn.
- 70–84: viable after fixes.
- 50–69: major rework needed.
- Under 50: reject.

| Criterion | Max | A | B | Basis |
|---|---|---|---|---|
| **Compliance** | **40** | **22** | **29** | |
| Zoning (adaptive reuse ordinance) | 5 | 5 | 5 | Both qualify by right |
| Room size, daylight, escape windows | 7 | 7 | 7 | All rooms pass the CBC 1208 and 1204 checks |
| Egress (stair door, stair separation, dead ends, elevator lobby) | 8 | 4 | 4 | Travel and dead ends OK. Stairs unproven, no elevator lobby |
| Accessibility (11A, and 11B if funded) | 8 | 3 | 5 | A: 1.05 m entries and tight baths. B: same baths, roomier units |
| Fire, sound, mixed occupancy, ventilation | 7 | 3 | 3 | Not addressed in either scheme; likely achievable |
| No hard failures | 5 | 0 | 5 | A: column C10 blocks the N8 entry |
| **Structure** | **30** | **16** | **23** | |
| Detected columns clear of usable rooms | 10 | 6 | 9 | A: one blocked entry. B: columns land in wide kitchens and living rooms |
| Robust to likely hidden columns | 8 | 3 | 7 | A: 3 baths and 1 entry hit. B: nothing critical |
| Drain and pipe-stack feasibility | 7 | 3 | 3 | Runs of 3.6–14.6 m through the floor 15 ceiling; stacks unknown |
| Gravity loads and seismic risk | 5 | 4 | 4 | Residential loads are below office loads. No seismic trigger, but the retrofit lists are unchecked |
| **Cost-benefit** | **30** | **15.6** | **15.1** | |
| Buyer yield vs 7.15% needed (12 × yield ÷ 7.15%) | 12 | 6.2 | 5.7 | 3.7% vs 3.4% |
| Owner view vs keeping it as office | 8 | 3 | 2 | 5.8% vs 5.2% on new spending. Both lose to an office lease |
| Space efficiency (6 × efficiency ÷ 80%) | 6 | 4.4 | 4.4 | Both rent 59% of the non-core floor |
| Unit and market fit | 4 | 2 | 3 | A: 408 sf units sit below the comp range, so leasing risk. B: near the comp median |
| **Total** | **100** | **54** | **67** | Both fall in "major rework needed" |

## Sources
- LA Ord. 188,793 text: https://cityclerk.lacity.org/onlinedocs/2021/21-1230-S9_ord_188793_12-23-25.pdf
- LA City Planning, adaptive reuse: https://planning.lacity.gov/project-review/adaptive-reuse
- Greenberg Glusker on the citywide ordinance: https://www.greenbergglusker.com/publications/citywide-adaptive-reuse-a-potential-solution-to-vacancy-and-housing
- CBC 11A scope: https://gocodebook.com/library/us/ca/ca-building-code/chapter-11a-housing-accessibility/section-1101a-application
- DGS 2025 Chapter 11A changes: https://www.dgs.ca.gov/BSC/Resources/2025-Title-24-California-Code-Changes/2025-Part-2-Chapter-11A-Housing-Accessibility
- CEBC change-of-occupancy seismic trigger: https://sandiego.gov/development-services/forms-publications/technical-bulletins/exst-5-1
- CEBC seismic evaluation: https://gocodebook.com/us/california/california-existing-building-code/seismic-retrofit-and-evaluation-guidelines/evaluation-and-applicability/when-is-a-seismic-evaluation-required
- LA retrofit ordinances: https://www.structuremag.org/article/seismic-retrofit-ordinances-part-4/
- Gensler on unit depth: https://bankerandtradesman.com/challenging-the-myth-how-to-convert-big-office-towers-to-residential/
- Commercial Observer on conversion design: https://commercialobserver.com/2024/03/office-residential-conversion-how-to/
- Conversion plumbing: https://www.phcppros.com/articles/24128-reimagining-existing-buildings-plumbing-strategies-for-adaptive-reuse-and-office-to-residential-conversions
- Conversion costs: https://carrierjohnson.com/from-vacancy-to-value-what-it-takes-to-make-office-conversions-work-on-the-west-coast/
- West LA office rents (Q4 2025): https://mktgdocs.cbre.com/2299/7275a7a8-6b9e-4fd9-b3aa-31e853d23e39-925379335/West_LA_Office_Figures_Q4_2025.pdf
- Wilshire Corridor listings: https://www.apartments.com/10747-wilshire-blvd-los-angeles-ca-unit-1103/zfmtsxy/ and https://www.apartments.com/10390-wilshire-blvd-los-angeles-ca-unit-506/75b1dmz
- Neighbouring building structure (10920 Wilshire): https://www.capitalprograms.ucla.edu/file/pdf/SeismicSafety/WILSHIRECTR.pdf
- Building facts: https://www.skyscrapercenter.com/building/wilshire-at-westwood/4926
