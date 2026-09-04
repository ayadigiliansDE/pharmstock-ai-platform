"""Run one Stage 4A Spark AvailableNow pass through Docker Compose."""

from __future__ import annotations

import subprocess

SPARK_PACKAGE = "org.apache.spark:spark-sql-kafka-0-10_2.13:4.2.0"


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
        "spark-stage4a",
        "/opt/spark/bin/spark-submit",
        "--master",
        "local[*]",
        "--packages",
        SPARK_PACKAGE,
        "--conf",
        "spark.jars.ivy=/root/.ivy2",
        "--conf",
        "spark.driver.host=127.0.0.1",
        "/opt/pharmstock/spark/jobs/stage4a_bronze.py",
    ]


def main() -> None:
    print("=== PharmStock V2 / Stage 4A Spark Runner ===")
    print("Spark image:       apache/spark:4.2.0-python3")
    print(f"Kafka connector:   {SPARK_PACKAGE}")
    print("Execution mode:    Docker / local[*] / Trigger.AvailableNow")
    print("Running Spark...")
    completed = subprocess.run(spark_compose_command(), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
