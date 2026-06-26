# bigquery_secrets

Query a BigQuery table through the runtime — with credentials injected via
`{"$secret": "..."}` — **without the app code ever touching a credential**.

This is **why we have a runtime**. The app in `app.py` calls
`rt.storage.query(...)` and nothing else. The `runtime.json` declares both
*which* storage backend to use and *how* to resolve the credential secret.
Swap the secrets impl and the BigQuery config, and the same code works in
dev, test, and production — zero application changes.

## What it demonstrates

| Concern | In `runtime.json` | In app code |
|---|---|---|
| Storage backend | `storage.implementation = "bq"` | `rt.storage.query(...)` |
| Credential source | `storage.config.credentials = {"$secret": "GCP_SA_JSON"}` | — |
| Secret resolution | `secrets.implementation = "dotenv"` | `rt.secrets.get("GCP_SA_JSON")` |

The app never imports `dotenv`, never reads `os.environ`, never constructs a
service-account path. **All of that lives in the runtime layer.**

## How `$secret` references are resolved

1. The runtime reads `runtime.json` and detects
   `{"$secret": "GCP_SA_JSON"}` in the storage config.
2. It loads the `secrets` primitive (`dotenv` in this example).
3. When constructing the storage impl (`bq`), it passes the resolved
   secret value as the `credentials` config key — the storage impl receives
   the raw JSON string and writes it to a temp file for the `bq` subprocess.

The `$secret` key is **not** a template variable in config strings — it must
be the *sole key* in a config object:

```json
{"credentials": {"$secret": "GCP_SA_JSON"}}   ✓
{"credentials": {"$secret": "GCP_SA_JSON", "extra": 1}}  ✗
```

## Two scenarios

### Local dev (this example) — dotenv

```
runtime.json  →  secrets: dotenv  →  .env  →  GCP_SA_JSON=...
```

The `.env` file is never committed. Copy `.env.example` to `.env` and fill in
your real service-account key.

### Production — local_file / Vault / K8s

Swap the secrets section in `runtime.json` and nothing else changes:

```json
{
  "secrets": {
    "implementation": "local_file",
    "config": { "path": "/etc/secrets/gcp-credentials.json" }
  }
}
```

The file at that path should be a JSON object keyed by secret name:

```json
{
  "GCP_SA_JSON": { "type": "service_account", ... }
}
```

Same `app.py`. Same `runtime.json` *structure*. Only the secrets impl
and its config path change.

## How to run for real

1. Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
   and ensure `bq` is on your `PATH`:
   ```bash
   which bq
   ```

2. Create a service-account key in the GCP Console or with `gcloud`:
   ```bash
   gcloud iam service-accounts keys create sa-key.json \
     --iam-account=your-sa@your-project.iam.gserviceaccount.com
   ```

3. Copy the example env file and paste in your key:
   ```bash
   cp .env.example .env
   # Edit .env with your service-account JSON
   ```

4. Update the BigQuery config in `runtime.json`:
   - `project` — your GCP project ID
   - `dataset` — the BigQuery dataset name
   - `table` — the table name

5. Run:
   ```bash
   PYTHONPATH=src python examples/bigquery_secrets/app.py
   ```

## How to run `--test` mode

No credentials, no `bq` CLI, no GCP project needed:

```bash
PYTHONPATH=src python examples/bigquery_secrets/app.py --test
```

The test creates an ephemeral `runtime.json` with `inmemory` storage, seeds
two sample rows, and runs the same `query_table()` function — proving the app
code is backend-agnostic. Expected output:

```
Test passed: retrieved 2 row(s)
  {'name': 'alice', 'score': 42}
  {'name': 'bob', 'score': 99}
```

## Porting to a different backend

To switch from BigQuery to, say, Postgres or SQLite:

```json
{
  "storage": {
    "implementation": "postgres",
    "config": { "dsn": "postgresql://user:pass@host/db" }
  }
}
```

The app code (`app.py`) is **unchanged**. Same calls to `rt.storage.query()`.
Same `--test` mode. This is the core runtime promise.
