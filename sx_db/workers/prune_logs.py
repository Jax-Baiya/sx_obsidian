from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class PruneResult:
    scanned: int
    deleted: int
    bytes_deleted: int


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def prune_logs(
    log_dir: Path,
    *,
    max_age_days: int = 14,
    dry_run: bool = False,
) -> PruneResult:
    """Delete old files under a log directory.

    This is meant for directories like `./_logs` that can grow indefinitely.

    Parameters
    ----------
    log_dir:
        Directory to prune.
    max_age_days:
        Delete files older than this many days (based on mtime).
    dry_run:
        If True, do not delete; just report what would be deleted.
    """

    root = Path(log_dir)
    if not root.exists() or not root.is_dir():
        return PruneResult(scanned=0, deleted=0, bytes_deleted=0)

    now = time.time()
    cutoff = now - max(0, int(max_age_days)) * 86400

    scanned = 0
    deleted = 0
    bytes_deleted = 0

    for p in _iter_files(root):
        scanned += 1
        try:
            st = p.stat()
        except FileNotFoundError:
            continue

        if st.st_mtime >= cutoff:
            continue

        bytes_deleted += int(st.st_size)
        if not dry_run:
            try:
                p.unlink()
                deleted += 1
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
        else:
            deleted += 1

    # Best-effort: remove empty directories bottom-up.
    if not dry_run:
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass

    return PruneResult(scanned=scanned, deleted=deleted, bytes_deleted=bytes_deleted)


def _main() -> None:  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Prune old log files under a directory")
    ap.add_argument("log_dir", nargs="?", default="_logs", help="Directory to prune (default: ./_logs)")
    ap.add_argument("--max-age-days", type=int, default=14, help="Delete files older than N days")
    ap.add_argument("--dry-run", action="store_true", help="Do not delete; only report")
    args = ap.parse_args()

    res = prune_logs(Path(args.log_dir), max_age_days=args.max_age_days, dry_run=args.dry_run)
    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(
        f"[{mode}] scanned={res.scanned} deleted={res.deleted} bytes_deleted={res.bytes_deleted} "
        f"(dir={os.path.abspath(args.log_dir)})"
    )


if __name__ == "__main__":  # pragma: no cover
    _main()
