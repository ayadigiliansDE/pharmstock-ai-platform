# Stage 7K v0.32.0

Adds a storage-safe local ML platform: four production-style models, MLflow
tracking and registry, champion aliases, local model artifacts, and one
multi-model inference API. BigQuery remains read-only throughout Stage 7K.

Build-safety hardening:
- `.dockerignore` excludes the multi-GB Stage 7G artifacts and local runtimes from Docker build context.
- MLflow readiness accepts its HTTP health response without assuming JSON.
- Acceptance includes one real inference smoke prediction per champion model.
