# PharmStock V2 — Stage 7E corrected patch (v0.26.1)

Stage 7E now builds a high-fidelity, privacy-safe Egyptian pharmacy customer/POS digital twin
and removes the production-scale audit bottleneck found in v0.26.0.

Key additions and corrections:

- Customer/household/loyalty/patient entities with pseudonymous identifiers only.
- 50 customer profiles, 20 households and 60 patient profiles per modeled branch.
- Known, anonymous, loyalty and delivery-registered transaction modes.
- Customer-to-sale and loyalty-to-sale linkage.
- Prescription context separated from customer identity; customer and patient are different entities.
- Chronic-repeat customers keep stable first-line product affinity across repeat purchases.
- Customer prescription propensity drives prescription transactions.
- Known-customer preferred payment and basket-size behavior influence POS transactions.
- Discount sensitivity influences discount incidence while the branch ceiling remains enforced.
- No names, phones, emails, addresses, national IDs or other direct PII are generated.
- `SYNTHETIC_CALIBRATED` is retained for all customer/patient/transaction behavior.
- Stage 7A product identity and observed retail prices remain `PUBLIC_MARKET_EGYPT`.

Performance/resilience correction:

- Removed the v0.26.0 final `UPDATE ... jsonb_build_object(... COUNT(*) ...)` over operational
  tables that caused long `BuffileRead` temporary-file scans.
- Removed explicit end-of-run `ANALYZE` operations from the blocking transaction.
- Materialized the stock plan once and reused it instead of repeating heavy branch/product work.
- Generation now commits before audit finalization.
- Final metrics use bounded staging aggregates rather than joins/rescans of multi-million-row
  operational tables.
- A committed `RUNNING` run can resume finalization without regenerating historical rows.
- Verification uses persisted metrics plus database constraints/index guards.

The default acceptance profile remains 5,000 branches over 14 days and still requires at least
1.2 million sale headers and 2.0 million sale lines.
