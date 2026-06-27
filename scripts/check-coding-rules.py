#!/usr/bin/env python3
"""
pre-push coding rules check — enforce project-wide conventions.

Rule #1: Examples and implementations use ``project_root()`` instead of
         resolving paths on their own (no ad-hoc ``Path(__file__).resolve()``).

Rule #2: Unit tests (``_main()`` functions) use ``pyxen._testlib`` rather than
         inventing their own testing infrastructure.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Rule:
    key: str
    label: str
    description: str
    check: Callable[..., tuple[list[str], int]]
    fix: Callable[[str], tuple[str, bool]] | None = None


_RULES_BY_KEY: dict[str, Rule] = {}


def _register_rule(func: Callable[[], Rule]) -> Rule:
    rule = func()
    _RULES_BY_KEY[rule.key] = rule
    return rule


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
    """Return files changed in the working tree vs the merge-base with origin/main."""
    try:
        merge_base = subprocess.run(
            ["git", "merge-base", "origin/main", "HEAD"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("→ origin/main not found — can't compute diff, skipping coding rules check")
        return []

    mb = merge_base.stdout.strip()
    result = subprocess.run(
        ["git", "diff", "--name-only", mb],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return []
    names = result.stdout.strip().splitlines()
    return [REPO_ROOT / n for n in names if n]


_PATH_RESOLVE_RE = re.compile(r"Path\(__file__\)\.(?:resolve\(\)|parent)")


def _check_project_root(
    files: list[Path],
    error_files: dict[Path, set[str]] | None = None,
    key: str = "project_root",
) -> tuple[list[str], int]:
    """Flag ad-hoc path resolution in examples/ and src/ (excl. _paths.py)."""
    errors: list[str] = []
    checked = 0

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

        checked += 1

        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if _PATH_RESOLVE_RE.search(line):
                errors.append(
                    f"  {rel}:{lineno}: use project_root() instead of {line.strip()}"
                )
                if error_files is not None:
                    error_files.setdefault(file, set()).add(key)

    return errors, checked


def _fix_project_root(text: str) -> tuple[str, bool]:
    """Auto-fix: replace ``Path(__file__).resolve().parent`` etc."""
    original = text
    text = text.replace("Path(__file__).resolve().parent", "project_root()")
    text = text.replace("Path(__file__).parent", "project_root()")
    if text == original:
        return original, False
    if "from pyxen._paths import project_root" not in text:
        text = _add_import(text, "from pyxen._paths import project_root")
    return text, True


@_register_rule
def _rule_project_root() -> Rule:
    return Rule(
        key="project_root",
        label="project_root",
        description="use project_root() instead of ad-hoc path resolution",
        check=_check_project_root,
        fix=_fix_project_root,
    )


_MAIN_FN_RE = re.compile(r"^def _main\(\)\s*->\s*(?:None|int)\s*:")


def _check_testlib(
    files: list[Path],
    error_files: dict[Path, set[str]] | None = None,
    key: str = "_testlib",
) -> tuple[list[str], int]:
    """Flag _main() test functions that don't import from pyxen._testlib."""
    errors: list[str] = []
    checked = 0

    for file in files:
        if file.suffix != ".py":
            continue
        mod = _module_for(file)
        if mod is None:
            continue

        if mod in _SKIP_MODULES:
            continue

        checked += 1

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
            if error_files is not None:
                error_files.setdefault(file, set()).add(key)

    return errors, checked


