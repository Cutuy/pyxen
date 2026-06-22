"""Integration test runner.

Guarded by ``PYXEN_INTEGRATION=true`` so it's never accidentally invoked
by ``pre-push`` or CI. These tests modify system state (e.g. crontab) and
require elevated trust.

Usage::

    PYXEN_INTEGRATION=true python -m pyxen.test_integration
    PYXEN_INTEGRATION=true pyxen-test-integration
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

MODULES: tuple[str, ...] = (
    "pyxen.core.ext.cron.test_crontab",
)


def _should_skip() -> bool:
    if os.environ.get("PYXEN_INTEGRATION", "").strip().lower() not in ("1", "true", "yes"):
        print(
            "SKIP: set PYXEN_INTEGRATION=true to run integration tests\n"
            "      These tests modify system state (crontab, …).",
            file=sys.stderr,
        )
        return True
    return False


def main() -> int:
    if _should_skip():
        return 0

    import importlib
    import time

    failed = 0
    for name in MODULES:
        start = time.monotonic()
        try:
            mod = importlib.import_module(name)
        except Exception as exc:
            print(f"  FAIL  {name}  (import failed: {exc!r})")
            failed += 1
            continue

        fn = getattr(mod, "_main", None)
        if fn is None:
            print(f"  SKIP  {name}  (no _main())")
            continue

        try:
            result = fn()
            if result is not None and isinstance(result, int) and result != 0:
                print(f"  FAIL  {name}  (_main() returned {result})")
                failed += 1
                continue
        except Exception as exc:
            print(f"  FAIL  {name}  ({type(exc).__name__}: {exc})")
            import traceback
            traceback.print_exc()
            failed += 1
            continue

        elapsed = (time.monotonic() - start) * 1000
        print(f"  ok    {name}  ({elapsed:.1f} ms)")

    total = len(MODULES)
    passed = total - failed
    print(f"\n{passed} passed, {failed} failed, {total} total")

    if not failed:
        repo_root = Path(__file__).resolve().parent.parent.parent
        ts_path = repo_root / ".last_integration_test"
        ts_path.write_text(str(time.time()))
        print(f"→ timestamp written to {ts_path}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
