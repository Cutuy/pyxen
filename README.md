# pyxen

A lightweight, portable Python library that decouples agent logic from underlying provider implementations.

Swap storage, secrets, identity, tokens, observability, package management, and IPC via `runtime.json`. Zero code changes.

```python
import asyncio
from pyxen import Runtime

async def main():
    rt = await Runtime.load("runtime.json")
    await rt.storage.put("greetings", "world", {"from": "me"})
    async with rt.observability.trace("greet") as span:
        span.log("info", "wrote greeting")

asyncio.run(main())
```

Swap backends by editing `runtime.json`, not code:

```json
// traces → stdout
{ "observability": { "implementation": "stdout", "config": {} } }
// traces → /tmp/traces.jsonl
{ "observability": { "implementation": "file", "config": { "path": "/tmp/traces.jsonl" } } }
// storage → SQLite
{ "storage": { "implementation": "local_sqlite", "config": { "path": "./runtime-data.db" } } }
// storage → in-memory (testing)
{ "storage": { "implementation": "inmemory", "config": {} } }
```

Same pattern for identity, secrets, tokens, pkg, ipc — every primitive.

```bash
pyxen init        # write starter runtime.json
pyxen validate    # validate it
pyxen doctor      # verify impls are importable
```

## The 7 primitives

| Primitive | What it answers | Backends |
|---|---|---|
| `identity` | Who's calling? | - `env` — reads identity from environment variables.<br>- `keychain` — reads identity from macOS Keychain. |
| `ipc` | Message another process | - `a2a` — Agent-to-Agent protocol communication.<br>- `inproc` — async in-process message bus. |
| `observability` | Emit a trace / log | - `file` — structured JSON to a local log file.<br>- `null` — drop everything.<br>- `openai_tracing` — wraps the OpenAI Agents SDK tracing.<br>- `stdout` — structured JSON to stdout. |
| `pkg` | Dependencies present? | - `dry_run` — no-op for environments where dependencies are<br>- `pip` — delegates to ``pip`` for lock-file-first dependency<br>- `uv` — delegates to ``uv`` for lock-file-first dependency |
| `secrets` | Get a credential | - `dotenv` — reads from a ``.env`` file.<br>- `local_file` — secrets from a local JSON file. |
| `storage` | Persist a record | - `gcs` — Google Cloud Storage-backed key-value store.<br>- `inmemory` — dict-backed, for tests and fast iteration.<br>- `local_fs_mount` — mounts a directory tree as the storage namespace.<br>- `local_sqlite` — single-file SQLite backend.<br>- `redis` — key-value backed by Redis.<br>- `router` — namespace-routed multi-backend storage. |
| `tokens` | Within LLM budget? | - `json_budget` — soft budget with JSON file backing.<br>- `openai_usage` — structured token accounting using the OpenAI SDK. |

## Extensions

| Extension | What it adds | Implementations |
|---|---|---|
| `cron` | Schedule recurring tasks | - `crontab` — crontab backend.<br>- `windows` — windows backend.<br>- `state` — execution history (timestamps, exit codes) queryable via runtime extension API. |

Extensions live under `pyxen.core.ext.*` and are initialized from
their section in `runtime.json`.


## How it compares

| vs | pyxen |
|---|---|
| **openai-agents SDK** | SDK is a framework. pyxen provides interfaces + optional backend (`pip install pyxen[openai]`). |
| **Dapr** | Dapr: sidecar / Kubernetes / any language. pyxen: in-process / zero infra / Python-only. |

## Examples

| Example | What it shows |
|---|---|
| [`a2a_chat`](./examples/a2a_chat/) | Runs an A2A-compatible agent that processes tasks sent via JSON-RPC.
Supports both request/reply (``tasks/sendMessage``) and streaming
(``tasks/sendStreamingMessage``) interaction patterns — `uvicorn examples.a2a_chat.agent:app --reload --port 8080` |
| [`cron_app`](./examples/cron_app/) | Loads a runtime.json that declares two cron jobs. The runtime auto-schedules
them on startup via the OS-native backend (crontab on Linux/macOS, schtasks on
Windows). The app itself is hands-off — it never calls a scheduler API — `python -m examples.cron_app.main` |
| [`data_pipeline`](./examples/data_pipeline/) | The point is to demonstrate that the **only thing** that changes between
"local dev" and "production deploy" is the ``runtime.json`` file. The
script code is identical — `PYTHONPATH=src python examples/data_pipeline/pipeline.py` |
| [`hello_runtime`](./examples/hello_runtime/) | A 30-line Python program that loads the runtime, exercises 3 primitives,
and prints a single line. It does the smallest possible thing that proves
the runtime architecture works end-to-end — `python -m examples.hello_runtime.main` |
| [`notes_app`](./examples/notes_app/) | This is a plain web app: no agents, no LLM calls. The point is to
demonstrate that the runtime serves a normal Python web app just as well
as an agent-containing one — `pip install pyxen[examples]      # adds fastapi + uvicorn
pyxen validate runtime.json
uvicorn examples.notes_app.app:app --reload` |
| [`pkg_demo`](./examples/pkg_demo/) | The runtime.json declares ``pkg`` with the ``pip`` implementation,
pointing to a ``requirements.txt``. On load, app code calls
``rt.pkg.ensure()`` to install any missing PyPI packages, then
imports and uses them normally — `python -m examples.pkg_demo.main` |


## Agent distribution artifacts

The [`agents/`](./agents/) directory gives agents the instructions to build portable apps using pyxen.

| File | When to use |
|---|---|
| [`agents/coding-agent-dist.md`](./agents/coding-agent-dist.md) | Point any agent at this to build pyxen apps. |
| [`agents/openclaw-dist.md`](./agents/openclaw-dist.md) | Copy into your openclaw workspace as a sub-agent. |

## Roadmap

- Agent skill or plugin that builds / translates apps into pyxen runtime
- Stateful runtime and daemon

## Fun fact

The pre-push hook calls DeepSeek via the OpenAI-compatible API to auto-update this README. Yes, this README reads itself, edits itself, and commits itself. It's READMEs all the way down.
