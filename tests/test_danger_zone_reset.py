from __future__ import annotations

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from sx_db.api import create_app
from sx_db.db import connect, init_db
from sx_db.settings import Settings


def _seed_db(db_path: Path) -> None:
    conn = connect(db_path)
    init_db(conn, enable_fts=False)

    # Minimal rows needed for joins + filters.
    conn.execute(
        """
        INSERT INTO videos(id, platform, author_id, author_unique_id, author_name, caption, bookmarked, video_path, cover_path, updated_at)
        VALUES
          ('v1', 'tiktok', 'a1', 'u1', 'Alice', 'vitamin c serum', 1, 'Following/a1/v1.mp4', 'Following/a1/v1.jpg', '2026-01-01T00:00:00Z'),
          ('v2', 'tiktok', 'a2', 'u2', 'Bob', 'retinol night routine', 0, 'Following/a2/v2.mp4', 'Following/a2/v2.jpg', '2026-01-02T00:00:00Z')
        """
    )

    conn.execute(
        """
        INSERT INTO user_meta(video_id, rating, status, tags, notes, updated_at)
        VALUES
          ('v1', 5, 'reviewed', 'skincare,vitamin-c', 'great', '2026-01-03T00:00:00Z'),
          ('v2', 2, 'raw', 'skincare', '', '2026-01-03T00:00:00Z')
        """
    )

    conn.execute(
        """
        INSERT INTO video_notes(video_id, markdown, template_version, updated_at)
        VALUES
                    ('v1', '# user note', 'user', '2026-01-03T00:00:00Z'),
                    ('v2', '# cached template', 'v1.1', '2026-01-03T00:00:00Z')
        """
    )

    conn.commit()


def test_danger_reset_preview_and_apply(tmp_path: Path):
    db_path = tmp_path / 'sx_obsidian.db'
    _seed_db(db_path)

    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE='linux',
    )
    app = create_app(settings)
    client = TestClient(app)

    # Preview: tag filter matches v1 only.
    resp = client.post(
        '/danger/reset',
        json={
            'apply': False,
            'confirm': '',
            'filters': {'tag': 'vitamin-c'},
            'reset_user_meta': True,
            'reset_user_notes': True,
            'reset_cached_notes': False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['ok'] is True
    assert data['apply'] is False
    assert data['matched'] == 1
    assert data['would_delete']['user_meta'] == 1
    assert data['would_delete']['user_notes'] == 1

    # Apply without confirmation should fail.
    resp2 = client.post(
        '/danger/reset',
        json={
            'apply': True,
            'confirm': '',
            'filters': {'tag': 'vitamin-c'},
            'reset_user_meta': True,
            'reset_user_notes': True,
            'reset_cached_notes': False,
        },
    )
    assert resp2.status_code == 400

    # Apply with confirmation.
    resp3 = client.post(
        '/danger/reset',
        json={
            'apply': True,
            'confirm': 'RESET',
            'filters': {'tag': 'vitamin-c'},
            'reset_user_meta': True,
            'reset_user_notes': True,
            'reset_cached_notes': False,
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3['apply'] is True
    assert data3['deleted']['user_meta'] == 1
    assert data3['deleted']['user_notes'] == 1

    # Verify remaining: v2 meta still exists; v1 meta removed.
    conn = connect(db_path)
    init_db(conn, enable_fts=False)
    left_meta = conn.execute('SELECT COUNT(*) FROM user_meta').fetchone()[0]
    assert left_meta == 1


@pytest.mark.parametrize('has_notes,expected', [(True, 1), (False, 1)])
def test_danger_reset_filter_has_notes(tmp_path: Path, has_notes: bool, expected: int):
    db_path = tmp_path / 'sx_obsidian.db'
    _seed_db(db_path)

    settings = Settings(
        SX_DB_PATH=db_path,
        SX_DB_ENABLE_FTS=False,
        SX_API_CORS_ALLOW_ALL=False,
        DATA_DIR=str(tmp_path),
        SX_MEDIA_VAULT=str(tmp_path),
        SX_MEDIA_DATA_DIR=str(tmp_path),
        SX_MEDIA_STYLE='linux',
    )
    app = create_app(settings)
    client = TestClient(app)

    resp = client.post(
        '/danger/reset',
        json={
            'apply': False,
            'filters': {'has_notes': has_notes},
            'reset_user_meta': True,
            'reset_user_notes': False,
            'reset_cached_notes': False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()['matched'] == expected
