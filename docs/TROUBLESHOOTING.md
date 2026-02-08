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
