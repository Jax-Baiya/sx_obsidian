"""Compatibility shim for legacy `sx` import path.

Canonical package location: `packages/sx`.
This shim preserves imports like `import sx.paths` and entrypoint usage.
"""

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_canonical = _pkg_dir.parent / "packages" / "sx"

if _canonical.is_dir():
    __path__.append(str(_canonical))
