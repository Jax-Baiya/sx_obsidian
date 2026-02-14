from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import yaml

from sx.paths import PathResolver

MANAGED_START = "<!-- sx-managed:start -->"
MANAGED_END = "<!-- sx-managed:end -->"
TEMPLATE_VERSION = "v1.1"


WORKFLOW_STATUSES = [
    "raw",
    "reviewing",
    "reviewed",
    "scheduling",
    "scheduled",
    "published",
    "archived",
]


def _statuses_to_list(v: object) -> list[str]:
    """Accept DB packed string (|a|b|), list, or comma-separated text."""

    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]

    s = str(v).strip()
    if not s:
        return []
    if s.startswith("|") and s.endswith("|"):
        parts = [p.strip() for p in s.split("|") if p.strip()]
        # de-dupe preserving order
        out: list[str] = []
        seen: set[str] = set()
        for p in parts:
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
        return out
    return [p.strip() for p in s.split(",") if p.strip()]


def _to_bool(v: object) -> bool:
    return bool(v) and str(v).strip().lower() not in ("0", "false", "no", "n")


def _tags_to_list(tags: object) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]

    s = str(tags).strip()
    if not s:
        return []

    # Accept common formats:
    # - JSON array
    # - comma-separated
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return [str(t).strip() for t in obj if str(t).strip()]
    except Exception:
        pass

    return [p.strip() for p in s.split(",") if p.strip()]


def _csv_or_json_list(v: object) -> list[object]:
    """Accept JSON array or comma-separated text and return a list."""

    if v is None:
        return []
    if isinstance(v, list):
        return v

    s = str(v).strip()
    if not s:
        return []
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    return [p.strip() for p in s.split(",") if p.strip()]


def _workflow_log_to_list(v: object) -> list[object]:
    """Workflow log should be a list (often list[dict]) in YAML."""

    if v is None:
        return []
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if not s:
        return []
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    # If the field isn't JSON, keep it as a single entry (don't silently split dict-ish strings).
    return [s]


def _one_line(text: str) -> str:
    return " ".join((text or "").split()).strip()


