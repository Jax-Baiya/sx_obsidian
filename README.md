# SX Obsidian

[![CI](https://github.com/Jax-Baiya/sx_obsidian/actions/workflows/ci.yml/badge.svg)](https://github.com/Jax-Baiya/sx_obsidian/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10-blue)
![Node](https://img.shields.io/badge/node-%3E%3D18-brightgreen)
![Obsidian](https://img.shields.io/badge/Obsidian-Desktop-purple)

**Local-first media intelligence stack for Obsidian** — source-scoped backend, fast plugin UX, TUI control plane, and a new web control surface.

---

## Why this exists

Large media libraries (10k–50k+) can cripple vault responsiveness when represented as raw Markdown files.

SX Obsidian keeps your vault fast by storing the heavy dataset in the database layer while exposing a curated active set inside Obsidian.

---

## What we’ve achieved 🚀

- ✅ **Source-scoped architecture** (no cross-profile bleed)
- ✅ **FastAPI backend** with explicit source/profile guardrails
- ✅ **Modularized Obsidian plugin** with restored rich library interactions
- ✅ **TUI control plane** for API, import, DB, and settings workflows
- ✅ **Web control plane scaffold** for library/queue/schedule/settings surfaces
- ✅ **Expanded regression coverage + CI hardening**
- ✅ **Operational runbooks and recovery workflows**

---

## Architecture at a glance

- **Core backend (`sx_db/`)**
  - API + repository layer
  - source registry and profile-aware resolution
  - scheduler and recovery tooling
- **Obsidian plugin (`obsidian-plugin/`)**
  - SX Library table/search UX
  - note pin/sync flows
  - hover/note preview + metadata editing
- **TUI (`sx_db/tui/`)**
  - terminal-first operations and diagnostics
- **Web (`web/`)**
  - Next.js control plane scaffold
- **Docs (`docs/`)**
  - structured by architecture/developer/user/runbooks/governance

---

## Achievement showcase (from `assets/`)

### Featured snapshots

| Milestone                        | Screenshot                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------- |
| UI/Theme polish                  | ![Screenshot 2026-02-21 201847](assets/Screenshot%202026-02-21%20201847.png) |
| Library interaction improvements | ![Screenshot 2026-02-21 202030](assets/Screenshot%202026-02-21%20202030.png) |
| Data/flow visual validation      | ![Screenshot 2026-02-21 202145](assets/Screenshot%202026-02-21%20202145.png) |
| Progress on advanced views       | ![Screenshot 2026-02-21 202301](assets/Screenshot%202026-02-21%20202301.png) |
| Control-plane maturity           | ![Screenshot 2026-02-21 203523](assets/Screenshot%202026-02-21%20203523.png) |
| Current achievement state        | ![Screenshot 2026-02-21 203615](assets/Screenshot%202026-02-21%20203615.png) |

<details>
<summary><strong>Full gallery (all captured progress screenshots)</strong></summary>

- ![Screenshot 2026-02-21 041859](assets/Screenshot%202026-02-21%20041859.png)
- ![Screenshot 2026-02-21 054803](assets/Screenshot%202026-02-21%20054803.png)
- ![Screenshot 2026-02-21 201847](assets/Screenshot%202026-02-21%20201847.png)
- ![Screenshot 2026-02-21 201917](assets/Screenshot%202026-02-21%20201917.png)
- ![Screenshot 2026-02-21 201934](assets/Screenshot%202026-02-21%20201934.png)
- ![Screenshot 2026-02-21 201951](assets/Screenshot%202026-02-21%20201951.png)
- ![Screenshot 2026-02-21 202010](assets/Screenshot%202026-02-21%20202010.png)
- ![Screenshot 2026-02-21 202030](assets/Screenshot%202026-02-21%20202030.png)
- ![Screenshot 2026-02-21 202048](assets/Screenshot%202026-02-21%20202048.png)
- ![Screenshot 2026-02-21 202101](assets/Screenshot%202026-02-21%20202101.png)
- ![Screenshot 2026-02-21 202119](assets/Screenshot%202026-02-21%20202119.png)
- ![Screenshot 2026-02-21 202145](assets/Screenshot%202026-02-21%20202145.png)
- ![Screenshot 2026-02-21 202203](assets/Screenshot%202026-02-21%20202203.png)
- ![Screenshot 2026-02-21 202217](assets/Screenshot%202026-02-21%20202217.png)
- ![Screenshot 2026-02-21 202301](assets/Screenshot%202026-02-21%20202301.png)
- ![Screenshot 2026-02-21 202337](assets/Screenshot%202026-02-21%20202337.png)
- ![Screenshot 2026-02-21 203508](assets/Screenshot%202026-02-21%20203508.png)
- ![Screenshot 2026-02-21 203523](assets/Screenshot%202026-02-21%20203523.png)
- ![Screenshot 2026-02-21 203615](assets/Screenshot%202026-02-21%20203615.png)

</details>

---

## Quickstart

### 1) Bootstrap

```bash
make bootstrap
cp .env.example .env
```

### 2) Initialize and import

```bash
make api-init
make api-import
```

### 3) Run backend

```bash
make api-serve
```

Default: `http://127.0.0.1:8123`

### 4) Build/install plugin

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/vault
make plugin-build
make plugin-install
```

Or:

```bash
./sxctl.sh plugin update
```

### 5) (Optional) Run web control plane

```bash
cd web
npm install
npm run dev
```

---

## Documentation map

Start with: [`docs/INDEX.md`](docs/INDEX.md)

- Architecture: [`docs/architecture/`](docs/architecture)
- Developer docs: [`docs/developer/`](docs/developer)
- User docs: [`docs/user/`](docs/user)
- Runbooks: [`docs/runbooks/`](docs/runbooks)
- Governance: [`docs/governance/`](docs/governance)

---

## Developer workflows

- Plugin build: `cd obsidian-plugin && npm run build`
- Focused test pass: `./.venv/bin/python -m pytest -q tests/test_sources_api.py tests/test_tui_api_control.py`
- Full tests: `make test`

---

## Security & operational notes

- Keep API local (`127.0.0.1`) unless explicitly intended.
- Use explicit source/profile context for operational commands.
- Follow governance safety rails in [`docs/governance/GIT_WORKFLOW_SAFETY.md`](docs/governance/GIT_WORKFLOW_SAFETY.md).
