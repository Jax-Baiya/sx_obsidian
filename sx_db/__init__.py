"""Compatibility shim for legacy `sx_db` import path.

Canonical package location: `packages/sx_db`.
This shim preserves imports like `import sx_db.api` and CLI invocation patterns.
"""

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_canonical = _pkg_dir.parent / "packages" / "sx_db"

if _canonical.is_dir():
    __path__.append(str(_canonical))
