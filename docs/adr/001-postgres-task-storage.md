# ADR-001: Postgres task storage

**Status:** Proposed (2026-11-20)

## Context

<!-- why a decision is needed: the forces and constraints -->

## Decision

Tasks persist in Postgres via psycopg 3 + psycopg_pool, with schema created by idempotent DDL under an advisory lock until a migration tool is needed

## Consequences

<!-- what becomes easier or harder, what a later change must keep -->
