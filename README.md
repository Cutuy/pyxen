# pyxen — Portable Python Runtime for Agent Apps


Agentic runtimes lock apps to themselves. pyxen flips this: 7 primitives (storage, secrets, identity, tokens, observability, pkg, ipc) with pluggable backends — swap via `runtime.json`, no code changes. The agentic runtime can build standalone apps that run elsewhere, or be shared.


## What

| Primitive | What it answers | Implementations |
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

Extensions live under `pyxen.core.ext.*` and are initialized lazily from
their section in `runtime.json`. They can be stateful and modify system
state (e.g. the OS crontab).


## How it compares

| vs | pyxen |
|---|-------|
| **openai-agents SDK** | SDK: framework. pyxen: interfaces + optional backend (`pip install pyxen[openai]`). |
| **Dapr** | Dapr: sidecar / Kubernetes / any language. pyxen: in-process / zero infra / Python-only. |

## Quick start

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

Swap backends by changing `runtime.json`, not code:

```json
// traces → stdout
{ "observability": { "implementation": "stdout", "config": {} } }

// traces → /tmp/traces.jsonl
{ "observability": { "implementation": "file", "config": { "path": "/tmp/traces.jsonl" } } }

// traces → OpenAI dashboard
{ "observability": { "implementation": "openai_tracing", "config": {} } }

// storage → local files
{ "storage": { "implementation": "local_fs_mount", "config": { "mounts": [{ "namespace": "data", "type": "local_dir", "src": "./data" }] } } }

// storage → SQLite
{ "storage": { "implementation": "local_sqlite", "config": { "path": "./runtime-data.db" } } }

// storage → in-memory (testing)
{ "storage": { "implementation": "inmemory", "config": {} } }
```

Same pattern applies to identity, secrets, tokens — every primitive.

```bash
pyxen init        # write starter runtime.json
pyxen validate    # validate it
pyxen doctor      # verify impls are importable
pyxen test        # run test suite
```

## Examples

The `examples/` directory has 5 runnable apps. Each one shows the runtime doing a different job.

### [`a2a_chat`](./examples/a2a_chat/README.md)

Runs an A2A-compatible agent that processes tasks sent via JSON-RPC.
Supports both request/reply (``tasks/sendMessage``) and streaming
(``tasks/sendStreamingMessage``) interaction patterns.

```bash
uvicorn examples.a2a_chat.agent:app --reload --port 8080
```

### [`cron_app`](./examples/cron_app/README.md)

Loads a runtime.json that declares two cron jobs. The runtime auto-schedules
them on startup via the OS-native backend (crontab on Linux/macOS, schtasks on
Windows). The app itself is hands-off — it never calls a scheduler API.

```bash
python -m examples.cron_app.main
```

### [`data_pipeline`](./examples/data_pipeline/README.md)

The point is to demonstrate that the **only thing** that changes between
"local dev" and "production deploy" is the ``runtime.json`` file. The
script code is identical.

```bash
PYTHONPATH=src python examples/data_pipeline/pipeline.py
```

### [`hello_runtime`](./examples/hello_runtime/README.md)

A 30-line Python program that loads the runtime, exercises 3 primitives,
and prints a single line. It does the smallest possible thing that proves
the runtime architecture works end-to-end.

```bash
python -m examples.hello_runtime.main
```

### [`notes_app`](./examples/notes_app/README.md)

This is a plain web app: no agents, no LLM calls. The point is to
demonstrate that the runtime serves a normal Python web app just as well
as an agent-containing one.

```bash
pip install pyxen[examples]      # adds fastapi + uvicorn
pyxen validate runtime.json
uvicorn examples.notes_app.app:app --reload
```


## Agent distribution artifacts

The [`agents/`](./agents/) directory gives agents the instructions they need to **write portable apps using pyxen**.

| File | When to use |
|---|---|
| [`agents/coding-agent-dist.md`](./agents/coding-agent-dist.md) | Point any agent at this to build pyxen apps. |
| [`agents/openclaw-dist.md`](./agents/openclaw-dist.md) | Copy into your openclaw workspace as a new sub-agent (see [`agents/forge/`](./agents/forge/)). |

Include the relevant file when asking your agent to build an app.

## Roadmap

- Agent skill or plugin that builds or translates apps into pyxen runtime rather than using their natives
- Stateful runtime and daemon

## Fun fact

The pre-push hook calls DeepSeek via the OpenAI-compatible API to auto-update this README — the roadmap and implementation table regenerate themselves before every push. Yes, this README reads itself, edits itself, and commits itself. It's READMEs all the way down.
