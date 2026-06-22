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
import io
import sys
import time
import traceback
from typing import NamedTuple

from pyxen._paths import project_root

# Every module that has a ``_main()`` test entry point.
# Add new modules here as the codebase grows.
MODULES: tuple[str, ...] = (
    # core
    "pyxen.core.identity",
    "pyxen.core.ext",
    "pyxen.core.ext.cron.errors",
    "pyxen.core.ext.cron.models",
    "pyxen.core.ext.cron.scheduler",
    "pyxen.core.ext.cron.state",
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
    "pyxen.impl.storage.redis",
    "pyxen.impl.storage.local_fs_mount",
    "pyxen.impl.storage.router",
    "pyxen.impl.storage.bq",
    "pyxen.impl.storage.gcs",
    # impl: tokens
    "pyxen.impl.tokens.json_budget",
    "pyxen.impl.tokens.openai_usage",
    # impl: ipc
    "pyxen.impl.ipc.inproc",
    "pyxen.impl.ipc.a2a",
    # impl: pkg
    "pyxen.impl.pkg.dry_run",
    "pyxen.impl.pkg.pip",
    "pyxen.impl.pkg.uv",
    # impl: secrets
    "pyxen.impl.secrets.dotenv",
    "pyxen.impl.secrets.local_file",
    # impl: observability
    "pyxen.impl.observability.stdout",
    "pyxen.impl.observability.null",
    "pyxen.impl.observability.file",
    "pyxen.impl.observability.openai_tracing",
    # examples
    "examples.hello_runtime.main",
    "examples.notes_app.app",
    "examples.data_pipeline.pipeline",
    "examples.cron_app.main",
)


# Examples live outside src/ and are not installed as a package. When the
# meta-runner imports them, it adds the repo root to sys.path so they can
# resolve as top-level modules.
_EXAMPLE_MODULES = {
    "examples.hello_runtime.main",
    "examples.notes_app.app",
    "examples.data_pipeline.pipeline",
    "examples.cron_app.main",
}


class ModuleResult(NamedTuple):
    """Result of running a single module's tests."""

    name: str
    passed: bool
    duration_s: float
    output: str = ""
    error: str | None = None


def _has_issues(output: str) -> bool:
    """Check if captured test output contains any SKIP, failure, or FAILED summary."""
    for line in output.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("SKIP")
            or stripped.startswith("\u2717")
            or "FAILED" in stripped
        ):
            return True
    return False


def run_one(name: str) -> ModuleResult:
    """Import ``name`` and call its ``_main()``, capturing stdout.

    Returns a result record with the captured output.
    """
    start = time.monotonic()
    if name in _EXAMPLE_MODULES:
        repo_root = project_root()
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
        return ModuleResult(name=name, passed=True, duration_s=time.monotonic() - start)

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        try:
            result = main()
            if result is not None and isinstance(result, int) and result != 0:
                return ModuleResult(
                    name=name,
                    passed=False,
                    duration_s=time.monotonic() - start,
                    output=buf.getvalue(),
                    error=f"_main() returned {result}",
                )
        except AssertionError as exc:
            return ModuleResult(
                name=name,
                passed=False,
                duration_s=time.monotonic() - start,
                output=buf.getvalue(),
                error=f"assertion failed: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — we report everything
            return ModuleResult(
                name=name,
                passed=False,
                duration_s=time.monotonic() - start,
                output=buf.getvalue(),
                error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            )
    finally:
        sys.stdout = old_stdout

    return ModuleResult(
        name=name,
        passed=True,
        duration_s=time.monotonic() - start,
        output=buf.getvalue(),
    )


def main(modules: list[str] | None = None, *, verbose: bool = True) -> int:
    """Run the test suite. Returns 0 on success, 1 on any failure.

    Args:
        modules: optional list of module names to test. Defaults to all
            modules registered in ``MODULES``.
        verbose: if True, print per-module pass/fail with test details;
            if False, only the summary.
    """
    targets = modules if modules is not None else list(MODULES)
    results: list[ModuleResult] = []

    for name in targets:
        result = run_one(name)
        results.append(result)

    for result in results:
        ms = result.duration_s * 1000

        if not result.passed:
            print(f"  FAIL  {result.name}  ({ms:.1f} ms)")
            _print_indented(result.output)
            if result.error:
                first = result.error.splitlines()[0]
                print(f"        {first}")
        elif _has_issues(result.output):
            print(f"  ok?   {result.name}  ({ms:.1f} ms)")
            _print_indented(result.output)
        else:
            print(f"  ok    {result.name}  ({ms:.1f} ms)")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    total_s = sum(r.duration_s for r in results)

    print()
    print(f"{passed} passed, {failed} failed, {len(results)} total ({total_s * 1000:.1f} ms)")

    return 0 if failed == 0 else 1


def _print_indented(output: str) -> None:
    """Print captured output indented by two spaces."""
    for line in output.splitlines():
        if line.strip():
            print(f"    {line}")


if __name__ == "__main__":
    sys.exit(main())
