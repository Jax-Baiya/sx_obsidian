# EXPECTED OUTCOMES

## Sample Output File (`_db/media/7534541116058635575.md`)

```markdown
---
id: '7534541116058635575'

# Media (generated)
video: "[[Favorites/videos/7534541116058635575.mp4]]"
video_path: Favorites/videos/7534541116058635575.mp4
cover: "[[Favorites/covers/7534541116058635575.jpg]]"
cover_path: Favorites/covers/7534541116058635575.jpg
video_url: https://www.tiktok.com/@<author_unique_id>/video/7534541116058635575
author_url: https://www.tiktok.com/@<author_unique_id>

# Platform + author (sourced)
platform: TikTok
author_name: <nickname>
author_unique_id: <author_unique_id>
author_id: '7525078778679510071'

# Content (sourced)
caption: "There’s always a moon that shines for you #digitaltechnology #atmosphere #moonlight"

# Metrics (numeric)
followers: 0
hearts: 0
videos_count: 0

# Workflow (user-editable; preserved)
status: raw
bookmarked: false
bookmark_timestamp: null
scheduled_time: null
product_link: null
tags: []

# Integrity
csv_row_hash: a1b2c3d4e5f6...
template_version: v1.1
media_missing: false
metadata_missing: false
files_seen:
  - Favorites/videos/7534541116058635575.mp4
  - Favorites/covers/7534541116058635575.jpg
---

<!-- sx-managed:start -->
... generated media cards + caption ...

## Local Files
[▶ Open Video](sxopen:/abs/path/to/vault/data/Favorites/videos/7534541116058635575.mp4) | [📂 Reveal](sxreveal:/abs/path/to/vault/data/Favorites/videos/7534541116058635575.mp4)
[🖼 Open Cover](sxopen:/abs/path/to/vault/data/Favorites/covers/7534541116058635575.jpg) | [📂 Reveal](sxreveal:/abs/path/to/vault/data/Favorites/covers/7534541116058635575.jpg)
<!-- sx-managed:end -->

My manual notes about this video.
```

## Logs Location
A new log file is created for every run in `./_logs/generator_YYYYMMDD_HHMMSS.log` (stored **outside** the vault by default).

If you want logs inside the vault (not recommended for large-scale use), set `LOG_IN_VAULT=1` and the path becomes `{VAULT}/{LOG_DIR}/generator_YYYYMMDD_HHMMSS.log`.

## Successful Run Summary
```text
2026-02-02 13:04:03 - INFO - Run Summary: {'created': 1828, 'updated': 85, 'skipped': 2472, 'no_media': 0, 'deleted': 0}
```
- **Created**: New assets found.
- **Updated**: Metadata changed in CSV for existing assets.
- **Skipped**: No changes detected.
- **No Media**: CSV entry found but files missing in `{VAULT}/{DATA_DIR}`.
- **Deleted**: Number of files removed during `--cleanup` runs.
