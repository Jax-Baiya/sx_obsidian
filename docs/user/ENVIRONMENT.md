# Environment & Profile Configuration

The SX Obsidian Media Control System uses a **namespaced environment** to support multiple vaults and workflows without modifying code.

## The `.env` File

The system looks for a `.env` file in the `sx_obsidian/` directory.

### Core Variables

These define the relative locations inside any vault:

- `DATA_DIR`: Where media lives (default: `data`)
- `DB_DIR`: Where markdown rows are generated (default: `_db/media`)
- `LOG_DIR`: Log directory name/path (default: `_logs`).
- `LOG_IN_VAULT`: If set to `1`/`true`, logs are stored inside the vault at `{VAULT}/{LOG_DIR}` (legacy behavior). Default is **off** (logs stored next to the project, not inside the vault).
- `LOG_RETAIN`: Max number of generator log files to keep (default: `50`).

- `ARCHIVE_DIR`: Where to move archived DB notes when using `--archive-stale` (default: `_archive/sx_obsidian_db`, stored next to the project unless absolute).

### API (sx_db) diagnostic logs

The FastAPI server can write a small rotating log file for diagnostics.

- `SX_API_LOG_DIR`: Log directory for the API (default: `_logs`, relative to the repo root)
- `SX_API_LOG_LEVEL`: Log level (default: `INFO`)
- `SX_API_LOG_ACCESS`: If set to `1`/`true`, include request access logs (can be noisy)
- `SX_API_LOG_BACKUP_COUNT`: How many rotated daily log files to keep (default: `14`)

### Profile Namespacing

Profiles allow you to define multiple distinct configurations.

#### 1. Defining a Profile

To define a profile called `client_a`, add variables with the `_client_a` suffix:

```env
VAULT_client_a=/mnt/d/Vaults/ClientA
CSV_consolidated_client_a=/home/user/pipeline/A_consolidated.csv
```

#### 2. Default Fallback

If no profile-specific variable exists, the system looks for the `_default` version:

```env
VAULT_default=/mnt/t/AlexNova
CSV_consolidated_1=/path/to/main.csv
```

#### 3. Multiple CSV Sources

You can enumerate consolidated CSVs for a single profile:

```env
CSV_consolidated_1=/path/to/part1.csv
CSV_consolidated_2=/path/to/part2.csv
```

## Active Profile Selection

The active profile is determined in this order of priority:

1. CLI Flag: `--profile name`
2. Env Var: `SX_PROFILE=name`
3. Fallback: `default`

## Launch-time profile adapter (sxctl / Make)

The launcher and Make targets now resolve SchedulerX profile context and print it before running API/plugin actions.

Supported SchedulerX key styles:

- `SRC_PROFILE_1`, `SRC_PROFILE_1_LABEL`, `DATABASE_PROFILE_1`
- `SRC_PATH_1`, `SRC_PATH_1_LABEL` (current SchedulerX pattern)

### Adapter variables

- `SX_SCHEDULERX_ENV` (recommended: `./.env` for self-contained sx_obsidian profile ownership)
- `SX_PROFILE_INDEX` (default: `1`)
- `SX_DB_PATH_TEMPLATE` (default: `data/sx_obsidian_{source_id}.db`)
- `SX_PIPELINE_DB_MODE` (`LOCAL` | `SESSION` | `TRANSACTION` | `SQL`)
  - `LOCAL/SESSION/TRANSACTION` target PostgreSQL aliases from the configured profile env
  - `SQL` targets SQLite `SQL_DB_PATH_N` (or falls back to `SX_DB_PATH_TEMPLATE`)
- `SX_DB_BACKEND_MODE` (`SQLITE` | `POSTGRES_MIRROR` | `POSTGRES_PRIMARY`)
  - `SQLITE` keeps sqlite-only runtime behavior
  - `POSTGRES_MIRROR` mirrors selected PostgreSQL source rows into sqlite-compatible tables at runtime (transitional mode)
  - `POSTGRES_PRIMARY` uses dedicated per-source schemas in PostgreSQL (recommended)
- `SX_DB_BACKEND_SYNC_TTL_SEC` (default: `120`)
- Optional overrides: `SX_PIPELINE_DB_PROFILE`, `SX_PIPELINE_DATABASE_URL`

### Recommended isolated alias namespace

To avoid cross-project DB coupling, use an sx_obsidian-owned alias namespace (example):

- `SRC_PATH_1_DB_LOCAL=SXO_LOCAL_1`
- `SRC_PATH_1_DB_SESSION=SXO_SESSION_1`
- `SRC_PATH_1_DB_TRANSACTION=SXO_TRANS_1`

With corresponding alias keys:

- `SXO_LOCAL_1_DB_USER`, `SXO_LOCAL_1_DB_PASSWORD`, `SXO_LOCAL_1_DB_HOST`, `SXO_LOCAL_1_DB_PORT`, `SXO_LOCAL_1_DB_NAME`, `SXO_LOCAL_1_DB_SCHEMA`

In this model:

- `DATABASE_PROFILE_N` should represent the source id (for example `assets_1`), not a comma-separated alias list.

At launch time, the adapter exports:

- `SX_DEFAULT_SOURCE_ID` (derived from profile mapping, fallback `assets_{index}`)
- `SX_DB_PATH` (derived from `SX_DB_PATH_TEMPLATE`)
- `SX_PA_PIPELINE_DB_SELECTED_PROFILE` and `SX_PA_PIPELINE_DB_URL_REDACTED`
- `SX_PA_PIPELINE_DB_SQL_PATH` when `SQL_DB_PATH_N` is configured

This keeps DB naming aligned with your SchedulerX source profile naming and avoids cross-profile mixups.
