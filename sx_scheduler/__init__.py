"""Compatibility shim for legacy `sx_scheduler` import path.

Canonical package location: `packages/sx_scheduler`.
"""

from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_canonical = _pkg_dir.parent / "packages" / "sx_scheduler"

if _canonical.is_dir():
    __path__.append(str(_canonical))
