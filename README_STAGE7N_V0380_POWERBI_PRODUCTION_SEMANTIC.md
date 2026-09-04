# PharmStock Stage 7N v0.38.0 patch

Adds the production Power BI semantic-serving boundary after Stage 7M.

Key properties:

- 9 metadata-only BigQuery views in `pharmstock_pbi_prod`
- 5 read-only PostgreSQL BI views in schema `bi`
- dedicated `pharmstock_bi` least-privilege role
- 24 explicit DAX measures
- 5 report pages
- no Power BI writeback
- no procurement / ML / decision mutation
- no BigQuery data-table copy
- BigQuery Sandbox storage guard preserved
