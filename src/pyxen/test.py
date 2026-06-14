"""Test meta-runner.

Each pyxen module exposes a ``_main()`` function that contains its unit
tests. The test meta-runner imports each module and calls ``_main()``,
collecting the results. This mirrors the Rust pattern of ``#[cfg(test)]``
modules at the bottom of each source file.

The single dependency is the Python standard library. The user invokes:

    pyxen-test                # via the script entry in pyproject.toml
    python -m pyxen.test       # equivalent
    python -m pyxen.core.identity  # run a single module's tests
"""

from __future__ import annotations

import importlib
import sys
import time
import traceback
from pathlib import Path
from typing import NamedTuple

# Every module that has a ``_main()`` test entry point.
# Add new modules here as the codebase grows.
MODULES: tuple[str, ...] = (
    # core
    "pyxen.core.identity",
    "pyxen.core.tokens",
    "pyxen.core.ipc",
    "pyxen.core.pkg",
    "pyxen.core.storage",
    "pyxen.core.secrets",
    "pyxen.core.observability",
    "pyxen.core.manifest",
    "pyxen.core.runtime",
    # impl: identity
    "pyxen.impl.identity.env",
    "pyxen.impl.identity.keychain",
    # impl: storage
    "pyxen.impl.storage.inmemory",
    "pyxen.impl.storage.local_sqlite",
    "pyxen.impl.storage.local_fs_mount",
    # impl: tokens
    "pyxen.impl.tokens.json_budget",
    # impl: ipc
    "pyxen.impl.ipc.inproc",
    # impl: pkg
    "pyxen.impl.pkg.dry_run",
    # impl: secrets
    "pyxen.impl.secrets.dotenv",
    # impl: observability
    "pyxen.impl.observability.stdout",
    "pyxen.impl.observability.null",
    "pyxen.impl.observability.file",
    "pyxen.impl.observability.openai_tracing",
    # examples
    "examples.hello_runtime.main",
    "examples.notes_app.app",
    "examples.data_pipeline.pipeline",
)


# Examples live outside src/ and are not installed as a package. When the
# meta-runner imports them, it adds the repo root to sys.path so they can
# resolve as top-level modules.
_EXAMPLE_MODULES = {
    "examples.hello_runtime.main",
    "examples.notes_app.app",
    "examples.data_pipeline.pipeline",
}


class ModuleResult(NamedTuple):
    """Result of running a single module's tests."""

    name: str
    passed: bool
    duration_s: float
    error: str | None = None


def run_one(name: str) -> ModuleResult:
    """Import ``name`` and call its ``_main()``. Returns a result record."""
    start = time.monotonic()
    if name in _EXAMPLE_MODULES:
        # Add the repo root to sys.path so example modules can be imported.
        # __file__ is src/pyxen/test.py; parents[2] is the repo root.
        repo_root = Path(__file__).resolve().parents[2]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        return ModuleResult(
            name=name,
            passed=False,
            duration_s=time.monotonic() - start,
            error=f"import failed: {exc!r}",
        )

    main = getattr(module, "_main", None)
    if main is None:
        # No test entry point — not a failure, just a skip.
        return ModuleResult(name=name, passed=True, duration_s=time.monotonic() - start)

    try:
        result = main()
        if result is not None and isinstance(result, int):
            # Module returned a non-zero exit code
            return ModuleResult(
                name=name,
                passed=False,
                duration_s=time.monotonic() - start,
                error=f"_main() returned {result}",
            )
    except AssertionError as exc:
        return ModuleResult(
            name=name,
            passed=False,
            duration_s=time.monotonic() - start,
            error=f"assertion failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — we report everything
        return ModuleResult(
            name=name,
            passed=False,
            duration_s=time.monotonic() - start,
            error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )

    return ModuleResult(name=name, passed=True, duration_s=time.monotonic() - start)


def main(modules: list[str] | None = None, *, verbose: bool = True) -> int:
    """Run the test suite. Returns 0 on success, 1 on any failure.

    Args:
        modules: optional list of module names to test. Defaults to all
            modules registered in ``MODULES``.
        verbose: if True, print per-module pass/fail; if False, only the
            summary.
    """
    targets = modules if modules is not None else list(MODULES)
    results: list[ModuleResult] = []

    for name in targets:
        result = run_one(name)
        results.append(result)
        if verbose:
            status = "ok  " if result.passed else "FAIL"
            print(f"  {status}  {name}  ({result.duration_s * 1000:.1f} ms)")
            if not result.passed and result.error:
                # Print the first line of the error for quick scanning
                first_line = result.error.splitlines()[0] if result.error else ""
                print(f"        {first_line}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    total_s = sum(r.duration_s for r in results)

    print()
    print(f"{passed} passed, {failed} failed, {len(results)} total ({total_s * 1000:.1f} ms)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
