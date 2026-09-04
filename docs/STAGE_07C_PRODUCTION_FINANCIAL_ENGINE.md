# Stage 7C — Production Pricing & Financial Engine

Stage 7C makes the digital twin financially usable while preserving the difference between
observed market data and simulation assumptions.

## Truth boundary

- `retail_price_egp`: carried from Stage 7A, `PUBLIC_MARKET_EGYPT`.
- `purchase_cost_egp`: deterministic `SYNTHETIC_CALIBRATED` value.
- `modeled_gross_margin_pct`: simulation parameter, **not** an EDA-approved margin schedule.
- customer discount ceilings / payment mix / shrinkage reserves: `SYNTHETIC_CALIBRATED`.
- tax: `NOT_INFERRED_NO_TAX_DECOMPOSITION`; Stage 7C does not invent a universal medicine VAT rate.

## Outputs

- `product_unit_economics.csv`
- `branch_commercial_policy.csv`
- `sample_transaction_financials.csv`
- `financial_model_assumptions.json`
- `financial_quality_report.json`
- `_SUCCESS`

The actual POS transaction simulator in a later stage will reuse the same line-financial
calculation contract so Revenue, COGS, Gross Profit and Inventory Value reconcile.
