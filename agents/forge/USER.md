# USER.md — About the Developer

_This file is filled in during the first conversation and updated as I learn more._

## Required (ask if missing)

- **Name / handle:** _(what to call them)_
- **Project name:** _(the app we're building)_
- **What the app does:** _(one paragraph)_
- **Deploy target(s):** local dev only · single-VM production · multi-instance cloud · serverless · something else

## Defaults to learn over time

- **Python version:** _(check the project, default 3.11+)_
- **Package manager:** _(pip · poetry · uv — default uv)_
- **Web framework (if any):** _(none · FastAPI · Flask · Django — default FastAPI if web)_
- **Async vs sync:** _(default async if FastAPI / aiohttp)_

## Preferences to remember

_Filled in as the user expresses opinions. Examples:_

- Always uses `local_sqlite` for storage in single-user apps.
- Prefers `dotenv` over `local_file` for secrets even in production.
- Wants `stdout` observability in dev, `file` in prod, never `openai_tracing`.
- Never uses the `tokens` primitive — just sets `daily_limit` very high and ignores it.
- Has their own auth service; never uses `rt.identity.current()` directly.

## Communication

- **Tone:** casual, peer-to-peer, direct.
- **Verbosity:** terse by default; expand only when explaining a non-obvious choice.
- **Push-back:** welcome. If I disagree, I say why once and move on. If you push back with a reason, I defer.

---

_The more I know, the better I can pre-fill decisions. But I never assume — if I don't know a field, I ask._