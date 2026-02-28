import csv
import glob
import hashlib
import json
import logging
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml
from tqdm import tqdm

from sx.paths import PathResolver
from sx_db.markdown import TEMPLATE_VERSION as NOTE_TEMPLATE_VERSION
from sx_db.markdown import render_note


MANAGED_START = "<!-- sx-managed:start -->"
MANAGED_END = "<!-- sx-managed:end -->"

SCRIPT_OWNED_KEYS = {
    # Keys produced/managed by the template renderer.
    "id",
    "fields",
    "video",
    "video_path",
    "video_abs",
    "sxopen_video",
    "sxreveal_video",
    "cover",
    "cover_path",
    "cover_abs",
    "sxopen_cover",
    "sxreveal_cover",
    "video_url",
    "author_url",
    "platform",
    "author_name",
    "author_unique_id",
    "author_id",
    "caption",
    "followers",
    "hearts",
    "videos_count",
    "signature",
    "is_private",
    # User-owned but may be populated by the DB/API flow.
    "rating",
    "notes",
    "bookmarked",
    "bookmark_timestamp",
    "csv_row_hash",
    "render_hash",
    "template_version",
    "media_missing",
    "metadata_missing",
    "files_seen",
}
USER_EDITABLE_KEYS = {
    "status",
    "rating",
    "notes",
    "scheduled_time",
    "product_link",
    "tags",
    # Optional compat fields that users/tools may mutate.
    "sx_select",
    "platform_targets",
    "workflow_log",
    "post_url",
    "published_time",
}


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "y", "t", "on"}


def _norm_rel(p: str | None) -> str:
    if not p:
        return ""
    return str(p).replace("\\", "/").lstrip("/")


def _pick_by_prefix(candidates: list[str], prefixes: list[str]) -> str | None:
    """Pick the first candidate that matches any preferred prefix (normalized)."""
    if not candidates:
        return None
    norm = [_norm_rel(c) for c in candidates if c]
    for pref in prefixes:
        pref_n = _norm_rel(pref)
        for c in norm:
            if c.startswith(pref_n):
                return c
    return norm[0] if norm else None


def _expected_media_paths(asset_id: str, author_id: str | None, bookmarked: bool) -> tuple[str, str]:
    """Return canonical (video_path, cover_path) relative to the data root."""
    if bookmarked:
        base = "Favorites"
    else:
        base = f"Following/{author_id}" if author_id else "Following"
    return (
        f"{base}/videos/{asset_id}.mp4",
        f"{base}/covers/{asset_id}.jpg",
    )