def render_note(video: dict, *, resolver: PathResolver) -> str:
    """Render a single markdown note for an item.

    This is intended for the *active set* inside the vault.
    """

    asset_id = str(video["id"])
    author_uid = (video.get("author_unique_id") or "").strip() or None
    author_url = f"https://www.tiktok.com/@{author_uid}" if author_uid else None
    video_url = f"{author_url}/video/{asset_id}" if author_url else None

    # Some pipelines (or older DBs) don't persist media paths. To keep the
    # note format stable, derive canonical paths when missing.
    video_path = video.get("video_path")
    cover_path = video.get("cover_path")

    if not video_path or not cover_path:
        bookmarked = _to_bool(video.get("bookmarked"))
        author_id = (str(video.get("author_id") or "").strip() or None)
        if bookmarked:
            base = "Favorites"
        else:
            base = f"Following/{author_id}" if author_id else "Following"

        if not video_path:
            video_path = f"{base}/videos/{asset_id}.mp4"
        if not cover_path:
            cover_path = f"{base}/covers/{asset_id}.jpg"

    video_abs = resolver.resolve_absolute(video_path)
    cover_abs = resolver.resolve_absolute(cover_path)

    v_open = resolver.format_protocol("sxopen", video_abs)
    v_reveal = resolver.format_protocol("sxreveal", video_abs)
    c_open = resolver.format_protocol("sxopen", cover_abs)
    c_reveal = resolver.format_protocol("sxreveal", cover_abs)

    cover_name = Path(str(cover_path or "")).name if cover_path else ""
    video_name = Path(str(video_path or "")).name if video_path else ""

    # Workflow defaults (multi-choice supported)
    statuses_list = _statuses_to_list(video.get("statuses"))
    if not statuses_list:
        s = (video.get("status") or "").strip()
        statuses_list = [s] if s else []

    if not statuses_list:
        statuses_list = ["raw"]

    # Preserve unknown states (do not validate away).
    primary_status = statuses_list[-1] if statuses_list else "raw"

    tags_list = _tags_to_list(video.get("tags"))

    # files_seen should reflect *actual presence on disk* (when we can check).
    #
    # - If the generator already scanned the filesystem, it may supply a richer
    #   inventory in `video['files_seen']`.
    # - When running from the SQLite API, we often only have the expected
    #   canonical paths; in that case we use resolver.exists() to verify.
    files_seen_set: set[str] = set()
    raw_files_seen = video.get("files_seen")
    can_check = hasattr(resolver, "exists")

    def _maybe_add_seen(p: object) -> None:
        s = str(p).strip()
        if not s:
            return
        if can_check:
            try:
                if not resolver.exists(s):
                    return
            except Exception:
                return
        files_seen_set.add(s)

    if isinstance(raw_files_seen, list):
        for p in raw_files_seen:
            _maybe_add_seen(p)

    # Ensure the canonical expectations are represented *only when present*.
    if cover_path:
        _maybe_add_seen(cover_path)
    if video_path:
        _maybe_add_seen(video_path)

    files_seen: list[str] = sorted(files_seen_set)

    # Prefer an existence-based check when available (important when we construct
    # canonical Favorites/Following paths even if the scan didn't find media).
    if hasattr(resolver, "exists"):
        media_missing = (not resolver.exists(video_path)) or (cover_path is not None and not resolver.exists(cover_path))
    else:
        # Legacy behavior: treat missing *video* as the primary media missing signal.
        media_missing = not bool(video_path)
    metadata_missing = not (
        (video.get("platform") or "").strip()
        and (video.get("author_name") or "").strip()
        and author_uid
        and (video.get("caption") or "").strip()
    )

    raw_is_private = video.get("is_private")
    if raw_is_private is None or str(raw_is_private).strip() == "":
        is_private_val = None
    else:
        is_private_val = _to_bool(raw_is_private)

    fm = {
        "fields": "sx_media",
        "id": asset_id,
        "video": f"[[{video_path}]]" if video_path else None,
        "video_path": video_path,
        "video_abs": video_abs,
        "sxopen_video": v_open,
        "sxreveal_video": v_reveal,
        "cover": f"[[{cover_path}]]" if cover_path else None,
        "cover_path": cover_path,
        "cover_abs": cover_abs,
        "sxopen_cover": c_open,
        "sxreveal_cover": c_reveal,
        "video_url": video_url,
        "author_url": author_url,
        "platform": video.get("platform") or "TikTok",
        "author_name": video.get("author_name"),
        "author_unique_id": author_uid,
        "author_id": video.get("author_id"),
        "caption": video.get("caption") or "",
        "followers": video.get("followers"),
        "hearts": video.get("hearts"),
        "videos_count": video.get("videos_count"),
        "signature": video.get("signature"),
        "is_private": is_private_val,
        # `status` may be a scalar (legacy) or a list (multi-choice).
        "status": statuses_list if len(statuses_list) > 1 else primary_status,
        # User-meta fields (owned by the user; sourced from `user_meta` when using the SQLite flow).
        "rating": video.get("rating"),
        "notes": video.get("notes"),
        "bookmarked": _to_bool(video.get("bookmarked")),
        "bookmark_timestamp": video.get("bookmark_timestamp"),
        # User-editable workflow fields (persist if present in input)
        "scheduled_time": video.get("scheduled_time"),
        "product_link": video.get("product_link"),
        "author_links": _csv_or_json_list(video.get("author_links")),
        "tags": tags_list,
        # Optional legacy/compat fields (kept for dataview/metadata menu parity)
        "sx_select": bool(video.get("sx_select")) if video.get("sx_select") is not None else False,
        "platform_targets": _csv_or_json_list(video.get("platform_targets")),
        "workflow_log": _workflow_log_to_list(video.get("workflow_log")),
        "post_url": video.get("post_url"),
        "published_time": video.get("published_time"),
        "csv_row_hash": video.get("csv_row_hash"),
        "template_version": TEMPLATE_VERSION,
        "media_missing": bool(media_missing),
        "metadata_missing": bool(metadata_missing),
        "files_seen": files_seen,
    }

    render_context = {
        "template_version": TEMPLATE_VERSION,
        "csv_row_hash": fm.get("csv_row_hash"),
        "video_path": fm.get("video_path"),
        "cover_path": fm.get("cover_path"),
        "files_seen": sorted(fm.get("files_seen") or []),
        "path_style": (resolver.style or "").lower(),
        "vault_root": resolver.vault_root or "",
        "data_dir": resolver.data_dir or "",
    }
    fm["render_hash"] = hashlib.md5(
        json.dumps(render_context, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    fm_block = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n"

    caption_one = _one_line(str(video.get("caption") or ""))
    vc_line = f"vc:: {author_uid}" if author_uid else ""
    caption_lines = [caption_one] + ([vc_line] if vc_line else [])

    managed = [
        MANAGED_START,
        ">[!blank-container|min-0]",
        ">>[!Desc]+ MEDIA",
        ">>>[!blank-container|min-0]",
        ">>>>[!multi-column]",
        ">>>>>[!Desc]+ Cover",
        f">>>>>> ![[{cover_name or (asset_id + '.jpg')}]]",
        ">>>>",
        ">>>>>[!Desc]+ Video",
        f">>>>>> ![[{video_name or (asset_id + '.mp4')}]]",
        ">>>>",
        ">>",
        ">>>[!blank-container|min-0]",
        ">>>>[!Desc]+ Caption",
        ">>>>> ```md",
        *[f">>>>> {line}" for line in caption_lines if line],
        ">>>>> ```",
        ">>",
        ">>>[!blank-container|min-0]",
        ">>>>[!multi-column]",
        ">>>>>[!Desc]+ author_url",
        ">>>>>> ```md",
        f">>>>>> {author_url or ''}",
        ">>>>>> ```",
        ">>>>",
        ">>>>>[!Desc]+ author_name",
        ">>>>>> ```md",
        f">>>>>> {author_uid or (video.get('author_name') or '')}",
        ">>>>>> ```",
        ">>",
        ">>>[!blank-container|min-0]",
        ">>>>[!Desc]+ Local Files",
        f">>>>> [▶ Open Video]({v_open}) | [📂 Reveal]({v_reveal})",
        f">>>>> [🖼 Open Cover]({c_open}) | [📂 Reveal]({c_reveal})",
        "",
        MANAGED_END,
        "",
    ]

    return fm_block + "\n".join(managed)
