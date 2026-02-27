# Local Media Open Protocols (sxopen / sxreveal)

This project provides custom URI protocols to bridge Obsidian with your local operating system, allowing you to open media files or reveal them in your file manager with a single click.

## Features
- **sxopen:** Opens the target file in the default OS application (e.g., VLC for video, Photos for images).
- **sxreveal:** Opens the containing folder and selects/highlights the file in the file manager (Explorer in Windows).

## Installation (Windows)
1. **Locate Protocol Assets**: Navigate to `tools/protocols/windows/`.
2. **Copy to a Stable Windows Path (recommended)**: Copy these files to a location that exists on Windows:
	- `sxopen.vbs`
	- `sxopen.ps1`

	Recommended location (matches the default template shipped in `sxopen-user.reg`):
	- `T:\AlexNova\sx_tools\`

3. **Edit Registration File**: Open `sxopen-user.reg` in a text editor (Notepad).
4. **Set Handler Path**: Ensure the registry command points to your copied `sxopen.vbs`, for example:
	- `wscript.exe "T:\\AlexNova\\sx_tools\\sxopen.vbs" "%1"`
5. **Register**: Double-click `sxopen-user.reg` and accept the prompt.
6. **Verify**: Click a link in Obsidian. The first time, Windows may ask you to confirm the app; select the WScript handler.

## Configuration (PATH_STYLE)
To ensure links work correctly across different environments (e.g., you sync your vault between Windows and WSL/Linux), you must configure the `PATH_STYLE` for your profile.

- **windows**: Generates `sxopen:T:\Vault\Data\file.mp4`
- **linux/wsl/mac**: Generates `sxopen:/mnt/t/Vault/Data/file.mp4`

### OS-Specific Roots
If your vault is mounted at different paths on different systems, use these keys in `.env`:
```env
VAULT_default=/mnt/t/AlexNova
VAULT_WIN_default=T:\AlexNova
PATH_STYLE_default=windows
```

## Security
- **Strict Parsing**: The handler only accepts a single file path as input.
- **No Command Injection**: The PowerShell handler uses strict quoting and does not execute arbitrary shell commands.
- **VBS Wrapper**: Used to suppress the PowerShell console window for a silent "premium" experience.

## Uninstallation
Double-click `tools/protocols/windows/uninstall.reg`.

## Quick Diagnostics (when clicking does nothing)

1. **The registry points to `sxopen.vbs`, not the `.reg` file location**
	- Copying `sxopen-user.reg` to another folder does **not** change the installed handler path.
	- Re-open `sxopen-user.reg` and confirm the path inside matches where you actually placed `sxopen.vbs`.

2. **Check the protocol log (Windows)**
	- `%LOCALAPPDATA%\sx_obsidian\logs\protocol.log`

3. **Common root cause: PATH_STYLE mismatch**
	- If Obsidian is running on Windows but your links look like `/mnt/t/...`, set:
	  - `PATH_STYLE_<profile>=windows`
	  - `VAULT_WINDOWS_<profile>=T:\AlexNova` (or your real vault root)
	- Then re-run sync so notes regenerate the links.
