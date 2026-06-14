# Contributing to pyxen

## Design rules

### 1. Interface is contract

The 7 `Protocol` classes in `src/pyxen/core/` are the public API. App code talks to `rt.identity`, `rt.storage`, etc. — never to an implementation directly.

To add an implementation: write `src/pyxen/impl/<primitive>/<name>.py` with a `build(config) -> Impl` function. The runtime finds it by import path.

To add a new primitive: Protocol class + `PRIMITIVE_TABLE` entry + manifest schema entry. Don't do this casually — the 7 are the 7.

### 2. OpenAI SDK = per-primitive consumption, no wrapper

When an impl needs the SDK, it imports the specific piece it needs locally. No `impl/openai/` wrapper. Optional deps raise a clear `RuntimeError` directing to `pip install pyxen[openai]`.

### 3. Per-module tests (Rust style)

Every `.py` has a `_main()` with unit tests. `PYTHONPATH=src python -m pyxen.core.runtime` runs one module. `pyxen test` runs all. Register new modules in `src/pyxen/test.py`'s `MODULES` tuple.

Test-only imports go *inside* `_main()`. Tests use plain `assert`.

### 4. `mypy --strict`. No decorative docstrings. Ruff for linting.

### 5. `runtime.json` is the only deployment artifact

App code never reads it. `Runtime.load()` does.

### 6. Soft budgets, hard interface

Tokens primitive returns `allowed: true` + `reason` — app decides. Hard-block is an implementation detail.

### 7. Any Python app, not just agents

Agent-specific code doesn't belong in core.

## Repo hygiene

- `main` only. Squash-merge. Conventional commits.
