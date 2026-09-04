# Stage 7D Lint Hotfix — v0.25.1

Quality-only hotfix for Stage 7D.

- Removed the unused `os` import from `scripts/run_stage7d_onprem.py`.
- No PostgreSQL schema, loader, CDC, Docker Compose, financial, or network behavior changed.
- Runtime acceptance remains `STAGE_7D_STATUS=PASS`.
