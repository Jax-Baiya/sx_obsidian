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
