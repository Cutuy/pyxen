#!/usr/bin/env python3
"""Warn if integration tests haven't been run in the last 24 hours."""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TS_PATH = REPO_ROOT / ".last_integration_test"
STALE_SECONDS = 86400  # 24 hours


def main() -> int:
    if not TS_PATH.exists():
        print(
            "⚠️  Integration tests never run — set PYXEN_INTEGRATION=true "
            "and run `python -m pyxen.test_integration`"
        )
        return 0

    try:
        last = float(TS_PATH.read_text().strip())
    except (ValueError, OSError):
        print("⚠️  Could not read .last_integration_test timestamp")
        return 0

    elapsed = time.time() - last
    if elapsed > STALE_SECONDS:
        hours = int(elapsed // 3600)
        print(
            f"⚠️  Integration tests last run {hours} hours ago "
            f"(>24h) — consider running with PYXEN_INTEGRATION=true"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
