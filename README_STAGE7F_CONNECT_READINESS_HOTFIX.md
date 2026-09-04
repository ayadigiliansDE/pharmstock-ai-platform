# Stage 7F Kafka Connect readiness hotfix

This hotfix makes the Stage 7F readiness probe tolerant of transient socket disconnects seen while the Debezium/Kafka Connect container is still starting on Docker Desktop.

The previous code converted `urllib.error.URLError` into `Stage7FExecutionError`, but a startup-time `http.client.RemoteDisconnected` escaped the retry loop and terminated the checkpoint. The runner now normalizes `OSError`-family socket failures into the same retryable Stage 7F error path.

No Stage 7E data, PostgreSQL schema, Kafka topics, connector configuration, or CDC acceptance semantics are changed.
