"""Small local operator CLI for Stage 7L governed decision cases."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

COMPOSE_FILES = (
    Path("infra/docker/docker-compose.kafka.yml"),
    Path("infra/docker/docker-compose.postgres.yml"),
    Path("infra/docker/docker-compose.stage7f.yml"),
    Path("infra/docker/docker-compose.stage7k.yml"),
    Path("infra/docker/docker-compose.stage7k5.yml"),
    Path("infra/docker/docker-compose.stage7l.yml"),
)


def _compose_run(*worker_args: str) -> int:
    command = ["docker", "compose"]
    for path in COMPOSE_FILES:
        command.extend(("-f", str(path)))
    command.extend(
        (
            "run",
            "--rm",
            "--no-deps",
            "stage7l-workflow",
            "python",
            "-m",
            "operations.stage7l.worker",
            *worker_args,
        )
    )
    env = os.environ.copy()
    env.setdefault("COMPOSE_IGNORE_ORPHANS", "true")
    return subprocess.run(command, check=False, env=env).returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Stage 7L decision cases")
    parser.add_argument("--list-open", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--case-id")
    parser.add_argument(
        "--action", choices=("acknowledge", "approve-draft", "reject", "close")
    )
    parser.add_argument("--actor", default="local-operator")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if args.list_open:
        raise SystemExit(_compose_run("--list-open", "--limit", str(args.limit)))
    if not args.case_id or not args.action:
        parser.error("use --list-open or provide --case-id and --action")
    raise SystemExit(
        _compose_run(
            "--case-id",
            args.case_id,
            "--action",
            args.action,
            "--actor",
            args.actor,
            "--note",
            args.note,
        )
    )


if __name__ == "__main__":
    main()
