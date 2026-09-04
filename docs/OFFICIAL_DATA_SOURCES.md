# Official Data Sources

## openFDA NDC Directory — Stage 2B
- Purpose: real marketed-drug product and package records for the U.S. source market.
- API: https://api.fda.gov/drug/ndc.json
- Documentation: https://open.fda.gov/apis/drug/ndc/
- Searchable fields: https://open.fda.gov/apis/drug/ndc/searchable-fields/
- Download page: https://open.fda.gov/apis/drug/ndc/download/
- Authentication/limits: https://open.fda.gov/apis/authentication/
- Paging: https://open.fda.gov/apis/paging/

Boundary: NDC is not treated as Egyptian registration data. The canonical PharmStock model is source-neutral so an official Egyptian Drug Authority adapter can be added separately when a suitable official machine-readable source is available.

## RxNorm — planned enrichment
- Purpose: standardized drug concept identifiers/names (RxCUI) and entity resolution.
- API documentation: https://lhncbc.nlm.nih.gov/RxNav/APIs/RxNormAPIs.html

Stage 2B keeps an RxCUI supplied by openFDA harmonization when present; it does not yet issue one RxNorm request per product.

## Stage 7A Egypt-market pharmaceutical sources

### Egyptian Drug Authority (official regulatory reference)
- EDDB is the official Egyptian Drug Database search reference for registered products.
- EDA documentation shows product/registration attributes including dosage form, route, strength,
  pack details, registration number, license status, price status, storage condition and dates.
- Pharma Data Hub documentation adds GTIN/package/priced-package concepts.
- Stage 7A does not bypass verification-code controls and does not claim a bulk EDDB export exists.

### Public Egypt-market snapshot (operational seed)
- Repository: `https://github.com/karem505/egyptian-drug-database`
- Default raw CSV: `data/egyptian-drugs.csv`
- License: CC0-1.0
- Classification in PharmStock: `PUBLIC_MARKET_EGYPT`
- It is used for market-oriented trade/scientific/manufacturer/class/route/EGP-price observations,
  not for asserting EDA registration or official price verification.
