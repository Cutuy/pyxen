"""Consistent test output helpers for pyxen module ``_main()`` entry points.

All modules should import these helpers instead of writing ad-hoc
``print()`` calls, so the test suite output is uniform and parseable.

Usage:

    from pyxen._testlib import skip, ok, summary, run_tests

    def _main() -> None:
        if not prerequisite:
            skip("not available")
            return

        def test_foo() -> None:
            assert ...

        def test_bar() -> None:
            assert ...

        run_tests(test_foo, test_bar)

Async::

    from pyxen._testlib import skip, summary, arun_tests, atest_fn

    async def _tests(s):
        async def test_foo():
            await s.put(...)

        async def test_bar():
            assert await s.get(...) == ...

        await arun_tests(test_foo, test_bar)
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
    """Run a sync test case. Prints ``\u2713`` / ``\u2717``. Returns ``True`` on pass."""
    try:
        fn()
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False


async def atest(name: str, coro: Awaitable[Any]) -> bool:
    """Run an async test case. Prints ``\u2713`` / ``\u2717``. Returns ``True`` on pass."""
    try:
        await coro
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False


# ---------------------------------------------------------------------------
# helpers that auto-derive display names from test_* function names
# ---------------------------------------------------------------------------

def _fmt_name(fn: Callable[..., Any]) -> str:
    """Derive a user-facing test name from a ``test_*`` function name.

    ``test_put_get`` → ``"put get"``, ``test_foo`` → ``"foo"``.
    """
    raw = fn.__name__
    if raw.startswith("test_"):
        raw = raw[5:]
    return raw.replace("_", " ")


def test_fn(fn: Callable[..., Any], *args: Any) -> bool:
    """Run *fn* as a sync test, printing its auto-derived name.

    Returns ``True`` on pass, ``False`` on failure.
    """
    name = _fmt_name(fn)
    try:
        fn(*args)
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False


async def atest_fn(fn: Callable[..., Any], *args: Any) -> bool:
    """Await *fn(*args)* as an async test, printing its auto-derived name.

    Returns ``True`` on pass, ``False`` on failure.
    """
    name = _fmt_name(fn)
    try:
        await fn(*args)
        print(f"  \u2713  {name}")
        return True
    except Exception as e:
        print(f"  \u2717  {name}: {e}")
        return False


def run_tests(*tests: Callable[..., Any], label: str = "") -> None:
    """Run zero-argument sync ``test_*`` functions, auto-naming each.

    Example::

        def test_foo() -> None:
            assert ...

        def test_bar() -> None:
            assert ...

        run_tests(test_foo, test_bar)
    """
    passed = 0
    failed = 0
    for fn in tests:
        if test_fn(fn):
            passed += 1
        else:
            failed += 1
    summary(passed, failed, label=label)


async def arun_tests(*tests: Callable[..., Any], label: str = "") -> None:
    """Run zero-argument async ``test_*`` functions, auto-naming each.

    Example::

        async def test_foo():
            ...

        async def test_bar():
            ...

        await arun_tests(test_foo, test_bar)
    """
    passed = 0
    failed = 0
    for fn in tests:
        if await atest_fn(fn):
            passed += 1
        else:
            failed += 1
    summary(passed, failed, label=label)

