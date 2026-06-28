# pyxen

A lightweight Python library that decouples agentic runtime from applications it builds. Allows openclaw or codex to build apps runnable elsewhere without it.


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

## Primitives

| Primitive | What it answers | Backends |
|---|---|---|
| `identity` | Who's calling? | `env`, `keychain` |
| `ipc` | Message another process | `a2a`, `inproc`, `mcp` |
| `observability` | Emit a trace / log | `file`, `null`, `openai_tracing`, `opentelemetry`, `stdout` |
| `pkg` | Dependencies present? | `dry_run`, `pip`, `uv` |
| `sandbox` |  | `wasi` |
| `secrets` | Get a credential | `dotenv`, `local_file` |
| `storage` | Persist a record | `bq`, `gcs`, `inmemory`, `local_fs_mount`, `local_sqlite`, `redis`, `router`, `s3`, `spanner` |
| `tokens` | Within LLM budget? | `json_budget`, `openai_usage` |

## Extensions

| Extension | What it adds | Backends |
|---|---|---|
| `cron` | Schedule recurring tasks | `crontab`, `windows`, `state` |

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
| [`a2a_chat`](./examples/a2a_chat/) | Agent-to-agent protocol interaction |
| [`bigquery_secrets`](./examples/bigquery_secrets/) | The point: the app never touches credentials, environment variables, or cloud SDK config directly. |
| [`cron_app`](./examples/cron_app/) | Declarative cron jobs auto-scheduled on startup |
| [`data_pipeline`](./examples/data_pipeline/) | Same script, different runtime.json = local dev vs production |
| [`hello_runtime`](./examples/hello_runtime/) | Smallest end-to-end runtime load, exercises 3 primitives |
| [`notes_app`](./examples/notes_app/) | Plain web app using the runtime — no agents or LLM calls |
| [`pkg_demo`](./examples/pkg_demo/) | Declare and install dependencies via the pkg primitive |
| [`playground`](./examples/playground/) | An interactive REPL that exercises all 7 pyxen primitives in a natural dependency graph rather… |

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