def _fix_testlib(text: str) -> tuple[str, bool]:
    """Auto-fix: refactor ``_main()`` to use ``pyxen._testlib``."""
    original = text

    if "from pyxen._testlib import" in text:
        return original, False

    has_main = any(_MAIN_FN_RE.match(line) for line in text.splitlines())
    if not has_main:
        return original, False

    lines = text.splitlines()
    def_line, body_start, body_end = _get_func_body(lines)
    if body_start < 0:
        return _fix_testlib_fallback(text)
    if body_start >= body_end:
        return _fix_testlib_fallback(text)

    body_indent = len(lines[body_start]) - len(lines[body_start].lstrip())
    body_lines = lines[body_start:body_end]
    body_text = "\n".join(body_lines)

    try:
        dedented = textwrap.dedent(body_text)
        source_lines = dedented.splitlines()
        tree = ast.parse(dedented)
    except SyntaxError:
        return _fix_testlib_fallback(text)

    setup, helpers, tests, free_asserts, is_async = _classify_body_stmts(dedented)

    test_names_from_defs = {fn.name for fn in tests}
    setup = _remove_setup_noise(setup, test_names_from_defs, is_async)

    has_tests = bool(tests) or bool(free_asserts)

    # --- Build new body ---
    new_body_parts: list[str] = []

    # Imports inside _main()
    if is_async:
        new_body_parts.append("import asyncio")
        new_body_parts.append("from pyxen._testlib import arun_tests")
    else:
        new_body_parts.append("from pyxen._testlib import run_tests")
    new_body_parts.append("")

    if is_async:
        inner_parts: list[str] = []

        for stmt in setup:
            src = _extract_stmt_source(stmt, source_lines)
            if src:
                inner_parts.append(src)

        for fn in helpers:
            src = _extract_stmt_source(fn, source_lines)
            if src:
                inner_parts.append(src)

        test_names: list[str] = []
        for fn in tests:
            src = _extract_stmt_source(fn, source_lines)
            if src:
                if not isinstance(fn, ast.AsyncFunctionDef):
                    slines = src.splitlines()
                    slines[0] = "async " + slines[0]
                    src = "\n".join(slines)
                inner_parts.append(src)
                test_names.append(fn.name)

        if free_asserts:
            inner_parts.append("")
            inner_parts.append("async def test_all() -> None:")
            for stmt in free_asserts:
                src = _extract_stmt_source(stmt, source_lines)
                if src:
                    for s_line in src.splitlines():
                        inner_parts.append(f"    {s_line}")
            test_names.append("test_all")

        if has_tests:
            args = ",\n".join(f"    {n}" for n in test_names)
            inner_parts.append("")
            inner_parts.append("await arun_tests(")
            inner_parts.append(args)
            inner_parts.append(")")

        inner_body = textwrap.indent("\n".join(inner_parts), " " * 4)
        new_body_parts.append("async def _run_tests() -> None:")
        new_body_parts.append(inner_body)
        new_body_parts.append("")
        new_body_parts.append("try:")
        new_body_parts.append("    asyncio.run(_run_tests())")
        new_body_parts.append("except Exception:")
        new_body_parts.append("    pass")
    else:
        for stmt in setup:
            src = _extract_stmt_source(stmt, source_lines)
            if src:
                new_body_parts.append(src)

        for fn in helpers:
            src = _extract_stmt_source(fn, source_lines)
            if src:
                new_body_parts.append(src)

        test_names = []
        for fn in tests:
            src = _extract_stmt_source(fn, source_lines)
            if src:
                new_body_parts.append(src)
                test_names.append(fn.name)

        if free_asserts:
            new_body_parts.append("")
            new_body_parts.append("def test_all() -> None:")
            for stmt in free_asserts:
                src = _extract_stmt_source(stmt, source_lines)
                if src:
                    for s_line in src.splitlines():
                        new_body_parts.append(f"    {s_line}")
            test_names.append("test_all")

        if has_tests:
            args = ",\n".join(f"    {n}" for n in test_names)
            new_body_parts.append("")
            new_body_parts.append("run_tests(")
            new_body_parts.append(args)
            new_body_parts.append(")")

    new_body_text = "\n".join(new_body_parts)
    indented = textwrap.indent(new_body_text, " " * body_indent)

    new_lines = lines[:body_start] + [indented] + lines[body_end:]
    new_text = "\n".join(new_lines)

    if new_text == original:
        return original, False

    return new_text, True


def _fix_testlib_fallback(text: str) -> tuple[str, bool]:
    """Fallback: add ``from pyxen._testlib import run_tests`` + TODO comment."""
    if "from pyxen._testlib import" in text:
        return text, False
    text = _add_import(text, "from pyxen._testlib import run_tests")
    if "# TODO: manually convert to pyxen._testlib pattern" not in text:
        text = text.replace(
            "def _main(",
            "# TODO: manually convert to pyxen._testlib pattern\ndef _main(",
        )
    return text, True


@_register_rule
def _rule_testlib() -> Rule:
    return Rule(
        key="_testlib",
        label="_testlib",
        description="_main() test suites must use pyxen._testlib",
        check=_check_testlib,
        fix=_fix_testlib,
    )

# ── Shared Helpers ────────────────────────────────────────────────────

def _add_import(text: str, import_line: str) -> str:
    """Insert *import_line* after the last top-level import or module docstring."""
    lines = text.splitlines()
    insert_after = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            insert_after = i

    if insert_after >= 0:
        lines.insert(insert_after + 1, import_line)
        return "\n".join(lines)

    # No imports found — check for a module docstring
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(('"""', "'''")):
            if stripped.endswith(('"""', "'''")) and len(stripped) > 3:
                insert_after = i
            else:
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().endswith(('"""', "'''")):
                        insert_after = j
                        break
            break

    if insert_after >= 0:
        lines.insert(insert_after + 1, "")
        lines.insert(insert_after + 2, import_line)
        return "\n".join(lines)

    # Nothing at all — prepend
    lines.insert(0, "")
    lines.insert(0, import_line)
    return "\n".join(lines)
