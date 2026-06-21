# pyxen — Portable Python Runtime for Agent Apps


**pyxen** is a lightweight **Python runtime interface** that makes AI agent-built apps **portable** — run them locally, share them with others, or deploy to the cloud without rewriting a single line of code. Swap storage, secrets, observability, identity, IPC, package management, and LLM tokens by editing one `runtime.json`. The agentic runtime itself can be fully stripped away — **the app stays.**

Agentic runtimes typically build apps locked to their runtime. pyxen flips this: apps use a pluggable runtime config — the agentic runtime can build standalone apps that run elsewhere, or can be shared.

> **One-line summary:** A 7-primitive runtime for portable Python apps. Swap backends via `runtime.json`. No code changes.

## Why pyxen?

AI coding agents hardcode environment-specific APIs (`os.environ`, `boto3`, etc.). pyxen decouples the app from its environment via 7 primitives — swap backends by changing one JSON file, no code changes.

## What

| Primitive | What it answers | Implementations |
|---|---|---|
| `identity` | Who's calling? | <br>- `env` — reads identity from environment variables.<br>- `keychain` — reads identity from macOS Keychain. |
| `ipc` | Message another process | <br>- `a2a` — Agent-to-Agent protocol communication.<br>- `inproc` — async in-process message bus. |
| `observability` | Emit a trace / log | <br>- `file` — structured JSON to a local log file.<br>- `null` — drop everything.<br>- `openai_tracing` — wraps the OpenAI Agents SDK tracing.<br>- `stdout` — structured JSON to stdout. |
| `pkg` | Dependencies present? | <br>- `dry_run` — no-op for environments where dependencies are<br>- `pip` — delegates to ``pip`` for lock-file-first dependency<br>- `uv` — delegates to ``uv`` for lock-file-first dependency |
| `secrets` | Get a credential | <br>- `dotenv` — reads from a ``.env`` file.<br>- `local_file` — secrets from a local JSON file. |
| `storage` | Persist a record | <br>- `gcs` — Google Cloud Storage-backed key-value store.<br>- `inmemory` — dict-backed, for tests and fast iteration.<br>- `local_fs_mount` — mounts a directory tree as the storage namespace.<br>- `local_sqlite` — single-file SQLite backend.<br>- `redis` — key-value backed by Redis.<br>- `router` — namespace-routed multi-backend storage. |
| `tokens` | Within LLM budget? | <br>- `json_budget` — soft budget with JSON file backing.<br>- `openai_usage` — structured token accounting using the OpenAI SDK. |

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

The `examples/` directory has 4 runnable apps. Each one shows the runtime doing a different job.

### [`a2a_chat`](./examples/a2a_chat/README.md)

Runs an A2A-compatible agent that processes tasks sent via JSON-RPC.
Supports both request/reply (``tasks/sendMessage``) and streaming
(``tasks/sendStreamingMessage``) interaction patterns.

```bash
uvicorn examples.a2a_chat.agent:app --reload --port 8080
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

## Keywords & topics

`python` `runtime` `portability` `agents` `agent-runtime` `a2a` `observability`

## Roadmap

- Agent skill or plugin that builds or translates apps into pyxen runtime rather than using their natives
- Stateful runtime and daemon

## License

MIT. See [`LICENSE`](./LICENSE). Attributions in [`NOTICE.md`](./NOTICE.md).

> This project was entirely AI-generated. Every line of code was written by an AI language model (Claude, DeepSeek) under human direction. The README, the docs, the tests, the slides — all of it. Use it, fork it, ship it. Just know the author never touched a keyboard to write a single line.

## Fun fact

The pre-push hook calls DeepSeek via the OpenAI-compatible API to auto-update this README — the roadmap and implementation table regenerate themselves before every push. Yes, this README reads itself, edits itself, and commits itself. It's READMEs all the way down.
