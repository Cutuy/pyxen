# playground — CLI Agent Playground

An **interactive REPL** that exercises all 7 pyxen primitives in a
natural dependency graph rather than a serial walk-through. Each user
command triggers a multi-step workflow that interleaves 4–6 primitives.
State persists across commands via `rt.storage` so later commands have
real data dependencies on earlier ones.

## Commands

| Command     | Primitives used                                                                 |
|-------------|---------------------------------------------------------------------------------|
| `deploy`    | identity → pkg → tokens → storage → observability → ipc                        |
| `diagnostic`| identity → secrets → pkg → storage → tokens → observability → ipc → storage    |
| `report`    | identity → secrets → storage → tokens → ipc → observability → storage          |
| `status`    | identity → storage → observability                                             |
| `help`      | Display command reference                                                      |
| `exit`      | Leave the playground                                                           |

## Primitive usage across commands

| Primitive      | Used in                                | Times |
|----------------|----------------------------------------|-------|
| identity       | deploy, diagnostic, report, status     | 4     |
| secrets        | diagnostic, report                     | 2     |
| pkg            | deploy, diagnostic                     | 2     |
| storage        | deploy, diagnostic, report, status     | 6     |
| tokens         | deploy, diagnostic, report             | 3     |
| observability  | deploy, diagnostic, report, status     | 4     |
| ipc            | deploy, diagnostic, report             | 3     |

## Quick start

```bash
cd examples/playground

# 1. Create your .env (copy the example)
cp .env.example .env

# 2. Run from repo root
PYTHONPATH=src python -m examples.playground.main
```

Or run directly from the example directory:

```bash
cd examples/playground
PYTHONPATH=../../src python main.py
```

## What to expect

You'll be greeted by the "CLI Agent Playground" banner and a `pyxen>` prompt.
Type `help` to see available commands, `deploy` to deploy a service, `diagnostic`
to run a diagnostic, `report` to generate a summary report of everything done so
far, or `status` to see the current agent state. Type `exit` to leave.

Each command prints its primitive steps with rich formatting (via `rich` if
installed; falls back to plain text otherwise).

## Workflow dependencies

The commands form a natural dependency chain:

1. `deploy` writes a deployment record to storage
2. `diagnostic` reads previous diagnostics and writes a new result
3. `report` queries both deployments and diagnostics, then writes a report
4. `status` lists everything (sessions, deployments, diagnostics, reports)

Running them out of order is fine — `report` will just show 0 deployments
and 0 diagnostics if nothing has been deployed or diagnosed yet.

## Self-test

A hermetic `_main()` entry point (discoverable by `pyxen-test`) pipes commands
into the REPL using in-memory backends — no `.env` or SQLite database required:

```bash
PYTHONPATH=src python -c "from examples.playground.main import _main; _main()"
```
