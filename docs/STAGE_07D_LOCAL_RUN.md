# Stage 7D — Windows / PowerShell local run

Run from the repository root.

## 1. Install and verify source

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gcp,analytics]"
.\.venv\Scripts\python.exe -c "import pharmstock; print(pharmstock.__version__)"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Expected version: `0.25.0`.

## 2. Optional local password overrides

The Compose file has explicitly local-only fallback credentials so the checkpoint is independently
runnable. For a stronger local setup, set these before the first database start:

```powershell
$env:PHARMSTOCK_POSTGRES_PASSWORD="choose-a-long-local-admin-password"
$env:PHARMSTOCK_APP_PASSWORD="choose-a-long-local-app-password"
$env:PHARMSTOCK_CDC_PASSWORD="choose-a-long-local-cdc-password"
```

Do not commit real credentials.

## 3. Run the visible checkpoint

```powershell
.\.venv\Scripts\python.exe scripts\run_checkpoint.py 7d
```

The command starts `pharmstock-postgres`, applies the idempotent schema/roles/publication,
loads Stage 7A/7B/7C master data, creates deterministic POS terminals and validates counts,
foreign keys, financial consistency and logical-replication readiness.

Expected final marker:

```text
STAGE_7D_STATUS=PASS
```

Expected core rows based on the current accepted artifacts:

```text
Products                 22,323
Price history             22,323
Organizations              3,558
Branches                   5,000
Product economics         22,323
Branch policies            5,000
Governorates                  27
POS terminals              >=5,000 (exactly sum(checkout_points))
CDC publication tables        13
```

## 4. Inspect PostgreSQL directly

```powershell
docker compose -f infra\docker\docker-compose.postgres.yml ps

docker compose -f infra\docker\docker-compose.postgres.yml exec -T postgres `
  psql -U pharmstock_admin -d pharmstock_ops -c "select count(*) from master.product;"

docker compose -f infra\docker\docker-compose.postgres.yml exec -T postgres `
  psql -U pharmstock_admin -d pharmstock_ops -c "select count(*) from pos.terminal;"
```

The database is also available to local tools on `localhost:5433`.

## 5. Stop without deleting data

```powershell
docker compose -f infra\docker\docker-compose.postgres.yml stop postgres
```

To start it again:

```powershell
docker compose -f infra\docker\docker-compose.postgres.yml up -d postgres
```

Do **not** use `down -v` unless you intentionally want to destroy the local PostgreSQL volume.
