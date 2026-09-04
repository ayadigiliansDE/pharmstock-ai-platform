# BigQuery

Stage 5A generates the executable/dry-run warehouse artifacts under `artifacts/stage5a/` from
code-owned contracts in `src/pharmstock/warehouse/bigquery_contracts.py`.

Do not hand-edit generated schema JSON files. Update the contract module and rerun Stage 5A so
schema, DDL, load plan, and tests stay synchronized.
