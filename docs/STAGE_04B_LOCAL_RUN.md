# Stage 4B — Local Run (Windows / PowerShell)

Prerequisites:

- Stage 4A has already completed successfully on the currently running local Kafka broker.
- `artifacts/stage4a/_SUCCESS` exists.
- Docker Desktop is running.
- `pharmstock-kafka` is healthy.

Do **not** recreate Kafka between Stage 4A and Stage 4B because the Stage 4A Spark checkpoint
belongs to the current local broker history.

## 1. Verify the project

```powershell
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Expected version: `0.15.0`.

## 2. Verify Kafka

```powershell
docker compose -f infra/docker/docker-compose.kafka.yml ps
```

`pharmstock-kafka` must be healthy.

## 3. Run Stage 4B

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 4b
```

The checkpoint intentionally publishes:

- replay copies of known Stage 4A events,
- one same-`event_id` semantic conflict,
- one common-envelope-valid but event-specific-invalid payload,
- coverage probes so all six Silver tables are visible.

It then runs an incremental Stage 4A pass, followed by two deterministic Stage 4B full
refreshes. The second Silver run must produce the same accounting counts.

Expected final marker:

```text
STAGE_4B_STATUS=PASS
```

## 4. Inspect the result

```text
artifacts/stage4b/
├── silver/
│   ├── event_index/
│   ├── sales_units_fulfilled/
│   ├── inventory_quantity_changed/
│   ├── inventory_reorder_required/
│   ├── purchase_order_created/
│   ├── goods_receipt_received/
│   └── restock_applied/
├── audit/
│   ├── exact_duplicates/
│   ├── event_id_conflicts/
│   └── payload_rejects/
├── run_summary.json
├── first_pass_summary.json
├── second_pass_summary.json
├── silver_verification.json
└── _SUCCESS
```
