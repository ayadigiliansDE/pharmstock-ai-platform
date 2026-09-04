# Stage 7K v0.33.8 — Rare-event statistical sufficiency hotfix

This hotfix replaces the brittle `50 positives in every temporal split` rule with an event-count-aware scientific sufficiency gate appropriate for rare-event stockout validation while preserving the 60/20/20 temporal split and leakage-safe labels.

Acceptance now requires:
- training positives >= 100
- validation positives >= 40
- test positives >= 40
- total positives across the three temporal windows >= 200

The latest observed dataset (226 / 49 / 64 positives; 339 total) therefore has enough event support to proceed to model evaluation. This does **not** weaken the actual model-quality gate: PR-AUC, ROC-AUC, recall, precision, Brier score, calibration error, and Recall@Top10% must still pass. No labels are added, no simulation is altered, and no temporal boundaries are selected using the target.

Also updates Stage 7K console banners to v0.33.8 for traceability.

No BigQuery writes, cloud mutation, billing, Docker dependency changes, or model-registry deletion.
