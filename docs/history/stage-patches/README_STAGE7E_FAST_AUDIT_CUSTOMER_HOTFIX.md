# Stage 7E v0.26.1 — Fast Audit + Customer Digital Twin

This release supersedes Stage 7E v0.26.0. Do not rerun v0.26.0.

It specifically addresses the observed PostgreSQL stall where the final audit spent a long time
inside `UPDATE audit.simulation_run` with `wait_event=BuffileRead`. The expensive full-table
rescan has been removed.

It also adds the previously agreed privacy-safe customer simulation: customer profiles,
households, loyalty accounts, patient profiles, known/anonymous customer modes, prescriptions,
repeat/chronic behavior and customer-linked POS transactions without direct personal data.

Additional resilience in v0.26.1:

- PostgreSQL keeps the run `RUNNING` after the fast metric finalizer; the Python acceptance layer
  marks it `PASS` only after all scale, financial, inventory, privacy and customer checks pass.
- A database-size increase is no longer a correctness gate, because an interrupted v0.26.0 run can
  leave reusable relation files/bloat even after rollback. Database size is still measured and
  reported.
- The fulfilled-demand insert now reads from the Stage 7E staging seeds rather than rescanning the
  multi-million-row operational sale tables.
- Customer profiles represent pseudonymous purchasers; direct PII is never generated. Child age
  bands are represented in `patient_profile`, not in the customer/purchaser identity.

Static acceptance in the build environment: `327 passed`, `compileall` PASS, and zero Python lines
above 100 characters. Ruff is intentionally re-run on Windows from the project's own `.venv` before
runtime acceptance.
