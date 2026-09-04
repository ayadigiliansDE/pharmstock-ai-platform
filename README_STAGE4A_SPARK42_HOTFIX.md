# Stage 4A Spark 4.2 isin Hotfix

Hotfix for Spark 4.2 `UNSUPPORTED_FEATURE.LITERAL_TYPE` caused by passing a tuple/list as one argument to `Column.isin`.

Change: `.isin(tuple(BRONZE_EVENT_TOPICS))` -> `.isin(*tuple(BRONZE_EVENT_TOPICS))`.

No business logic or version change. Version remains 0.14.0.
