"""Allow `python -m smartess_local ...` invocation."""

from __future__ import annotations

import asyncio
import sys

from smartess_local.cli import main


def _entry() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    _entry()
