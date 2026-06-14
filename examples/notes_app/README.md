# notes_app

A small FastAPI notes service that uses the runtime for identity, tokens, storage, and observability. **No agents** — this is a plain web app; the point is to show that the runtime serves ordinary Python apps just as well as agent-containing ones.

## Run

```bash
pip install pyxen[examples]      # adds fastapi + uvicorn
pyxen validate runtime.json
uvicorn examples.notes_app.app:app --reload
```

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | Liveness probe; no runtime access |
| POST | `/notes` | `{"text": "..."}` — auth via `rt.identity`, budget via `rt.tokens`, persistence via `rt.storage`, trace via `rt.observability` |
| GET | `/notes` | List all notes |
| GET | `/notes/{id}` | Fetch a single note |
| DELETE | `/notes/{id}` | Remove a note |

## Porting demo

To run with a different backend (e.g., Postgres instead of SQLite), just write a new `runtime.json`:

```json
{
  "version": "1",
  "storage": {
    "implementation": "postgres",
    "config": { "dsn": "postgresql://user:pass@db/notes" }
  },
  ...
}
```

The app code never changes. The same FastAPI app, the same endpoints, the same semantics — just a different `runtime.json`.

## Auth

The `env` identity impl reads `PYXEN_IDENTITY_ID` from the environment. Set it to your user id (or a CI token) before running. For dev, set `PYXEN_ALLOW_ANON=1` to permit `anonymous` writes.

## Tests

Run the per-module tests:

```bash
pyxen test --module examples.notes_app.app
```

The smoke test uses FastAPI's `TestClient` (in-process HTTP). It exercises identity, tokens, storage, and observability end-to-end.
