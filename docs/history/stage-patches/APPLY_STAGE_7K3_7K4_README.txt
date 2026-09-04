PharmStock AI Platform V2 — Stage 7K v0.33.1
Scientific Validation + Scale-Safe Sampling + MLflow 3.15.2 + Zero-Cost Cloud-Ready Blueprint

Extract this root-relative patch directly into:
D:\Data_Engineer_Work_With_VSCode\Projects\pharmstock-ai-platform-v2

Then run:

$env:PHARMSTOCK_BQ_PROJECT="pharmstock-ai-bq2-2026"
$env:PHARMSTOCK_BQ_SANDBOX="1"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests\test_stage7k_ml.py -q
.\.venv\Scripts\python.exe scripts\run_stage7k.py
.\.venv\Scripts\python.exe scripts\run_stage7k.py --execute

Only after Stage 7K scientific PASS:
.\.venv\Scripts\python.exe scripts\run_stage7k_cloud_ready.py --write-plan
.\.venv\Scripts\python.exe scripts\export_stage7k_cloud_bundle.py --replace

The cloud-ready commands are LOCAL ONLY. They do not enable billing, run
terraform apply, push images, or deploy Vertex AI / Cloud Run resources.

Note: v0.33.1 upgrades the Stage 7K image to MLflow 3.15.2, so the first execute must rebuild the Docker image. Subsequent reruns may use --no-build.
