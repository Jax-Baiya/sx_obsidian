"""Compatibility entrypoint for `python -m sx_db`.

Delegates to canonical package implementation under `packages/sx_db`.
"""

from packages.sx_db.__main__ import main


if __name__ == "__main__":
    main()
