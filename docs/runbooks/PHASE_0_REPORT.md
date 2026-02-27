# Phase 0: Project Integration Report

## 1. Top-Level Integration Seams & Architecture

Based on analyzing the `sx_obsidian` ecosystem, the integration spans three distinct layers:
1. **The Core Database & API (`sx_db`)**: A FastAPI Python application backed by SQLite (and a Supabase mirror). This acts as the source of truth for all content profiles.
2. **The Output Generation (`sx`)**: A pure-Python CLI that imports CSVs and triggers the initial sync boundary.
3. **The Obsidian Plugin (`obsidian-plugin`)**: A TypeScript user experience layer operating strictly within the Obsidian vault, using standard `fs` (or Obsidian Vault API) and HTTP to the `sx_db` API.

### Integration Boundaries
- **Status Trigger:** The `status` inside the Markdown YAML frontmatter is the defining trigger-point. The system must observe changes to this status (e.g., transitioning to `scheduling`).
- **Media Upload (R2):** This **must** be handled by the Local Python Pipeline (`sx_db` context) to ensure it has full FS access to raw image/video paths before they are copied/pinned into the vault.
- **Artifact Generation:** The JSON publishing artifacts belong to the Local Python Pipeline. Obsidian should not directly create these; Obsidian merely edits the YAML `status`.
- **The Cloud Bridge (Supabase):** The newly proposed Next.js Web App will interact **strictly with the Supabase PostgreSQL database**. It should never attempt to connect to the local SQLite DB or local files. The Python layer (`postgres_mirror.py` or a dedicated worker) is responsible for syncing local SQLite <-> Supabase.

## 2. Breaking-Change Risks & Mitigations

| Risk Factor | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **Path Resolution Mismatch** | Web App attempting to read local paths (e.g., `/Users/.../Assets`) will fail on Vercel. | Web App **only** reads the `R2_media_url` from the database. The Python backend is solely responsible for translating local paths to R2 URLs. |
| **Double-Publishing / Concurrency** | Two platforms or manual triggers causing duplicate scheduling jobs. | The JSON Artifact generation must be idempotent based on `note_id` + `platform` + `hash`. Jobs in the database must use pessimistic locking during execution. |
| **YAML Corruption** | Writing back the `R2_media_url` and `post_url` from Python while the user is editing the note in Obsidian. | Strict adherence to the `managed regions` strategy in `markdownMerge.ts` and `sx_db.markdown`. Python should only rewrite the bottom-half of the frontmatter. |
| **Local vs. Cloud DB Split-Brain** | SQLite and Postgres get out of sync, showing different statuses in CLI vs. Web. | Elevate the Postgres mirror strategy (`postgres_mirror.py`) into a continuous sync worker for the `scheduling` queue table. |

## 3. Recommended "Bridge Flow" Architecture

This is how the system safely transports a decision from Obsidian to the Web App:

1. **User Action:** In Obsidian, user sets `status: scheduling` (via plugin UI or manual YAML).
2. **Sync / Detection:** A background worker in the Python `sx_db` (or a triggered hook from the plugin's `X-SX-Sync` command) detects this change.
3. **Artifact Creation:** Python worker creates `{basename}.json` with publish metadata.
4. **Media Upload:** Python worker uploads the referenced local media to Cloudflare R2, receiving an `r2_url`.
5. **Writeback:** Python worker uses the managed-region YAML writer to append `R2_media_url: <url>` to the `.md` file.
6. **DB Sync:** The row in `SQLite` is updated with the JSON artifact payload and the R2 URL, which immediately syncs to `Supabase`.
7. **Web Visibility:** The Next.js app (reading Supabase) now sees the item in the "Scheduling Library" and the user can click "Publish Now".

---

## Next Steps for Execution

If this architecture and risk assessment look correct, we will move to **Step 2 & 3: Finalizing Architecture and Implementing the Python Bridge Flow (Detect -> R2 Upload -> DB Sync).**
