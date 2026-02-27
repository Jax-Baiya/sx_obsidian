#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_profile(env: dict[str, str], index: int) -> dict[str, str]:
    source_id = (
        env.get(f"SRC_PROFILE_{index}_ID")
        or env.get(f"DATABASE_PROFILE_{index}")
        or f"assets_{index}"
    )

    schema_prefix = env.get("SX_POSTGRES_SCHEMA_PREFIX") or env.get("SX_PROFILE_DB_SCHEMA_PREFIX") or "sxo"
    schema = (
        env.get(f"SXO_LOCAL_{index}_DB_SCHEMA")
        or env.get(f"SRC_SCHEMA_{index}")
        or f"{schema_prefix}_{source_id}"
    )

    vault_path = env.get(f"VAULT_PATH_{index}", "")
    assets_path = env.get(f"ASSETS_PATH_{index}", "")

    csv_c = env.get(f"CSV_consolidated_{index}") or (
        str(Path(assets_path) / "xlsx_files" / "consolidated.csv") if assets_path else ""
    )
    csv_a = env.get(f"CSV_authors_{index}") or (
        str(Path(assets_path) / "xlsx_files" / "authors.csv") if assets_path else ""
    )
    csv_b = env.get(f"CSV_bookmarks_{index}") or (
        str(Path(assets_path) / "xlsx_files" / "bookmarks.csv") if assets_path else ""
    )

    return {
        "source_id": source_id,
        "schema": schema,
        "vault_path": vault_path,
        "csv_consolidated": csv_c,
        "csv_authors": csv_a,
        "csv_bookmarks": csv_b,
    }


def run_cmd(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def truncate_schema(dsn: str, schema: str) -> tuple[dict[str, int], dict[str, int], list[str]]:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET lock_timeout = '5s'")
            cur.execute("SET statement_timeout = '120s'")
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND usename = current_user
                  AND pid <> pg_backend_pid()
                """
            )
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema=%s AND table_type='BASE TABLE'
                ORDER BY table_name
                """,
                (schema,),
            )
            tables = [r[0] for r in cur.fetchall()]
            if not tables:
                raise RuntimeError(f"No base tables found in schema {schema}")

            before: dict[str, int] = {}
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                before[t] = int(cur.fetchone()[0])

            qualified = ", ".join([f'"{schema}"."{t}"' for t in tables])
            cur.execute(f"TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE")

            after: dict[str, int] = {}
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                after[t] = int(cur.fetchone()[0])

    return before, after, tables


def delete_vault_markdown(vault_path: str) -> tuple[int, int]:
    if not vault_path:
        return 0, 0
    root = Path(vault_path) / "_db"
    try:
        exists = root.exists()
        is_dir = root.is_dir()
    except OSError as e:
        print(f"PROFILE_RECOVERY_WARN vault_unreachable path={root} error={e}")
        return 0, 0

    if not exists or not is_dir:
        return 0, 0

    removed = 0
    try:
        for p in sorted(root.rglob("*.md")):
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except OSError as e:
                print(f"PROFILE_RECOVERY_WARN md_delete_failed path={p} error={e}")
        remaining = len(list(root.rglob("*.md")))
    except OSError as e:
        print(f"PROFILE_RECOVERY_WARN vault_scan_failed path={root} error={e}")
        return removed, 0

    return removed, remaining


def main() -> None:
    parser = argparse.ArgumentParser(description="Targeted profile recovery: reset + import + refresh.")
    parser.add_argument("--profile-index", type=int, required=True, help="Profile index N from *_N env keys")
    parser.add_argument("--skip-reset", action="store_true", help="Skip schema truncate + vault markdown cleanup")
    parser.add_argument("--skip-import", action="store_true", help="Skip CSV import")
    parser.add_argument("--skip-refresh", action="store_true", help="Skip refresh-notes")
    parser.add_argument("--limit", type=int, default=0, help="Optional refresh-notes limit (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved plan and exit")
    args = parser.parse_args()

    if not ENV_PATH.exists():
        raise RuntimeError(f".env not found at {ENV_PATH}")

    env = parse_env(ENV_PATH)
    dsn = env.get("SX_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("SX_POSTGRES_DSN missing in .env")

    cfg = resolve_profile(env, args.profile_index)
    source_id = cfg["source_id"]
    schema = cfg["schema"]
    vault_path = cfg["vault_path"]
    csv_c = cfg["csv_consolidated"]
    csv_a = cfg["csv_authors"]
    csv_b = cfg["csv_bookmarks"]

    plan = {
        "profile_index": args.profile_index,
        "source_id": source_id,
        "schema": schema,
        "vault_path": vault_path,
        "csv_consolidated": csv_c,
        "csv_authors": csv_a,
        "csv_bookmarks": csv_b,
        "skip_reset": args.skip_reset,
        "skip_import": args.skip_import,
        "skip_refresh": args.skip_refresh,
        "refresh_limit": args.limit,
    }

    print("PROFILE_RECOVERY_PLAN")
    print(json.dumps(plan, indent=2))

    if args.dry_run:
        return

    backup_file = None
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    tables: list[str] = []
    deleted = 0
    remaining = 0

    if not args.skip_reset:
        before, after, tables = truncate_schema(dsn, schema)
        deleted, remaining = delete_vault_markdown(vault_path)

        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        backup_file = ROOT / "_logs" / f"profile{args.profile_index}_recovery_backup_{stamp}.json"
        backup_file.write_text(
            json.dumps(
                {
                    "timestamp_utc": stamp,
                    "profile_index": args.profile_index,
                    "source_id": source_id,
                    "schema": schema,
                    "vault_path": vault_path,
                    "tables_before": before,
                    "tables_after": after,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if not args.skip_import:
        for label, value in {
            "consolidated": csv_c,
            "authors": csv_a,
            "bookmarks": csv_b,
        }.items():
            p = Path(value)
            if not value or not p.exists():
                raise RuntimeError(
                    f"Missing {label} CSV for profile {args.profile_index}: {value!r}. "
                    "Set CSV_*_N in .env or ensure ASSETS_PATH_N/xlsx_files exists."
                )

        run_cmd(
            [
                sys.executable,
                "-m",
                "sx_db",
                "import-csv",
                "--source",
                source_id,
                "--csv",
                csv_c,
                "--authors",
                csv_a,
                "--bookmarks",
                csv_b,
            ]
        )

    if not args.skip_refresh:
        cmd = [sys.executable, "-m", "sx_db", "refresh-notes", "--source", source_id]
        if args.limit and args.limit > 0:
            cmd.extend(["--limit", str(args.limit)])
        run_cmd(cmd)

    print("PROFILE_RECOVERY_DONE")
    print("profile_index=", args.profile_index)
    print("source_id=", source_id)
    print("schema=", schema)
    print("tables=", len(tables))
    print("rows_before_total=", sum(before.values()) if before else 0)
    print("rows_after_total=", sum(after.values()) if after else 0)
    print("nonzero_after=", {k: v for k, v in after.items() if v} if after else {})
    print("vault=", vault_path)
    print("vault_md_deleted=", deleted)
    print("vault_md_remaining=", remaining)
    print("backup_file=", str(backup_file) if backup_file else "")


if __name__ == "__main__":
    main()
