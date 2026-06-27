#!/usr/bin/env python3
"""
pre-push coding rules check — enforce project-wide conventions.

Rule #1: Examples and implementations use ``project_root()`` instead of
         resolving paths on their own (no ad-hoc ``Path(__file__).resolve()``).

Rule #2: Unit tests (``_main()`` functions) use ``pyxen._testlib`` rather than
         inventing their own testing infrastructure.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

# Modules whose _main() is a CLI entry point, not a test suite.
# Must stay in sync with test.py:_SKIP_MODULES.
_SKIP_MODULES: frozenset[str] = frozenset({
    "pyxen.test",
    "pyxen.test_integration",
    "pyxen._testlib",
    "pyxen._cli",
    "pyxen._paths",
    "pyxen.__main__",
    "pyxen.core.ext.cron.record",
})


def _module_for(file: Path) -> str | None:
    """Convert a src/pyxen/foo.py path to dotted module name (e.g. pyxen.foo)."""
    try:
        rel = file.relative_to(REPO_ROOT / "src")
    except ValueError:
        return None
    return str(rel.with_suffix("")).replace("/", ".")


def _changed_files() -> list[Path]:
    """Return files changed in the push diff vs origin/main."""
    try:
        subprocess.run(
            ["git", "rev-parse", "origin/main"],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError:
        print("→ origin/main not found — can't compute diff, skipping coding rules check")
        return []

    result = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return []
    names = result.stdout.strip().splitlines()
    return [REPO_ROOT / n for n in names if n]


# ── Rule #1: project_root() preferred over ad-hoc path resolution ──────

_PATH_RESOLVE_RE = re.compile(r"Path\(__file__\)\.(?:resolve\(\)|parent)")


def _check_rule1(files: list[Path]) -> list[str]:
    """Flag ad-hoc path resolution in examples/ and src/ (excl. _paths.py)."""
    errors: list[str] = []

    for file in files:
        if file.suffix != ".py":
            continue
        try:
            rel = file.relative_to(REPO_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 2 or parts[0] not in ("examples", "src"):
            continue
        if file.name == "_paths.py":
            continue

        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if _PATH_RESOLVE_RE.search(line):
                errors.append(
                    f"  {rel}:{lineno}: use project_root() instead of {line.strip()}"
                )

    return errors


# ── Rule #2: _main() test suites must use pyxen._testlib ────────────────

_MAIN_FN_RE = re.compile(r"^def _main\(\)\s*->\s*(?:None|int)\s*:")


def _check_rule2(files: list[Path]) -> list[str]:
    """Flag _main() test functions that don't import from pyxen._testlib."""
    errors: list[str] = []

    for file in files:
        if file.suffix != ".py":
            continue
        mod = _module_for(file)
        if mod is None:
            # Not under src/pyxen/ — check examples/ separately
            continue

        if mod in _SKIP_MODULES:
            continue

        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        has_main = any(_MAIN_FN_RE.match(line) for line in text.splitlines())
        if not has_main:
            continue

        if "from pyxen._testlib import" not in text:
            errors.append(
                f"  {file.relative_to(REPO_ROOT)}: tests in _main() must use pyxen._testlib"
            )

    return errors


# ── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    files = _changed_files()
    if not files:
        print("→ no changed files — skipping coding rules check")
        return 0

    errors: list[str] = []

    r1 = _check_rule1(files)
    if r1:
        errors.append("Rule #1: use project_root() instead of ad-hoc path resolution")
        errors.extend(r1)

    r2 = _check_rule2(files)
    if r2:
        errors.append("Rule #2: _main() test suites must use pyxen._testlib")
        errors.extend(r2)

    if not errors:
        print("✓ coding rules check passed")
        return 0

    print()
    for err in errors:
        print(err)
    print()
    print("Push ABORTED — fix violations above before pushing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
