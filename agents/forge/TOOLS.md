# TOOLS.md — Local Environment

_pyxen-specific notes. Everything I need to know about the library I'm building apps for._

## Find pyxen

pyxen is installed as a Python package. To find its install path:

```bash
python -c "import pyxen, pathlib; print(pathlib.Path(pyxen.__file__).parent)"
```

This gives me the absolute path to pyxen on the user's machine. From there I can read any file in the package, including the reference examples below.

## Install

The user is expected to have pyxen installed in their project's venv:

```bash
pip install pyxen                         # core (jsonschema only)
pip install "pyxen[examples]"             # adds fastapi + uvicorn (for notes_app-style apps)
pip install "pyxen[openai,cloud,a2a]"     # full set of optional impls
```

Verify:

```bash
pyxen --version
python -c "import pyxen; print(pyxen.__file__)"
```

## CLI

| Command | Purpose |
|---|---|
| `pyxen init` | Write a starter `runtime.json` in the cwd. **This is how I generate the initial manifest for every build.** |
| `pyxen validate <path>` | Validate against `schemas/runtime.schema.json`. Exit 0 on pass, non-zero on fail. |
| `pyxen doctor <path>` | Check that every `implementation` module is importable. Catches missing optional deps. |
| `pyxen test` | Run the per-module test suite |

`validate` and `doctor` are non-negotiable before declaring a build done.

## Reference patterns (the canonical examples)

I do **not** carry my own templates. I read pyxen's own `examples/` directory and adapt:

| Reference | When to read it |
|---|---|
| `pyxen/examples/notes_app/` | FastAPI web app with identity + tokens + storage + observability. The pattern for any HTTP-served pyxen app. |
| `pyxen/examples/hello_runtime/` | 30-line CLI script using 3 primitives. The pattern for the smallest possible pyxen program. |
| `pyxen/examples/data_pipeline/` | Pipeline that loads two separate `Runtime` instances (source + destination). The pattern for "same code, different backends." |
| `pyxen/examples/a2a_chat/` | A2A-compatible agent with request/reply and streaming. The pattern for inter-agent communication. |

Read the reference's `app.py` (or `main.py`) and `runtime.json` to understand the shape, then adapt to the user's package name and primitives.

## Key paths inside the pyxen install

| Path | What's there |
|---|---|
| `pyxen/__init__.py` | `Runtime` class — single entry point |
| `pyxen/core/runtime.py` | `Runtime.load()` implementation |
| `pyxen/core/manifest.py` | `Manifest` + `load_manifest()` — parses `runtime.json` |
| `pyxen/core/{identity,storage,secrets,tokens,observability,ipc,pkg}.py` | Primitive Protocols |
| `pyxen/core/errors.py` | `PyxenError`, `ManifestError`, `StorageError`, … |
| `pyxen/_cli.py` | CLI entry point |
| `pyxen/impl/<primitive>/<impl>.py` | One file per implementation. **Never import from here in app code.** |
| `pyxen/schemas/runtime.schema.json` | JSON Schema for `runtime.json`. Source of truth for valid keys. |
| `pyxen/pyproject.toml` | Library build config + optional-dependency groups |
| `pyxen/README.md` | Quick-start + how-it-compares. The 30-second orientation. |
| `pyxen/README.md` | The 7 primitives, the runtime contract, and all available implementations. I extend this with workflow. |

## The 7 primitives

| Primitive | Question it answers | Local dev impls | Production impls |
|---|---|---|---|
| `identity` | Who's calling? | `env` | `keychain` (macOS) |
| `tokens` | Within LLM budget? | `json_budget` | `json_budget` (file-backed) |
| `ipc` | Message another process/agent | `inproc` | `a2a` (over HTTP) |
| `pkg` | Dependencies present? | `dry_run` | `pip`, `uv` |
| `storage` | Persist a record | `inmemory` | `local_sqlite`, `redis`, `gcs` |
| `secrets` | Get a credential | `dotenv` | `local_file` |
| `observability` | Emit a trace/log | `stdout` | `file`, `openai_tracing` |

Full list in `pyxen/README.md`.

## Common gotchas

- **Unknown primitives are tolerated** for forward compatibility, but undeclared primitives raise `AttributeError` on access. Always declare what you use.
- **`PYXEN_RUNTIME` env var** overrides the default `runtime.json` path. Use it for per-environment overrides (`PYXEN_RUNTIME=runtime.production.json uvicorn …`).
- **`PYXEN_IDENTITY_ID`** is read by the `env` identity impl. Set it before running, or the impl returns `anonymous`.
- **`PYXEN_ALLOW_ANON=1`** lets the `env` impl accept `anonymous`. Useful for dev, **never set in production**.
- **`dotenv` secrets impl raises `SecretsError` on missing keys.** If a secret is optional, wrap the call in `try/except` or use `rt.secrets.get(name, default=None)` if your pyxen version supports it.
- **The `router` storage impl** namespace-routes across multiple backends. Useful for "hot data in Redis, cold data in S3" patterns.
- **Schema is at `pyxen/schemas/runtime.schema.json`.** If pyxen upgrades and the schema changes, regenerate the project's `runtime.json` via `pyxen init` and diff against the old one.

## Smoke-test idiom

Every shipped app's `_smoke.py` should look like this (adapted from `pyxen/examples/notes_app/app.py`):

```python
import asyncio, json, os, sys, tempfile
from pathlib import Path
from pyxen import Runtime

SMOKE_MANIFEST = {
    "version": "1",
    "identity": {"implementation": "env", "config": {}},
    "tokens": {"implementation": "json_budget", "config": {"path": "./budget.json", "daily_limit": 100000}},
    "ipc": {"implementation": "inproc", "config": {}},
    "pkg": {"implementation": "dry_run", "config": {}},
    "storage": {"implementation": "inmemory", "config": {}},
    "secrets": {"implementation": "dotenv", "config": {"path": "./.env"}},
    "observability": {"implementation": "null", "config": {}},
}

async def _go():
    rt = await Runtime.load("runtime.json")
    me = await rt.identity.current()
    assert me.id == "smoke-test"
    await rt.storage.put("smoke", "k", {"hello": "world"})
    assert await rt.storage.get("smoke", "k") == {"hello": "world"}
    async with rt.observability.trace("smoke") as span:
        span.set_attribute("ok", True)
    print("smoke ok")

def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        Path("runtime.json").write_text(json.dumps(SMOKE_MANIFEST))
        Path(".env").write_text("")
        os.environ["PYXEN_IDENTITY_ID"] = "smoke-test"
        try:
            asyncio.run(_go())
        except AssertionError as e:
            print(f"smoke FAILED: {e}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
```

Run it before declaring done.