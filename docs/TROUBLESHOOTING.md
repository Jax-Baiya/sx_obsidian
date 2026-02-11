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
If `run.sh` fails with "Permission denied", ensure it is executable:
```bash
chmod +x run.sh deploy.sh
```

### 3. Missing Dependencies
If you get `ModuleNotFoundError`, run the deploy script again:
```bash
./deploy.sh
```

### 4. Broken Layout
If the generated Markdown looks strange in Obsidian, ensure you haven't deleted the `<!-- sx-managed -->` tags. If you do, the script might treat the whole file as managed and overwrite it, or fail to update it.

### 5. Media Not Found
The script searches `data/` recursively. If your images are elsewhere, use the `--data-dir` argument to point to the correct subfolder.

## Backend server ops (Linux)

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

This repo includes a lightweight maintenance worker you can run manually or via cron/systemd timers:

```bash
python -m sx_db.workers.prune_logs _logs --max-age-days 14
```

Use `--dry-run` to preview what would be deleted.
