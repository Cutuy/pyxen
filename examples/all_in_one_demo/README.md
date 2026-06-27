# all_in_one_demo — Dev Session Tracker

A single async CLI app that exercises **all 7 pyxen primitives** plus the
**cron extension** in a coherent, useful workflow.

## Primitives used

| # | Primitive   | Implementation | What it does |
|---|-------------|----------------|-------------|
| 1 | identity    | `env`          | Identifies the current user |
| 2 | secrets     | `dotenv`       | Loads `API_KEY` from `.env` |
| 3 | pkg         | `pip`          | Installs `rich` for pretty table output |
| 4 | storage     | `local_sqlite` | Persists a session record to SQLite |
| 5 | tokens      | `json_budget`  | Checks & charges a token budget |
| 6 | observability | `stdout`     | Emits a trace + span attributes |
| 7 | ipc         | `inproc`       | Publishes an event consumed by a background listener |
| 8 | cron        | (extension)    | Lists a declared hourly report job |

## Quick start

```bash
cd examples/all_in_one_demo

# 1. Create your .env (copy the example)
cp .env.example .env

# 2. Run from repo root
PYTHONPATH=src python -m examples.all_in_one_demo.main
```

Or run directly from the example directory:

```bash
cd examples/all_in_one_demo
PYTHONPATH=../../src python main.py
```

## What to expect

On first run, `pyxen` will `pip install rich` (the only extra dependency).
You'll see debug output from each primitive step, followed by a colour
summary table rendered by `rich`.

## Self-test

A hermetic `_main()` entry point (discoverable by `pyxen-test`) exercises
all primitives using in-memory backends and temp files — no `.env` or
SQLite database required:

```bash
PYTHONPATH=src python -c "from examples.all_in_one_demo.main import _main; _main()"
```
