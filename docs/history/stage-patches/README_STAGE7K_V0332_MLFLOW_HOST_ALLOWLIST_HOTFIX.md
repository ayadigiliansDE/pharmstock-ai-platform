# Stage 7K v0.33.2 — MLflow Docker Host-Allowlist Hotfix

Fixes MLflow 3.15.2 DNS-rebinding protection rejecting internal Docker service requests with `Host: mlflow:5000`.

Changes:
- Explicitly allows only `mlflow`, `mlflow:5000`, `localhost:*`, and `127.0.0.1:*`.
- Keeps MLflow security middleware enabled; does **not** use wildcard `*`.
- Restricts browser CORS to local MLflow UI origins.
- Adds a regression test.
- No BigQuery writes, no model/registry deletion, no CDC changes, no cloud billing.

After extraction, rerun Stage 7K with `--no-build`; the ML image already contains MLflow 3.15.2 and the compose command change will recreate only the MLflow service as needed.
