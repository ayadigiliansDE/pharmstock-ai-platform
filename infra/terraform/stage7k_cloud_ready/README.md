# Stage 7K.4 — Cloud-ready blueprint (zero-cost mode)

This folder is **architecture-as-code only**. The hard cost guard is:

```hcl
enable_billable_resources = false
```

With the default value, the resource collections are empty and no Google Cloud
resource is intended to be created. Do not run `terraform apply` with the flag
set to `true` unless billing and deployment are explicitly approved later.

Planned production split:

- Demand forecast → Vertex AI custom prediction container.
- Stockout classifier → Vertex AI custom prediction container.
- Reorder optimizer → Cloud Run decision API.
- Expiry sell-through risk → Cloud Run decision API.
- Container images → Artifact Registry.
- Secrets → Secret Manager references; never Terraform plaintext.
- Predictive model drift → Vertex monitoring design.
- Decision-engine drift → Cloud Run logs/metrics plus input distribution checks.

The local exporter `scripts/export_stage7k_cloud_bundle.py` creates an immutable
build context with SHA-256 checksums. It does not push images or call any cloud
API.
