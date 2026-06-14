# data_pipeline

A script that reads records from one storage backend, transforms each, and writes to another. **No agents** — the interesting bit is the *provider swap*.

## The point

The pipeline code is identical between local and production. The **only** thing that changes is `runtime.json`:

| | Local (this example) | Production (hypothetical) |
|---|---|---|
| `storage` (source) | `inmemory` (seeded by the script) | `postgres` |
| `storage` (dest) | `inmemory` | `s3` |
| `observability` | `stdout` | `otel` |

Same code. Different backends. The app code never knows.

## Run

```bash
PYTHONPATH=src python examples/data_pipeline/pipeline.py
```

Expected output (stdout observability + a summary line):

```json
{"event": "span_start", "span": "data_migration"}
{"event": "span_end", "span": "data_migration", "attributes": {"source_count": 5, "written_count": 5}}
migrated 5 records from source to dest
```

## Tests

```bash
PYTHONPATH=src python examples/data_pipeline/pipeline.py --test
```

The self-test seeds 5 sample records, runs the migration, and asserts the dest has the expected transformed output. Uses `inmemory` for both ends.

## Porting to a real backend

To migrate from local `inmemory` to a real backend, just add a new entry under `impl/storage/` (e.g., `postgres.py` or `s3.py`) that satisfies the `StorageImpl` protocol. Then change `source.json` / `dest.json` to use the new implementation:

```json
{
  "version": "1",
  "storage": {
    "implementation": "postgres",
    "config": { "dsn": "postgresql://..." }
  }
}
```

The `pipeline.py` script is unchanged.
