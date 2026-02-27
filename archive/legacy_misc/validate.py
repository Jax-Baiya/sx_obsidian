"""Legacy validator.

This script is intentionally kept for historical reference, but it does not
match the current frontmatter schema and the recommended validation path is:

    python -m sx --validate
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    raise SystemExit(
        "This legacy validator is deprecated. Use: python -m sx --validate"
    )


if __name__ == "__main__":
    raise SystemExit(main())
