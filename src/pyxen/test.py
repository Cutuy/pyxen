"""Test meta-runner.

Each pyxen module exposes a ``_main()`` function that contains its unit
tests. The test meta-runner discovers those modules automatically (via AST,
no side-effectful imports), imports each, and calls ``_main()``. This mirrors
the Rust pattern of ``#[cfg(test)]`` modules at the bottom of each source file.

The single dependency is the Python standard library. The user invokes:

    pyxen-test                # via the script entry in pyproject.toml
    python -m pyxen.test       # equivalent
    python -m pyxen.core.identity  # run a single module's tests
"""

from __future__ import annotations

import ast
import importlib
import io
import sys
import time
import traceback
from pathlib import Path
from typing import NamedTuple

from pyxen._paths import project_root

# ---------------------------------------------------------------------------
# Auto-discovery — AST-based for pyxen.* (safe), explicit list for examples
# ---------------------------------------------------------------------------

_SKIP_MODULES = frozenset({
    # runner / helpers (not tests)
    "pyxen.test",
    "pyxen.test_integration",
    "pyxen._testlib",
    "pyxen._cli",
    "pyxen._paths",
    "pyxen.__main__",
    # CLI entry points, not test suites
    "pyxen.core.ext.cron.record",
})

# Examples that have a ``_main()`` test entry point.  Kept explicit because
# importing example modules can have side effects (e.g. ``uvicorn.run()``).
_EXAMPLE_MODULES: tuple[str, ...] = (
    "examples.hello_runtime.main",
    "examples.notes_app.app",
    "examples.data_pipeline.pipeline",
    "examples.cron_app.main",
)


def _has_main_ast(path: Path) -> bool:
    """Return True if the file defines a top-level ``_main`` function (AST)."""
    try:
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    except SyntaxError:
        return False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_main":
            return True
    return False


def _discover_modules() -> list[str]:
    """Walk src/pyxen and yield every module that has ``def _main()``.

    Only the ``pyxen.*`` namespace is scanned (safe to import). Example
    modules are listed explicitly in ``_EXAMPLE_MODULES``.
    """
    src = project_root() / "src"
    modules: list[str] = []

    for py_file in sorted(src.rglob("*.py")):
        rel = py_file.relative_to(src)
        modname = str(rel.with_suffix("")).replace("/", ".")
        if not modname.startswith("pyxen."):
            continue
        if modname in _SKIP_MODULES:
            continue
        if _has_main_ast(py_file):
            modules.append(modname)

    return modules


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


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


def _print_indented(output: str) -> None:
    """Print captured output indented by two spaces."""
    for line in output.splitlines():
        if line.strip():
            print(f"    {line}")


def run_one(name: str) -> ModuleResult:
    """Import ``name`` and call its ``_main()``, capturing stdout.

    Returns a result record with the captured output.
    """
    start = time.monotonic()

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


def discover() -> list[str]:
    """Return all known test module names."""
    return _discover_modules() + list(_EXAMPLE_MODULES)


def main(modules: list[str] | None = None, *, verbose: bool = True) -> int:
    """Run the test suite. Prints results as each module completes.

    Args:
        modules: optional list of module names to test. Defaults to
            auto-discovered modules (every module with a ``_main()``).
        verbose: if True, print per-module pass/fail with test details;
            if False, only the summary.
    """
    targets = modules if modules is not None else discover()

    results: list[ModuleResult] = []

    for name in targets:
        result = run_one(name)
        results.append(result)

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


if __name__ == "__main__":
    sys.exit(main())
