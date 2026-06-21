# MEMORY.md — Long-Term

_This is my curated memory. Daily files in `memory/YYYY-MM-DD.md` are raw logs; this is the distilled wisdom._

## User preferences

_(Filled in as the user expresses opinions. Examples below — delete and replace as I learn.)_

- **Storage:** `local_sqlite` for single-user apps; `redis` if they have Redis on the box.
- **Secrets:** `dotenv` everywhere; `local_file` only if the user explicitly wants JSON.
- **Observability:** `stdout` in dev, `file` in prod, `null` in tests.
- **Web framework:** FastAPI when a web UI is needed; plain asyncio scripts otherwise.
- **Package manager:** uv. They have a `uv.lock` already.
- **Auth:** they have their own OIDC service; never use `rt.identity` for auth checks, only for "who's calling" logging.

## Apps built

| Name | Reference pattern | Primitives used | Deploy target | Built | Notes |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

## Reference patterns I've leaned on

_(Which `pyxen/examples/` reference each app was scaffolded from.)_

- _(none yet — log the reference pattern when adapting for the first time, e.g., "FastAPI notes_app pattern adapted for <project-name> with <changes>")_

## Patterns that worked

_(Things the user liked or that solved recurring problems.)_

- _FastAPI + lifespan → load runtime once, store on `app.state.runtime` → handlers access via `_rt()` helper._
- _For CLI apps, `__main__.py` is the entry point; the actual logic goes in a `run(rt)` function that's importable for tests._
- _For scheduled work, use `asyncio` + `apscheduler` in the same process; never pyxen's `ipc` for in-app scheduling._
- _`pyxen init` gives a clean starter `runtime.json`. Edit + validate, never hand-write from scratch._

## Gotchas to avoid

_(Bugs I've hit, fixes that worked.)_

- _Don't import `from pyxen.impl.storage.local_sqlite import …` — the runtime is the only entry point. If you catch yourself doing this, stop._
- _The `env` identity impl returns `anonymous` if `PYXEN_IDENTITY_ID` is unset. Always set it in tests or guard with `PYXEN_ALLOW_ANON=1`._
- _Schema changes between pyxen versions: when upgrading pyxen, regenerate `runtime.json` via `pyxen init` and diff against the old one._
- _The `dotenv` secrets impl raises `SecretsError` on missing keys. Wrap optional secrets in try/except._
- _Smoke-test `_smoke.py` runs in a temp dir via `os.chdir(tmp)` — the cwd before invocation doesn't matter._

## pyxen version tracking

_(Latest version I've validated against. Update after each pyxen release.)_

- **Last validated:** _(version, date)_
- **Optional deps installed:** _(openai · cloud · a2a · examples · dev — which ones)_

---

_I update this after every build. Daily notes go in `memory/YYYY-MM-DD.md`; the durable lessons get distilled here._