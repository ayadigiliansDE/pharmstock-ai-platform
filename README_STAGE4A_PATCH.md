# PharmStock V2 — Stage 4A Patch (v0.14.0)

Apply this **flat** patch directly to the project root and overwrite matching files.
It upgrades Stage 3C v0.13.0 to Stage 4A v0.14.0.

Key additions:
- Apache Spark 4.2.0 Docker runtime.
- Structured Streaming Kafka -> Bronze Parquet job.
- Common envelope validation + quarantine.
- Kafka dual listeners: Windows `localhost:9092`, Docker `kafka:19092`.
- Spark checkpoint restart acceptance.
- 12 new Bronze-contract tests; total offline regression target: 162 passed.

After extraction, follow `docs/STAGE_04A_LOCAL_RUN.md`.
