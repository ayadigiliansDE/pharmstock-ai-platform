# Stage 7F CDC JSON Envelope Hotfix — v0.27.3

## Diagnosis
The PostgreSQL replication slot, Debezium connector and Kafka supplier topic were healthy.
The diagnostic showed two complete probe sequences already present in Kafka (`c -> u -> d`).

Kafka Connect JSON Converter is emitting schema-enabled records as:

```json
{
  "schema": {"...": "..."},
  "payload": {"op": "c", "before": null, "after": {}, "source": {}}
}
```

Keys use the same wrapper. The Stage 7F acceptance consumer incorrectly read `op`,
`before`, `after`, `source`, and `supplier_id` from the outer object, so valid CDC
records were ignored.

## Fix
- Unwrap Kafka Connect's `payload` object for both record value and record key.
- Keep compatibility with schemaless JSON records.
- Preserve the v0.27.2 high-watermark pinning so the probe starts exactly after
  existing topic data.
- No changes to Stage 7E history, PostgreSQL publication, replication slot, Debezium
  connector contract, Kafka topics, or cloud resources.

## Expected acceptance

```text
Probe INSERT/UPDATE/DELETE:    c -> u -> d
STAGE_7F_STATUS=PASS
```
