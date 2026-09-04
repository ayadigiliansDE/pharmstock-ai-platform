PharmStock V2 - Stage 7H v0.29.0

Extract this ZIP directly into the existing pharmstock-ai-platform-v2 project root and replace files.
There is no extra outer project directory in this archive.

1) pip install -e ".[dev,gcp,analytics]"
2) python -m pytest -q
3) ruff check .
4) python scripts/run_checkpoint.py 7h

The checkpoint is local-only. Actual Google Cloud mutation requires:
python scripts/run_stage7h_cloud.py --execute --replace

Do not rerun 7E/7F/7G just to deploy Stage 7H.
