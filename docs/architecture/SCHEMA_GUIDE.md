# 🔒 SX Media Schema v1 (LOCKED)

This is the definitive contract for the SX Obsidian Media Control System database layer.

## Frontmatter v1 Structure

The system generates and maintains the following YAML structure in `_db/media/*.md`:

```yaml
---
id: <numeric_id>

# === Media (generated) ===
video: "[[<id>.mp4]]"
video_path: <id>.mp4
cover: "[[<id>.jpg]]"
cover_path: <id>.jpg
video_url: <derived platform video URL>
author_url: <derived platform author URL>

# === Platform (sourced) ===
platform: TikTok
author_name: <string>
author_unique_id: <string>
author_id: <string>

# === Content (sourced) ===
caption: <string>

# === Metrics (numeric) ===
followers: <number>
hearts: <number>
videos_count: <number>

# === Workflow (USER-EDITABLE) ===
status: raw # raw | reviewed | scheduled | published
bookmarked: true
bookmark_timestamp: <ISO-8601 or null>
scheduled_time: <ISO-8601 or null>
product_link: <url or null>

# === Classification (USER-EDITABLE) ===
tags: []

# === Integrity ===
csv_row_hash: <hash>
media_missing: false
metadata_missing: false
files_seen: []
---
```

## Field Ownership & Preservation

### 🔒 Script-Owned

These fields are overwritten on every sync. **Do not edit manually**:

- Media paths/links (`video`, `cover`, etc.)
- Metadata sourced from CSV (`author_name`, `metrics`, etc.)
- URLs and Integrity hashes.

### ✍️ User-Owned & Custom Fields

These fields are **preserved** during sync. Manual changes win over script defaults:

- `status`, `scheduled_time`, `product_link`, `tags`
- **Any other custom field** you add (e.g., `cssclass`, `published_time`) will be kept safely in the YAML.

## Manual Notes Safety

You can write notes anywhere **outside** the `sx-managed` tags. Your notes above or below the managed block will be preserved across syncs.

## 🛡️ User Work Protection (Deletion Guard)

The system includes a **Deletion Guard** to prevent accidental loss of manual work:

- **Soft Cleanup** (`--cleanup soft`) will **automatically skip** any file that:
  1. Has manual notes outside the managed block.
  2. Has a non-default `status` or non-empty `tags`.
  3. Has custom YAML fields (like `cssclass`).
- **To override**: Use the `--force` flag if you truly want to wipe all files, including your manual edits.

> [!IMPORTANT]
> To apply schema changes, use `./scripts/run.sh --cleanup soft --force` followed by a sync.
