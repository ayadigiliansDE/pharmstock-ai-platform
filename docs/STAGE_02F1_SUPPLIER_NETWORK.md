# Stage 2F.1 — Supplier Network Scaling

Stage 2F proved the physical procurement loop with six fictional suppliers. Stage 2F.1 keeps that checkpoint runnable but adds a supplier ecosystem sized for the long-term target of 1,000+ pharmacy branches.

## Default synthetic network

- 12 national distributors
- 24 regional wholesalers (6 per EgyptRegion)
- 81 local wholesalers (3 per governorate)
- 24 direct manufacturers
- 12 cold-chain specialists
- total: 153 fictional suppliers

Every supplier has deterministic synthetic service metadata: geographic coverage, catalog coverage ratio, expected fill rate, reliability score, lead time, cycle capacity, and cold-chain capability.

## Branch supplier panel

A branch does not order from all 153 suppliers. It receives a deterministic preferred panel of 12 geographically valid suppliers spanning national, regional, local, manufacturer-direct, and cold-chain archetypes.

For each product requiring replenishment, suppliers are ranked using:

1. governorate / region eligibility;
2. deterministic catalog-assortment coverage;
3. reliability score;
4. expected fill rate;
5. lead time;
6. product-specific supplier affinity;
7. remaining procurement-cycle capacity.

If the preferred panel cannot supply a product, the engine may fall back to other geographically valid suppliers in the wider network. If the network still cannot allocate the required quantity, the deferred units are written to `procurement_backlog.csv` instead of being silently lost.

## Truth boundary

All supplier names, service metrics, capacities, coverage and lead times remain synthetic. They are not claims about real Egyptian pharmaceutical distributors. Prices and costs remain outside the simulation.

## New inspectable outputs

- `supplier_master.csv`: all supplier master and capability fields.
- `supplier_utilization.csv`: POs, lines, ordered units, capacity use and branches served per supplier.
- `branch_supplier_panels.csv`: the 12 preferred suppliers selected for every branch.
- `branch_procurement_kpis.csv`: includes preferred panel size and active suppliers per branch.
- `procurement_manifest.json`: records supplier type counts and the supplier-network policy.

Stage 2F remains runnable with its original six-supplier checkpoint. Stage 2F.1 is the scaled path used before Kafka is introduced.

Expected fill rate is currently a supplier-selection signal, not a simulated partial-delivery outcome. Stage 2F.1 still receives ordered quantities in full after allocation; supplier disruptions can be introduced later without changing the master-data contract.