def _load_schema(schema_path: str | None) -> dict:
    if not schema_path:
        return {}
    try:
        p = Path(schema_path)
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_bool_env(val: str | None) -> bool:
    if val is None:
        return False
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _prune_old_logs(log_path: str, pattern: str, retain: int, logger: logging.Logger | None) -> None:
    if retain <= 0:
        return
    try:
        files = sorted(
            glob.glob(os.path.join(log_path, pattern)),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        for p in files[retain:]:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
    except Exception as e:
        if logger:
            logger.debug(f"Log prune skipped: {e}")


def setup_logging(log_dir, vault_root, *, log_in_vault: bool | None = None):
    """Setup dual-output logging (console + file).

    Important for performance: by default logs are stored **outside** the vault to
    avoid Obsidian indexing thousands of log notes.

    - If `log_dir` is absolute, it's used directly.
    - Otherwise logs go to `<project_root>/<log_dir>`.
    - Set `LOG_IN_VAULT=1` (or pass `log_in_vault=True`) to restore legacy behavior
      `<vault_root>/<log_dir>`.
    """

    if log_in_vault is None:
        log_in_vault = _parse_bool_env(os.getenv("LOG_IN_VAULT"))

    project_root = Path(__file__).resolve().parents[2]  # .../sx_obsidian

    if os.path.isabs(log_dir):
        log_path = log_dir
    else:
        base = Path(vault_root) if log_in_vault else project_root
        log_path = str(base / log_dir)

    os.makedirs(log_path, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_path, f"generator_{timestamp}.log")
    latest_file = os.path.join(log_path, "latest.log")

    logger = logging.getLogger("SX_Generator")
    logger.setLevel(logging.INFO)

    file_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    console_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(file_formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(console_formatter)
        logger.addHandler(ch)

        # Update/overwrite a stable pointer for convenience.
        try:
            shutil.copyfile(log_file, latest_file)
        except Exception:
            pass

        # Keep the log directory bounded.
        try:
            retain = int(os.getenv("LOG_RETAIN", "50"))
        except ValueError:
            retain = 50
        _prune_old_logs(log_path, "generator_*.log", retain, logger)

    return logger, log_file


class IngredientRegistry:
    def __init__(self, logger):
        self.logger = logger
        self.media_index = {}
        self.consolidated = []
        self.authors = {}
        self.bookmarks = {}
        self.schema = {}

    def load_all(self, config):
        self.logger.info(f"--- Loading Ingredients (Profile: {config['profile']}) ---")
        self.schema = _load_schema(config.get("schema"))
        data_root = os.path.join(config["vault"], config["data_dir"])
        if os.path.exists(data_root):
            self.logger.info(f"Scanning media in {data_root}...")
            self.media_index = self._scan_media(data_root)
        else:
            self.logger.warning(f"Media dir not found: {data_root}")

        for csv_path in config["csv_consolidated"] or []:
            if os.path.exists(csv_path):
                self.consolidated.extend(self._load_csv(csv_path))
                self.logger.info(f"Loaded {len(self.consolidated)} rows from {csv_path}")

        if config.get("csv_authors") and os.path.exists(config["csv_authors"]):
            rows = self._load_csv(config["csv_authors"])
            self.authors = {row.get("authors_id"): row for row in rows if row.get("authors_id")}

        if config.get("csv_bookmarks") and os.path.exists(config["csv_bookmarks"]):
            rows = self._load_csv(config["csv_bookmarks"])
            self.bookmarks = {
                row.get("bookmarks_bookmark_id"): row
                for row in rows
                if row.get("bookmarks_bookmark_id")
            }

    def _load_csv(self, path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def _scan_media(self, root):
        index = {}
        media_cfg = self.schema.get("media") if isinstance(self.schema, dict) else None
        video_exts = set((media_cfg or {}).get("video_exts") or [".mp4", ".mov", ".mkv"])
        cover_exts = set(
            (media_cfg or {}).get("cover_exts") or [".jpg", ".jpeg", ".png", ".webp"]
        )
        ignore_folders = (media_cfg or {}).get(
            "ignore_folders", [".appdata", ".git", "_db", "_logs"]
        )

        video_exts = {str(x).lower() for x in video_exts}
        cover_exts = {str(x).lower() for x in cover_exts}
        ignore_folders = [str(x) for x in ignore_folders]

        for path in glob.glob(os.path.join(root, "**", "*.*"), recursive=True):
            if any(ign in path for ign in ignore_folders):
                continue
            p = Path(path)
            ext = p.suffix.lower()
            rel_path = os.path.relpath(path, root)
            nums = re.findall(r"\d+", p.name)
            if not nums:
                continue
            asset_id = nums[0]
            if asset_id not in index:
                index[asset_id] = {
                    "video": None,
                    "cover": None,
                    "videos": [],
                    "covers": [],
                    "all_seen": [],
                }
            index[asset_id]["all_seen"].append(rel_path.replace("\\", "/"))
            if ext in video_exts:
                rel = rel_path.replace("\\", "/")
                index[asset_id]["videos"].append(rel)
                if index[asset_id]["video"] is None:
                    index[asset_id]["video"] = rel
            elif ext in cover_exts:
                rel = rel_path.replace("\\", "/")
                index[asset_id]["covers"].append(rel)
                if index[asset_id]["cover"] is None:
                    index[asset_id]["cover"] = rel
        return index


class ValidationEngine:
    def __init__(self, logger):
        self.logger = logger
        self.errors = []

    def validate(self, config, registry):
        self.logger.info("--- Starting Deep Validation ---")
        if not os.path.exists(config["vault"]):
            self.errors.append(f"Vault path does not exist: {config['vault']}")

        schema_c = (getattr(registry, "schema", {}) or {}).get("consolidated") or {}
        id_key = schema_c.get("id") or "c_videos_id"

        ids = [row.get(id_key) for row in registry.consolidated if row.get(id_key)]
        dup_ids = [k for k, v in Counter(ids).items() if v > 1]
        if dup_ids:
            self.errors.append(f"Duplicate IDs found in consolidated CSVs: {dup_ids[:5]}...")

        missing_count = sum(
            1
            for row in registry.consolidated
            if row.get(id_key) and row.get(id_key) not in registry.media_index
        )
        if missing_count > 0:
            self.logger.warning(
                f"Media coverage gap: {missing_count} IDs in CSV have no matching media files."
            )

        if self.errors:
            for err in self.errors:
                self.logger.error(f"Validation Error: {err}")
        else:
            self.logger.info("✅ Validation successful - No critical errors found.")
        return len(self.errors) == 0


class DatabaseLayer:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.db_root = os.path.join(config["vault"], config["db_dir"])
        self.stats = {"created": 0, "updated": 0, "skipped": 0, "no_media": 0, "deleted": 0}
        self.path_resolver = PathResolver(config)

    def cleanup(self, mode, force=False, dry_run=False):
        if not os.path.exists(self.db_root):
            return

        if mode == "soft":
            self.logger.info(
                f"Performing SOFT cleanup in {self.db_root}... (Dry Run: {dry_run}, Force: {force})"
            )
            files = glob.glob(os.path.join(self.db_root, "*.md"))
            skipped_dirty = 0
            for f in files:
                dirty, reason = self._is_dirty(f)
                if dirty and not force:
                    self.logger.warning(
                        f"Skipping DIRTY file: {os.path.basename(f)} (Reason: {reason})"
                    )
                    skipped_dirty += 1
                    continue
                if not dry_run:
                    try:
                        os.remove(f)
                        self.stats["deleted"] += 1
                    except FileNotFoundError:
                        pass
            self.logger.info(
                f"{'Would delete' if dry_run else 'Deleted'} {self.stats['deleted']} files. Skipped {skipped_dirty} dirty files."
            )

        elif mode == "hard":
            if not force:
                self.logger.error("HARD cleanup requires --force flag.")
                return
            self.logger.info(
                f"Performing HARD cleanup (db, logs, reports)... (Dry Run: {dry_run})"
            )
            paths = [
                self.db_root,
                os.path.join(self.config["vault"], self.config["log_dir"]),
                os.path.join(self.config["vault"], self.config["reports_dir"]),
            ]
            for p in paths:
                if os.path.exists(p):
                    if not dry_run:
                        shutil.rmtree(p)
                    self.logger.info(f"{'Would remove' if dry_run else 'Removed'} directory: {p}")
            if not dry_run:
                import sys

                sys.exit(0)

    def _is_dirty(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            body = content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    body = parts[2]
            body_clean = re.sub(f"{MANAGED_START}.*?{MANAGED_END}", "", body, flags=re.DOTALL).strip()
            if body_clean:
                return True, "Manual notes found"
            if content.startswith("---"):
                parts = content.split("---", 2)
                fm = yaml.safe_load(parts[1]) or {}
                custom_keys = set(fm.keys()) - SCRIPT_OWNED_KEYS - USER_EDITABLE_KEYS
                if custom_keys:
                    return True, f"Custom YAML keys: {list(custom_keys)}"
                if (
                    fm.get("status") not in ["raw", None]
                    or fm.get("tags")
                    or fm.get("rating") not in [None, ""]
                    or fm.get("notes")
                    or fm.get("scheduled_time")
                    or fm.get("product_link")
                ):
                    return True, "User-editable fields modified"
            return False, ""
        except Exception as e:
            return True, f"Error parsing: {e}"

    def sync(self, registry, args):
        os.makedirs(self.db_root, exist_ok=True)

        schema_c = (getattr(registry, "schema", {}) or {}).get("consolidated") or {}
        cmap = {
            "id": schema_c.get("id") or "c_videos_id",
            "author": schema_c.get("author_id") or "c_videos_authorid",
            "text": schema_c.get("text_content") or "c_texts_text_content",
            "author_uid": schema_c.get("author_unique_id") or "c_authors_uniqueids",
            "author_name": schema_c.get("author_nickname") or "c_authors_nicknames",
        }
        rows = registry.consolidated

        # Reduce note count: filter to a smaller active set.
        only_ids: set[str] | None = None
        if getattr(args, "only_ids_file", None):
            only_ids = self._load_ids_file(args.only_ids_file)

        if getattr(args, "only_bookmarked", False):
            bookmarked_ids = set(registry.bookmarks.keys())
            rows = [r for r in rows if r.get(cmap["id"]) in bookmarked_ids]

        if only_ids is not None:
            rows = [r for r in rows if r.get(cmap["id"]) in only_ids]

        if args.limit:
            rows = rows[: args.limit]

        active_ids: set[str] = set()
        for row in tqdm(rows, desc="Syncing DB"):
            asset_id = row.get(cmap["id"])
            if not asset_id:
                continue
                # schema.yaml uses `unique_id` / `nickname`
                "author_uid": schema_c.get("unique_id") or schema_c.get("author_unique_id") or "c_authors_uniqueids",
                "author_name": schema_c.get("nickname") or schema_c.get("author_nickname") or "c_authors_nicknames",

            author_id = row.get(cmap["author"])
            author_info = registry.authors.get(author_id) or {}
            author_uid = author_info.get("authors_uniqueids") or row.get(cmap["author_uid"])

            media = registry.media_index.get(asset_id, {})
            author_url = f"https://www.tiktok.com/@{author_uid}" if author_uid else None
            video_url = f"{author_url}/video/{asset_id}" if author_url and asset_id else None

            cover_bn = os.path.basename(media.get("cover")) if media.get("cover") else f"{asset_id}.jpg"
            video_bn = os.path.basename(media.get("video")) if media.get("video") else f"{asset_id}.mp4"
            bookmark_data = registry.bookmarks.get(asset_id) or {}

            # Consolidated may carry bookmark info even if a standalone bookmarks CSV isn't provided.
            row_bookmarked = _truthy(row.get("bookmarked"))
            for k in ("bookmark_timestamp", "bookmarks_timestamp", "bookmarked_timestamp"):
                if not bookmark_data.get("bookmarks_timestamp") and row.get(k):
                    bookmark_data["bookmarks_timestamp"] = row.get(k)

            # Best-effort bookmark detection from consolidated.
            bookmarked = (asset_id in registry.bookmarks) or row_bookmarked
            if not bookmarked:
                for k in ("bookmarks_list_type", "bookmarks_bookmark_id", "bookmark_id"):
                    if row.get(k):
                        bookmarked = True
                        break

            # Absolute paths for Protocols
            video_abs = self.path_resolver.resolve_absolute(media.get("video"))
            cover_abs = self.path_resolver.resolve_absolute(media.get("cover"))

            # Unify rendering with the API renderer (sx_db/markdown.py).
            # This avoids the two-template drift documented in docs/context.md.

            # Prefer a stable hash if provided by the upstream pipeline.
            csv_row_hash = None
            if row.get("csv_row_hash"):
                csv_row_hash = row.get("csv_row_hash")
            else:
                for k, v in row.items():
                    if "csv_row_hash" in str(k) and v:
                        csv_row_hash = v
                        break
            if not csv_row_hash:
                csv_row_hash = hashlib.md5(str(row).encode()).hexdigest()

            video = {
                "id": asset_id,
                "platform": row.get("platform", "TikTok"),
                "author_id": author_id,

                # Canonical media paths: Favorites for bookmarks, Following/<author_id> otherwise.
                expected_video, expected_cover = _expected_media_paths(str(asset_id), str(author_id) if author_id else None, bool(bookmarked))

                media = registry.media_index.get(asset_id, {})
                video_candidates = media.get("videos") or ([] if media.get("video") is None else [media.get("video")])
                cover_candidates = media.get("covers") or ([] if media.get("cover") is None else [media.get("cover")])

                # Prefer the correct root when both Favorites and Following exist.
                if bookmarked:
                    preferred_video = _pick_by_prefix(video_candidates, ["Favorites/videos/"])
                    preferred_cover = _pick_by_prefix(cover_candidates, ["Favorites/covers/"])
                else:
                    preferred_video = _pick_by_prefix(video_candidates, [f"Following/{author_id}/videos/"] if author_id else ["Following/"])
                    preferred_cover = _pick_by_prefix(cover_candidates, [f"Following/{author_id}/covers/"] if author_id else ["Following/"])

                chosen_video = preferred_video or expected_video
                chosen_cover = preferred_cover or expected_cover
                "author_unique_id": author_uid,
                video_abs = self.path_resolver.resolve_absolute(chosen_video)
                cover_abs = self.path_resolver.resolve_absolute(chosen_cover)
                "followers": self._to_num(author_info.get("authors_followercount")),
                "hearts": self._to_num(author_info.get("authors_heartcount")),
                "videos_count": self._to_num(author_info.get("authors_videocount")),
                "signature": author_info.get("authors_signature") or row.get("c_authors_signature"),
                "is_private": _truthy(author_info.get("authors_is_private") or row.get("c_authors_is_private")),
                "bookmarked": bool(bookmarked),
                "bookmark_timestamp": bookmark_data.get("bookmarks_timestamp"),
                "video_path": media.get("video"),
                "cover_path": media.get("cover"),
                "files_seen": media.get("all_seen", []),
                "csv_row_hash": csv_row_hash,
                # Provide abs paths too (the renderer will also derive them, but keep for compatibility).
                "video_abs": video_abs,
                "cover_abs": cover_abs,
            }

            self._sync_file(asset_id, video, args.dry_run)

        if getattr(args, "archive_stale", False):
            self._archive_stale_notes(active_ids, args)


    def _load_ids_file(self, path: str) -> set[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {line.strip() for line in f if line.strip() and not line.strip().startswith("#")}
        except FileNotFoundError:
                    "is_private": _truthy(author_info.get("authors_privateaccount") or row.get("c_authors_is_private")),
            return set()

                    "video_path": _norm_rel(chosen_video),
                    "cover_path": _norm_rel(chosen_cover),
                    # Keep full inventory, but ensure canonical expectations are present.
                    "files_seen": sorted(
                        set((media.get("all_seen", []) or []) + [_norm_rel(expected_video), _norm_rel(expected_cover)])
                    ),
        if os.path.isabs(archive_dir):
            return archive_dir
        project_root = Path(__file__).resolve().parents[2]  # .../sx_obsidian
        return str(project_root / archive_dir)


    def _archive_stale_notes(self, active_ids: set[str], args) -> None:
        """Move notes not in active_ids out of db_root to an archive directory.

        This is the main lever to keep Obsidian vaults snappy: keep only an
        "active working set" of notes inside the vault.
        """

        archive_root = self._resolve_archive_root()
        os.makedirs(archive_root, exist_ok=True)

        stale_files = glob.glob(os.path.join(self.db_root, "*.md"))
        moved = 0
        skipped_dirty = 0

        for fpath in tqdm(stale_files, desc="Archiving stale notes"):
            asset_id = Path(fpath).stem
            if asset_id in active_ids:
                continue

            dirty, reason = self._is_dirty(fpath)
            if dirty and not getattr(args, "force", False):
                skipped_dirty += 1
                self.logger.warning(
                    f"Skipping DIRTY stale note: {os.path.basename(fpath)} (Reason: {reason})"
                )
                continue

            dest = os.path.join(archive_root, os.path.basename(fpath))
            if getattr(args, "dry_run", False):
                continue

            try:
                shutil.move(fpath, dest)
                moved += 1
            except FileNotFoundError:
                pass

        self.logger.info(
            f"Archived {moved} stale notes to {archive_root}. Skipped {skipped_dirty} dirty notes."
        )

    def _to_num(self, val):
        try:
            return int(val) if val else 0
        except Exception:
            return 0

    def _sync_file(self, asset_id, video: dict, dry_run: bool):
        target = os.path.join(self.db_root, f"{asset_id}.md")
        if os.path.exists(target):
            with open(target, "r") as f:
                existing = f.read()
            # Pull forward any user-editable fields + any unknown keys
            # (do not overwrite the renderer-managed keys).
            existing_fm: dict = {}
            try:
                if existing.startswith("---"):
                    parts = existing.split("---", 2)
                    if len(parts) >= 3:
                        existing_fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                existing_fm = {}
        else:
            existing = None

        # Render using the shared renderer.
        rendered = render_note(video, resolver=self.path_resolver)
        if not rendered.startswith("---"):
            raise RuntimeError("render_note() returned unexpected markdown (missing frontmatter)")

        parts = rendered.split("---", 2)
        new_fm = yaml.safe_load(parts[1]) or {}

        # Preserve user-editable fields (status/tags/etc), and any unknown custom keys.
        if existing:
            for k, v in (existing_fm or {}).items():
                if k in USER_EDITABLE_KEYS:
                    # Only override when the user actually set something.
                    if v is not None and str(v).strip() != "":
                        new_fm[k] = v
                elif k not in new_fm:
                    new_fm[k] = v

        # Normalize template version to the shared renderer.
        new_fm["template_version"] = NOTE_TEMPLATE_VERSION

        # Skip when render_hash + template version match (fast path).
        if existing and new_fm.get("render_hash"):
            if (
                f"render_hash: {new_fm.get('render_hash')}" in existing
                and f"template_version: {NOTE_TEMPLATE_VERSION}" in existing
            ):
                self.stats["skipped"] += 1
                return

        fm_block = "---\n" + yaml.safe_dump(new_fm, sort_keys=False, allow_unicode=True) + "---\n\n"

        if MANAGED_START not in rendered or MANAGED_END not in rendered:
            raise RuntimeError("render_note() returned unexpected markdown (missing managed block markers)")

        managed_mid = rendered.split(MANAGED_START, 1)[1].split(MANAGED_END, 1)[0]
        managed_block = MANAGED_START + managed_mid + MANAGED_END + "\n"

        if existing:
            if MANAGED_START in existing and MANAGED_END in existing:
                body = existing.split("---", 2)[-1].strip()
                pre = body.split(MANAGED_START, 1)[0].strip()
                post = body.split(MANAGED_END, 1)[-1].strip()
                final_content = (
                    fm_block
                    + (pre + "\n\n" if pre else "")
                    + managed_block
                    + ("\n\n" + post if post else "")
                )
            else:
                final_content = fm_block + existing.split("---", 2)[-1].strip() + "\n\n" + managed_block
            self.stats["updated"] += 1
        else:
            final_content = fm_block + managed_block
            self.stats["created"] += 1

        if not dry_run:
            with open(target, "w") as f:
                f.write(final_content)
