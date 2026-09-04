# Stage 7E — High-Fidelity Historical POS & Operational Simulator

Stage 7E turns the Stage 7D PostgreSQL source of record into a production-like pharmacy workload.
It generates deterministic historical operations directly inside PostgreSQL instead of exporting a
small CSV fixture.

## Truth boundary

- Product identity and observed retail price: `PUBLIC_MARKET_EGYPT` from Stage 7A.
- Pharmacy branches: `SYNTHETIC_CALIBRATED` from Stage 7B.
- Purchase cost and commercial policy: `SYNTHETIC_CALIBRATED` from Stage 7C.
- POS, returns, inventory, suppliers, procurement, and historical operations generated here:
  `SYNTHETIC_CALIBRATED`.
- No customer names, phone numbers, addresses, loyalty IDs, prescription-patient identity, or other
  customer PII is generated.

## Production behavior modeled

The workload uses branch demand indices, Egypt Friday/Saturday weekend effects, branch opening
hours, 24-hour branches, service modes, checkout capacity, branch-specific payment mix and discount
ceilings. Product selection follows a deterministic long-tail popularity curve. Baskets contain
1–4 lines with a mostly single-unit quantity distribution. Demand is captured independently from
sales so fulfilled demand, partial fulfillment, lost units and full stockouts are measurable rather
than inferred from completed sales alone.

Every generated sale is financially reconciled:

- gross sales - discount = net sales
- net sales - COGS = gross profit
- one captured payment equals the sale net amount

Historical inventory is generated from sold branch/product combinations. Each branch/product gets
opening stock, a batch, an inventory position, an opening receipt movement, and one stock movement
per sale line. Opening-stock procurement is represented with a calibrated supplier network,
purchase orders, purchase-order lines, goods receipts and receipt lines. Goods receipts include a
deterministic calibrated 0–5 day delay distribution so future supplier-delay ML has positive and
negative labels.

Returns are deliberately low-rate and use `QUARANTINE` disposition so customer returns do not
silently re-enter sellable medicine inventory.

## Profiles

- `dev`: 27 branches, 3 days. Fast functional smoke test.
- `acceptance`: 5,000 branches, 14 days. Default checkpoint and million-scale local workload.
- `prod_like`: 5,000 branches, 365 days. Intended final production-like history; guarded by an
  explicit `--allow-large-run` because it can create tens of millions of transactions and much more
  than that in operational rows.

The default acceptance profile is expected to create roughly 1.7 million sale headers and about
3.1 million sale lines with the deterministic Stage 7B network. Actual acceptance is based on
measured database counts, not on these estimates.

## Idempotency

Each run has a deterministic run token derived from profile/window/seed. An already completed run
is not silently duplicated. Choose a different window/profile for another history segment.

## CDC boundary

Stage 7E does not create the Debezium connector or replication slot. Stage 7D's existing 13-table
publication remains unchanged here; Stage 7F will add the new `pos.demand_attempt` table to the CDC
publication, attach Debezium to this database, and test the real-time change path.
