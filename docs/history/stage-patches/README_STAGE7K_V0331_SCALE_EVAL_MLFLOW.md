# Stage 7K v0.33.1 — Scale, Evaluation, MLflow Upgrade

This cumulative patch supersedes v0.33.0. Apply v0.33.1 directly if v0.33.0 was not applied.

## Why this revision exists

A production ML project must distinguish the total warehouse row count from the eligible training observations for each model. PharmStock has 31,954,735 rows across 26 relational tables. Those rows are not one homogeneous training table and should never be concatenated blindly into a model.

v0.33.1 changes the training data strategy from a simple fixed row LIMIT to deterministic, time-preserving, model-specific sampling:

- Demand forecasting: complete product histories are selected dynamically to fit the row budget. The full time axis is preserved for every sampled product.
- Stockout risk: complete branch-product histories are selected with a cumulative historical-row budget. The future 7-day label remains temporally valid.
- Expiry risk: batches are stratified across expiry-horizon buckets before deterministic sampling.
- Reorder optimization reuses the stockout historical replay set because it needs the same observed future-demand trajectories.

Default model feature-row budget is 500,000 and remains configurable through `PHARMSTOCK_ML_MAX_TRAINING_ROWS`.

## MLflow

The Stage 7K Docker image is pinned to MLflow 3.15.2. This is an explicit reproducible dependency, not an unpinned `latest` install.

## Scientific evaluation

Demand forecasting:
- 1/7/14/30 day horizons
- temporal train/validation/test split
- rolling-origin backtesting
- multiple naive baselines
- MAE, RMSE, R2, WAPE, sMAPE, median AE, p90 AE, bias
- paired bootstrap 95% confidence interval for MAE improvement
- demand-volume quartile diagnostics

Stockout risk:
- observed future 7-day stockout label
- PR-AUC / average precision
- ROC-AUC
- Brier score
- expected calibration error
- precision, recall, specificity, balanced accuracy, F1, F2
- Precision@Top10%, Recall@Top10%, Lift@Top10%
- class imbalance handling and probability calibration

Reorder optimization:
- historical future-demand replay
- fill rate versus baseline
- lost units versus baseline
- overstock guard
- positive recommendation rate
- invariant stress scenarios

Expiry / slow-moving:
- sell-through probability rather than fabricated labels
- stochastic Poisson / negative-binomial calibration
- calibration MAE and maximum error
- rank correlation
- right-censoring explicitly disclosed
- expiry-horizon stratified validation sample

## BigQuery / cost safety

- BigQuery remains READ ONLY.
- No feature tables are created.
- No raw baseline copy is created.
- No billing is enabled.
- No paid GCP service is deployed.
- Existing 8.2 GiB warning and 8.5 GiB hard-stop policy remains unchanged.

## Streaming integration

Kafka is not a decorative component. Stage 7I already provides the durable CDC path into the BigQuery delta/current-state layer. Stage 7K.5 will add operational streaming ML:

PostgreSQL -> Debezium -> Kafka -> Spark Structured Streaming -> live features -> Stage 7K serving API -> prediction/alert Kafka topics.

The stream will drive near-real-time stockout/reorder scoring, monitoring, and later dashboard/assistant freshness. Historical data remains the source for training and backtesting; stream data is accumulated into history and participates in later retraining windows.
