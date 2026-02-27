import json
import re
from pathlib import Path
from datetime import datetime

import psycopg

ROOT = Path('/home/An_Xing/projects/ANA/core/portfolio/sx_obsidian')
ENV_PATH = ROOT / '.env'
ENV_TEXT = ENV_PATH.read_text(errors='ignore')


def get_env(key: str, default: str = '') -> str:
    m = re.search(rf'(?m)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$', ENV_TEXT)
    return m.group(1).strip() if m else default


def main() -> None:
    source_id = get_env('SRC_PROFILE_2_ID', 'assets_2')
    schema = get_env('SXO_LOCAL_2_DB_SCHEMA', '') or f"{get_env('SX_POSTGRES_SCHEMA_PREFIX', 'sxo')}_{source_id}"
    dsn = get_env('SX_POSTGRES_DSN')
    if not dsn:
        raise RuntimeError('SX_POSTGRES_DSN missing in .env')

    vault_path = get_env('VAULT_PATH_2', '/mnt/t/Motiv')
    vault_db = Path(vault_path) / '_db'

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Avoid hanging forever on active API/background locks.
            cur.execute("SET lock_timeout = '5s'")
            cur.execute("SET statement_timeout = '120s'")

            # Best-effort: clear other sessions owned by the same DB user.
            # This is safe for a hard reset workflow and prevents TRUNCATE deadlocks.
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
                raise RuntimeError(f'No base tables found in schema {schema}')

            before: dict[str, int] = {}
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                before[t] = int(cur.fetchone()[0])

            stamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            backup = ROOT / '_logs' / f'profile2_hard_reset_backup_{stamp}.json'
            backup.write_text(
                json.dumps(
                    {
                        'timestamp_utc': stamp,
                        'source_id': source_id,
                        'schema': schema,
                        'vault_path': vault_path,
                        'tables_before': before,
                    },
                    indent=2,
                ),
                encoding='utf-8',
            )

            qualified = ', '.join([f'"{schema}"."{t}"' for t in tables])
            cur.execute(f'TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE')

            after: dict[str, int] = {}
            for t in tables:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                after[t] = int(cur.fetchone()[0])

    removed = 0
    if vault_db.exists() and vault_db.is_dir():
        for p in sorted(vault_db.rglob('*.md')):
            p.unlink(missing_ok=True)
            removed += 1

    remaining = len(list(vault_db.rglob('*.md'))) if vault_db.exists() else 0

    print('HARD_RESET_PROFILE2_DONE')
    print('source_id=', source_id)
    print('schema=', schema)
    print('tables=', len(before))
    print('rows_before_total=', sum(before.values()))
    print('rows_after_total=', sum(after.values()))
    print('nonzero_after=', {k: v for k, v in after.items() if v})
    print('vault=', vault_path)
    print('vault_md_deleted=', removed)
    print('vault_md_remaining=', remaining)
    print('backup_file=', str(backup))


if __name__ == '__main__':
    main()
