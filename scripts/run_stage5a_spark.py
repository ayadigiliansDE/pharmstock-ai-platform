"""Run Stage 5A Silver -> warehouse-ready Parquet validation through Docker Compose."""

from __future__ import annotations

import subprocess


def spark_compose_command() -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        "infra/docker/docker-compose.kafka.yml",
        "-f",
        "infra/docker/docker-compose.spark.yml",
        "run",
        "--rm",
        "spark-stage5a",
        "/opt/spark/bin/spark-submit",
        "--master",
        "local[*]",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "/opt/pharmstock/spark/jobs/stage5a_warehouse_export.py",
    ]


def main() -> None:
    print("=== PharmStock V2 / Stage 5A Spark Warehouse Export ===")
    print("Spark image:       apache/spark:4.2.0-python3")
    print("Input:             Stage 4B Silver Parquet")
    print("Output:            BigQuery-ready local Parquet")
    print("Cloud dependency:  NONE")
    print("Running Spark...")
    completed = subprocess.run(spark_compose_command(), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
