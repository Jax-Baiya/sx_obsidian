"""Compatibility entrypoint for `python -m sx`.

Delegates to canonical package implementation under `packages/sx`.
"""

from packages.sx.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
