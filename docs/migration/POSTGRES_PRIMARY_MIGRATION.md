# PostgreSQL-Primary Migration (Phase A → E)

## Overview

This document tracks the incremental migration from SQLite-primary + mirror mode to PostgreSQL-primary with schema isolation per source profile.

For operations-grade cutover steps, see:

- `docs/POSTGRES_PRIMARY_CUTOVER_RUNBOOK.md`
- `scripts/postgres_primary_smoke.sh`

Runtime modes:

- `SQLITE` — existing behavior
- `POSTGRES_MIRROR` — transitional compatibility mode
- `POSTGRES_PRIMARY` — target architecture (primary runtime)

---

## Tenant model

- One PostgreSQL database for `sx_obsidian`
- One schema per source: `sx_<source_id>` (prefix configurable)
- Global source registry in `public.sx_source_registry`
- Source metadata in `public.sources`

Isolation guarantees:

1. Source IDs are sanitized (`[A-Za-z0-9._-]`)
2. Schema identifiers are strictly validated (`^[A-Za-z_][A-Za-z0-9_]*$`)
3. Runtime sets per-request search path: `<schema>, public`
4. Missing source→schema mapping in `POSTGRES_PRIMARY` returns HTTP 400 (no silent fallback)

---

## Bootstrap / migration commands

### Initialize a source schema

- API: `POST /admin/bootstrap/schema` body `{ "source_id": "assets_1" }`
- CLI: `python -m sx_db pg-bootstrap --source assets_1`

### Import CSV into PostgreSQL primary

When `SX_DB_BACKEND_MODE=POSTGRES_PRIMARY`, `sx_db import` writes directly into the source schema tables.

---

## Backup strategy

### Logical full backup (recommended)

Use PostgreSQL native dump tooling:

- Full DB dump with schema + data
- Optional per-schema dump for profile-level rollback

Suggested schedule:

- Nightly full backup
- Pre-deployment on-demand backup
- Keep at least 7 rolling backups

### Minimal profile-scoped backup

Dump one tenant schema and global registry rows for that source before risky operations.

---

## Restore strategy

1. Restore global tables (`public.sources`, `public.sx_source_registry`)
2. Restore affected tenant schema(s)
3. Verify source→schema mappings
4. Run API health checks against each restored source

---

## Schema export / import

Export options:

- Full database
- Single schema (`sx_<source_id>`)

Import order:

1. `public` metadata tables
2. Tenant schemas
3. Validation pass (`/health`, `/stats`, `/items` by source)

---

## Rollback instructions

### Fast rollback (runtime)

1. Set `SX_DB_BACKEND_MODE=SQLITE`
2. Restart API
3. Keep PostgreSQL data intact for forensic replay

### Controlled rollback (data)

1. Restore latest PostgreSQL backup
2. Repoint app to restored DSN
3. Re-run schema bootstrap only for missing mappings

---

## Mirror mode policy

`POSTGRES_MIRROR` remains available only for transition compatibility.

- API now marks mirror mode as deprecated in backend context.
- New deployments should prefer `POSTGRES_PRIMARY`.
