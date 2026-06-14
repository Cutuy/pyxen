"""The ``pyxen`` command-line interface.

Sub-commands:

- ``pyxen init``     — write a starter ``runtime.json`` in the current directory.
- ``pyxen validate`` — parse and validate a ``runtime.json`` against the schema.
- ``pyxen test``     — run the per-module test suite (alias for ``python -m pyxen.test``).

The CLI is intentionally tiny. The heavy lifting lives in the runtime and
the test meta-runner; this file is just glue.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TEMPLATE: dict[str, object] = {
    "version": "1",
    "identity": {"implementation": "env", "config": {}},
    "tokens": {"implementation": "json_budget", "config": {"path": "./budget.json", "daily_limit": 100000}},
    "ipc": {"implementation": "inproc", "config": {}},
    "pkg": {"implementation": "dry_run", "config": {}},
    "storage": {"implementation": "local_sqlite", "config": {"path": "./runtime-data.db"}},
    "secrets": {"implementation": "dotenv", "config": {"path": "./.env"}},
    "observability": {"implementation": "stdout", "config": {"level": "info"}},
}


def cmd_init(args: argparse.Namespace) -> int:
    """Write a starter ``runtime.json`` to the current directory."""
    out = Path(args.path)
    if out.exists() and not args.force:
        print(
            f"refusing to overwrite {out} (use --force to clobber)",
            file=sys.stderr,
        )
        return 1
    out.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Parse and validate a ``runtime.json`` against the schema."""
    from .core import load_manifest
    from .core.errors import ManifestError

    path = Path(args.path)
    try:
        manifest = load_manifest(path)
    except ManifestError as exc:
        print(f"{path}: FAIL — {exc}", file=sys.stderr)
        return 1

    print(f"{path}: ok")
    print(f"  version: {manifest.version}")
    print(f"  primitives bound: {len(manifest.bindings)}")
    for name in sorted(manifest.bindings):
        binding = manifest.bindings[name]
        print(f"    {name}: {binding.implementation}")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run the per-module test suite. Delegates to ``pyxen.test``."""
    from . import test as _test

    if args.module:
        return _test.main([args.module], verbose=not args.quiet)
    return _test.main(verbose=not args.quiet)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Show which primitives are configured in a ``runtime.json`` and verify each
    implementation module is importable."""
    from .core import load_manifest
    from .core.errors import ManifestError

    path = Path(args.path)
    try:
        manifest = load_manifest(path)
    except ManifestError as exc:
        print(f"{path}: FAIL — {exc}", file=sys.stderr)
        return 1

    import importlib

    from .core.runtime import PRIMITIVE_TABLE

    print(f"{path}:")
    all_ok = True
    for name in sorted(manifest.bindings):
        binding = manifest.bindings[name]
        package = PRIMITIVE_TABLE.get(name)
        module_name = f"{package}.{binding.implementation}"
        try:
            importlib.import_module(module_name)
            status = "ok"
        except ImportError as exc:
            status = f"FAIL — {exc}"
            all_ok = False
        print(f"  {name}: {binding.implementation}  [{status}]")

    if not all_ok:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="pyxen",
        description="pyxen — a userland runtime interface for portable Python apps.",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="write a starter runtime.json")
    p_init.add_argument(
        "--path", default="runtime.json", help="output path (default: ./runtime.json)"
    )
    p_init.add_argument(
        "--force", action="store_true", help="overwrite if the file exists"
    )

    # validate
    p_val = sub.add_parser("validate", help="validate a runtime.json")
    p_val.add_argument(
        "path", nargs="?", default="runtime.json", help="manifest path"
    )

    # doctor
    p_doc = sub.add_parser(
        "doctor", help="verify each bound implementation is importable"
    )
    p_doc.add_argument(
        "path", nargs="?", default="runtime.json", help="manifest path"
    )

    # test
    p_test = sub.add_parser("test", help="run the per-module test suite")
    p_test.add_argument(
        "--module", help="run only this module (e.g., pyxen.core.runtime)"
    )
    p_test.add_argument("--quiet", action="store_true", help="suppress per-module output")

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on success, non-zero on failure."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return cmd_init(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "test":
        return cmd_test(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
