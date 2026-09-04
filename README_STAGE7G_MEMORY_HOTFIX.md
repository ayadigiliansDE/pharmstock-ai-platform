# Stage 7G v0.28.1 Memory Safety Hotfix

This hotfix addresses the observed Spark `java.lang.OutOfMemoryError: Java heap space` during the million-row PostgreSQL -> Parquet snapshot.

Changes:
- Spark local master is capped at `local[2]` instead of `local[*]` to prevent 8-12 concurrent Parquet writers from exhausting the local JVM heap.
- Driver heap is explicitly set to `2g`.
- Spark default parallelism and shuffle partitions are capped at 4.
- JDBC fetch size is reduced from 20,000 to 5,000 rows per fetch.
- Parquet row-group size is reduced to 64 MiB.
- Output files are capped at 250,000 records per file.

No Stage 7E or Stage 7F data is mutated. The failed Stage 7G output is disposable and the next Stage 7G run rebuilds it cleanly.
