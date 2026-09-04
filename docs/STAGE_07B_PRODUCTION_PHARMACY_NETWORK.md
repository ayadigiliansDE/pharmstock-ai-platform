# Stage 7B — Production Egyptian Pharmacy Network

Stage 7B replaces the tiny 25-branch demonstration network with a deterministic,
production-like Egyptian pharmacy-market digital twin.

## Public calibration anchors

The generated businesses are fictional. The simulator uses public 2024 statistics only as
calibration inputs:

- CAPMAS population estimate on 1 January 2024: **105,914,499**.
- CAPMAS population and urban/rural shares for all **27 governorates**.
- CAPMAS national total of **86,741 general pharmacies in 2024**.
- Egyptian Drug Authority licensing reports are retained as an external regulatory reference.

The project does **not** claim generated branch names, ownership, locality codes, capacities,
or operating profiles are real licensed pharmacies.

## Profiles

| Profile | Branches | Intended use |
| --- | ---: | --- |
| `dev` | 27 | Fast code checks while retaining all governorates |
| `acceptance` | 5,000 | Default laptop-friendly production-like scale |
| `full_market` | 86,741 | National reference-scale generation |

The default 5,000-branch network is a modeled sample covering 5.76% of the national pharmacy
reference. Every branch therefore carries a `branch_expansion_weight` of 17.3482 for analyses
that intentionally estimate national-scale totals. Raw operational simulations should still use
the actual 5,000 generated branches unless a downstream stage explicitly applies this weight.

## Allocation policy

Branches are allocated across governorates by CAPMAS population share using deterministic
largest-remainder allocation. Each governorate receives at least one branch. Urban/rural locality
assignment uses the published 2024 urban share for that governorate.

Per-governorate pharmacy totals are **not** claimed as official. The field
`modeled_full_market_pharmacies` is a population-proportional modeled allocation that reconciles
to the official national total of 86,741.

## Synthetic operating assumptions

The default branch-level ownership mix is a simulator assumption:

- independent: 70%
- chain: 24%
- hospital network: 4%
- digital operator: 2%

These values are `SYNTHETIC_CALIBRATED`, not published Egyptian market shares. Branch scale,
24-hour operation, assortment capacity, delivery support, cold-chain support, and demand index
are generated deterministically from ownership/locality/scale policies.

## Outputs

`artifacts/stage7b/` contains:

- `production_pharmacy_organizations.csv`
- `production_pharmacy_branches.csv`
- `governorate_calibration.csv`
- `network_summary.json`
- `network_quality_report.json`
- `calibration_references.json`
- `_SUCCESS`

## Quality gates

Stage 7B fails if:

- fewer than all 27 governorates are represented;
- branch IDs or branch codes are duplicated;
- a branch references a missing organization;
- generated rows are not explicitly marked `SYNTHETIC_CALIBRATED`;
- modeled governorate counts do not reconcile to the selected profile;
- the modeled full-market allocation does not reconcile to 86,741.
