# Architecture decision records

| ADR | Decision |
|---|---|
| [001](001-postgres-task-storage.md) | Tasks persist in Postgres via psycopg 3 + psycopg_pool, with schema created by idempotent DDL under an advisory lock until a migration tool is needed |
