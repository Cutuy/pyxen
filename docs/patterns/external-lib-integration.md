# External Library Integration Pattern

This document describes the canonical pattern for wrapping an external Python
library or CLI behind a pyxen primitive. Follow this checklist when adding a
new implementation.

## Checklist

### 1. Module location

Place the implementation in `src/pyxen/impl/<primitive>/<name>.py`, matching
the primitive directory (e.g. `storage/`, `identity/`, `tokens/`).

### 2. Implement the protocol

Create a class that implements the relevant `Protocol` from `pyxen.core.<primitive>`.
For example, storage implementations follow `StorageImpl`:

```python
from ...core.storage import QueryFilter

class GcsStorage:
    async def put(self, namespace: str, key: str, value: dict[str, Any]) -> None: ...
    async def get(self, namespace: str, key: str) -> dict[str, Any] | None: ...
    async def query(self, ...) -> list[dict[str, Any]]: ...
    async def delete(self, namespace: str, key: str) -> bool: ...
```

### 3. Handle credentials in `__init__`

Accept configuration via `def __init__(self, config: dict[str, object])`.
Resolve credentials, connection URLs, and other settings from this dict.
Use a lazy-construction pattern (create client on first use) with
`threading.Lock` for thread safety.

Credential resolution should follow a priority order — for example:
1. Explicit path to a credential file
2. Inline credential string from config
3. Environment / Application Default Credentials

### 4. Export a `build` factory function

Every impl module must expose a top-level `build` function:

```python
def build(config: dict[str, object]) -> MyImpl:
    return MyImpl(config)
```

The runtime uses this factory to instantiate implementations dynamically.

### 5. Declare optional dependencies in `pyproject.toml`

Add the required packages to `[project.optional-dependencies]` — for example,
the `cloud` group:

```toml
[project.optional-dependencies]
cloud = [
    "boto3>=1.34",
    "my-cloud-sdk>=1.0",
]
```

Also add a `[[tool.mypy.overrides]]` entry for the package to suppress
missing import warnings:

```toml
[[tool.mypy.overrides]]
module = "mylib.*"
ignore_missing_imports = true
```

### 6. Register in `src/pyxen/test.py`

Add the module's dotted path to the `MODULES` tuple so the meta-runner
discovers it:

```python
MODULES: tuple[str, ...] = (
    ...
    "pyxen.impl.storage.my_impl",
    ...
)
```

### 7. Write a `_main()` test function

Every module includes a `_main()` function at module level. Tests must:

- Run all operations (put, get, query, delete, etc.)
- Use an async inner function: `async def go(): ...` + `asyncio.run(go())`
- Skip gracefully when required environment variables are not set
- Import anything needed from pyxen at runtime inside the function
- Print `"<name>: SKIP"` when skipping, `"<name>: OK"` on success
- Catch exceptions and print `"<name>: SKIP (<reason>)"` instead of crashing

Example:

```python
def _main() -> None:
    import asyncio
    import os

    bucket = os.environ.get("PYXEN_MY_TEST_BUCKET")
    if not bucket:
        print("my_impl: SKIP (PYXEN_MY_TEST_BUCKET not set)")
        return

    async def go() -> None:
        s = build({"bucket": bucket})
        await s.put("ns", "k", {"v": 1})
        assert await s.get("ns", "k") == {"v": 1}
        print("my_impl: OK")

    try:
        asyncio.run(go())
    except Exception as exc:
        print(f"my_impl: SKIP ({exc})")


if __name__ == "__main__":
    _main()
```

### 8. Wrap errors

Wrap all external-library exceptions in the appropriate pyxen error type
from `pyxen.core.errors` (e.g. `StorageError`, `IdentityError`). Keep the
original exception as the cause via `raise ... from exc`:

```python
from ...core.errors import StorageError

try:
    blob.upload_from_string(data)
except Exception as exc:
    raise StorageError(f"gcs put failed: {exc}") from exc
```

### 9. Style conventions

- `from __future__ import annotations` at the top
- Type hints everywhere (function signatures, instance variables)
- `threading.Lock` for thread safety (especially lazy initialization)
- Follow existing docstring style (module-level with code-block config example)
- No extra comments unless clarifying a non-obvious decision
