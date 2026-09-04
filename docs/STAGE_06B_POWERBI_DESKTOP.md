# Stage 6B — Power BI Desktop Semantic Model & Operational Report

Stage 6B is the first Desktop authoring stage. It consumes only the dedicated
`pharmstock_pbi` serving dataset produced by Stage 6A.

## Scope

- Google BigQuery connector, new implementation / ADBC V2.
- Import storage mode for the initial model.
- 11 serving views.
- 17 active one-to-many, single-direction relationships.
- `dim_date` marked as the model Date table.
- 18 explicit, non-monetary DAX measures.
- Three source-controlled report-page specifications.

## Important acceptance boundary

The Python checkpoint only generates and validates the Desktop build kit. It does
not claim that a PBIX/PBIP semantic model exists. `STAGE_6B_STATUS=PASS` is only
valid after the model is built and refreshed inside Power BI Desktop.

## Truth boundary

The report must not introduce price, revenue, cost, or margin. The current
warehouse does not contain authoritative monetary data.
