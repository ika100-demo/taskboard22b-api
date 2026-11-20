# Environment variables

Configuration is read exclusively from environment variables. Defaults below are the application defaults. The deployed values are set per environment in the system's gitops-app repo (`system.yaml`: a component's `env`, and `replicas`, `resources` under `instances.<env>`).

## Core

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP port the service listens on. |
| `LOG_LEVEL` | `INFO` | Logging level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | _(none)_ | Postgres connection URL, of the form `postgresql://<user>@<host>:5432/<db>` (password via the URL or `PGPASSWORD`); a `postgresql+driver://` scheme is accepted. Set by the component's gitops entry. |
| `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` | _(unset)_ | Fallback used when `DATABASE_URL` is unset and `PGHOST` is set (libpq reads them). With neither, the service fails at startup. |

Timeouts are fixed, not configurable: connect 2 s, pool wait 3 s, statement 3 s, `/ready` probe 1 s. While the database is unreachable `/tasks` answers 503 and `/ready` answers 503; the service recovers without a restart.

## Observability

| Variable | Default | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset — tracing disabled)_ | Standard OpenTelemetry endpoint, e.g. `http://otel-collector:4318`; injected by the platform's observability setting of the environment. When set, `configure_tracing()` runs at startup. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf` or `grpc`. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | _(project name)_ | Resource attributes; set by the observability setting of the environment. |
| `OTLP_ENDPOINT` | _(unset)_ | Legacy gRPC endpoint (kept for compatibility); prefer the standard variables. |
| `METRICS_PORT` | `8080` | Port serving `/metrics` (same as the main HTTP port unless overridden). |
