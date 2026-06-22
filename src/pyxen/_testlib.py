"""Consistent test output helpers for pyxen module ``_main()`` entry points.

All modules should import these helpers instead of writing ad-hoc
``print()`` calls, so the test suite output is uniform and parseable.

Usage::

    from pyxen._testlib import skip, ok, summary, atest

    def _main() -> None:
        if not prerequisite:
            skip("not available")
            return

        # assertion-style tests — just assert and let it raise
        assert 1 + 1 == 2

        # named test cases with per-case output
        passed = 0
        failed = 0
        for name, coro in [("case 1", some_async_test())]:
            if await atest(name, coro):
                passed += 1
            else:
                failed += 1
        summary(passed, failed)

        ok()
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def skip(reason: str) -> None:
    """Print a standardized skip message and return.

    Call this when a prerequisite is missing, then ``return`` from
    ``_main()``. The test meta-runner treats a clean return as a pass.
    """
    print(f"  SKIP  {reason}")


def ok(label: str = "") -> None:
    """Print a standardized OK message."""
    if label:
        print(f"  OK    {label}")
    else:
        print("  OK")


def summary(passed: int, failed: int, label: str = "") -> None:
    """Print a standardized test summary."""
    prefix = f"{label}: " if label else ""
    if failed:
        print(f"  {prefix}{passed} passed, {failed} FAILED")
    else:
        print(f"  {prefix}{passed} passed \u2014 OK")


def test(name: str, fn: Callable[[], Any]) -> bool:
    """Run a sync test case. Prints ``✓`` / ``✗``. Returns ``True`` on pass."""
    try:
        fn()
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False


async def atest(name: str, coro: Awaitable[Any]) -> bool:
    """Run an async test case. Prints ``✓`` / ``✗``. Returns ``True`` on pass."""
    try:
        await coro
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False
