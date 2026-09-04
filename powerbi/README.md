# PharmStock Power BI serving assets

Stage 6A prepares a dedicated BigQuery serving dataset (`pharmstock_pbi`) and a
source-controlled semantic contract for Power BI Desktop.

## Initial connection mode

Use **Import** first. The model is currently small, and Import gives predictable
interactive performance. DirectQuery and incremental-refresh decisions are deferred
until production scale and refresh SLAs are measured.

Use the 64-bit Google BigQuery connector and, when available in the installed Power BI
Desktop build, the ADBC v2 implementation. Set the Billing Project ID to the PharmStock
GCP project.

## Model rules

- `dim_date`, `dim_product`, `dim_branch`, and `dim_supplier` are dimensions.
- Facts and marts are on the many side of relationships.
- Cross-filter direction is single, from dimension to fact/mart.
- Technical identifiers are hidden from report authors after relationships are created.
- Explicit DAX measures come from `measures.dax`.
- No price, revenue, cost, or margin measure exists until an authoritative monetary source
  is added upstream.
- Product metadata remains an official U.S. openFDA reference catalog; the Egyptian
  pharmacy and supplier networks remain explicitly synthetic.

## Suggested first report pages

1. **Operations Overview** — requested, fulfilled, lost units, fulfillment rate, active
   branches, reorder events, and a daily requested-vs-fulfilled trend.
2. **Inventory Health** — units in/out, net movement, reorders by branch and product.
3. **Product Demand** — products by requested/lost units and fulfillment rate.
4. **Procurement & Suppliers** — purchase orders, ordered/received/restocked units,
   procurement fill rate, and supplier delivery performance.

The actual PBIX/PBIP authoring is a later stage because Power BI Desktop is the authority
that validates proprietary report/semantic-model project files.

## Stage 6B Desktop build kit

Run `python scripts/run_checkpoint.py 6b` only after Stage 6A cloud deployment has
passed. The generated `artifacts/stage6b` directory contains the exact Desktop build
manifest, relationship checklist, DAX checklist, report specification, and acceptance
checklist. The build kit does not fabricate a PBIX/PBIP file outside Power BI Desktop.

## Stage 7N production upgrade

For the current Stage 7H–7M architecture, use the generated Stage 7N build kit in
`artifacts/stage7n/` and the `pharmstock_pbi_prod` dataset. Stage 7N supersedes the original
Stage 6A/6B source contract for the production-like project path because it includes the 31.9M-row
rebuild, current inventory/expiry state, ML predictions and governed decision workflow.
