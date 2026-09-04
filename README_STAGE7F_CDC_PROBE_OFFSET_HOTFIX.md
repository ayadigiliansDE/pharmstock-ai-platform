# Stage 7F v0.27.2 — CDC probe offset hotfix

This hotfix fixes a Kafka consumer race in the Stage 7F acceptance probe.

The consumer previously waited for partition assignment and then immediately generated the PostgreSQL INSERT/UPDATE/DELETE probe while relying on `auto.offset.reset=latest`. Kafka can assign partitions before the initial `latest` position is concretely resolved. In that narrow window the probe events may be produced first, then the consumer resolves `latest` after them and skips the exact events the acceptance check is meant to observe.

The runner now captures the current high watermark for every assigned supplier-topic partition and explicitly seeks to those offsets before the PostgreSQL probe is generated. This preserves the intended boundary: ignore old topic content, then consume every new probe event.

No Stage 7E historical data, PostgreSQL schema, connector configuration, or cloud resources are modified by this hotfix.
