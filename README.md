# pyxen

A userland runtime interface that makes AI agent-built apps portable — run them locally, share with others, or deploy to the cloud without rewriting them.

## What

| Primitive | What it answers | Implementations |
|---|---|---|
| `identity` | Identity primitive — who's calling, and on whose behalf. | `env` — ``env`` identity impl — reads identity from environment variables., `keychain` — ``keychain`` identity impl — reads identity from macOS Keychain. |
| `ipc` | IPC primitive — inter-process or inter-agent messaging. | `inproc` — ``inproc`` ipc impl — async in-process message bus. |
| `observability` | Observability primitive — structured, routable telemetry. | `file` — ``file`` observability impl — structured JSON to a local log file., `null` — ``null`` observability impl — drop everything., `openai_tracing` — ``openai_tracing`` observability impl — wraps the OpenAI Agents SDK tracing., `stdout` — ``stdout`` observability impl — structured JSON to stdout. |
| `pkg` | Pkg primitive — environment / dependency declaration and satisfaction. | `dry_run` — ``dry_run`` pkg impl — no-op for environments where dependencies are |
| `secrets` | Secrets primitive — named, audited access to credentials. | `dotenv` — ``dotenv`` secrets impl — reads from a ``.env`` file., `local_file` — ``local_file`` secrets backend — secrets from a local JSON file. |
| `storage` | Storage primitive — key-value or document store interface. | `inmemory` — ``inmemory`` storage impl — dict-backed, for tests and fast iteration., `local_fs_mount` — ``local_fs_mount`` storage impl — mounts a directory tree as the storage namespace., `local_sqlite` — ``local_sqlite`` storage impl — single-file SQLite backend., `redis` — ``redis`` storage backend — key-value backed by Redis. |
| `tokens` | Tokens primitive — model/token budget check and charge. | `json_budget` — ``json_budget`` tokens impl — soft budget with JSON file backing., `openai_usage` — ``openai_usage`` tokens backend — structured token accounting using the OpenAI SDK. |

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

- [done] `pyxen describe <primitive> <impl>` — print config schema per impl (each impl exports `config_schema` dict)
- [done] `pyxen validate` — validate `runtime.json` against per-impl schemas
- [done] Redis storage backend
- [done] Local file secrets backend
- [done] Inmemory storage backend
- [done] Local SQLite storage backend
- [done] Local filesystem mount storage backend
- [done] Dotenv secrets backend
- [done] Env identity backend
- [done] Keychain identity backend
- [done] Inproc IPC backend
- [done] File observability backend
- [done] Null observability backend
- [done] OpenAI tracing observability backend
- [done] Stdout observability backend
- [done] Dry run pkg backend
- [done] JSON budget tokens backend
- [done] OpenAI usage tokens backend
- Port existing OpenClaw apps onto pyxen primitives
- Implement `pyxen run` command to execute runtime.json
- Add integration tests for all primitive/implementation combinations
- Write documentation for each primitive and implementation

## Design

Portability lives in userland, not syscalls. See [`docs/userland-runtime.md`](./docs/userland-runtime.md).

## License

MIT. See [`LICENSE`](./LICENSE). Attributions in [`NOTICE.md`](./NOTICE.md).

> This project was entirely AI-generated. Every line of code was written by an AI language model (Claude, DeepSeek) under human direction. The README, the docs, the tests, the slides — all of it. Use it, fork it, ship it. Just know the author never touched a keyboard to write a single line.
