"""Legacy entrypoint.

The preferred entrypoint is now:

    python -m sx

This file is kept only for reference.
"""

import sys

from sx.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
