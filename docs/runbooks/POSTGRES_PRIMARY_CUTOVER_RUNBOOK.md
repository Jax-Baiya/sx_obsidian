# PostgreSQL Primary Cutover Runbook (Phase F)

This runbook is the operational guide for moving a profile from `SQLITE` to `POSTGRES_PRIMARY` with verifiable checkpoints and rollback.

Use this for **one profile at a time** (`source_id` scoped cutover).

---

## 0) Prerequisites

- API code includes `POSTGRES_PRIMARY` support.
- PostgreSQL credentials are configured:
  - `SX_POSTGRES_DSN`
  - `SX_POSTGRES_ADMIN_DSN` (if required by your deployment)
- Runtime mode is set to:
  - `SX_DB_BACKEND_MODE=POSTGRES_PRIMARY`
- Target source/profile is known (example: `assets_1`).

---

## 1) Pre-cutover safety snapshot

Before any switch:

1. Export SQLite user-owned data (defensive backup).
2. Take PostgreSQL backup snapshot (full DB or schema-scope + registry rows).
3. Record current API health + stats in SQLite mode.

Checkpoint criteria:

- SQLite backup exists and is readable.
- Postgres snapshot exists.
- Baseline health endpoint returns `ok=true`.

---

## 2) Tenant bootstrap (source -> schema)

Bootstrap the target source schema via either:

- API: `POST /admin/bootstrap/schema`
- CLI: `sx_db pg-bootstrap --source <source_id>`

Expected result:

- Mapping exists in registry table.
- Schema is created and queryable.

Failure policy:

- If bootstrap fails, do **not** proceed to import/cutover.

---

## 3) Data load to Postgres primary

Run import while `SX_DB_BACKEND_MODE=POSTGRES_PRIMARY`.

Expected behavior:

- `sx_db import` writes into the source schema tables.
- No writes to SQLite for the primary path.

Checkpoint criteria:

- `/stats` returns non-zero items for target source.
- `/items` returns expected rows for the target source.

---

## 4) Smoke checks (required)

Run:

- `scripts/postgres_primary_smoke.sh`

The script verifies:

- `/health` reachable
- backend reports `postgres_primary`
- target source header/query routing works
- source mismatch fails when expected

If any smoke check fails: stop and rollback.

---

## 5) Production cutover window

During cutover:

1. Restart API in `POSTGRES_PRIMARY` mode.
2. Validate target profile via smoke script.
3. Validate plugin operations:
   - Search
   - Item open
   - Note/meta read/write

Success criteria:

- All smoke checks pass.
- No cross-source data leakage.
- No 5xx bursts in API logs.

---

## 6) Fast rollback (runtime)

If any critical issue appears:

1. Set `SX_DB_BACKEND_MODE=SQLITE`
2. Restart API
3. Re-run health + minimal plugin verification

This rollback does not destroy Postgres data and allows later forensics.

---

## 7) Controlled rollback (data)

When runtime rollback is insufficient:

1. Restore PostgreSQL snapshot (global + affected schema).
2. Validate registry mapping integrity.
3. Re-run bootstrap only for missing/invalid mappings.

---

## 8) Post-cutover checklist

- [ ] `backend=postgres_primary` observed in responses
- [ ] source-scoped reads validated for target source
- [ ] write path validated (`/items/{id}/meta`, notes)
- [ ] plugin UX validated (search, table, note pin/open)
- [ ] logs reviewed for 400/500 anomalies
- [ ] rollback instructions shared with operators

---

## 9) Recommended timeline (single profile)

- **T-30m**: backups + baseline checks
- **T-20m**: schema bootstrap
- **T-15m**: import into Postgres primary
- **T-10m**: smoke checks
- **T-0**: switch traffic for target profile
- **T+10m**: plugin validation + log review
- **T+30m**: close cutover window
