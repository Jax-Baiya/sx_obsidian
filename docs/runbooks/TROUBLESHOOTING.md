# TROUBLESHOOTING

## Common Issues

### 1. WSL Path Issues

If your vault is on a Windows drive (e.g., `D:`), ensure you use the `/mnt/` prefix in WSL:

- **Correct**: `/mnt/d/Obsidian/MyVault`
- **Incorrect**: `D:\Obsidian\MyVault`

### 2. Windows "Zone.Identifier" Files

If you see strange files ending in `:Zone.Identifier`, these are Windows security metadata. The `deploy.sh` script attempts to clean these, but you can also run:

```bash
find . -name "*:Zone.Identifier" -delete
```

### 3. Permissions

If `scripts/run.sh` fails with "Permission denied", ensure it is executable:

```bash
chmod +x scripts/run.sh scripts/deploy.sh
```

### 3. Missing Dependencies

If you get `ModuleNotFoundError`, run the deploy script again:

```bash
./scripts/deploy.sh
```

### 4. Broken Layout

If the generated Markdown looks strange in Obsidian, ensure you haven't deleted the `<!-- sx-managed -->` tags. If you do, the script might treat the whole file as managed and overwrite it, or fail to update it.

### 5. Media preview shows "Media not found"

The API now resolves media paths using **source roots first** (from `SRC_PATH_N`) with deterministic candidate fallback and structured diagnostics.

#### What changed

- Media existence checks prefer `SRC_PATH_N` (not vault root).
- Cross-environment normalization is handled for mixed path styles:
  - Windows style: `T:\...`
  - WSL/Linux style: `/mnt/t/...`
- Candidate paths are evaluated in order and logged with per-candidate existence.

#### What to inspect

Check API logs for `sx_db.media` entries. Each resolution attempt logs:

- `source_id`
- `profile_index`
- `resolution` mode
- `relative_path`
- `checked` candidate list with existence flags
- `selected` candidate (or `none`)

Example indicators:

- `selected=/mnt/t/.../data/Favorites/covers/...jpg` → successful
- `selected=none` + all candidates `exists=false` → true missing file or wrong root mapping

#### Fast operator checks

1. Confirm `SRC_PATH_N` matches the active source profile used by the plugin.
2. Confirm media file exists under `<SRC_PATH_N>/<DATA_DIR>/...`.
3. Verify active source in plugin Database settings matches expected source id.
4. Re-test:
   - `/items/{id}/links`
   - `/media/cover/{id}`
   - `/media/video/{id}`

#### Rollback / mitigation

- Immediate mitigation: keep API up and verify candidate logs before reverting.
- Code rollback target: revert `sx_db/api.py` to previous resolver behavior.

### 6. Profiles tab shows unexpected profile list

Profiles tab now defaults to **active-source scope**.

#### Expected behavior

- Active source comes from Database settings (`Active source ID`).
- Profiles tab shows only profile(s) whose `source_id` matches active source.
- Status line shows:
  - active source id
  - current filter mode (`active-only` vs `show-all`)
  - shown/total counts

If no profile maps to active source, the UI safely falls back to showing all profiles (no hard failure) and labels fallback status.

#### Troubleshooting override

- Enable **Show all profiles** toggle in Profiles tab.
- Use this only for diagnosis; default mode should remain active-only for safety.

#### Rollback / mitigation

- Immediate mitigation: turn on **Show all profiles**.
- Code rollback target: revert `obsidian-plugin/src/settings.ts` Profiles tab filtering block.

## Backend server ops (Linux)

### Run the API in the background (sxctl quick method)

If you just want the server to run in the background quickly (without systemd):

```bash
./scripts/sxctl.sh api serve-bg
./scripts/sxctl.sh api server-status
./scripts/sxctl.sh api stop
```

Logs are written to a rotating diagnostic file:

- `_logs/sx_db_api.log` (daily rotation)
- Old rotated logs are auto-deleted (see `SX_API_LOG_BACKUP_COUNT` in `.env`)

### Run the API in the background (systemd --user)

If you want the FastAPI server to keep running after you close your terminal, a user-level systemd service is the most reliable option.

1. Create a file at `~/.config/systemd/user/sx-db.service`:

```ini
[Unit]
Description=sx_db API server

[Service]
WorkingDirectory=%h/projects/ANA/core/portfolio/sx_obsidian
ExecStart=%h/projects/ANA/core/portfolio/sx_obsidian/.venv/bin/python -m sx_db serve
Restart=on-failure

[Install]
WantedBy=default.target
```

2. Enable + start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now sx-db
systemctl --user status sx-db
```

### Prune cached logs

The API server writes rotating logs and auto-deletes older rotated files.

If you also want an explicit cleanup tool (useful for other log folders), this repo includes a lightweight maintenance worker you can run manually or via cron/systemd timers:

```bash
python -m sx_db.workers.prune_logs _logs --max-age-days 14
```

Use `--dry-run` to preview what would be deleted.
