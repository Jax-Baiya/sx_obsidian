# Setup and Launch Guide (Windows, Linux, macOS)

Owner: @plugin

This guide is the recommended starting point for end users who want to run the project reliably on different operating systems.

It covers:

- first-time setup,
- daily launch commands,
- OS-specific notes (Windows, Linux, macOS),
- and how to create your own local scripts without changing repository-managed scripts.

---

## 1) Prerequisites

- Git
- Python 3.10+
- `pip` (usually bundled with Python)
- Obsidian installed (for plugin use)

Optional but useful:

- `make`
- Node.js + npm (only needed for plugin build workflows)

---

## 2) First-time setup (all platforms)

From the project root:

1. Run deployment bootstrap:
   - `./scripts/deploy.sh --dev`
2. (Optional) Full bootstrap including plugin dependencies:
   - `./scripts/bootstrap.sh`

What this does:

- creates/updates `.venv`,
- installs runtime and dev dependencies,
- prepares your environment for CLI/API commands.

---

## 3) Daily launch commands

From the project root:

- Interactive control plane:
  - `./scripts/sxctl.sh`
- Start API server (foreground):
  - `./scripts/sxctl.sh api serve`
- Start API server (background):
  - `./scripts/sxctl.sh api serve-bg`
- API status:
  - `./scripts/sxctl.sh api server-status`
- Stop API server:
  - `./scripts/sxctl.sh api stop`
- Plugin update flow:
  - `./scripts/sxctl.sh plugin update`

If `.venv` is missing, scripts now auto-bootstrap using `./scripts/deploy.sh`.

---

## 4) Platform-specific guidance

## 4.1 Windows

Recommended: **WSL2 (Ubuntu)** for best compatibility with repository shell scripts.

### Windows + WSL2 (recommended)

1. Install WSL2 + Ubuntu.
2. Open Ubuntu terminal.
3. Clone repo inside Linux filesystem (recommended):
   - e.g., `~/projects/...`
4. Run setup:
   - `./scripts/deploy.sh --dev`
5. Use normal launch commands from this guide.

Why WSL2: scripts are Bash-first, and path handling is most reliable there.

### Windows native (PowerShell/Git Bash)

Possible, but less predictable for shell-heavy workflows.

- If using PowerShell, prefer calling repository scripts through bash-compatible environments.
- If you hit path or executable issues, switch to WSL2.

---

## 4.2 Linux

Most distributions work directly.

1. Ensure Python is available:
   - `python --version` or `python3 --version`
2. Ensure scripts are executable (if needed):
   - `chmod +x scripts/*.sh`
3. Run setup:
   - `./scripts/deploy.sh --dev`
4. Launch with `./scripts/sxctl.sh`.

---

## 4.3 macOS

1. Install Python 3.10+ (python.org or Homebrew).
2. Install Xcode command line tools if needed.
3. Run setup:
   - `./scripts/deploy.sh --dev`
4. Launch with `./scripts/sxctl.sh`.

If your shell blocks execution:

- run `chmod +x scripts/*.sh`
- then retry.

---

## 5) User-created scripts (safe pattern)

To avoid conflicts with repository-maintained scripts, place your own scripts here:

- `scripts/user/`

This path is ignored by Git, so local automation stays local.

Suggested approach:

1. Create `scripts/user/my-launch.sh`.
2. Start with:
   - `#!/usr/bin/env bash`
   - `set -euo pipefail`
3. Make executable:
   - `chmod +x scripts/user/my-launch.sh`
4. Call stable project entrypoints (`./scripts/sxctl.sh`, `./scripts/run.sh`, `./scripts/deploy.sh`).

Also supported:

- `scripts/*.local.sh` for one-off local helpers (ignored by Git).

---

## 6) Troubleshooting quick checks

If setup/launch fails:

1. Verify Python:
   - `python --version`
   - `python3 --version`
2. Rebuild environment:
   - `rm -rf .venv`
   - `./scripts/deploy.sh --dev`
3. Confirm script path usage:
   - use `./scripts/...` (not old root-level script paths)
4. For Windows issues:
   - retry in WSL2

---

## 7) Related user guides

- Usage: [`USAGE.md`](USAGE.md)
- Profiles: [`PROFILES.md`](PROFILES.md)
- Profile recovery: [`PROFILE_RECOVERY.md`](PROFILE_RECOVERY.md)
- Environment: [`ENVIRONMENT.md`](ENVIRONMENT.md)
- Local open/reveal: [`LOCAL_OPEN.md`](LOCAL_OPEN.md)
