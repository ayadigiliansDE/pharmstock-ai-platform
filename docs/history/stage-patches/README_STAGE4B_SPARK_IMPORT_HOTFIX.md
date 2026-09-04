# Stage 4B Spark Import Isolation Hotfix

This hotfix keeps the Spark analytics import path dependency-light.

Changes:
- adds `pharmstock.analytics.silver_contracts` for Spark-safe Silver routing constants;
- makes `pharmstock.analytics` lazy-load application-side Silver validation helpers;
- updates the Stage 4B Spark job to import only the dependency-light contract module;
- adds regressions proving Spark analytics imports work with Python `-S` (no site-packages/Pydantic).

No business logic or version change. Project version remains `0.15.0`.
