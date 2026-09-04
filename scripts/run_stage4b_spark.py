"""Run the Stage 4B Spark Silver transformation through Docker Compose."""

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
        "spark-stage4b",
        "/opt/spark/bin/spark-submit",
        "--master",
        "local[*]",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "/opt/pharmstock/spark/jobs/stage4b_silver.py",
    ]


def main() -> None:
    print("=== PharmStock V2 / Stage 4B Spark Runner ===")
    print("Spark image:       apache/spark:4.2.0-python3")
    print("Input:             Stage 4A Bronze Parquet")
    print("Output:            Deduplicated normalized Silver Parquet")
    print("Execution mode:    Docker / local[*] / deterministic full refresh")
    print("Running Spark...")
    completed = subprocess.run(spark_compose_command(), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
