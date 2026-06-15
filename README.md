# pyxen

A userland runtime interface that makes AI agent-built apps portable — run them locally, share with others, or deploy to the cloud without rewriting them. Portability also means the agentic runtime can be fully stripped away — the app stays.

## What

| Primitive | What it answers | Implementations |
|---|---|---|
| `identity` | Who's calling? | <br>- `env` — reads identity from environment variables.<br>- `keychain` — reads identity from macOS Keychain. |
| `ipc` | Message another process | <br>- `inproc` — async in-process message bus. |
| `observability` | Emit a trace / log | <br>- `file` — structured JSON to a local log file.<br>- `null` — drop everything.<br>- `openai_tracing` — wraps the OpenAI Agents SDK tracing.<br>- `stdout` — structured JSON to stdout. |
| `pkg` | Dependencies present? | <br>- `dry_run` — no-op for environments where dependencies are |
| `secrets` | Get a credential | <br>- `dotenv` — reads from a ``.env`` file.<br>- `local_file` — secrets from a local JSON file. |
| `storage` | Persist a record | <br>- `inmemory` — dict-backed, for tests and fast iteration.<br>- `local_fs_mount` — mounts a directory tree as the storage namespace.<br>- `local_sqlite` — single-file SQLite backend.<br>- `redis` — key-value backed by Redis. |
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

## Roadmap

- Agent skill or plugin that builds or translates apps into pyxen runtime rather than using their natives
- Stateful runtime and daemon

## Design

Portability lives in userland, not syscalls. See [`docs/userland-runtime.md`](./docs/userland-runtime.md).

## License

MIT. See [`LICENSE`](./LICENSE). Attributions in [`NOTICE.md`](./NOTICE.md).

> This project was entirely AI-generated. Every line of code was written by an AI language model (Claude, DeepSeek) under human direction. The README, the docs, the tests, the slides — all of it. Use it, fork it, ship it. Just know the author never touched a keyboard to write a single line.

## Fun fact

The pre-push hook calls DeepSeek via the OpenAI-compatible API to auto-update this README — the roadmap and implementation table regenerate themselves before every push. Yes, this README reads itself, edits itself, and commits itself. It's READMEs all the way down.