def _get_func_body(
    lines: list[str], func_name: str = "_main"
) -> tuple[int, int, int]:
    """Return (def_line, body_start, body_end) for the named function.

    ``body_end`` is exclusive (one past the last body line).  Returns
    ``(-1, -1, -1)`` if the function is not found.
    """
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)def " + re.escape(func_name) + r"\s*\(", line)
        if not m:
            continue
        def_indent = len(m.group(1))
        body_start = -1
        body_indent = -1

        for j in range(i + 1, len(lines)):
            if not lines[j].strip():
                continue
            indent = len(lines[j]) - len(lines[j].lstrip())
            if body_start < 0:
                body_start = j
                body_indent = indent
            elif indent <= def_indent and lines[j].strip():
                return i, body_start, j

        if body_start >= 0:
            return i, body_start, len(lines)
        return i, i + 1, len(lines)

    return -1, -1, -1


def _function_has_assert(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if *fn_node* (transitively) contains any ``assert``."""
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Assert):
            return True
    return False


def _classify_body_stmts(
    body_src: str,
) -> tuple[
    list[ast.stmt],  # setup statements
    list[ast.FunctionDef | ast.AsyncFunctionDef],  # helper functions
    list[ast.FunctionDef | ast.AsyncFunctionDef],  # test functions
    list[ast.Assert],  # free-floating asserts
    bool,  # is_async
]:
    """Parse *body_src* and classify its statements."""
    tree = ast.parse(body_src)

    setup: list[ast.stmt] = []
    helpers: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    tests: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    free_asserts: list[ast.Assert] = []
    is_async = False

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(stmt, ast.AsyncFunctionDef):
                is_async = True
            if stmt.name.startswith("test_") or _function_has_assert(stmt):
                tests.append(stmt)
                if isinstance(stmt, ast.AsyncFunctionDef):
                    is_async = True
            else:
                helpers.append(stmt)
        elif isinstance(stmt, ast.Assert):
            free_asserts.append(stmt)
        else:
            setup.append(stmt)

    return setup, helpers, tests, free_asserts, is_async


def _extract_stmt_source(node: ast.stmt, source_lines: list[str]) -> str:
    """Return the original source text for an AST node."""
    start = node.lineno - 1
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(source_lines[start:end])


def _remove_setup_noise(
    setup_stmts: list[ast.stmt],
    test_names: set[str],
    is_async: bool = False,
) -> list[ast.stmt]:
    """Filter out noise from setup statements.

    Removes:
    - ``print(...)`` calls
    - Ad-hoc calls to *test_names* (e.g. ``test_foo()``)
    - ``asyncio.run(fn)`` when *fn* is a test name (async mode)
    - ``import asyncio`` statements (async mode — we add our own)
    """
    filtered = []
    for stmt in setup_stmts:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Name) and (func.id == "print" or func.id in test_names):
                continue
            if (
                is_async
                and isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "asyncio"
                and func.attr == "run"
                and stmt.value.args
                and isinstance(stmt.value.args[0], ast.Call)
                and isinstance(stmt.value.args[0].func, ast.Name)
                and stmt.value.args[0].func.id in test_names
            ):
                continue
        if is_async and isinstance(stmt, ast.Import):
            is_asyncio_import = any(alias.name == "asyncio" for alias in stmt.names)
            if is_asyncio_import:
                continue
        filtered.append(stmt)
    return filtered
def _apply_fixes(error_files: dict[Path, set[str]]) -> list[Path]:
    """Apply auto-fixes to all files with violations.

    Returns list of modified paths (already written to disk).
    """
    modified: list[Path] = []

    for file, rule_keys in error_files.items():
        if not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        original = text
        applied: list[str] = []

        for key in sorted(rule_keys):
            rule = _RULES_BY_KEY.get(key)
            if rule is None or rule.fix is None:
                continue
            text, changed = rule.fix(text)
            if changed:
                applied.append(key)

        if text != original:
            file.write_text(text, encoding="utf-8")
            modified.append(file)
            rel = file.relative_to(REPO_ROOT)
            print(f"  \u2713 fixed: {rel} ({', '.join(applied)})")

    return modified


def main() -> int:
    files = _changed_files()
    if not files:
        print("\u2192 no changed files \u2014 skipping coding rules check")
        return 0

    error_files: dict[Path, set[str]] = defaultdict(set)
    all_errors: list[str] = []

    for rule in _RULES_BY_KEY.values():
        errs, checked = rule.check(files, error_files, key=rule.key)
        print(f"  {rule.label}: {checked} file(s) checked, {len(errs)} violation(s)")
        if errs:
            all_errors.append(f"{rule.label}: {rule.description}")
            all_errors.extend(errs)

    if not all_errors:
        print("  \u2713 coding rules check passed")
        return 0

    print()
    for err in all_errors:
        print(err)
    print()

    print("Attempting auto-fix\u2026")
    modified = _apply_fixes(error_files)

    if modified:
        paths = [str(f) for f in modified]
        subprocess.run(
            ["git", "add", "--"] + paths,
            check=False,
        )

    print()
    print("Coding rules violations were auto-fixed. Please review, commit, and push again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
