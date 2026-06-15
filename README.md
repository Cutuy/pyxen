# pyxen

A userland runtime interface that makes AI agent-built apps portable — run them locally, share with others, or deploy to the cloud without rewriting them.

## What

| Primitive | What it answers | Implementations |
|---|---|---|
| `identity` | Who's calling? | `env` — ``env`` identity impl — reads identity from environment variables., `keychain` — ``keychain`` identity impl — reads identity from macOS Keychain. |
| `tokens` | Within LLM budget? | `json_budget` — ``json_budget`` tokens impl — soft budget with JSON file backing., `openai_usage` — ``openai_usage`` tokens backend — structured token accounting using the OpenAI SDK. |
| `ipc` | Message another process | `inproc` — ``inproc`` ipc impl — async in-process message bus. |
| `pkg` | Dependencies present? | `dry_run` — ``dry_run`` pkg impl — no-op for environments where dependencies are |
| `storage` | Persist a record | `inmemory` — ``inmemory`` storage impl — dict-backed, for tests and fast iteration., `local_fs_mount` — ``local_fs_mount`` storage impl — mounts a directory tree as the storage namespace., `local_sqlite` — ``local_sqlite`` storage impl — single-file SQLite backend., `redis` — ``redis`` storage backend — key-value backed by Redis. |
| `secrets` | Get a credential | `dotenv` — ``dotenv`` secrets impl — reads from a ``.env`` file., `local_file` — ``local_file`` secrets backend — secrets from a local JSON file. |
| `observability` | Emit a trace / log | `file` — ``file`` observability impl — structured JSON to a local log file., `null` — ``null`` observability impl — drop everything., `openai_tracing` — ``openai_tracing`` observability impl — wraps the OpenAI Agents SDK tracing., `stdout` — ``stdout`` observability impl — structured JSON to stdout. |

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

- `pyxen describe <primitive> <impl>` — print config schema per impl (each impl exports `config_schema` dict)
- `pyxen validate` — validate `runtime.json` against per-impl schemas
- Redis storage backend
- Local file secrets backend
- Port existing OpenClaw apps onto pyxen primitives

## Design

Portability lives in userland, not syscalls. See [`docs/userland-runtime.md`](./docs/userland-runtime.md).

## License

MIT. See [`LICENSE`](./LICENSE). Attributions in [`NOTICE.md`](./NOTICE.md).

> This project was entirely AI-generated. Every line of code was written by an AI language model (Claude, DeepSeek) under human direction. The README, the docs, the tests, the slides — all of it. Use it, fork it, ship it. Just know the author never touched a keyboard to write a single line.
